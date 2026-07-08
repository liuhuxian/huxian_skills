#!/usr/bin/env bash
set -euo pipefail

AGENT_DIR="${1:-}"
INTERVAL="${2:-5}"
if [[ -z "$AGENT_DIR" ]]; then
  echo "usage: watch_agent_status.sh openspec/changes/<change>/agent [interval_seconds]" >&2
  exit 2
fi
STATUS="$AGENT_DIR/status.json"
LOG="$AGENT_DIR/progress.log"

printed_header=0
last_state_key=""
last_heartbeat=0
heartbeat_active=0

get_field() {
  local field="$1"
  python3 - "$STATUS" "$field" <<'PYFIELD'
import json, sys
try:
    s = json.load(open(sys.argv[1], encoding='utf-8'))
except Exception:
    print("")
    raise SystemExit
value = s.get(sys.argv[2], "")
print(value if value is not None else "")
PYFIELD
}

is_terminal_state() {
  local state="$1"
  [[ "$state" == "ready_for_commit" || "$state" == "blocked" || "$state" == "failed" ]]
}

pipeline_is_running() {
  local pid="$1"
  if [[ "$pid" =~ ^[0-9]+$ ]] && kill -0 "$pid" 2>/dev/null; then
    return 0
  fi
  local change
  change="$(get_field change)"
  if [[ -n "$change" ]] && tmux has-session -t "agent-$change" 2>/dev/null; then
    local active_windows
    active_windows="$(tmux list-windows -t "agent-$change" -F '#W' 2>/dev/null | grep -vc '^status$' || true)"
    [[ "${active_windows:-0}" -gt 0 ]] && return 0
  fi
  return 1
}

print_status() {
  local mode="$1"
  python3 - "$STATUS" "$LOG" "$mode" <<'PYSTATUS'
import json, sys
from pathlib import Path

status_path = Path(sys.argv[1])
log_path = Path(sys.argv[2])
mode = sys.argv[3]
try:
    s = json.load(status_path.open(encoding='utf-8'))
except Exception as exc:
    print(f"invalid status: {exc}")
    raise SystemExit(1)

change = s.get('change')
state = s.get('state')
phase = s.get('phase')
round_no = s.get('round')
max_rounds = s.get('max_review_rounds')
updated_at = s.get('updated_at')
blocking = s.get('blocking_issue')

def role_label(role):
    if not isinstance(role, dict):
        return str(role)
    runner = role.get('runner', '?')
    provider = role.get('provider', '')
    model = role.get('model', '?')
    return f"{runner}:{provider + '/' if provider else ''}{model}"

if mode == 'header':
    print("Call-Agent-Code status")
    print(f"change: {change}")
    print(f"agent_dir: {status_path.parent}")
    print("")
    print("roles:")
    print(f"  developer: {role_label(s.get('developer'))}")
    print(f"  code_reviewer: {role_label(s.get('code_reviewer'))}")
    print(f"  task_verifier: {role_label(s.get('task_verifier'))}")
    print("")
    sessions = s.get('sessions') or {}
    print("sessions:")
    print(f"  developer: {sessions.get('developer')}")
    print(f"  code_reviewer: {sessions.get('code_reviewer')}")
    print(f"  task_verifier: {sessions.get('task_verifier')}")
    print("")
    print(f"log: {log_path}")
    print(f"status: {status_path}")
    print("")

phase_text = {
    'protocol_files_ready': 'protocol files prepared',
    'developer_agent': 'developer is implementing from OpenSpec',
    'developer_agent_failed': 'developer process failed',
    'code_reviewer': 'code reviewer is checking implementation',
    'code_reviewer_failed': 'code reviewer process failed',
    'task_verifier': 'task verifier is checking task completion',
    'task_verifier_failed': 'task verifier process failed',
    'codex_lead_review': 'Codex lead review is running',
    'review_feedback_pending_fix': 'reviews found issues; next developer fix round is being prepared',
    'all_reviews_passed': 'all reviews passed; ready for commit preparation',
    'max_review_rounds_exceeded': 'review loop exceeded max rounds',
}.get(str(phase), str(phase))

print(f"round {round_no}/{max_rounds} | {phase} | {state}")
print(f"  progress: {phase_text}")
print(f"  updated_at: {updated_at}")
if blocking:
    print(f"  blocking_issue: {blocking}")
print("")
PYSTATUS
}

while true; do
  now_epoch="$(date +%s)"
  now_text="$(date '+%Y-%m-%d %H:%M:%S')"
  if [[ ! -f "$STATUS" ]]; then
    if [[ "$printed_header" -eq 0 ]]; then
      echo "Call-Agent-Code status"
      echo "status: $STATUS"
      echo "log: $LOG"
      echo ""
      printed_header=1
    fi
    echo "[$now_text] status not found"
    sleep "$INTERVAL"
    continue
  fi

  state_key="$(python3 - "$STATUS" <<'PYSTATE'
import json, sys
try:
    s = json.load(open(sys.argv[1], encoding='utf-8'))
    print(f"{s.get('round')}|{s.get('phase')}|{s.get('state')}|{s.get('blocking_issue')}")
except Exception as exc:
    print(f"invalid|invalid|invalid|{exc}")
PYSTATE
)"
  status_brief="$(python3 - "$STATUS" <<'PYBRIEF'
import json, sys
try:
    s = json.load(open(sys.argv[1], encoding='utf-8'))
    print(f"round {s.get('round')}/{s.get('max_review_rounds')} | {s.get('phase')} | {s.get('state')}")
except Exception as exc:
    print(f"invalid status: {exc}")
PYBRIEF
)"

  state="$(get_field state)"
  pid="$(get_field pipeline_pid)"
  stalled=0
  if ! is_terminal_state "$state" && ! pipeline_is_running "$pid"; then
    stalled=1
  fi

  if [[ "$printed_header" -eq 0 ]]; then
    print_status header
    printed_header=1
    last_state_key="$state_key"
    last_heartbeat="$now_epoch"
    if [[ "$stalled" -eq 1 ]]; then
      echo "[$now_text] stalled"
      echo "  progress: status is non-terminal, but no pipeline process/window is running"
      echo "  next: resume this change with call-agent-code resume"
      echo ""
    fi
  elif [[ "$state_key" != "$last_state_key" ]]; then
    if [[ "$heartbeat_active" -eq 1 ]]; then
      echo ""
      heartbeat_active=0
    fi
    echo "[$now_text]"
    if [[ "$stalled" -eq 1 ]]; then
      echo "stalled"
    fi
    print_status body
    if [[ "$stalled" -eq 1 ]]; then
      echo "  progress: status is non-terminal, but no pipeline process/window is running"
      echo "  next: resume this change with call-agent-code resume"
      echo ""
    fi
    last_state_key="$state_key"
    last_heartbeat="$now_epoch"
  elif (( now_epoch - last_heartbeat >= 60 )); then
    if [[ "$stalled" -eq 1 ]]; then
      printf "\r\033[2K[%s] stalled | %s | next: resume" "$now_text" "$status_brief"
    else
      printf "\r\033[2K[%s] still running | %s" "$now_text" "$status_brief"
    fi
    heartbeat_active=1
    last_heartbeat="$now_epoch"
  fi

  sleep "$INTERVAL"
done
