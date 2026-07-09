#!/usr/bin/env python3
"""Validate call-agent-code completion artifacts."""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

REQUIRED_FILES = [
    "status.json",
    "completion_gate.json",
    "verification.md",
    "changed_files.txt",
    "self_review.md",
    "handover.md",
]
REQUIRED_TRUE = [
    "tasks_completed",
    "changed_files_listed",
    "verification_recorded",
    "verification_exit_codes_recorded",
    "code_review_passed",
    "task_verification_passed",
    "no_major_findings",
    "handover_written",
]
VERDICT_RE = re.compile(r"^\s*(?:[-*]\s*)?(?:\*\*)?Verdict\s*:\s*(?:\*\*)?\s*(PASS|NEEDS_CHANGES)\b", re.IGNORECASE | re.MULTILINE)
TOOL_ERROR_MARKERS = (
    "Invalid Tool",
    "JSON Parse error",
    "Error: stdin is not a terminal",
    "Traceback (most recent call last)",
)
MIN_REVIEW_BODY_CHARS = 40


def load_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        raise SystemExit(f"invalid JSON: {path}: {exc}") from exc


def parse_verdict_file(path: Path) -> tuple[str, str]:
    if not path.exists():
        return "INVALID", f"missing file: {path.name}"
    if path.stat().st_size == 0:
        return "INVALID", f"empty file: {path.name}"
    text = path.read_text(encoding="utf-8", errors="replace")
    leading = text.lstrip()[:1000]
    for marker in TOOL_ERROR_MARKERS:
        if leading.startswith(marker):
            return "INVALID", f"tool/error output in {path.name}: {marker}"
    matches = [m.group(1).upper() for m in VERDICT_RE.finditer(text)]
    if not matches:
        return "INVALID", f"missing explicit Verdict in {path.name}"
    unique = set(matches)
    if len(unique) > 1:
        return "INVALID", f"conflicting Verdict lines in {path.name}: {sorted(unique)}"
    first = VERDICT_RE.search(text)
    assert first is not None
    body = text[first.end():].strip()
    if not body:
        return "INVALID", f"missing review body in {path.name}"
    if len(body) < MIN_REVIEW_BODY_CHARS:
        return "INVALID", f"review body too short in {path.name}"
    return matches[-1], f"verdict={matches[-1]} in {path.name}"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("agent_dir", help="openspec/changes/<change>/agent")
    parser.add_argument("--require-codex-review", action="store_true")
    args = parser.parse_args()

    agent_dir = Path(args.agent_dir).resolve()
    missing = [name for name in REQUIRED_FILES if not (agent_dir / name).exists()]
    if missing:
        print("FAIL missing files:", ", ".join(missing))
        return 1

    for text_file in ["verification.md", "changed_files.txt", "self_review.md", "handover.md"]:
        if not (agent_dir / text_file).read_text(encoding="utf-8", errors="replace").strip():
            print(f"FAIL empty file: {text_file}")
            return 1

    gate = load_json(agent_dir / "completion_gate.json")
    required = list(REQUIRED_TRUE)
    if args.require_codex_review:
        required.append("codex_review_passed")
    failures = [key for key in required if gate.get(key) is not True]
    if failures:
        print("FAIL completion gate false/missing:", ", ".join(failures))
        return 1

    status = load_json(agent_dir / "status.json")
    if status.get("state") != "ready_for_commit":
        print(f"FAIL unexpected state: {status.get('state')}")
        return 1
    round_no = int(status.get("round") or 0)
    if round_no < 1:
        print(f"FAIL invalid round: {round_no}")
        return 1

    review_files = [
        agent_dir / f"code_review_round_{round_no}.md",
        agent_dir / f"task_verification_round_{round_no}.md",
    ]
    if args.require_codex_review:
        review_files.append(agent_dir / f"codex_review_round_{round_no}.md")
    for path in review_files:
        verdict, reason = parse_verdict_file(path)
        if verdict != "PASS":
            print(f"FAIL review verdict: {reason}")
            return 1

    print("PASS completion gate")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
