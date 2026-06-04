# OpenSpec Artifacts

OpenSpec is the source of truth for formal requirements, implementation handoff, reviews, and final records.

## Required Files

Every automated workflow change should end with:

```text
openspec/changes/<change>/
  proposal.md
  design.md
  specs/**/spec.md
  tasks.md
  agent_prompt.md
  agent_status.json
  implementation_notes.md
  code_review.md
  final_review.md
```

If any required generic file is intentionally absent, explain why in `final_review.md`.

## Agent Prompt Requirements

The prompt must tell the selected agent:

- Source of truth is `openspec/changes/<change>`.
- Implement strictly according to `tasks.md`.
- Do not expand scope.
- Do not commit.
- Update `tasks.md` checkboxes.
- Write implementation details and exact verification results to `implementation_notes.md`.
- Create and update `agent_status.json`.
- If `.trellis/` exists, update the Trellis task state at the beginning and end of each implementation/review cycle.
- Formal handoff must be in OpenSpec, not only `.trellis/` or chat.

## Language

Write `proposal.md`, `design.md`, `specs/**/spec.md`, `tasks.md`, `agent_prompt.md`, `implementation_notes.md`, `code_review.md`, and `final_review.md` in the same primary language as the conversation unless the user requests another language.

Keep code identifiers, file paths, command names, metric names, and API names in their original spelling.
