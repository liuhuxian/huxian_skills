#!/usr/bin/env python3
"""File-based external-agent pipeline for call_agent_code."""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import shlex
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

SKILL_DIR = Path(__file__).resolve().parents[1]
CONFIG_PATH = SKILL_DIR / "config.yaml"

BUILTIN_DEFAULTS: dict[str, Any] = {
    "defaults": {
        "developer": {"runner": "opencode", "provider": "volcengine-plan", "model": "glm-5.2", "session_id": "change-name"},
        "code_reviewer": {"runner": "opencode", "provider": "volcengine-plan", "model": "minimax-m3"},
        "task_verifier": {"runner": "opencode", "provider": "volcengine-plan", "model": "glm-5.2"},
        "codex_review": {"enabled": True, "command": "codex --no-alt-screen"},
        "background": True,
        "auto_commit": False,
        "max_review_rounds": 3,
        "status_poll_seconds": 20,
    }
}


def now_iso() -> str:
    return dt.datetime.now().astimezone().isoformat(timespec="seconds")


def read_yaml_like(path: Path) -> dict[str, Any]:
    if not path.exists():
        return BUILTIN_DEFAULTS
    try:
        import yaml  # type: ignore

        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        return data
    except Exception:
        # Minimal fallback for this skill's simple config shape.
        return BUILTIN_DEFAULTS


def parse_role_spec(value: str | None, default: dict[str, str]) -> dict[str, str]:
    role = dict(default)
    if not value:
        return role

    # Supported forms:
    #   runner:provider/model
    #   runner:model              (keeps default provider)
    #   provider/model            (keeps default runner)
    #   model                     (keeps default runner/provider)
    runner_part: str | None = None
    model_part = value.strip()
    if ":" in model_part:
        runner_part, model_part = model_part.split(":", 1)
        role["runner"] = runner_part.strip()
    if "/" in model_part:
        provider, model = model_part.split("/", 1)
        role["provider"] = provider.strip()
        role["model"] = model.strip()
    elif model_part:
        role["model"] = model_part.strip()
    if "runner" not in role:
        # Backward-compatible migration from the old field name if a user config still has it.
        role["runner"] = role.pop("cli", role.pop("provider", "opencode"))
        role.setdefault("provider", "")
    return role


def role_model_arg(role: dict[str, str], *, include_provider: bool) -> str:
    provider = role.get("provider", "")
    model = role["model"]
    if include_provider and provider:
        return f"{provider}/{model}"
    return model


def deep_get(config: dict[str, Any], *keys: str, default: Any = None) -> Any:
    cur: Any = config
    for key in keys:
        if not isinstance(cur, dict) or key not in cur:
            return default
        cur = cur[key]
    return cur


def resolve_worktree(value: str | None, defaults: dict[str, Any]) -> Path:
    raw = value or defaults.get("worktree") or os.getcwd()
    if raw == "wk1":
        cwd = Path(os.getcwd()).resolve()
        candidate = cwd / ".worktree" / "wk1"
        if candidate.exists():
            return candidate.resolve()
        parent_candidate = cwd.parent / ".worktree" / "wk1"
        if parent_candidate.exists():
            return parent_candidate.resolve()
    return Path(raw).expanduser().resolve()


def detect_change(worktree: Path) -> str:
    changes = worktree / "openspec" / "changes"
    if not changes.exists():
        raise SystemExit(f"openspec changes dir not found: {changes}")
    candidates = [p for p in changes.iterdir() if p.is_dir() and p.name != "archive"]
    if not candidates:
        raise SystemExit(f"no OpenSpec change found in {changes}")
    candidates.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return candidates[0].name


def atomic_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def append_log(agent_dir: Path, message: str) -> None:
    line = f"[{now_iso()}] {message}"
    print(line, flush=True)
    with (agent_dir / "progress.log").open("a", encoding="utf-8") as f:
        f.write(line + "\n")
        f.flush()


