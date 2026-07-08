# File Protocol

All per-task runtime files live under:

```text
openspec/changes/<change>/agent/
```

Required files:

```text
request.json
status.json
progress.log
agent_prompt.md
code_reviewer_prompt.md
task_verifier_prompt.md
codex_review_prompt.md
changed_files.txt
verification.md
self_review.md
code_review_round_<n>.md
task_verification_round_<n>.md
codex_review_round_<n>.md
completion_gate.json
handover.md
final_status.json
```

`status.json` is the low-token state surface. It must be atomically rewritten and contain:

```json
{
  "change": "change-name",
  "state": "implementing",
  "phase": "editing",
  "round": 1,
  "max_review_rounds": 3,
  "updated_at": "2026-07-08T12:00:00+08:00",
  "developer": {"runner": "opencode", "provider": "volcengine-plan", "model": "glm-5.2"},
  "code_reviewer": {"runner": "opencode", "provider": "volcengine-plan", "model": "minimax-m3"},
  "task_verifier": {"runner": "opencode", "provider": "volcengine-plan", "model": "glm-5.2"},
  "session_id": "change-name",
  "blocking_issue": null
}
```

Allowed `state` values:

```text
created
agent_started
implementing
code_reviewing
task_verifying
codex_reviewing
fixing_after_review
ready_for_codex_review
ready_for_commit
blocked
failed
stopped
```

`completion_gate.json` must contain booleans for:

```json
{
  "tasks_completed": true,
  "changed_files_listed": true,
  "verification_recorded": true,
  "verification_exit_codes_recorded": true,
  "code_review_passed": true,
  "task_verification_passed": true,
  "codex_review_passed": true,
  "no_major_findings": true,
  "handover_written": true,
  "ready_for_commit": true
}
```

Validation rule: missing evidence is failure. Do not infer test success from prose.
