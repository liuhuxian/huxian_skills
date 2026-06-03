#!/usr/bin/env bash
set -euo pipefail

patch_hook() {
  local hook_path="$1"
  local label="$2"

  if [[ ! -f "$hook_path" ]]; then
    echo "OpenCode Trellis $label hook not found; skipping."
    return 0
  fi

  if rg -q 'process\.env\.TRELLIS_HOOKS !== "1"' "$hook_path"; then
    echo "OpenCode Trellis $label hook already opt-in."
    return 0
  fi

  if ! rg -q 'process\.env\.TRELLIS_HOOKS === "0" \|\| process\.env\.TRELLIS_DISABLE_HOOKS === "1"' "$hook_path"; then
    echo "ERROR: Unrecognized OpenCode Trellis $label hook shape: $hook_path" >&2
    echo "Expected default-on TRELLIS_HOOKS/TRELLIS_DISABLE_HOOKS guard or existing opt-in guard." >&2
    return 1
  fi

  perl -0pi -e 's/if \(process\.env\.TRELLIS_HOOKS === "0" \|\| process\.env\.TRELLIS_DISABLE_HOOKS === "1"\) \{\n\s*(?:debugLog\([^)]*\)\n\s*)?return\n\s*\}/if (process.env.TRELLIS_HOOKS !== "1") {\n          debugLog("trellis", "Skipping - TRELLIS_HOOKS not enabled")\n          return\n        }/g' "$hook_path"

  if ! rg -q 'process\.env\.TRELLIS_HOOKS !== "1"' "$hook_path"; then
    echo "ERROR: Failed to patch OpenCode Trellis $label hook: $hook_path" >&2
    return 1
  fi

  echo "Patched OpenCode Trellis $label hook to opt-in mode."
}

patch_hook ".opencode/plugins/session-start.js" "SessionStart"
patch_hook ".opencode/plugins/inject-workflow-state.js" "WorkflowState"
patch_hook ".opencode/plugins/inject-subagent-context.js" "SubagentContext"