def write_status(agent_dir: Path, request: dict[str, Any], state: str, phase: str, round_no: int, blocking_issue: str | None = None) -> None:
    print(f"[{now_iso()}] status state={state} phase={phase} round={round_no}/{request['max_review_rounds']} blocking={blocking_issue}", flush=True)
    atomic_json(
        agent_dir / "status.json",
        {
            "change": request["change"],
            "state": state,
            "phase": phase,
            "round": round_no,
            "max_review_rounds": request["max_review_rounds"],
            "updated_at": now_iso(),
            "developer": request["developer"],
            "code_reviewer": request["code_reviewer"],
            "task_verifier": request["task_verifier"],
            "sessions": request["sessions"],
            "blocking_issue": blocking_issue,
            "pipeline_pid": os.getpid(),
        },
    )


def build_prompt_files(agent_dir: Path, request: dict[str, Any]) -> None:
    change = request["change"]
    agent_prompt = f"""You are the developer agent for OpenSpec change `{change}`.

Read the OpenSpec files under `openspec/changes/{change}/` and implement them exactly in worktree `{request['worktree']}`.

Hard requirements:
- Do not commit.
- Communicate only through files in `openspec/changes/{change}/agent/`.
- Keep `status.json` updated at phase changes.
- Write `changed_files.txt`, `verification.md`, `self_review.md`, `handover.md`, and `completion_gate.json`.
- Do not claim tests passed unless `verification.md` records exact commands, exit codes, and key outputs/artifact paths.
- If blocked, write `status.json` with `state=blocked` and a concrete `blocking_issue`.
"""
    code_review_prompt = f"""You are subagent1, the code reviewer for OpenSpec change `{change}`.

Review the implementation diff in worktree `{request['worktree']}`. Focus on bugs, regressions, missing tests, unsafe behavior, and incompatibilities. Write `openspec/changes/{change}/agent/code_review_round_<round>.md` with PASS or NEEDS_CHANGES and severity-ranked findings.
"""
    task_prompt = f"""You are subagent2, the task verifier for OpenSpec change `{change}`.

Verify that the OpenSpec requirements and tasks are actually complete. Check `verification.md`, `changed_files.txt`, `handover.md`, `completion_gate.json`, and the OpenSpec tasks. Do not focus primarily on code style. Write `openspec/changes/{change}/agent/task_verification_round_<round>.md` with PASS or NEEDS_CHANGES and evidence per requirement.
"""
    codex_prompt = f"""You are Codex lead reviewer for OpenSpec change `{change}`.

Read the OpenSpec change, agent handoff artifacts, secondary reviews, completion gate, and git diff in worktree `{request['worktree']}`. Perform the final review. Output PASS only if the change is truly ready for user commit confirmation; otherwise output NEEDS_CHANGES with concrete required fixes.
"""
    files = {
        "agent_prompt.md": agent_prompt,
        "code_reviewer_prompt.md": code_review_prompt,
        "task_verifier_prompt.md": task_prompt,
        "codex_review_prompt.md": codex_prompt,
    }
    for name, text in files.items():
        path = agent_dir / name
        if not path.exists():
            path.write_text(text, encoding="utf-8")


def build_runner_cmd(role: dict[str, str], prompt_file: Path, request: dict[str, Any], session_id: str | None, *, resume_existing_session: bool = False) -> list[str]:
    runner = role["runner"]
    prompt = prompt_file.read_text(encoding="utf-8")
    if runner == "opencode":
        cmd = ["opencode", "run", "--model", role_model_arg(role, include_provider=True)]
        if session_id and resume_existing_session:
            cmd += ["--session", session_id]
        elif session_id:
            cmd += ["--title", session_id]
        cmd.append(prompt)
        return cmd
    if runner == "codebuddy":
        return ["codebuddy", "-p", "--model", role_model_arg(role, include_provider=False), "--permission-mode", "acceptEdits", prompt]
    raise SystemExit(f"unsupported runner: {runner}")


def run_cmd(cmd: list[str], cwd: Path, log_path: Path) -> int:
    cmd_line = f"$ {' '.join(shlex.quote(c) for c in cmd)}"
    print(cmd_line, flush=True)
    with log_path.open("a", encoding="utf-8") as log:
        log.write("\n" + cmd_line + "\n")
        log.flush()
        proc = subprocess.Popen(cmd, cwd=str(cwd), stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)
        assert proc.stdout is not None
        for line in proc.stdout:
            print(line, end="", flush=True)
            log.write(line)
            log.flush()
        proc.wait()
        exit_line = f"[exit_code] {proc.returncode}\n"
        print(exit_line, end="", flush=True)
        log.write(exit_line)
        log.flush()
        return int(proc.returncode)


