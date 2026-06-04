# CodeBuddy Adapter

Use for `$call_agent_code codebuddy`.

## Preflight

Before starting CodeBuddy, run from the repository root:

```bash
/users/huxian/.codex/skills/call_agent_code/scripts/check_agent_trellis_setup.sh codebuddy .
```

Record the output in `implementation_notes.md`. If `openspec_ready=no`, stop before launch and show the OpenSpec initialization commands from `shared/initialization.md`. Do not assume CodeBuddy has Trellis hooks, agents, settings, or context injection unless this preflight reports them. If `trellis_platform_init=incomplete`, show the CodeBuddy Trellis initialization guidance from `shared/initialization.md`. CodeBuddy may still run in prompt-only OpenSpec mode: all required context must be included in `agent_prompt.md`, and Trellis is used only through explicit `.trellis/scripts/task.py` commands when available.

`codebuddy --help` confirms non-interactive mode is `codebuddy -p` or `codebuddy --print`.

## Model Selection

Before starting CodeBuddy, ask the user which CodeBuddy model to use. Do this even
when the OpenSpec change has already been approved.

Show this concise model list:

```text
1. deepseek-v4-pro     Recommended for implementation/review quality
2. deepseek-v4-flash   Faster, cheaper debugging or small edits
3. glm-5.1             General strong model
4. kimi-k2.6           Long-context/spec-heavy tasks
5. minimax-m2.7        Alternative strong model
6. Other               User supplies an exact CodeBuddy model id
```

Recommended default: `deepseek-v4-pro`.

After the user chooses, include the selected model in every CodeBuddy launch
command:

```bash
--model <selected-model>
```

If the user already named a model in the same request, use that model directly
and do not ask again.

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
  'cd <repo-root> && codebuddy -p --model <selected-model> --permission-mode acceptEdits "$(cat openspec/changes/<change>/agent_prompt.md)" 2>&1 | tee /tmp/codebuddy-<change>.log'
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
