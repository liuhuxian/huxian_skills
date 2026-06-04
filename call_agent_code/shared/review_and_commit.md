# Review And Commit

## Codex Review

After the selected agent reports `done` or `needs_review`, review:

- `git diff`
- `openspec/changes/<change>/tasks.md`
- `openspec/changes/<change>/implementation_notes.md`
- `openspec/changes/<change>/agent_status.json`
- verification output recorded in OpenSpec artifacts

Write:

```text
openspec/changes/<change>/code_review.md
```

Use this shape:

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

If blocking issues exist, write `agent_fix_prompt.md` and run another adapter cycle.

## Final Review

When accepted, write:

```text
openspec/changes/<change>/final_review.md
```

Include:

- Summary of implementation.
- Verification commands and results.
- Review decision.
- Recommended commit message.

## Commit Preparation

Run:

```bash
git status --short
git diff --stat
git diff --check
```

Stage only files related to the change. Then show:

```bash
git diff --cached --stat
git diff --cached --name-only
```

Ask for explicit commit confirmation. Only then commit.
