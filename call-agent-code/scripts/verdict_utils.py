"""Shared verdict-parsing utilities for the call-agent-code pipeline."""
from __future__ import annotations

import re
from pathlib import Path

VERDICT_RE = re.compile(
    r"^\s*(?:[-*]\s*)?(?:\*\*)?Verdict\s*:\s*(?:\*\*)?\s*(PASS|NEEDS_CHANGES)\b",
    re.IGNORECASE | re.MULTILINE,
)
TOOL_ERROR_MARKERS = (
    "Invalid Tool",
    "JSON Parse error",
    "Error: stdin is not a terminal",
    "Traceback (most recent call last)",
)
MIN_REVIEW_BODY_CHARS = 40


def parse_verdict_file(path: Path) -> tuple[str, str]:
    """Return (PASS|NEEDS_CHANGES|INVALID, reason)."""
    if not path.exists():
        return "INVALID", f"missing file: {path.name}"
    if path.stat().st_size == 0:
        return "INVALID", f"empty file: {path.name}"
    text = path.read_text(encoding="utf-8", errors="replace")
    leading = text.lstrip()[:1000]
    for marker in TOOL_ERROR_MARKERS:
        if leading.startswith(marker):
            return "INVALID", f"tool/error output in {path.name}: {marker}"
    lines = text.splitlines()
    for idx, line in enumerate(lines):
        stripped = line.strip()
        if not stripped:
            continue
        m = VERDICT_RE.match(stripped)
        if not m:
            continue
        verdict = m.group(1).upper()
        body = "\n".join(lines[idx + 1:]).strip()
        if not body:
            return "INVALID", f"missing review body in {path.name}"
        if len(body) < MIN_REVIEW_BODY_CHARS:
            return "INVALID", f"review body too short in {path.name}"
        return verdict, f"verdict={verdict} in {path.name}"
    return "INVALID", f"missing explicit Verdict in {path.name}"


def verdict_is_pass(path: Path) -> bool:
    verdict, _reason = parse_verdict_file(path)
    return verdict == "PASS"


def should_retry_artifact(reason: str) -> bool:
    retry_markers = (
        "missing file:",
        "empty file:",
        "missing review body",
        "review body too short",
    )
    return any(marker in reason for marker in retry_markers)
