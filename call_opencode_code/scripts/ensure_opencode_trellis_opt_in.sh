#!/usr/bin/env bash
set -euo pipefail

hook_path=".opencode/plugins/session-start.js"

if [[ ! -f "$hook_path" ]]; then
  echo "OpenCode Trellis SessionStart hook not found; skipping opt-in patch."
  exit 0
fi

if rg -q 'process\.env\.TRELLIS_HOOKS !== "1"' "$hook_path"; then
  echo "OpenCode Trellis SessionStart hook already opt-in."
  exit 0
fi

if ! rg -q 'process\.env\.TRELLIS_HOOKS === "0" \|\| process\.env\.TRELLIS_DISABLE_HOOKS === "1"' "$hook_path"; then
  echo "ERROR: Unrecognized OpenCode Trellis SessionStart hook shape: $hook_path" >&2
  echo "Expected default-on TRELLIS_HOOKS/TRELLIS_DISABLE_HOOKS guard or existing opt-in guard." >&2
  exit 1
fi

perl -0pi -e 's/if \(process\.env\.TRELLIS_HOOKS === "0" \|\| process\.env\.TRELLIS_DISABLE_HOOKS === "1"\) \{\n\s*debugLog\("session", "Skipping - TRELLIS_HOOKS disabled"\)\n\s*return\n\s*\}/if (process.env.TRELLIS_HOOKS !== "1") {\n          debugLog("session", "Skipping - TRELLIS_HOOKS not enabled")\n          return\n        }/' "$hook_path"

if ! rg -q 'process\.env\.TRELLIS_HOOKS !== "1"' "$hook_path"; then
  echo "ERROR: Failed to patch OpenCode Trellis SessionStart hook: $hook_path" >&2
  exit 1
fi

echo "Patched OpenCode Trellis SessionStart hook to opt-in mode."