def file_contains_pass(path: Path) -> bool:
    if not path.exists():
        return False
    text = path.read_text(encoding="utf-8", errors="replace")[:4000].upper()
    return "PASS" in text and "NEEDS_CHANGES" not in text and "CRITICAL" not in text and "MAJOR" not in text


def ensure_initial_gate(agent_dir: Path) -> None:
    gate = agent_dir / "completion_gate.json"
    if not gate.exists():
        atomic_json(
            gate,
            {
                "tasks_completed": False,
                "changed_files_listed": False,
                "verification_recorded": False,
                "verification_exit_codes_recorded": False,
                "code_review_passed": False,
                "task_verification_passed": False,
                "codex_review_passed": False,
                "no_major_findings": False,
                "handover_written": False,
                "ready_for_commit": False,
            },
        )


def update_gate(agent_dir: Path, **updates: bool) -> None:
    gate_path = agent_dir / "completion_gate.json"
    gate = json.loads(gate_path.read_text(encoding="utf-8")) if gate_path.exists() else {}
    gate.update(updates)
    atomic_json(gate_path, gate)


def selected_developer_arg(args: argparse.Namespace) -> str | None:
    return getattr(args, "developer_opt", None) or getattr(args, "developer", None)


def create_request(args: argparse.Namespace) -> tuple[Path, dict[str, Any]]:
    config = read_yaml_like(CONFIG_PATH)
    defaults = config.get("defaults", BUILTIN_DEFAULTS["defaults"])
    worktree = resolve_worktree(args.worktree, defaults)
    change = args.change or detect_change(worktree)
    agent_dir = worktree / "openspec" / "changes" / change / "agent"
    developer_default = defaults.get("developer", {})
    developer_session = args.session_id or developer_default.get("session_id") or "change-name"
    if developer_session == "change-name":
        developer_session = change
    sessions = {
        "developer": developer_session,
        "code_reviewer": f"{developer_session}-code-reviewer",
        "task_verifier": f"{developer_session}-task-verifier",
    }
    session_modes = {
        "developer": "resume" if args.session_id and args.session_id.startswith("ses_") else "title",
        "code_reviewer": "title",
        "task_verifier": "title",
    }
    developer_role_default = defaults.get("developer", defaults.get("agent", BUILTIN_DEFAULTS["defaults"]["developer"]))
    request = {
        "change": change,
        "worktree": str(worktree),
        "agent_dir": str(agent_dir),
        "background": not args.foreground,
        "auto_commit": False,
        "max_review_rounds": int(args.max_review_rounds or defaults.get("max_review_rounds", 3)),
        "status_poll_seconds": int(defaults.get("status_poll_seconds", 20)),
        "sessions": sessions,
        "session_modes": session_modes,
        "developer": parse_role_spec(selected_developer_arg(args), developer_role_default),
        "code_reviewer": parse_role_spec(args.code_reviewer, defaults["code_reviewer"]),
        "task_verifier": parse_role_spec(args.task_verifier, defaults["task_verifier"]),
        "codex_review": {
            "enabled": not args.no_codex_review and bool(deep_get(defaults, "codex_review", "enabled", default=True)),
            "command": deep_get(defaults, "codex_review", "command", default="codex --no-alt-screen"),
        },
    }
    agent_dir.mkdir(parents=True, exist_ok=True)
    atomic_json(agent_dir / "request.json", request)
    build_prompt_files(agent_dir, request)
    ensure_initial_gate(agent_dir)
    write_status(agent_dir, request, "created", "protocol_files_ready", 0)
    return agent_dir, request


def read_status(agent_dir: Path) -> dict[str, Any] | None:
    status_path = agent_dir / "status.json"
    if not status_path.exists():
        return None
    try:
        return json.loads(status_path.read_text(encoding="utf-8"))
    except Exception:
        return None


