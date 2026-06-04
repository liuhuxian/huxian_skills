# Agent Status Protocol

Use generic status file:

```text
openspec/changes/<change>/agent_status.json
```

## Schema

```json
{
  "agent": "opencode",
  "state": "running",
  "phase": "queued",
  "updated_at": "2026-06-04T00:00:00+08:00",
  "message": "等待外部 agent 开始执行"
}
```

## States

```text
running | blocked | failed | needs_review | done
```

## Phase Examples

```text
queued | reading_spec | editing | running_verification | writing_notes | addressing_review | done
```

## Minimum Updates Required From Agent

- Start: `running / reading_spec`
- Before editing: `running / editing`
- Before verification: `running / running_verification`
- Before handoff notes: `running / writing_notes`
- Completion: `done / done` or `needs_review / done`
- Failure: `failed / <phase>` with short summary
- Blockage: `blocked / <phase>` with decision needed

Codex polls status only during normal execution.
