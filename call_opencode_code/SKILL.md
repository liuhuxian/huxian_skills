---
name: call_opencode_code
description: "Use when the user wants Codex to manage a change through OpenSpec + Trellis + OpenCode: Codex drafts and reviews, OpenCode implements and verifies, Trellis tracks local task context, and OpenSpec stores the git-tracked source of truth."
---

# OpenSpec + Trellis + OpenCode Workflow

Use this skill to run the user's preferred AI development loop:

- Codex drafts requirements and reviews code.
- OpenCode implements and verifies.
- Trellis provides local task state and context injection.
- OpenSpec stores formal, git-tracked artifacts and handoff records.
- The user confirms the proposal before implementation and confirms the final commit.

Role boundaries:

- OpenSpec is the source of truth for formal requirements, handoff notes, reviews, and final records.
- Trellis is local task state, current phase tracking, and context injection. It is not the formal record.
- OpenCode performs implementation, verification, status updates, and notes.
- Codex writes specs/handoffs, starts OpenCode, reviews final diffs/notes, and prepares commits.

Do not treat `.trellis/`, `.opencode/`, `.codex/`, `.agents/`, or `AGENTS.md` as formal records. They are local runtime/config files and may be ignored by git. All durable handoff information MUST be written under `openspec/changes/<change>/`.

## Language Policy

Write OpenSpec artifacts and handoff records in the same primary language as the current user conversation unless the user explicitly requests another language. If the user is discussing the change in Chinese, write `proposal.md`, `design.md`, `specs/**/spec.md`, `tasks.md`, `opencode_prompt.md`, `implementation_notes.md`, `code_review.md`, and `final_review.md` in Chinese. Keep code identifiers, file paths, command names, metric names, and API names in their original spelling.


## State Machine

### State 1: Draft Change

Create or update an OpenSpec change. Prefer `openspec-propose` when available.

Required output location:

```text
openspec/changes/<change>/
  proposal.md
  design.md
  specs/**/spec.md
  tasks.md
```

The proposal MUST define:

- Problem and motivation.
- Exact implementation scope.
- Non-goals.
- Verification requirements.
- Files likely to be touched.
- User approval is required before implementation.

If the requested change is ambiguous, ask concise questions before drafting. If the user provides enough context, make reasonable decisions and proceed.

### State 2: Await User Approval

Stop after drafting the OpenSpec artifacts. Summarize:

- Change name and path.
- Key behavioral contract.
- Verification plan.
- Any risks or open assumptions.

Do not run OpenCode or edit implementation files until the user confirms the proposal.

Approval examples include:

```text
确认
approved
可以执行
按这个做
```

### State 3: Auto Implement With OpenCode

After approval, create a Trellis task with the same slug as the OpenSpec change when `.trellis/` exists.

Before starting OpenCode, ensure local OpenCode Trellis SessionStart injection is opt-in rather than default-on. Run the skill-provided helper from the repository root:

```bash
~/.codex/skills/call_opencode_code/scripts/ensure_opencode_trellis_opt_in.sh
```

The helper patches `.opencode/plugins/session-start.js` only when the expected Trellis default-on hook is present. If `.opencode/` is unavailable it no-ops. If the hook has an unknown shape it fails and Codex must report the issue instead of guessing. This keeps ordinary user-launched `opencode` sessions free of Trellis injection, while this workflow explicitly enables it with `TRELLIS_HOOKS=1`.

Use:

```bash
python3 ./.trellis/scripts/task.py create "<title>" --slug <change>
python3 ./.trellis/scripts/task.py start <change>
```

If Trellis is unavailable, continue with OpenSpec + OpenCode only and record that fallback in `implementation_notes.md`.

Generate:

```text
openspec/changes/<change>/opencode_prompt.md
openspec/changes/<change>/opencode_status.json
```

Initialize `opencode_status.json` before starting OpenCode:

```json
{
  "state": "running",
  "phase": "queued",
  "updated_at": "<ISO8601 timestamp>",
  "message": "等待 OpenCode 开始执行"
}
```

The prompt MUST tell OpenCode:

- Source of truth is `openspec/changes/<change>`.
- Implement strictly according to `tasks.md`.
- Do not expand scope.
- Do not commit.
- Update `tasks.md` checkboxes for completed implementation work.
- Write implementation details and verification results to `implementation_notes.md`.
- Create and update `opencode_status.json` during the run.
- If `.trellis/` exists, update the Trellis task state at the beginning and end of each implementation/review cycle.
- Formal handoff must be in OpenSpec, not only `.trellis/` or chat.

OpenCode status protocol:

```text
state: running | blocked | failed | needs_review | done
phase examples: queued | reading_spec | editing | running_verification | writing_notes | addressing_review | done
```

OpenCode MUST update `opencode_status.json` at minimum:

- At start: `running / reading_spec`
- Before editing: `running / editing`
- Before verification: `running / running_verification`
- Before writing handoff notes: `running / writing_notes`
- On completion: `done / done` or `needs_review / done`
- On failure: `failed / <phase>` with a short failure summary
- On blockage: `blocked / <phase>` with the decision needed

If `.trellis/` exists, OpenCode MUST also refresh the current task state at the beginning of the cycle:

```bash
python3 ./.trellis/scripts/task.py start <change>
```

At the end of the cycle, OpenCode SHOULD update Trellis to a completed or review-ready state if the installed Trellis scripts support it. If no suitable Trellis command exists, record the fallback in `implementation_notes.md`. OpenSpec remains the formal record either way.

