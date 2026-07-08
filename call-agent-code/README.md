# call-agent-code 使用说明

`call-agent-code` 是一个基于 OpenSpec 的外部 agent 开发流水线。它的目标是让 Codex 负责架构和主审核，让外部 coding agent 负责开发，再通过独立审核和文件协议降低“任务没完成却说完成”的风险。

## 核心角色

```text
Codex
  负责：写 OpenSpec、架构设计、最终主审核、准备 commit 信息。

developer agent
  负责：按 OpenSpec 开发代码、运行验证、写交接文件。

code reviewer
  负责：独立代码审核，重点查 bug、回归、边界条件、测试缺失。

task verifier
  负责：独立任务验收，检查 OpenSpec 是否真的完成、验证证据是否充分。

orchestrator
  负责：本地脚本调度流程，不是模型，不做代码判断。
```

## 默认配置

配置文件：

```text
~/.codex/huxian_skills/call-agent-code/config.yaml
```

当前默认值：

```yaml
defaults:
  worktree: /users/huxian/project/le-wm/.worktree/wk1
  developer:
    runner: opencode
    provider: deepseek
    model: deepseek-v4-pro
    session_id: change-name
  code_reviewer:
    runner: opencode
    provider: volcengine-plan
    model: glm-5.2
  task_verifier:
    runner: opencode
    provider: volcengine-plan
    model: glm-5.2
  codex_review:
    enabled: true
    command: codex --no-alt-screen
  background: true
  auto_commit: false
  max_review_rounds: 10
  status_poll_seconds: 20
```


字段含义：

```text
runner   = 调哪个本地 CLI，例如 opencode、codebuddy。
provider = 该 CLI 里的模型提供商，例如 volcengine-plan、deepseek、openai。
model    = 模型名，例如 glm-5.2、minimax-m3、deepseek-v4-pro。
```


`developer.session_id` 只控制开发 agent 的会话标签。默认情况下 OpenCode 使用 `--title` 创建新会话，不会用 `--session` 恢复不存在的会话。只有命令行显式传入形如 `ses_...` 的已有 OpenCode session id 时，developer 才会用 `--session` 恢复该会话。code reviewer 和 task verifier 始终使用自动派生的独立 title：

```text
developer     = <session_id>
code_reviewer = <session_id>-code-reviewer
task_verifier = <session_id>-task-verifier
```

OpenCode 使用的模型格式是：

```text
provider/model
```

例如：

```text
volcengine-plan/glm-5.2
volcengine-plan/minimax-m3
```

## 常用调用

默认启动：

```text
$call-agent-code
```

指定模型：

```text
$call-agent-code start opencode:volcengine-plan/glm-5.2
```

指定开发 agent、代码审核、任务验收：

```text
$call-agent-code start opencode:volcengine-plan/glm-5.2 \
  --code-reviewer opencode:volcengine-plan/minimax-m3 \
  --task-verifier opencode:volcengine-plan/glm-5.2
```

指定 worktree：

```text
$call-agent-code --worktree wk1
```

`wk1` 会解析为当前项目的：

```text
.worktree/wk1
```

不过当前全局配置已经默认指向：

```text
/users/huxian/project/le-wm/.worktree/wk1
```

所以在 le-wm 项目里通常不用显式传 `--worktree`。

中断后恢复当前最近的 OpenSpec change：

```text
$call-agent-code resume
```

中断后恢复指定 change：

```text
$call-agent-code resume stage1-ddp-safe-sigreg-logging
```

如果要显式指定 worktree：

```text
$call-agent-code resume stage1-ddp-safe-sigreg-logging --worktree wk1
```

`resume` 会根据 `status.json` 和已有产物从中断阶段继续，不是简单从头重跑。

## 推荐工作流

```text
1. Codex 写 OpenSpec
2. 用户审核并确认
3. $call-agent-code 启动后台流水线
4. developer agent 开发
5. code reviewer 独立代码审核
6. task verifier 独立任务验收
7. Codex CLI 自动主审核
8. 如果失败，流水线进入下一轮修复
9. 全部通过后进入 ready_for_commit
10. 用户确认是否提交
```

## 外部循环轮次

`max_review_rounds` 控制的是外部循环次数：

```text
developer -> code reviewer -> task verifier -> Codex review -> fix
```

它不限制 developer agent 内部自己思考、修复、测试的次数。

例如：

```yaml
max_review_rounds: 3
```

表示最多允许 3 轮外部“开发-审核-修复”循环。超过后仍不通过，状态会变成 `blocked`。

## 状态查看

状态文件：

```text
openspec/changes/<change>/agent/status.json
```

查看状态，不消耗 Codex token：

```bash
~/.codex/huxian_skills/call-agent-code/scripts/watch_agent_status.sh \
  openspec/changes/<change>/agent
```

查看日志：

```bash
tail -f openspec/changes/<change>/agent/progress.log
```

Codex 内部也可以一次性查看：

```text
$call-agent-code status <change>
$call-agent-code logs <change>
```

但持续轮询应该用 shell 脚本，不要让 Codex 轮询。

## 状态语义与中断恢复

`watch_agent_status.sh` 的输出区分三类情况：

```text
still running  = pipeline 进程/窗口仍在，当前阶段只是还没结束。
stalled        = status.json 仍是非终态，但 pipeline 进程/窗口已经不在。
failed/blocked = pipeline 主动写入失败或阻塞原因。
```

首屏只打印一次 change、角色、session、status/log 路径。后续只打印当前轮次、阶段、状态和简短进度，不打印代码 diff、不 tail `progress.log`。

`resume` 是阶段级恢复，不是简单从头重跑。它读取 `status.json` 和已有产物文件，尽量从中断阶段继续：

```text
protocol_files_ready / developer_agent / developer_agent_failed -> developer
code_reviewer / code_reviewer_failed                           -> code_reviewer
task_verifier / task_verifier_failed                           -> task_verifier
codex_lead_review                                               -> codex review
review_feedback_pending_fix                                     -> 下一轮 developer
ready_for_commit / blocked                                      -> 不重复启动
```

如果某个 review 文件存在但大小为 0，会视为未完成并重跑该阶段。

## 任务文件

每个 change 会生成：

```text
openspec/changes/<change>/agent/
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

## 完成门禁

不能相信 agent 口头说“完成了”。必须看：

```text
completion_gate.json
verification.md
changed_files.txt
handover.md
code_review_round_<n>.md
task_verification_round_<n>.md
codex_review_round_<n>.md
```

`completion_gate.json` 里关键字段必须为 true：

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

缺少验证命令、退出码、输出路径，都不能算完成。

## 禁止事项

```text
不要让外部 agent commit。
不要在没有用户确认时 commit。
不要用 Trellis。
不要让 Codex 持续轮询 status。
不要把 developer agent 的口头完成当作完成证据。
```

## 什么时候用严格模式

训练代码、验证代码、loss、checkpoint、resume、dataset、cache、闭环评估等任务，默认使用完整流程：

```text
developer + code reviewer + task verifier + Codex lead review
```

文档、小配置、小脚本可以考虑后续增加轻量模式，但当前默认应以严格流程为主。