def next_resume_step(agent_dir: Path, request: dict[str, Any]) -> tuple[int, str]:
    status = read_status(agent_dir)
    if not status:
        return 1, "developer"
    state = status.get("state")
    phase = status.get("phase")
    round_no = int(status.get("round") or 1)
    if state == "ready_for_commit" or phase == "all_reviews_passed":
        return round_no, "done"
    if state == "blocked" and phase == "max_review_rounds_exceeded":
        return round_no, "done"
    if phase in {"developer_agent", "developer_agent_failed", "protocol_files_ready", "review_feedback_pending_fix"}:
        return max(1, round_no), "developer"
    if phase in {"code_reviewer", "code_reviewer_failed"}:
        return max(1, round_no), "code_reviewer"
    if phase in {"task_verifier", "task_verifier_failed"}:
        return max(1, round_no), "task_verifier"
    if phase == "codex_lead_review":
        return max(1, round_no), "codex_lead_review"
    return max(1, round_no), "developer"


def run_developer_round(agent_dir: Path, request: dict[str, Any], worktree: Path, log_path: Path, round_no: int) -> int:
    write_status(agent_dir, request, "implementing", "developer_agent", round_no)
    append_log(agent_dir, f"round {round_no}: starting developer agent")
    return run_cmd(
        build_runner_cmd(
            request["developer"],
            agent_dir / "agent_prompt.md",
            request,
            request["sessions"]["developer"],
            resume_existing_session=request.get("session_modes", {}).get("developer") == "resume",
        ),
        worktree,
        log_path,
    )


def run_code_review_round(agent_dir: Path, request: dict[str, Any], worktree: Path, log_path: Path, round_no: int) -> int:
    write_status(agent_dir, request, "code_reviewing", "code_reviewer", round_no)
    return run_cmd(
        build_runner_cmd(
            request["code_reviewer"],
            agent_dir / "code_reviewer_prompt.md",
            request,
            request["sessions"]["code_reviewer"],
            resume_existing_session=False,
        ),
        worktree,
        log_path,
    )


def run_task_verification_round(agent_dir: Path, request: dict[str, Any], worktree: Path, log_path: Path, round_no: int) -> int:
    write_status(agent_dir, request, "task_verifying", "task_verifier", round_no)
    return run_cmd(
        build_runner_cmd(
            request["task_verifier"],
            agent_dir / "task_verifier_prompt.md",
            request,
            request["sessions"]["task_verifier"],
            resume_existing_session=False,
        ),
        worktree,
        log_path,
    )


def run_codex_review_round(agent_dir: Path, request: dict[str, Any], worktree: Path, log_path: Path, round_no: int) -> bool:
    if not request["codex_review"].get("enabled"):
        return True
    write_status(agent_dir, request, "codex_reviewing", "codex_lead_review", round_no)
    codex_out = agent_dir / f"codex_review_round_{round_no}.md"
    cmd = shlex.split(request["codex_review"].get("command", "codex --no-alt-screen"))
    prompt = (agent_dir / "codex_review_prompt.md").read_text(encoding="utf-8")
    with codex_out.open("w", encoding="utf-8") as out, log_path.open("a", encoding="utf-8") as log:
        log.write(f"\n$ {' '.join(shlex.quote(c) for c in cmd)} < codex_review_prompt.md\n")
        log.flush()
        proc = subprocess.run(cmd, cwd=str(worktree), input=prompt, stdout=out, stderr=subprocess.STDOUT, text=True)
        log.write(f"[codex_exit_code] {proc.returncode}\n")
        log.flush()
    codex_pass = proc.returncode == 0 and file_contains_pass(codex_out)
    update_gate(agent_dir, codex_review_passed=codex_pass)
    return codex_pass


def prepare_next_fix_round(agent_dir: Path, request: dict[str, Any], round_no: int) -> None:
    append_log(agent_dir, f"round {round_no}: review failed, preparing another fix round")
    write_status(agent_dir, request, "fixing_after_review", "review_feedback_pending_fix", round_no)
    fix_prompt = agent_dir / "agent_prompt.md"
    marker = f"Round {round_no} reviews did not pass."
    text = fix_prompt.read_text(encoding="utf-8")
    if marker not in text:
        fix_prompt.write_text(
            text
            + f"\n\n{marker} Read code_review_round_{round_no}.md, task_verification_round_{round_no}.md, and codex_review_round_{round_no}.md if present. Fix all required issues, rerun verification, and update handoff artifacts.\n",
            encoding="utf-8",
        )


