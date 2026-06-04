#!/usr/bin/env bash
set -euo pipefail

agent="${1:-}"
if [[ -z "$agent" ]]; then
  echo "usage: $0 <opencode|codebuddy> [repo-root]" >&2
  exit 2
fi

repo_root="${2:-.}"
cd "$repo_root"

has_file() { [[ -f "$1" ]] && echo yes || echo no; }
has_dir() { [[ -d "$1" ]] && echo yes || echo no; }

if [[ -d openspec && -f openspec/config.yaml && -d openspec/changes ]]; then
  openspec_ready=yes
else
  openspec_ready=no
fi

printf 'agent=%s\n' "$agent"
printf 'repo=%s\n' "$(pwd)"
printf 'openspec_dir=%s\n' "$(has_dir openspec)"
printf 'openspec_config=%s\n' "$(has_file openspec/config.yaml)"
printf 'openspec_changes_dir=%s\n' "$(has_dir openspec/changes)"
printf 'openspec_specs_dir=%s\n' "$(has_dir openspec/specs)"
printf 'openspec_ready=%s\n' "$openspec_ready"
printf 'trellis_dir=%s\n' "$(has_dir .trellis)"
printf 'trellis_task_py=%s\n' "$(has_file .trellis/scripts/task.py)"

case "$agent" in
  opencode)
    printf 'platform_dir=%s\n' "$(has_dir .opencode)"
    printf 'skills_dir=%s\n' "$(has_dir .opencode/skills)"
    printf 'agents_dir=%s\n' "$(has_dir .opencode/agents)"
    printf 'trellis_implement_agent=%s\n' "$(has_file .opencode/agents/trellis-implement.md)"
    printf 'trellis_check_agent=%s\n' "$(has_file .opencode/agents/trellis-check.md)"
    printf 'trellis_commands=%s\n' "$(has_dir .opencode/commands/trellis)"
    printf 'session_start_plugin=%s\n' "$(has_file .opencode/plugins/session-start.js)"
    printf 'workflow_state_plugin=%s\n' "$(has_file .opencode/plugins/inject-workflow-state.js)"
    printf 'subagent_context_plugin=%s\n' "$(has_file .opencode/plugins/inject-subagent-context.js)"
    if [[ -f .opencode/plugins/session-start.js ]] && rg -q 'TRELLIS_HOOKS !== "1"' .opencode/plugins/session-start.js; then
      printf 'trellis_hooks_opt_in=yes\n'
    else
      printf 'trellis_hooks_opt_in=no\n'
    fi
    ;;
  codebuddy)
    printf 'platform_dir=%s\n' "$(has_dir .codebuddy)"
    printf 'skills_dir=%s\n' "$(has_dir .codebuddy/skills)"
    printf 'agents_dir=%s\n' "$(has_dir .codebuddy/agents)"
    printf 'hooks_dir=%s\n' "$(has_dir .codebuddy/hooks)"
    printf 'settings_json=%s\n' "$(has_file .codebuddy/settings.json)"
    printf 'trellis_implement_agent=%s\n' "$(has_file .codebuddy/agents/trellis-implement.md)"
    printf 'trellis_check_agent=%s\n' "$(has_file .codebuddy/agents/trellis-check.md)"
    printf 'openspec_skills=%s\n' "$(has_dir .codebuddy/skills/openspec-propose)"
    if [[ -d .codebuddy/agents && -d .codebuddy/hooks && -f .codebuddy/settings.json ]]; then
      printf 'trellis_platform_init=complete\n'
    else
      printf 'trellis_platform_init=incomplete\n'
    fi
    ;;
  *)
    echo "unknown agent: $agent" >&2
    exit 2
    ;;
esac
