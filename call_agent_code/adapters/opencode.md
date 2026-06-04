# OpenCode Adapter

Use for `$call_agent_code opencode`.

## Preflight

Before starting OpenCode, run from the repository root:

```bash
/users/huxian/.codex/skills/call_agent_code/scripts/ensure_opencode_trellis_opt_in.sh
```

The helper makes local OpenCode Trellis hooks opt-in. Ordinary user-launched `opencode` sessions should remain free of Trellis injection; this workflow enables it explicitly with `TRELLIS_HOOKS=1`.

If the helper fails, report the issue instead of guessing.

## Files

Generic files:

```text
agent_prompt.md
agent_status.json
agent_fix_prompt.md
```

## Launch

Use detached tmux:

```bash
tmux new-session -d -s opencode-<change> \
  'cd <repo-root> && TRELLIS_HOOKS=1 opencode run "$(cat openspec/changes/<change>/agent_prompt.md)" 2>&1 | tee /tmp/opencode-<change>.log'
```

If the session already exists, do not start another copy.

Tell the user:

```bash
tmux attach -t opencode-<change>
tail -f /tmp/opencode-<change>.log
```

## Fix Cycles

For fix cycle `<N>`:

```bash
tmux new-session -d -s opencode-<change>-fix<N> \
  'cd <repo-root> && TRELLIS_HOOKS=1 opencode run "$(cat openspec/changes/<change>/agent_fix_prompt.md)" 2>&1 | tee /tmp/opencode-<change>-fix<N>.log'
```

## Normal Polling

Poll:

```bash
cat openspec/changes/<change>/agent_status.json
```
