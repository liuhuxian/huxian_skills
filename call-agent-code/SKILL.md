---
name: call-agent-code
description: "Use when the user wants Codex to delegate implementation to an external coding CLI such as OpenCode or CodeBuddy from an OpenSpec change, with file-based status, automated code review, task verification, Codex CLI lead review, and commit preparation. Trigger on $call-agent-code or requests to have another agent implement/fix/review code from a spec."
---

# Call Agent Code

Delegate OpenSpec implementation to external coding CLIs through a file-based local pipeline.

## Core Contract

Codex owns architecture, OpenSpec, final lead review, and commit preparation. External agents own implementation. Review agents own secondary checks. Communication happens through files under `openspec/changes/<change>/agent/`; do not rely on chat history or external-agent claims.

## Default Workflow

1. Confirm an OpenSpec change exists and the user has approved it.
2. Resolve configuration from `config.yaml`, then CLI/user overrides.
3. Generate or refresh `openspec/changes/<change>/agent/request.json` and prompt files.
4. Start the local pipeline script in the background unless the user asks for foreground or prepare-only mode.
5. Tell the user the tmux session name, status file, log file, and watch command.
6. Do not poll continuously from Codex. The local script handles waiting and loop control.
7. When asked for final review or commit prep, read the agent artifacts and `git diff`, then perform Codex lead review.

## Interface

Preferred invocations:

```text
$call-agent-code
$call-agent-code start
$call-agent-code start opencode:volcengine-plan/glm-5.2
$call-agent-code start codebuddy:deepseek/deepseek-v4-pro --code-reviewer opencode:volcengine-plan/minimax-m3 --task-verifier opencode:volcengine-plan/glm-5.2
$call-agent-code status [change]
$call-agent-code logs [change]
$call-agent-code stop [change]
$call-agent-code resume [change]
```

Role specs use `runner:provider/model`, for example `opencode:volcengine-plan/glm-5.2`. `runner` is the CLI adapter; `provider` is the model provider ID from that CLI; `model` is the model ID.

`resume` is stage-aware: it reads `status.json` and existing artifacts to continue from developer, code reviewer, task verifier, or Codex lead review instead of blindly restarting from the beginning.

Useful options:

```text
--change <name>                 OpenSpec change name; default: auto-detect.
--worktree <path>               Worktree/project root; default from config, then current cwd. In le-wm, `wk1` resolves to `.worktree/wk1` when present.
--session-id <id>               External developer session id; default: change name.
--code-reviewer <runner:provider/model>
--task-verifier <runner:provider/model>
--max-review-rounds <n>         External develop-review-fix rounds; default from config.
--foreground                    Run pipeline in current terminal.
--no-auto-start                 Only write protocol files and commands.
--no-codex-review               Skip automated Codex CLI lead review.
```

## Required Resources

Use these bundled scripts instead of retyping pipeline logic:

- `scripts/run_agent_pipeline.py`: create protocol files, run agent/review loops, update status.
- `scripts/watch_agent_status.sh`: zero-Codex-token terminal status watcher.
- `scripts/validate_completion_gate.py`: validate handoff artifacts before lead review.

Read `references/file_protocol.md` before changing protocol filenames or completion-gate rules. Read `references/providers.md` before adding a new CLI provider.

## Completion Rules

Never accept “done” as evidence. A handoff is reviewable only when these files exist and are internally consistent:

```text
agent/status.json
agent/completion_gate.json
agent/verification.md
agent/self_review.md
agent/code_review_round_<n>.md
agent/task_verification_round_<n>.md
agent/changed_files.txt
agent/handover.md
```

The pipeline may mark `ready_for_commit` only after code review, task verification, and Codex lead review pass, or when Codex review is explicitly disabled.

Never let external agents commit. Never commit without explicit user confirmation.