def run_pipeline(request_path: Path) -> int:
    request = json.loads(request_path.read_text(encoding="utf-8"))
    worktree = Path(request["worktree"])
    agent_dir = Path(request["agent_dir"])
    log_path = agent_dir / "progress.log"
    append_log(agent_dir, "pipeline started")

    round_no, step = next_resume_step(agent_dir, request)
    append_log(agent_dir, f"resume point: round {round_no}, step {step}")
    if step == "done":
        append_log(agent_dir, "pipeline already terminal; nothing to resume")
        return 0

    while round_no <= request["max_review_rounds"]:
        if step == "developer":
            code = run_developer_round(agent_dir, request, worktree, log_path, round_no)
            if code != 0:
                write_status(agent_dir, request, "failed", "developer_agent_failed", round_no, f"developer exit code {code}")
                return code
            step = "code_reviewer"

        if step == "code_reviewer":
            code_review_file = agent_dir / f"code_review_round_{round_no}.md"
            if not code_review_file.exists() or code_review_file.stat().st_size == 0:
                code = run_code_review_round(agent_dir, request, worktree, log_path, round_no)
                if code != 0:
                    write_status(agent_dir, request, "failed", "code_reviewer_failed", round_no, f"code reviewer exit code {code}")
                    return code
            step = "task_verifier"

        if step == "task_verifier":
            task_file = agent_dir / f"task_verification_round_{round_no}.md"
            if not task_file.exists() or task_file.stat().st_size == 0:
                code = run_task_verification_round(agent_dir, request, worktree, log_path, round_no)
                if code != 0:
                    write_status(agent_dir, request, "failed", "task_verifier_failed", round_no, f"task verifier exit code {code}")
                    return code
            step = "codex_lead_review"

        code_review_pass = file_contains_pass(agent_dir / f"code_review_round_{round_no}.md")
        task_pass = file_contains_pass(agent_dir / f"task_verification_round_{round_no}.md")
        update_gate(agent_dir, code_review_passed=code_review_pass, task_verification_passed=task_pass)

        codex_pass = True
        if step == "codex_lead_review":
            codex_out = agent_dir / f"codex_review_round_{round_no}.md"
            if not codex_out.exists() or codex_out.stat().st_size == 0:
                codex_pass = run_codex_review_round(agent_dir, request, worktree, log_path, round_no)
            else:
                codex_pass = file_contains_pass(codex_out)
                update_gate(agent_dir, codex_review_passed=codex_pass)

        if code_review_pass and task_pass and codex_pass:
            update_gate(agent_dir, no_major_findings=True, ready_for_commit=True)
            write_status(agent_dir, request, "ready_for_commit", "all_reviews_passed", round_no)
            atomic_json(agent_dir / "final_status.json", {"state": "ready_for_commit", "updated_at": now_iso(), "round": round_no})
            append_log(agent_dir, "pipeline completed: ready_for_commit")
            return 0

        prepare_next_fix_round(agent_dir, request, round_no)
        round_no += 1
        step = "developer"

    write_status(agent_dir, request, "blocked", "max_review_rounds_exceeded", request["max_review_rounds"], "review loop did not pass")
    append_log(agent_dir, "pipeline blocked: max review rounds exceeded")
    return 2


def start_background(agent_dir: Path) -> int:
    request = agent_dir / "request.json"
    session = f"agent-{agent_dir.parent.name}"
    cmd = ["tmux", "new-session", "-d", "-s", session, sys.executable, str(Path(__file__).resolve()), "run", str(request)]
    subprocess.run(cmd, check=True)
    watch_cmd = f"{shlex.quote(str(SKILL_DIR / 'scripts' / 'watch_agent_status.sh'))} {shlex.quote(str(agent_dir))} 5"
    subprocess.run(["tmux", "new-window", "-t", session, "-n", "status", "bash", "-lc", watch_cmd], check=False)
    print(f"started tmux session: {session}")
    print("tmux windows: 0=pipeline, 1=status")
    print(f"status: {agent_dir / 'status.json'}")
    print(f"log:    {agent_dir / 'progress.log'}")
    print(f"watch:  {SKILL_DIR / 'scripts' / 'watch_agent_status.sh'} {agent_dir}")
    return 0


