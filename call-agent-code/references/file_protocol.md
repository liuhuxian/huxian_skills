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

Review verdict files are round-specific. For each review stage the pipeline generates an intermediate task file such as `code_review_task_round_5.md` plus a short prompt file such as `code_reviewer_prompt_round_5.md`. The reviewer/verifier must read the task file and write the exact corresponding output file such as `code_review_round_5.md` themselves. The first non-empty verdict line must be one of:

```text
- **Verdict:** PASS
- **Verdict:** NEEDS_CHANGES
```

A missing file, empty file, tool error, truncated output, or missing explicit verdict is a hard failure for that stage.

The task/prompt files are temporary protocol files. They are kept on failure, interruption, or blocked states for debugging. Once the pipeline reaches `ready_for_commit`, it deletes:

```text
code_review_task_round_*.md
task_verification_task_round_*.md
codex_review_task_round_*.md
code_reviewer_prompt_round_*.md
task_verifier_prompt_round_*.md
codex_review_prompt_round_*.md
.opencode_runtime/
```

Formal evidence files such as `code_review_round_*.md`, `task_verification_round_*.md`, `codex_review_round_*.md`, `verification.md`, `handover.md`, `completion_gate.json`, `status.json`, `progress.log`, and `final_status.json` are retained.
