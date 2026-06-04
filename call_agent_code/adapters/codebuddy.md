# CodeBuddy Adapter

Use for `$call_agent_code codebuddy`.

## Status

This adapter defines the expected shape but may need the exact local CodeBuddy CLI command confirmed from the user's installation.

If `codebuddy --help` is available locally, inspect it before launch. If the launch command is unclear, ask the user for the exact non-interactive command instead of inventing one.

## Files

Use generic agent protocol files:

```text
agent_prompt.md
agent_status.json
agent_fix_prompt.md
```

## Launch Pattern

Preferred shape once command is confirmed:

```bash
tmux new-session -d -s codebuddy-<change> \
  'cd <repo-root> && <codebuddy non-interactive command using agent_prompt.md> 2>&1 | tee /tmp/codebuddy-<change>.log'
```

Tell the user:

```bash
tmux attach -t codebuddy-<change>
tail -f /tmp/codebuddy-<change>.log
```

## Requirements For CodeBuddy Prompt

The prompt must require CodeBuddy to:

- Implement strictly from `openspec/changes/<change>/tasks.md`.
- Not commit.
- Update `agent_status.json` using the shared status protocol.
- Write implementation and verification handoff to `implementation_notes.md`.
- Update Trellis task state if `.trellis/` exists and commands are available.

## Fallback

If CodeBuddy cannot run non-interactively, stop after writing OpenSpec artifacts and ask the user how they want to launch it. Do not silently switch to OpenCode unless the user approves.