Run OpenCode in a detached tmux session and write logs to `/tmp`. Codex MUST NOT stream OpenCode stdout into the conversation.

Preferred launch:

```bash
tmux new-session -d -s opencode-<change> \
  'cd <repo-root> && TRELLIS_HOOKS=1 opencode run "$(cat openspec/changes/<change>/opencode_prompt.md)" 2>&1 | tee /tmp/opencode-<change>.log'
```

If the tmux session already exists, do not start another copy. Tell the user how to view it:

```bash
tmux attach -t opencode-<change>
tail -f /tmp/opencode-<change>.log
```

### State 4: Codex Review Loop

While OpenCode runs, Codex polls only:

```bash
cat openspec/changes/<change>/opencode_status.json
```

Codex MUST NOT read full OpenCode stdout/logs during normal execution. If `updated_at` is stale for 5-10 minutes, report that OpenCode may be stuck and suggest the user inspect the tmux session. Do not automatically take over implementation.

Only read `/tmp/opencode-<change>.log` when:

- `opencode_status.json` says `failed`
- `opencode_status.json` says `blocked`
- the status file is stale and the user wants diagnosis
- the user explicitly asks to inspect the log

When log inspection is necessary, read only a bounded tail by default:

```bash
tail -n 120 /tmp/opencode-<change>.log
```

After `opencode_status.json` is `done` or `needs_review`, Codex reviews:

- `git diff`
- `openspec/changes/<change>/tasks.md`
- `openspec/changes/<change>/implementation_notes.md`
- `openspec/changes/<change>/opencode_status.json`
- Verification output recorded by OpenCode in OpenSpec artifacts

Write review to:

```text
openspec/changes/<change>/code_review.md
```

Review format:

```text
# Code Review

## Findings

1. Severity: title
   File/line:
   Issue:
   Impact:
   Required fix:

## Verification Reviewed

- command: result

## Decision

- blocking changes required
- or accepted
```

If there are blocking issues, create or update:

```text
openspec/changes/<change>/opencode_fix_prompt.md
```

Then run OpenCode again:

```bash
tmux new-session -d -s opencode-<change>-fix<N> \
  'cd <repo-root> && TRELLIS_HOOKS=1 opencode run "$(cat openspec/changes/<change>/opencode_fix_prompt.md)" 2>&1 | tee /tmp/opencode-<change>-fix<N>.log'
```

Repeat review for up to 3 implementation/review cycles. If still blocked after 3 cycles, stop and ask the user how to proceed.

If useful, ask OpenCode to run a self-check before Codex's final review, but use the same detached tmux/log pattern:

```bash
tmux new-session -d -s opencode-<change>-check \
  'cd <repo-root> && TRELLIS_HOOKS=1 opencode run "Check implementation for openspec/changes/<change>; verify scope, tasks, and recorded commands. Do not commit. Record results in openspec/changes/<change>/implementation_notes.md and opencode_status.json." 2>&1 | tee /tmp/opencode-<change>-check.log'
```

Codex remains the final reviewer even if `trellis-check` passes.

### State 5: Prepare Commit And Ask User

When Codex accepts the change, write:

```text
openspec/changes/<change>/final_review.md
```

Include:

- Summary of implementation.
- Verification commands and results.
- Review decision.
- Recommended commit message.

Then prepare the commit without committing:

1. Check status and diff:

```bash
git status --short
git diff --stat
git diff --check
```

2. Stage only files related to the change. Include implementation files and OpenSpec artifacts. Do not stage unrelated dirty files.

3. Show the user:

```bash
git diff --cached --stat
git diff --cached --name-only
```

4. Ask for explicit commit confirmation.

Only commit after the user confirms. Suggested commit command:

```bash
git commit -m "<message>"
```

## Required OpenSpec Files

Every automated workflow change should end with these files:

```text
openspec/changes/<change>/
  proposal.md
  design.md
  specs/**/spec.md
  tasks.md
  opencode_prompt.md
  opencode_status.json
  implementation_notes.md
  code_review.md
  final_review.md
```

If some files are intentionally absent, explain why in `final_review.md`.

## Verification Policy

Use the project's verification rules. For this repo's ML training changes, if the user says training verification is needed and stable running for one minute counts as passing, use a bounded timeout command and report whether it ran stably.

Always record exact verification commands and outcomes in OpenSpec artifacts.

Codex does not run verification commands in this workflow. OpenCode owns verification. Codex may review the commands and results recorded by OpenCode, and may request another OpenCode cycle if verification is missing or insufficient. Codex may run tests only if the user explicitly tells Codex to take over verification or implementation.

## Task Size Guidance

For very small bug fixes, roughly fewer than 3 files and less than 30 lines of expected implementation, warn the user that the OpenSpec + Trellis + OpenCode workflow may cost more overhead than direct Codex implementation. If the user still invokes or confirms this skill, proceed with the full workflow.

## Safety Rules

- Never let OpenCode commit.
- Never auto-commit without user approval.
- Do not stage unrelated dirty files.
- Do not rely on `.trellis/` as the only record.
- Do not continue implementation if proposal is not approved.
- Do not hide verification failures; record them and review accordingly.
- If OpenCode cannot run, continue manually only after telling the user the fallback.
- Codex must not directly edit implementation files in this workflow unless the user explicitly asks Codex to take over.
- Codex must not run verification commands in this workflow unless the user explicitly asks Codex to take over verification.
- Codex must not stream or summarize OpenCode stdout during normal execution; use `opencode_status.json` for status.
