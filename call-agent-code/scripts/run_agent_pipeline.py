#!/usr/bin/env python3
"""File-based external-agent pipeline for call_agent_code."""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

SKILL_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_DIR / "scripts"))
from verdict_utils import (
    MIN_REVIEW_BODY_CHARS,
    TOOL_ERROR_MARKERS,
    VERDICT_RE,
    parse_verdict_file,
    should_retry_artifact,
    verdict_is_pass,
)
CONFIG_PATH = SKILL_DIR / "config.yaml"

DEVELOPER_ARTIFACTS = [
    "verification.md",
    "changed_files.txt",
    "self_review.md",
    "handover.md",
    "completion_gate.json",
    "status.json",
]

BUILTIN_DEFAULTS: dict[str, Any] = {
    "defaults": {
        "developer": {"runner": "opencode", "provider": "volcengine-plan", "model": "glm-5.2"},
        "code_reviewer": {"runner": "opencode", "provider": "volcengine-plan", "model": "minimax-m3"},
        "task_verifier": {"runner": "opencode", "provider": "volcengine-plan", "model": "glm-5.2"},
        "codex_review": {"enabled": True, "command": "codex exec -s read-only"},
        "background": True,
        "auto_commit": False,
        "max_review_rounds": 10,
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
    role.setdefault("runner", "opencode")
    role.setdefault("provider", "")
    return role


def normalize_session_id(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    if text.lower() in {"change-name", "none", "null", "auto"}:
        return None
    return text


def is_explicit_opencode_session_id(value: str | None) -> bool:
    return bool(value) and str(value).strip().startswith("ses_")


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


ROLE_KEYS = ("developer", "code_reviewer", "task_verifier")
SESSION_LIST_RE = re.compile(r"^(ses_\S+)\s{2,}(.*?)\s{2,}\S.*$")


def default_session_label(change: str, role_key: str) -> str:
    if role_key == "developer":
        return change
    if role_key == "code_reviewer":
        return f"{change}-code-reviewer"
    if role_key == "task_verifier":
        return f"{change}-task-verifier"
    raise KeyError(role_key)


def ensure_session_state(request: dict[str, Any]) -> dict[str, Any]:
    change = request["change"]
    legacy_sessions = dict(request.get("sessions") or {})
    labels = dict(request.get("session_labels") or {})
    ids = dict(request.get("session_ids") or {})
    for role_key in ROLE_KEYS:
        label = labels.get(role_key) or legacy_sessions.get(role_key) or default_session_label(change, role_key)
        legacy_value = normalize_session_id(legacy_sessions.get(role_key))
        session_id = normalize_session_id(ids.get(role_key))
        if not session_id and is_explicit_opencode_session_id(legacy_value):
            session_id = legacy_value
        labels[role_key] = str(label)
        ids[role_key] = session_id or ""
    request["session_labels"] = labels
    request["session_ids"] = ids
    request.pop("sessions", None)
    for role_key in ROLE_KEYS:
        request.setdefault(role_key, {}).pop("session_id", None)
    return request


def list_opencode_sessions() -> list[dict[str, str]]:
    proc = subprocess.run(["opencode", "session", "list"], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, timeout=30)
    if proc.returncode != 0:
        return []
    sessions: list[dict[str, str]] = []
    for raw_line in proc.stdout.splitlines():
        line = raw_line.rstrip()
        match = SESSION_LIST_RE.match(line)
        if match:
            sessions.append({"id": match.group(1), "title": match.group(2).strip()})
    return sessions


def find_latest_opencode_session_id_by_title(title: str) -> str | None:
    for item in list_opencode_sessions():
        if item["title"] == title:
            return item["id"]
    return None


def adopt_role_session_id(request_path: Path, request: dict[str, Any], role_key: str) -> str | None:
    ensure_session_state(request)
    role = request.get(role_key, {})
    if role.get("runner") != "opencode":
        return None
    title = request["session_labels"][role_key]
    session_id = find_latest_opencode_session_id_by_title(title)
    if session_id and request["session_ids"].get(role_key) != session_id:
        request["session_ids"][role_key] = session_id
        atomic_json(request_path, request)
    return session_id


def resolve_role_session(agent_dir: Path, request: dict[str, Any], role_key: str) -> tuple[str, str | None]:
    request_path = agent_dir / "request.json"
    ensure_session_state(request)
    label = request["session_labels"][role_key]
    session_id = normalize_session_id(request["session_ids"].get(role_key))
    if not session_id:
        session_id = adopt_role_session_id(request_path, request, role_key)
    return label, session_id


def resolve_retry_label(request: dict[str, Any], role_key: str, suffix: str) -> str:
    ensure_session_state(request)
    return f"{request['session_labels'][role_key]}-{suffix}"


def resolve_worktree(value: str | None, defaults: dict[str, Any]) -> Path:
    raw = value or defaults.get("worktree") or os.getcwd()
    if raw == "wk1":
        cwd = Path(os.getcwd()).resolve()
        for parent in [cwd] + list(cwd.parents):
            candidate = parent / ".worktree" / "wk1"
            if candidate.exists():
                return candidate.resolve()
        return cwd / ".worktree" / "wk1"
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
    ensure_session_state(request)
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
            "session_labels": request["session_labels"],
            "session_ids": request["session_ids"],
            "blocking_issue": blocking_issue,
            "pipeline_pid": os.getpid(),
        },
    )


def build_prompt_files(agent_dir: Path, request: dict[str, Any]) -> None:
    change = request["change"]
    agent_prompt = f"""You are the developer agent for OpenSpec change `{change}`.

Read the round task file for implementation instructions.
Fix notes from previous review rounds (if any) are appended below.
"""
    code_review_prompt = f"""You are subagent1, the code reviewer for OpenSpec change `{change}`.

Review the implementation diff in worktree `{request['worktree']}`. Focus on bugs, regressions, missing tests, unsafe behavior, and incompatibilities. The runtime pipeline will generate a round-specific prompt with the exact output file path and required Verdict format.
"""
    task_prompt = f"""You are subagent2, the task verifier for OpenSpec change `{change}`.

Verify that the OpenSpec requirements and tasks are actually complete. Check `verification.md`, `changed_files.txt`, `handover.md`, `completion_gate.json`, and the OpenSpec tasks. Do not focus primarily on code style. The runtime pipeline will generate a round-specific prompt with the exact output file path and required Verdict format.
"""
    codex_prompt = f"""You are Codex lead reviewer for OpenSpec change `{change}`.

Read only the OpenSpec change (proposal, design, tasks, specs) and git diff in worktree `{request['worktree']}`. Do NOT read developer handoff artifacts, secondary reviews, or completion gate. Form your own independent judgment from spec requirements and actual code. The runtime pipeline will generate a round-specific prompt with the exact required Verdict format.

Important: do NOT try to write workspace files yourself. Emit only the final review markdown to stdout; the CLI wrapper will save it to the required artifact path.
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


def verdict_contract(output_path: Path) -> str:
    return f"""Output contract:
- You MUST write exactly this file before exiting: `{output_path}`
- The first non-empty verdict line in that file MUST be exactly one of:
  - `- **Verdict:** PASS`
  - `- **Verdict:** NEEDS_CHANGES`
- Use PASS only when the scope you are responsible for is fully satisfied.
- Use NEEDS_CHANGES when any required issue remains.
- Before exiting, verify the file exists, is non-empty, and contains exactly one verdict meaning.
"""


def prune_runtime_noise(agent_dir: Path) -> None:
    runtime_dir = agent_dir / ".opencode_runtime"
    if runtime_dir.exists():
        shutil.rmtree(runtime_dir)
        append_log(agent_dir, "cleanup: removed agent/.opencode_runtime before review step")


def normalize_codex_review_artifact(path: Path) -> bool:
    """Best-effort normalize Codex stdout into a valid verdict artifact.

    Returns True only when the file was rewritten.
    """
    if not path.exists() or path.stat().st_size == 0:
        return False
    text = path.read_text(encoding="utf-8", errors="replace")
    verdict, _ = parse_verdict_file(path)
    if verdict in {"PASS", "NEEDS_CHANGES"}:
        return False

    candidates: list[str] = []

    fence_match = re.search(
        r"Intended review artifact content:\s*```(?:md|markdown)?\n(.*?)\n```",
        text,
        re.IGNORECASE | re.DOTALL,
    )
    if fence_match:
        candidates.append(fence_match.group(1).strip())

    verdict_match = VERDICT_RE.search(text)
    if verdict_match:
        candidates.append(text[verdict_match.start():].strip())

    for candidate in candidates:
        tmp = path.with_suffix(path.suffix + ".normalize.tmp")
        tmp.write_text(candidate.rstrip() + "\n", encoding="utf-8")
        parsed, _reason = parse_verdict_file(tmp)
        if parsed in {"PASS", "NEEDS_CHANGES"}:
            tmp.replace(path)
            return True
        tmp.unlink(missing_ok=True)
    return False


def write_round_task(agent_dir: Path, request: dict[str, Any], role: str, round_no: int) -> Path:
    change = request["change"]
    worktree = request["worktree"]
    if role == "developer":
        task_path = agent_dir / f"developer_task_round_{round_no}.md"
        body = f"""# Developer Task - Round {round_no}

You are the developer agent for OpenSpec change `{change}`.

## Required Inputs

- Worktree: `{worktree}`
- OpenSpec change directory: `openspec/changes/{change}/`
- Handoff directory: `openspec/changes/{change}/agent/`

## Steps You Must Execute

1. Read `agent_prompt.md` in the handoff directory — it may contain fix notes from
   previous review rounds.
2. Read `proposal.md`, `design.md` if present, `tasks.md`, and all spec delta files
   under `specs/`.
3. Implement the change exactly as specified in the OpenSpec documents.
4. Find the verification items in `tasks.md` and run every listed test command.
   Do not skip any.
5. For each test, record in `verification.md`: the exact bash command, the raw
   stdout output, and the exit code. Never describe what a test "would" produce —
   paste what actually ran.
6. If a test fails, record the failure honestly with the actual exit code and error
   output. Do not hide failures.
7. If a file read, bash command, or external access is rejected by the platform,
   treat it as a task blocker. Write `status.json` with `state=blocked` and a
   concrete `blocking_issue`. Do NOT exit as if the task succeeded.
8. Write `changed_files.txt`, `self_review.md`, `handover.md`, and
   `completion_gate.json`. Do not commit.
9. Before exiting, verify all required handoff files exist and are non-empty.
"""
        task_path.write_text(body, encoding="utf-8")
        append_log(agent_dir, f"generated task: {task_path.name}")
        return task_path
    if role == "code_reviewer":
        task_path = agent_dir / f"code_review_task_round_{round_no}.md"
        output = agent_dir / f"code_review_round_{round_no}.md"
        body = f"""# Code Review Task - Round {round_no}

You are subagent1, the code reviewer for OpenSpec change `{change}`.

## Required Inputs

- Worktree: `{worktree}`
- OpenSpec change directory: `openspec/changes/{change}/`
- Developer handoff directory: `openspec/changes/{change}/agent/`
- Required output file: `{output}`

## Steps You Must Execute

1. Read `proposal.md`, `design.md` if present, `tasks.md`, and all spec delta files under `specs/`.
2. Read `changed_files.txt`, `verification.md`, `self_review.md`, `handover.md`, and `completion_gate.json`.
3. Inspect `git status --porcelain`, `git diff HEAD --stat`, and the relevant `git diff HEAD` content.
4. Do not recursively scan the whole change directory. Do not inspect `agent/.opencode_runtime/`, `node_modules/`, `.git/`, or temporary protocol files unless the task explicitly names them. Focus on the named OpenSpec files, handoff artifacts, and `git diff`.
5. Review for bugs, regressions, unsafe behavior, missing tests, architecture/config/checkpoint/resume/logging incompatibilities, and unstated scope changes. Additionally: open `verification.md` and verify it contains raw command output (actual stdout excerpts, exit codes, artifact paths), not just prose claims like "PASS" or "验证通过". If verification.md lacks concrete output for any required test, flag it as a NEEDS_CHANGES finding.
6. Decide `PASS` only if the implemented code and verification evidence satisfy the approved OpenSpec.
7. Write the required output file once with the final verdict line and the full review body. Do not write a temporary placeholder; write the complete file in one pass. Do not merely describe the review in chat.
8. Before exiting, verify the output file exists, is non-empty, and starts with a valid verdict line.

{verdict_contract(output)}

## Output Body Requirements

- Put severity-ranked findings first.
- If PASS, include the concrete evidence you checked and residual risks.
- If NEEDS_CHANGES, list concrete required fixes that the developer can act on.
"""
    elif role == "task_verifier":
        task_path = agent_dir / f"task_verification_task_round_{round_no}.md"
        output = agent_dir / f"task_verification_round_{round_no}.md"
        body = f"""# Task Verification Task - Round {round_no}

You are subagent2, the task verifier for OpenSpec change `{change}`.

## Required Inputs

- Worktree: `{worktree}`
- OpenSpec change directory: `openspec/changes/{change}/`
- Developer handoff directory: `openspec/changes/{change}/agent/`
- Required output file: `{output}`

## Steps You Must Execute

1. Read `proposal.md`, `design.md` if present, `tasks.md`, and all spec delta files under `specs/`.
2. Read `changed_files.txt`, `verification.md`, `self_review.md`, `handover.md`, and `completion_gate.json`.
3. Do not recursively scan the whole change directory. Do not inspect `agent/.opencode_runtime/`, `node_modules/`, `.git/`, or temporary protocol files unless the task explicitly names them. Focus on the named OpenSpec files, handoff artifacts, and `git diff`.
4. Check whether every task/spec requirement is actually satisfied by files, code, and recorded verification evidence.
5. Open `verification.md`. For each required verification item in `tasks.md`, confirm the file contains: the exact command, raw stdout excerpts, and the exit code. If any item has only prose claims without concrete output, flag it as a NEEDS_CHANGES finding with the specific missing item. Do not infer test success from prose.
6. Confirm generated review files and completion gate fields are consistent with the current round.
7. Write the required output file once with the final verdict line and the full verification body. Do not write a temporary placeholder; write the complete file in one pass. Do not merely describe the verification in chat.
8. Before exiting, verify the output file exists, is non-empty, and starts with a valid verdict line.

{verdict_contract(output)}

## Output Body Requirements

- Provide evidence per requirement/task.
- If PASS, explain what evidence proves completion.
- If NEEDS_CHANGES, list missing or insufficient evidence and concrete fixes.
"""
    elif role == "codex_review":
        task_path = agent_dir / f"codex_review_task_round_{round_no}.md"
        output = agent_dir / f"codex_review_round_{round_no}.md"
        body = f"""# Codex Lead Review Task - Round {round_no}

You are Codex lead reviewer for OpenSpec change `{change}`.

## Required Inputs

- Worktree: `{worktree}`
- OpenSpec change directory: `openspec/changes/{change}/`
- Final artifact path (written by CLI wrapper, not by you): `{output}`

## Steps You Must Execute

1. Read `proposal.md`, `design.md` if present, `tasks.md`, and all spec delta files under `specs/`.
2. Inspect `git diff HEAD --stat` and the relevant `git diff HEAD` content.
3. Do NOT read developer handoff artifacts (`changed_files.txt`, `verification.md`, `self_review.md`, `handover.md`, `completion_gate.json`). Do NOT read secondary reviews (`code_review_round_*.md`, `task_verification_round_*.md`). Form your own independent judgment.
4. Do not recursively scan the whole change directory. Do not inspect `agent/`, `node_modules/`, `.git/`, or temporary protocol files. Focus on the OpenSpec spec files and `git diff`.
5. Check architecture-level compatibility, code correctness, and whether the change satisfies the spec requirements.
6. Do NOT try to write workspace files yourself. Output the final review markdown to stdout only; the `codex exec -o` wrapper will save it to the artifact path above.
7. The first non-empty line of your stdout MUST be exactly one of:
   - `- **Verdict:** PASS`
   - `- **Verdict:** NEEDS_CHANGES`
8. Your very first output line MUST be the final verdict line. Do not put findings, narration, numbering, or preambles before it.
9. After the verdict line, emit the full review body in one pass. Do not emit tool narration, preambles, code fences around the final answer, "intended artifact" wrappers, or explanations about file-writing limitations.

## Output Body Requirements

- If NEEDS_CHANGES, list concrete required fixes.
- If PASS, include the evidence basis and residual risks.
"""
    else:
        raise ValueError(f"unsupported task role: {role}")
    task_path.write_text(body, encoding="utf-8")
    append_log(agent_dir, f"generated task: {task_path.name}; expected output: {output.name}")
    return task_path


def write_round_prompt(agent_dir: Path, request: dict[str, Any], role: str, round_no: int) -> Path:
    task_path = write_round_task(agent_dir, request, role, round_no)
    prompt_path = agent_dir / f"{role}_prompt_round_{round_no}.md"
    if role == "codex_review":
        prompt = f"""Read `{task_path}` and follow it exactly.

You MUST execute every required step in that task file.
Do NOT try to write workspace files yourself.
Emit only the final review markdown to stdout; the CLI wrapper will save it to the required artifact path.
Your first output line must be exactly the final verdict line.
Do not finish with chat narration, tool narration, file-writing explanations, or an "intended artifact" wrapper.
"""
    else:
        prompt = f"""Read `{task_path}` and follow it exactly.

You MUST execute every required step in that task file.
You MUST write the required output file named in that task file before exiting.
Do not finish with only a chat summary.
"""
    prompt_path.write_text(prompt, encoding="utf-8")
    return prompt_path


def build_runner_cmd(role: dict[str, str], prompt_file: Path, request: dict[str, Any], session_label: str | None, session_id: str | None, *, resume_existing_session: bool = False) -> list[str]:
    runner = role["runner"]
    prompt = prompt_file.read_text(encoding="utf-8")
    normalized_session_id = normalize_session_id(session_id)
    normalized_session_label = normalize_session_id(session_label)
    if runner == "opencode":
        cmd = ["opencode", "run", "--model", role_model_arg(role, include_provider=True)]
        if resume_existing_session and is_explicit_opencode_session_id(normalized_session_id):
            cmd += ["--session", normalized_session_id]
        elif normalized_session_label:
            cmd += ["--title", normalized_session_label]
        cmd.append(prompt)
        return cmd
    if runner == "codebuddy":
        return ["codebuddy", "-p", "--model", role_model_arg(role, include_provider=False), "--permission-mode", "acceptEdits", prompt]
    raise SystemExit(f"unsupported runner: {runner}")


def run_cmd(cmd: list[str], cwd: Path, log_path: Path, env_extra: dict[str, str] | None = None, timeout: int = 1800) -> int:
    cmd_line = f"$ {' '.join(shlex.quote(c) for c in cmd)}"
    print(cmd_line, flush=True)
    with log_path.open("a", encoding="utf-8") as log:
        log.write("\n" + cmd_line + "\n")
        log.flush()
        env = os.environ.copy()
        if env_extra:
            env.update(env_extra)
        try:
            proc = subprocess.run(cmd, cwd=str(cwd), env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, timeout=timeout)
            if proc.stdout:
                print(proc.stdout, end="", flush=True)
                log.write(proc.stdout)
            exit_line = f"[exit_code] {proc.returncode}\n"
            exit_code = proc.returncode
        except subprocess.TimeoutExpired as exc:
            partial = exc.stdout or ""
            if partial:
                print(partial, end="", flush=True)
                log.write(partial)
            exit_line = f"[timeout] killed after {timeout}s\n[exit_code] -1\n"
            exit_code = -1
            print(f"[timeout] killed after {timeout}s", flush=True)
        print(exit_line, end="", flush=True)
        log.write(exit_line)
        log.flush()
        return exit_code

def validate_developer_artifacts(agent_dir: Path, worktree: Path | None = None) -> tuple[bool, str]:
    for name in DEVELOPER_ARTIFACTS:
        path = agent_dir / name
        if not path.exists():
            return False, f"missing developer artifact: {name}"
        if path.stat().st_size == 0:
            return False, f"empty developer artifact: {name}"
    try:
        gate = json.loads((agent_dir / "completion_gate.json").read_text(encoding="utf-8"))
    except Exception as exc:
        return False, f"invalid completion_gate.json: {exc}"
    for key in ("tasks_completed", "changed_files_listed", "verification_recorded", "verification_exit_codes_recorded", "handover_written"):
        if gate.get(key) is not True:
            return False, f"completion_gate.{key} is not true"
    wt = worktree or _git_root(agent_dir)
    if wt is None:
        return False, "cannot determine git worktree root"
    res = subprocess.run(
        ["git", "diff", "HEAD", "--stat"],
        capture_output=True, text=True, cwd=str(wt),
    )
    if res.returncode != 0:
        return False, f"git diff HEAD failed (exit {res.returncode}): {res.stderr.strip()}"
    if not res.stdout.strip():
        untracked = subprocess.run(
            ["git", "ls-files", "--others", "--exclude-standard"],
            capture_output=True, text=True, cwd=str(wt),
        )
        if not untracked.stdout.strip():
            return False, "no implementation: git diff HEAD is empty"
    return True, "developer artifacts valid"


def _git_root(path: Path) -> Path | None:
    res = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        capture_output=True, text=True, cwd=str(path),
    )
    if res.returncode == 0:
        return Path(res.stdout.strip())
    return None


def earliest_resume_point_for_round(agent_dir: Path, round_no: int, worktree: Path | None = None) -> tuple[int, str, str]:
    """Return the earliest stage that must run for this round."""
    ok, reason = validate_developer_artifacts(agent_dir, worktree)
    if not ok:
        return round_no, "developer", reason

    code_review = agent_dir / f"code_review_round_{round_no}.md"
    code_verdict, code_reason = parse_verdict_file(code_review)
    if code_verdict == "INVALID":
        return round_no, "code_reviewer", code_reason
    if code_verdict == "NEEDS_CHANGES":
        return round_no + 1, "developer", code_reason

    task_file = agent_dir / f"task_verification_round_{round_no}.md"
    task_verdict, task_reason = parse_verdict_file(task_file)
    if task_verdict == "INVALID":
        return round_no, "task_verifier", task_reason
    if task_verdict == "NEEDS_CHANGES":
        return round_no + 1, "developer", task_reason

    codex_file = agent_dir / f"codex_review_round_{round_no}.md"
    codex_verdict, codex_reason = parse_verdict_file(codex_file)
    if codex_verdict == "INVALID":
        if codex_file.exists():
            codex_file.unlink()
        return round_no, "codex_lead_review", codex_reason
    if codex_verdict == "NEEDS_CHANGES":
        return round_no + 1, "developer", codex_reason

    return round_no, "done", "all review verdicts PASS"


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
    developer_role_default = defaults.get("developer", defaults.get("agent", BUILTIN_DEFAULTS["defaults"]["developer"]))
    request = {
        "change": change,
        "worktree": str(worktree),
        "agent_dir": str(agent_dir),
        "background": bool(defaults.get("background", True)) and not args.foreground,
        "auto_commit": False,
        "max_review_rounds": int(args.max_review_rounds or defaults.get("max_review_rounds", 3)),
        "status_poll_seconds": int(defaults.get("status_poll_seconds", 20)),
        "session_labels": {
            "developer": default_session_label(change, "developer"),
            "code_reviewer": default_session_label(change, "code_reviewer"),
            "task_verifier": default_session_label(change, "task_verifier"),
        },
        "session_ids": {
            "developer": "",
            "code_reviewer": "",
            "task_verifier": "",
        },
        "developer": parse_role_spec(selected_developer_arg(args), developer_role_default),
        "code_reviewer": parse_role_spec(args.code_reviewer, defaults.get("code_reviewer", BUILTIN_DEFAULTS["defaults"]["code_reviewer"])),
        "task_verifier": parse_role_spec(args.task_verifier, defaults.get("task_verifier", BUILTIN_DEFAULTS["defaults"]["task_verifier"])),
        "codex_review": {
            "enabled": not args.no_codex_review and bool(deep_get(defaults, "codex_review", "enabled", default=True)),
            "command": deep_get(defaults, "codex_review", "command", default="codex exec -s read-only"),
        },
    }
    ensure_session_state(request)
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
        recovered_round, recovered_step, _reason = earliest_resume_point_for_round(agent_dir, max(1, round_no), Path(request.get("worktree", "")))
        if recovered_step != "done":
            return recovered_round, recovered_step
        return round_no, "done"

    if phase == "previous_review_round_invalid" and round_no > 1:
        recovered_round, recovered_step, _reason = earliest_resume_point_for_round(agent_dir, round_no - 1, Path(request.get("worktree", "")))
        return recovered_round, recovered_step

    if phase in {"protocol_files_ready", "developer_agent", "developer_agent_failed", "developer_invalid_output"}:
        recovered_round, recovered_step, _reason = earliest_resume_point_for_round(agent_dir, max(1, round_no), Path(request.get("worktree", "")))
        return recovered_round, recovered_step
    if phase in {"developer_agent_done", "code_reviewing", "code_reviewer", "code_reviewer_failed", "code_reviewer_invalid_output"}:
        recovered_round, recovered_step, _reason = earliest_resume_point_for_round(agent_dir, max(1, round_no), Path(request.get("worktree", "")))
        return recovered_round, recovered_step
    if phase in {"code_reviewer_done", "task_verifying", "task_verifier", "task_verifier_failed", "task_verifier_invalid_output"}:
        recovered_round, recovered_step, _reason = earliest_resume_point_for_round(agent_dir, max(1, round_no), Path(request.get("worktree", "")))
        return recovered_round, recovered_step
    if phase in {"task_verifier_done", "codex_reviewing", "codex_lead_review", "codex_review_failed", "codex_review_invalid_output"}:
        recovered_round, recovered_step, _reason = earliest_resume_point_for_round(agent_dir, max(1, round_no), Path(request.get("worktree", "")))
        return recovered_round, recovered_step
    if phase == "review_feedback_pending_fix":
        recovered_round, recovered_step, _reason = earliest_resume_point_for_round(agent_dir, max(1, round_no), Path(request.get("worktree", "")))
        return recovered_round, recovered_step
    return max(1, round_no), "developer"


def run_developer_round(agent_dir: Path, request: dict[str, Any], worktree: Path, log_path: Path, round_no: int) -> int:
    write_status(agent_dir, request, "implementing", "developer_agent", round_no)
    append_log(agent_dir, f"round {round_no}: starting developer agent")
    request_path = agent_dir / "request.json"
    prompt_path = write_round_prompt(agent_dir, request, "developer", round_no)
    session_label, session_id = resolve_role_session(agent_dir, request, "developer")
    if session_id:
        append_log(agent_dir, f"round {round_no}: developer reusing session {session_id}")
    log_before = (agent_dir / "progress.log").stat().st_size
    code = run_cmd(
        build_runner_cmd(request["developer"], prompt_path, request, session_label, session_id, resume_existing_session=bool(session_id)),
        worktree, log_path,
    )
    if code != 0 and session_id:
        with (agent_dir / "progress.log").open(encoding="utf-8", errors="replace") as f:
            f.seek(log_before)
            new_output = f.read()
        if "Session not found" in new_output:
            append_log(agent_dir, f"round {round_no}: stale developer session {session_id}; falling back to title launch")
            request["session_ids"]["developer"] = ""
            atomic_json(request_path, request)
            code = run_cmd(
                build_runner_cmd(request["developer"], prompt_path, request, session_label, None, resume_existing_session=False),
                worktree, log_path,
            )
    adopted = adopt_role_session_id(request_path, request, "developer")
    if adopted:
        append_log(agent_dir, f"round {round_no}: developer session recorded as {adopted}")
    return code


def run_code_review_round(agent_dir: Path, request: dict[str, Any], worktree: Path, log_path: Path, round_no: int) -> int:
    prune_runtime_noise(agent_dir)
    write_status(agent_dir, request, "code_reviewing", "code_reviewer", round_no)
    request_path = agent_dir / "request.json"
    prompt_path = write_round_prompt(agent_dir, request, "code_reviewer", round_no)
    session_label, session_id = resolve_role_session(agent_dir, request, "code_reviewer")
    if session_id:
        append_log(agent_dir, f"round {round_no}: code reviewer reusing session {session_id}")
    code = run_cmd(
        build_runner_cmd(
            request["code_reviewer"],
            prompt_path,
            request,
            session_label,
            session_id,
            resume_existing_session=bool(session_id),
        ),
        worktree,
        log_path,
    )
    adopted = adopt_role_session_id(request_path, request, "code_reviewer")
    if adopted:
        append_log(agent_dir, f"round {round_no}: code reviewer session recorded as {adopted}")
    return code


def run_code_review_artifact_retry(agent_dir: Path, request: dict[str, Any], worktree: Path, log_path: Path, round_no: int) -> int:
    output = agent_dir / f"code_review_round_{round_no}.md"
    prompt_path = agent_dir / f"code_reviewer_artifact_retry_round_{round_no}.md"
    prompt = f"""You previously completed the analysis but did not create the required review artifact.

Do not re-review the code.
Do not continue exploring.
Only create this exact file now: `{output}`

Requirements:
- The first non-empty line must be exactly one of:
  - `- **Verdict:** PASS`
  - `- **Verdict:** NEEDS_CHANGES`
- The file must be non-empty.
- If you already know your decision from the previous analysis, write it now.
- Before exiting, read the file back and confirm it exists.
"""
    prompt_path.write_text(prompt, encoding="utf-8")
    append_log(agent_dir, f"round {round_no}: code reviewer artifact missing; running one retry focused only on writing {output.name}")
    retry_role = dict(request["code_reviewer"])
    retry_session = resolve_retry_label(request, "code_reviewer", f"artifact-retry-r{round_no}")
    return run_cmd(
        build_runner_cmd(
            retry_role,
            prompt_path,
            request,
            retry_session,
            None,
            resume_existing_session=False,
        ),
        worktree,
        log_path,
    )



def run_task_verification_artifact_retry(agent_dir: Path, request: dict[str, Any], worktree: Path, log_path: Path, round_no: int) -> int:
    output = agent_dir / f"task_verification_round_{round_no}.md"
    prompt_path = agent_dir / f"task_verifier_artifact_retry_round_{round_no}.md"
    prompt = f"""You previously completed the verification analysis but did not create the required verification artifact.

Do not re-verify the task.
Do not continue exploring.
Only create this exact file now: `{output}`

Requirements:
- The first non-empty line must be exactly one of:
  - `- **Verdict:** PASS`
  - `- **Verdict:** NEEDS_CHANGES`
- The file must be non-empty.
- If you already know your decision from the previous analysis, write it now.
- Before exiting, read the file back and confirm it exists.
"""
    prompt_path.write_text(prompt, encoding="utf-8")
    append_log(agent_dir, f"round {round_no}: task verifier artifact missing; running one retry focused only on writing {output.name}")
    retry_role = dict(request["task_verifier"])
    retry_session = resolve_retry_label(request, "task_verifier", f"artifact-retry-r{round_no}")
    return run_cmd(
        build_runner_cmd(
            retry_role,
            prompt_path,
            request,
            retry_session,
            None,
            resume_existing_session=False,
        ),
        worktree,
        log_path,
    )

def run_task_verification_round(agent_dir: Path, request: dict[str, Any], worktree: Path, log_path: Path, round_no: int) -> int:
    prune_runtime_noise(agent_dir)
    write_status(agent_dir, request, "task_verifying", "task_verifier", round_no)
    request_path = agent_dir / "request.json"
    prompt_path = write_round_prompt(agent_dir, request, "task_verifier", round_no)
    session_label, session_id = resolve_role_session(agent_dir, request, "task_verifier")
    if session_id:
        append_log(agent_dir, f"round {round_no}: task verifier reusing session {session_id}")
    code = run_cmd(
        build_runner_cmd(
            request["task_verifier"],
            prompt_path,
            request,
            session_label,
            session_id,
            resume_existing_session=bool(session_id),
        ),
        worktree,
        log_path,
    )
    adopted = adopt_role_session_id(request_path, request, "task_verifier")
    if adopted:
        append_log(agent_dir, f"round {round_no}: task verifier session recorded as {adopted}")
    return code


def run_codex_review_round(agent_dir: Path, request: dict[str, Any], worktree: Path, log_path: Path, round_no: int) -> bool:
    if not request["codex_review"].get("enabled"):
        return True
    prune_runtime_noise(agent_dir)
    write_status(agent_dir, request, "codex_reviewing", "codex_lead_review", round_no)
    codex_out = agent_dir / f"codex_review_round_{round_no}.md"
    cmd = shlex.split(request["codex_review"].get("command", "codex exec -s read-only"))
    prompt_path = write_round_prompt(agent_dir, request, "codex_review", round_no)
    if cmd[:2] == ["codex", "exec"]:
        cmd = cmd + ["-C", str(worktree), "-o", str(codex_out), str(prompt_path)]
    if codex_out.exists():
        codex_out.unlink()
    with log_path.open("a", encoding="utf-8") as log:
        log.write(f"\n$ {' '.join(shlex.quote(c) for c in cmd)}\n")
        log.flush()
        proc = subprocess.run(cmd, cwd=str(worktree), stdout=log, stderr=subprocess.STDOUT, text=True)
        log.write(f"[codex_exit_code] {proc.returncode}\n")
        log.flush()
    if proc.returncode != 0:
        codex_err = f"codex exec exit code {proc.returncode}, no output file"
        tail = (agent_dir / "progress.log").read_text(encoding="utf-8", errors="replace").splitlines()[-30:]
        for line in tail:
            if any(k in line for k in ("out of credits", "api key", "authentication", "rate limit", "billing", "quota")):
                codex_err = line.strip()
                break
        write_status(agent_dir, request, "failed", "codex_review_failed", round_no, codex_err)
        append_log(agent_dir, f"hard gate failed: {codex_err}")
        return False
    normalized = normalize_codex_review_artifact(codex_out)
    if normalized:
        append_log(agent_dir, f"normalized codex artifact: {codex_out.name}")
    codex_pass = verdict_is_pass(codex_out)
    update_gate(agent_dir, codex_review_passed=codex_pass)
    return codex_pass


def prepare_next_fix_round(agent_dir: Path, request: dict[str, Any], round_no: int) -> None:
    append_log(agent_dir, f"round {round_no}: review failed, preparing another fix round")
    write_status(agent_dir, request, "fixing_after_review", "review_feedback_pending_fix", round_no)
    fix_prompt = agent_dir / "agent_prompt.md"
    marker = f"## Round {round_no} Fix Checklist"
    content = fix_prompt.read_text(encoding="utf-8")
    if marker not in content:
        tmp = fix_prompt.with_suffix(fix_prompt.suffix + ".tmp")
        tmp.write_text(
            content
            + f"\n\n{marker}\n\n"
            + f"The following reviews found issues. Fix every issue listed, then re-run verification.\n\n"
            + f"- Read agent/code_review_round_{round_no}.md\n"
            + f"- Read agent/task_verification_round_{round_no}.md\n"
            + f"- Read agent/codex_review_round_{round_no}.md (if it exists)\n\n"
            + f"Do NOT start by re-exploring the codebase. Read the review files first.\n",
            encoding="utf-8",
        )
        tmp.replace(fix_prompt)


def finish_failed_review_round(agent_dir: Path, request: dict[str, Any], round_no: int) -> None:
    prepare_next_fix_round(agent_dir, request, round_no)


def refresh_request_from_config(request_path: Path, request: dict[str, Any]) -> dict[str, Any]:
    config = read_yaml_like(CONFIG_PATH)
    defaults = config.get("defaults", BUILTIN_DEFAULTS["defaults"])
    codex_defaults = defaults.get("codex_review", {})
    codex = dict(request.get("codex_review", {}))
    codex["command"] = codex_defaults.get("command", "codex exec -s read-only")
    codex["enabled"] = bool(codex.get("enabled", codex_defaults.get("enabled", True)))
    request["codex_review"] = codex
    request["status_poll_seconds"] = int(defaults.get("status_poll_seconds", request.get("status_poll_seconds", 20)))
    for role_key, cfg_key in [("developer", "developer"), ("code_reviewer", "code_reviewer"), ("task_verifier", "task_verifier")]:
        if request[role_key]["model"] == BUILTIN_DEFAULTS["defaults"][cfg_key]["model"]:
            cfg_default = defaults.get(cfg_key, BUILTIN_DEFAULTS["defaults"][cfg_key])
            request[role_key] = parse_role_spec(None, cfg_default)
    ensure_session_state(request)
    request.pop("opencode_config_dir", None)
    request.pop("session_modes", None)
    atomic_json(request_path, request)
    return request


def cleanup_temporary_protocol_files(agent_dir: Path) -> None:
    patterns = (
        "developer_task_round_*.md",
        "code_review_task_round_*.md",
        "task_verification_task_round_*.md",
        "codex_review_task_round_*.md",
        "developer_prompt_round_*.md",
        "code_reviewer_prompt_round_*.md",
        "code_reviewer_artifact_retry_round_*.md",
        "task_verifier_artifact_retry_round_*.md",
        "task_verifier_prompt_round_*.md",
        "codex_review_prompt_round_*.md",
    )
    removed = 0
    for pattern in patterns:
        for path in agent_dir.glob(pattern):
            path.unlink(missing_ok=True)
            removed += 1
    runtime_dir = agent_dir / ".opencode_runtime"
    if runtime_dir.exists():
        shutil.rmtree(runtime_dir)
        removed += 1
    append_log(agent_dir, f"cleanup: removed {removed} temporary protocol files after ready_for_commit")


def _best_blocking_issue(agent_dir: Path, fallback: str) -> str:
    status = read_status(agent_dir)
    if status and status.get("blocking_issue"):
        return status["blocking_issue"]
    return fallback


def run_pipeline(request_path: Path) -> int:
    request = json.loads(request_path.read_text(encoding="utf-8"))
    request = refresh_request_from_config(request_path, request)
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
            ok, reason = validate_developer_artifacts(agent_dir, worktree)
            if not ok:
                write_status(agent_dir, request, "failed", "developer_invalid_output", round_no, reason)
                append_log(agent_dir, f"hard gate failed: {reason}")
                return 3
            step = "code_reviewer"

        if step == "code_reviewer":
            code_review_file = agent_dir / f"code_review_round_{round_no}.md"
            if not code_review_file.exists() or code_review_file.stat().st_size == 0:
                code = run_code_review_round(agent_dir, request, worktree, log_path, round_no)
                if code != 0:
                    write_status(agent_dir, request, "failed", "code_reviewer_failed", round_no, f"code reviewer exit code {code}")
                    return code
            code_review_verdict, reason = parse_verdict_file(code_review_file)
            if code_review_verdict == "INVALID" and should_retry_artifact(reason):
                code = run_code_review_artifact_retry(agent_dir, request, worktree, log_path, round_no)
                if code != 0:
                    write_status(agent_dir, request, "failed", "code_reviewer_failed", round_no, f"code reviewer artifact retry exit code {code}")
                    return code
                code_review_verdict, reason = parse_verdict_file(code_review_file)
            if code_review_verdict == "INVALID":
                write_status(agent_dir, request, "failed", "code_reviewer_invalid_output", round_no, reason)
                append_log(agent_dir, f"hard gate failed: {reason}")
                return 3
            code_review_pass = code_review_verdict == "PASS"
            update_gate(agent_dir, code_review_passed=code_review_pass)
            if code_review_verdict == "NEEDS_CHANGES":
                finish_failed_review_round(agent_dir, request, round_no)
                round_no += 1
                step = "developer"
                continue
            step = "task_verifier"

        if step == "task_verifier":
            task_file = agent_dir / f"task_verification_round_{round_no}.md"
            if not task_file.exists() or task_file.stat().st_size == 0:
                code = run_task_verification_round(agent_dir, request, worktree, log_path, round_no)
                if code != 0:
                    write_status(agent_dir, request, "failed", "task_verifier_failed", round_no, f"task verifier exit code {code}")
                    return code
            task_verdict, reason = parse_verdict_file(task_file)
            if task_verdict == "INVALID" and should_retry_artifact(reason):
                code = run_task_verification_artifact_retry(agent_dir, request, worktree, log_path, round_no)
                if code != 0:
                    write_status(agent_dir, request, "failed", "task_verifier_failed", round_no, f"task verifier artifact retry exit code {code}")
                    return code
                task_verdict, reason = parse_verdict_file(task_file)
            if task_verdict == "INVALID":
                write_status(agent_dir, request, "failed", "task_verifier_invalid_output", round_no, reason)
                append_log(agent_dir, f"hard gate failed: {reason}")
                return 3
            task_pass = task_verdict == "PASS"
            update_gate(agent_dir, task_verification_passed=task_pass)
            if task_verdict == "NEEDS_CHANGES":
                finish_failed_review_round(agent_dir, request, round_no)
                round_no += 1
                step = "developer"
                continue
            step = "codex_lead_review"

        if step == "codex_lead_review":
            if not request["codex_review"].get("enabled"):
                update_gate(agent_dir, codex_review_passed=True)
                append_log(agent_dir, "codex review disabled, skipping lead review")
            else:
                codex_out = agent_dir / f"codex_review_round_{round_no}.md"
                if not codex_out.exists() or codex_out.stat().st_size == 0:
                    run_codex_review_round(agent_dir, request, worktree, log_path, round_no)
                if codex_out.exists() and codex_out.stat().st_size > 0:
                    normalized = normalize_codex_review_artifact(codex_out)
                    if normalized:
                        append_log(agent_dir, f"normalized codex artifact during resume: {codex_out.name}")
                codex_verdict, reason = parse_verdict_file(codex_out)
                if codex_verdict == "INVALID":
                    reason = _best_blocking_issue(agent_dir, reason)
                    write_status(agent_dir, request, "failed", "codex_review_invalid_output", round_no, reason)
                    append_log(agent_dir, f"hard gate failed: {reason}")
                    return 3
                codex_pass = codex_verdict == "PASS"
                update_gate(agent_dir, codex_review_passed=codex_pass)
                if codex_verdict == "NEEDS_CHANGES":
                    finish_failed_review_round(agent_dir, request, round_no)
                    round_no += 1
                    step = "developer"
                    continue

        update_gate(agent_dir, code_review_passed=True, task_verification_passed=True, codex_review_passed=True, no_major_findings=True, ready_for_commit=True)
        cleanup_temporary_protocol_files(agent_dir)
        write_status(agent_dir, request, "ready_for_commit", "all_reviews_passed", round_no)
        atomic_json(agent_dir / "final_status.json", {"state": "ready_for_commit", "updated_at": now_iso(), "round": round_no})
        append_log(agent_dir, "pipeline completed: ready_for_commit")
        return 0

    write_status(agent_dir, request, "blocked", "max_review_rounds_exceeded", request["max_review_rounds"], "review loop did not pass")
    append_log(agent_dir, "pipeline blocked: max review rounds exceeded")
    return 2

def tmux_session_exists(session: str) -> bool:
    return subprocess.run(["tmux", "has-session", "-t", session], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0


def tmux_window_names(session: str) -> list[str]:
    proc = subprocess.run(["tmux", "list-windows", "-t", session, "-F", "#W"], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
    if proc.returncode != 0:
        return []
    return [line.strip() for line in proc.stdout.splitlines() if line.strip()]


def start_background(agent_dir: Path) -> int:
    request = agent_dir / "request.json"
    session = re.sub(r"[^a-zA-Z0-9._-]", "-", f"agent-{agent_dir.parent.name}")
    run_cmd_args = [sys.executable, str(Path(__file__).resolve()), "run", str(request)]
    watch_cmd = f"{shlex.quote(str(SKILL_DIR / 'scripts' / 'watch_agent_status.sh'))} {shlex.quote(str(agent_dir))} 5"

    try:
        if tmux_session_exists(session):
            subprocess.run(["tmux", "kill-session", "-t", session], check=True)
            print(f"restarting tmux session: {session}")
        subprocess.run(["tmux", "new-session", "-d", "-s", session, "-n", "pipeline", *run_cmd_args], check=True)
        subprocess.run(["tmux", "new-window", "-t", session, "-n", "status", "bash", "-lc", watch_cmd], check=False)
        print(f"started tmux session: {session}")
        print("tmux windows: pipeline/status")
    except subprocess.CalledProcessError as exc:
        print(f"tmux command failed (exit {exc.returncode}): {exc}")
        print("tmux is required for background mode. Install tmux or use --foreground.", flush=True)
        return 1
    print(f"status: {agent_dir / 'status.json'}")
    print(f"log:    {agent_dir / 'progress.log'}")
    print(f"watch:  {SKILL_DIR / 'scripts' / 'watch_agent_status.sh'} {agent_dir}")
    return 0

def resolve_agent_dir(worktree: Path, change: str | None) -> Path:
    if not change:
        change = detect_change(worktree)
    return worktree / "openspec" / "changes" / change / "agent"


def resolve_cli_worktree(value: str | None) -> Path:
    config = read_yaml_like(CONFIG_PATH)
    defaults = config.get("defaults", BUILTIN_DEFAULTS["defaults"])
    return resolve_worktree(value, defaults)


def cmd_status(worktree: Path, change: str | None) -> int:
    status = resolve_agent_dir(worktree, change) / "status.json"
    if not status.exists():
        print(f"status not found: {status}")
        return 1
    print(status.read_text(encoding="utf-8"))
    return 0


def cmd_logs(worktree: Path, change: str | None, tail: int) -> int:
    from collections import deque
    log_path = resolve_agent_dir(worktree, change) / "progress.log"
    print(f"log: {log_path}")
    if not log_path.exists():
        print("log not created yet")
        return 0
    last = deque(maxlen=tail)
    with log_path.open(encoding="utf-8", errors="replace") as f:
        for line in f:
            last.append(line.rstrip("\n"))
    for line in last:
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
        return cmd_status(resolve_cli_worktree(args.worktree), args.change)
    if args.command == "logs":
        return cmd_logs(resolve_cli_worktree(args.worktree), args.change, args.tail)
    if args.command == "stop":
        return cmd_stop(resolve_cli_worktree(args.worktree), args.change)
    if args.command == "resume":
        return cmd_resume(resolve_cli_worktree(args.worktree), args.change)
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
