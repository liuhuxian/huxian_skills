#!/usr/bin/env python3
"""Validate call_agent_code completion artifacts."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

REQUIRED_FILES = [
    "status.json",
    "completion_gate.json",
    "verification.md",
    "changed_files.txt",
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


def load_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        raise SystemExit(f"invalid JSON: {path}: {exc}") from exc


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

    gate = load_json(agent_dir / "completion_gate.json")
    required = list(REQUIRED_TRUE)
    if args.require_codex_review:
        required.append("codex_review_passed")
    failures = [key for key in required if gate.get(key) is not True]
    if failures:
        print("FAIL completion gate false/missing:", ", ".join(failures))
        return 1

    status = load_json(agent_dir / "status.json")
    if status.get("state") not in {"ready_for_codex_review", "ready_for_commit"}:
        print(f"FAIL unexpected state: {status.get('state')}")
        return 1

    for text_file in ["verification.md", "changed_files.txt", "handover.md"]:
        if not (agent_dir / text_file).read_text(encoding="utf-8", errors="replace").strip():
            print(f"FAIL empty file: {text_file}")
            return 1

    print("PASS completion gate")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