def resolve_agent_dir(worktree: Path, change: str | None) -> Path:
    if not change:
        change = detect_change(worktree)
    return worktree / "openspec" / "changes" / change / "agent"


def cmd_status(worktree: Path, change: str | None) -> int:
    status = resolve_agent_dir(worktree, change) / "status.json"
    if not status.exists():
        print(f"status not found: {status}")
        return 1
    print(status.read_text(encoding="utf-8"))
    return 0


def cmd_logs(worktree: Path, change: str | None, tail: int) -> int:
    log_path = resolve_agent_dir(worktree, change) / "progress.log"
    print(f"log: {log_path}")
    if not log_path.exists():
        print("log not created yet")
        return 0
    lines = log_path.read_text(encoding="utf-8", errors="replace").splitlines()
    for line in lines[-tail:]:
        print(line)
    return 0


def cmd_stop(worktree: Path, change: str | None) -> int:
    agent_dir = resolve_agent_dir(worktree, change)
    name = f"agent-{agent_dir.parent.name}"
    proc = subprocess.run(["tmux", "kill-session", "-t", name], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    if proc.returncode == 0:
        print(f"stopped tmux session: {name}")
        return 0
    print(proc.stdout.strip() or f"tmux session not found: {name}")
    return proc.returncode


def cmd_resume(worktree: Path, change: str | None) -> int:
    agent_dir = resolve_agent_dir(worktree, change)
    request = agent_dir / "request.json"
    if not request.exists():
        print(f"request not found: {request}")
        return 1
    return start_background(agent_dir)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command")

    def add_common(p: argparse.ArgumentParser) -> None:
        p.add_argument("developer", nargs="?", help="runner:provider/model, e.g. opencode:volcengine-plan/glm-5.2")
        p.add_argument("--developer", dest="developer_opt", help="runner:provider/model alias for the positional developer")
        p.add_argument("--change")
        p.add_argument("--worktree")
        p.add_argument("--session-id", help="developer session id; reviewer/verifier sessions are derived automatically")
        p.add_argument("--code-reviewer")
        p.add_argument("--task-verifier")
        p.add_argument("--max-review-rounds")
        p.add_argument("--foreground", action="store_true")
        p.add_argument("--no-auto-start", action="store_true")
        p.add_argument("--no-codex-review", action="store_true")

    add_common(sub.add_parser("start"))
    add_common(sub.add_parser("prepare"))
    run_p = sub.add_parser("run")
    run_p.add_argument("request_json")
    status_p = sub.add_parser("status")
    status_p.add_argument("change", nargs="?")
    status_p.add_argument("--worktree")
    logs_p = sub.add_parser("logs")
    logs_p.add_argument("change", nargs="?")
    logs_p.add_argument("--worktree")
    logs_p.add_argument("--tail", type=int, default=80)
    stop_p = sub.add_parser("stop")
    stop_p.add_argument("change", nargs="?")
    stop_p.add_argument("--worktree")
    resume_p = sub.add_parser("resume")
    resume_p.add_argument("change", nargs="?")
    resume_p.add_argument("--worktree")

    args = parser.parse_args()
    if args.command == "run":
        return run_pipeline(Path(args.request_json).resolve())
    if args.command == "status":
        return cmd_status(Path(args.worktree or os.getcwd()).resolve(), args.change)
    if args.command == "logs":
        return cmd_logs(Path(args.worktree or os.getcwd()).resolve(), args.change, args.tail)
    if args.command == "stop":
        return cmd_stop(Path(args.worktree or os.getcwd()).resolve(), args.change)
    if args.command == "resume":
        return cmd_resume(Path(args.worktree or os.getcwd()).resolve(), args.change)
    if args.command in {"start", "prepare", None}:
        if args.command is None:
            args.command = "start"
        agent_dir, _request = create_request(args)
        if args.command == "prepare" or args.no_auto_start:
            print(f"prepared: {agent_dir}")
            print(f"run: {sys.executable} {Path(__file__).resolve()} run {agent_dir / 'request.json'}")
            return 0
        if args.foreground:
            return run_pipeline(agent_dir / "request.json")
        return start_background(agent_dir)
    parser.print_help()
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
