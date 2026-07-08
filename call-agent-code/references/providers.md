# Runner and Model Providers

Role specs use `runner:provider/model`.

- `runner` is the local CLI adapter, such as `opencode` or `codebuddy`.
- `provider` is the model provider ID configured in that CLI, such as `volcengine-plan`, `deepseek`, `openai`, or `alibaba-cn`.
- `model` is the provider model ID, such as `glm-5.2`, `minimax-m3`, or `deepseek-v4-pro`.

For OpenCode, the command should pass the model as `provider/model`, matching OpenCode config and recent model state files. Example: `volcengine-plan/glm-5.2`.

For CodeBuddy, use the model/provider format supported by the installed CLI. If the CLI only accepts a bare model name, the adapter may pass `model` only.

Provider failures must write `status.json` with `state=failed` and a concise `blocking_issue`.

Do not add external workflow-state setup, hook checks, task updates, or status mirrors.
