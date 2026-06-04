# Shared Workflow

Use this state machine for every supported external coding CLI.

## State 1: Draft Change

Create or update:

```text
openspec/changes/<change>/
  proposal.md
  design.md
  specs/**/spec.md
  tasks.md
```

The artifacts must be in the current conversation language unless the user requests otherwise. Chinese conversation means Chinese OpenSpec artifacts.

The proposal must define:

- Problem and motivation.
- Exact implementation scope.
- Non-goals.
- Verification requirements.
- Files likely to be touched.
- That user approval is required before implementation.

Stop after drafting. Do not start any external agent until the user confirms.

## State 2: Await User Approval

Summarize:

- Change slug and path.
- Key behavioral contract.
- Verification plan.
- Risks and open assumptions.

Approval examples: `确认`, `approved`, `可以执行`, `按这个做`.

## State 3: Start External Agent

After approval:

1. If `.trellis/` exists, create/start a Trellis task with the same slug.
2. Generate `agent_prompt.md`.
3. Initialize `agent_status.json`.
4. Start the selected adapter in detached `tmux`.
5. Tell the user the tmux attach command and log path.

If Trellis is unavailable, continue with OpenSpec + selected agent and record the fallback in `implementation_notes.md`.

## State 4: Review Loop

Poll only `agent_status.json` during normal execution. Do not stream or summarize full agent stdout.

Read bounded log tails only when:

- status is `failed` or `blocked`;
- status is stale for 5-10 minutes and the user wants diagnosis;
- the user explicitly asks to inspect the log.

After status is `done` or `needs_review`, Codex reviews diffs and OpenSpec handoff notes.

If blocking issues exist, write `agent_fix_prompt.md` and run another adapter cycle. Limit to 3 implementation/review cycles before asking the user how to proceed.

## State 5: Prepare Commit

When accepted:

1. Write `final_review.md`.
2. Check status/diff/diff check.
3. Stage only related implementation and OpenSpec files.
4. Show cached stat and cached file list.
5. Ask for explicit commit confirmation.

Commit only after user approval.
