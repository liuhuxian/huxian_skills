---
name: call_agent_code
description: "Use when the user wants Codex to delegate implementation or verification to an external coding CLI such as OpenCode or CodeBuddy while Codex keeps OpenSpec records, reviews diffs, and prepares commits."
---

# Call Agent Code

This skill routes the user's OpenSpec + Trellis + external-agent development workflow through a shared state machine and a concrete agent adapter.

## Agent Selection

Recognize these invocations:

- `$call_agent_code opencode ...`: use the OpenCode adapter.
- `$call_agent_code codebuddy ...`: use the CodeBuddy adapter.

If no agent is named, default to `opencode` unless the user has already specified another CLI in the current request.

## Load Order

Read only the files needed for the current state:

1. `shared/workflow.md`
2. `shared/openspec.md`
3. `shared/status_protocol.md`
4. `shared/initialization.md`
5. The selected adapter under `adapters/`
6. `shared/review_and_commit.md` only after the external agent reports completion

## Hard Boundaries

- Codex drafts OpenSpec artifacts, starts the selected agent, reviews final diffs/notes, and prepares commits.
- The selected external agent implements and verifies.
- Codex does not directly edit implementation files or run verification in this workflow unless the user explicitly asks Codex to take over.
- OpenSpec artifacts under `openspec/changes/<change>/` are the durable record.
- `.trellis/`, `.opencode/`, `.codex/`, `.agents/`, and `AGENTS.md` are local runtime/config files, not formal records.
- Never let the external agent commit.
- Never commit without explicit user confirmation.

## Agent Files

Use only the generic agent protocol files:

```text
agent_prompt.md
agent_fix_prompt.md
agent_status.json
```

Do not create or rely on adapter-specific protocol files.
