---
name: openspec-trellis-opencode-workflow
description: Use when the user wants Codex to manage a change through OpenSpec + Trellis + OpenCode: Codex drafts and reviews, OpenCode implements and verifies, Trellis tracks local task context, and OpenSpec stores the git-tracked source of truth.
---

# OpenSpec + Trellis + OpenCode Workflow

Use this skill to run the user's preferred AI development loop:

- Codex drafts requirements and reviews code.
- OpenCode implements and verifies.
- Trellis provides local task state and context injection.
- OpenSpec stores formal, git-tracked artifacts and handoff records.
- The user confirms the proposal before implementation and confirms the final commit.

Do not treat `.trellis/`, `.opencode/`, `.codex/`, `.agents/`, or `AGENTS.md` as formal records. They are local runtime/config files and may be ignored by git. All durable handoff information MUST be written under `openspec/changes/<change>/`.

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

Use:

```bash
python3 ./.trellis/scripts/task.py create "<title>" --slug <change>
python3 ./.trellis/scripts/task.py start <change>
```

If Trellis is unavailable, continue with OpenSpec + OpenCode only and record that fallback in `implementation_notes.md`.

Generate:

```text
openspec/changes/<change>/opencode_prompt.md
```

The prompt MUST tell OpenCode:

- Source of truth is `openspec/changes/<change>`.
- Implement strictly according to `tasks.md`.
- Do not expand scope.
- Do not commit.
- Update `tasks.md` checkboxes for completed implementation work.
- Write implementation details and verification results to `implementation_notes.md`.
- Formal handoff must be in OpenSpec, not only `.trellis/` or chat.

Run OpenCode non-interactively when available:

```bash
opencode run --agent trellis-implement "$(cat openspec/changes/<change>/opencode_prompt.md)"
```

If `trellis-implement` is unavailable, use:

```bash
opencode run "$(cat openspec/changes/<change>/opencode_prompt.md)"
```

### State 4: Codex Review Loop

After OpenCode returns, Codex reviews:

- `git diff`
- `openspec/changes/<change>/tasks.md`
- `openspec/changes/<change>/implementation_notes.md`
- Verification output recorded by OpenCode

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
opencode run --agent trellis-implement "$(cat openspec/changes/<change>/opencode_fix_prompt.md)"
```

Repeat review for up to 3 implementation/review cycles. If still blocked after 3 cycles, stop and ask the user how to proceed.

If useful, run a Trellis/OpenCode self-check before Codex's final review:

```bash
opencode run --agent trellis-check "Check implementation for openspec/changes/<change>; verify scope, tasks, and recorded commands. Do not commit."
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
  implementation_notes.md
  code_review.md
  final_review.md
```

If some files are intentionally absent, explain why in `final_review.md`.

## Verification Policy

Use the project's verification rules. For this repo's ML training changes, if the user says training verification is needed and stable running for one minute counts as passing, use a bounded timeout command and report whether it ran stably.

Always record exact verification commands and outcomes in OpenSpec artifacts.

## Safety Rules

- Never let OpenCode commit.
- Never auto-commit without user approval.
- Do not stage unrelated dirty files.
- Do not rely on `.trellis/` as the only record.
- Do not continue implementation if proposal is not approved.
- Do not hide verification failures; record them and review accordingly.
- If OpenCode cannot run, continue manually only after telling the user the fallback.
