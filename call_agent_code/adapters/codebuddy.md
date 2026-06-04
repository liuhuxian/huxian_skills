# CodeBuddy Adapter

Use for `$call_agent_code codebuddy`.

## Preflight

Before starting CodeBuddy, run from the repository root:

```bash
/users/huxian/.codex/skills/call_agent_code/scripts/check_agent_trellis_setup.sh codebuddy .
```

Record the output in `implementation_notes.md`. If `openspec_ready=no`, stop before launch and show the OpenSpec initialization commands from `shared/initialization.md`. Do not assume CodeBuddy has Trellis hooks, agents, settings, or context injection unless this preflight reports them. If `trellis_platform_init=incomplete`, show the CodeBuddy Trellis initialization guidance from `shared/initialization.md`. CodeBuddy may still run in prompt-only OpenSpec mode: all required context must be included in `agent_prompt.md`, and Trellis is used only through explicit `.trellis/scripts/task.py` commands when available.

`codebuddy --help` confirms non-interactive mode is `codebuddy -p` or `codebuddy --print`.

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
  'cd <repo-root> && codebuddy -p --permission-mode acceptEdits "$(cat openspec/changes/<change>/agent_prompt.md)" 2>&1 | tee /tmp/codebuddy-<change>.log'
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
