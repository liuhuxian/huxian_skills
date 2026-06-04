# Initialization Guidance

If preflight reports missing initialization, do not start an external agent. Tell the user exactly what is missing and provide commands they can run manually.

## OpenSpec Missing

Symptoms:

```text
openspec_ready=no
openspec_dir=no
openspec_config=no
openspec_changes_dir=no
```

Tell the user to initialize OpenSpec before using `call_agent_code`:

```bash
mkdir -p openspec/changes openspec/specs
cat > openspec/config.yaml <<'YAML'
schema: spec-driven
YAML
```

If the project already has an OpenSpec CLI or template workflow, prefer the project's documented OpenSpec init command instead. Do not invent network-dependent installation steps.

## Trellis Shared Runtime Missing

Symptoms:

```text
trellis_dir=no
# or
trellis_task_py=no
```

Tell the user Trellis is optional for the formal OpenSpec workflow but required for Trellis task tracking/context. Ask them to run their installed Trellis init for this repo. If they want platform-specific init, include the target platform:

```bash
trellis init --opencode
# or
trellis init --codebuddy
```

If the exact Trellis init flags are uncertain on the machine, ask the user to run:

```bash
trellis --help
```

and then rerun preflight.

## OpenCode Platform Missing

Symptoms:

```text
platform_dir=no
agents_dir=no
trellis_implement_agent=no
trellis_check_agent=no
session_start_plugin=no
```

Tell the user OpenCode can still run in prompt-only OpenSpec mode, but Trellis hook injection is unavailable. To enable Trellis integration, ask them to initialize Trellis for OpenCode:

```bash
trellis init --opencode
```

Then run:

```bash
/users/huxian/.codex/skills/call_agent_code/scripts/check_agent_trellis_setup.sh opencode .
```

## CodeBuddy Platform Missing

Symptoms:

```text
trellis_platform_init=incomplete
agents_dir=no
hooks_dir=no
settings_json=no
```

Tell the user CodeBuddy can run in prompt-only OpenSpec mode, but Trellis hooks/agents/context injection are unavailable. To enable Trellis integration, ask them to initialize Trellis for CodeBuddy:

```bash
trellis init --codebuddy
```

Then run:

```bash
/users/huxian/.codex/skills/call_agent_code/scripts/check_agent_trellis_setup.sh codebuddy .
```

If `trellis init --codebuddy` is unsupported by the installed Trellis version, keep CodeBuddy in prompt-only OpenSpec mode and record that fallback in `implementation_notes.md`.
