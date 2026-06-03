# huxian_skills

个人 AI CLI skills 集合，通过 symlink 同步到多个 CLI 工具（OpenCode、Claude Code、Codex、CodeBuddy）。

## 快速开始

```bash
# 1. 克隆仓库
git clone git@github.com:liuhuxian/huxian_skills.git
cd huxian_skills

# 2. 交互式安装（选择 CLI 和 skill）
./install.sh

# 3. 查看状态
./install.sh --list
```

## install.sh 使用说明

### 交互模式

```bash
./install.sh
```

运行后展示所有 skill 和已检测到的 CLI，用复选框界面选择：
- **选择 CLI**：空格勾选，方向键移动，回车确认
- **每个 CLI 选择 skill**：同上
- 已安装的 skill 和 CLI 会自动标注 `(installed)`

```bash
./install.sh --uninstall
```

同样交互式：展示所有已安装的 skill 及其所在 CLI，勾选后回车确认移除。

> 在非终端环境（管道/脚本）中自动退回到数字输入模式（如 `1,3` 或 `all`）。

### 快捷命令

| 命令 | 说明 |
|------|------|
| `./install.sh <cli>` | 将仓库所有 skill 安装到指定 CLI（如 `./install.sh codex`） |
| `./install.sh <cli> <skill>` | 将单个 skill 安装到指定 CLI（如 `./install.sh codex paper-analyzer`） |
| `./install.sh --list` | 列出所有 CLI 的安装状态 |
| `./install.sh --check` | 检查所有 symlink 是否有效 |
| `./install.sh --uninstall` | 交互式选择要移除的 skill |
| `./install.sh --uninstall <name>` | 从所有 CLI 移除指定 skill |

### 添加新 skill

1. 在仓库根目录创建新 skill 目录和 `SKILL.md`
2. 运行 `./install.sh`，交互式选择要安装到哪些 CLI

无需编辑配置文件——脚本自动扫描仓库目录发现所有 skill。

### 工作原理

```
huxian_skills/ (git repo — 唯一源)
├── call_opencode_code/SKILL.md    ← 实际文件
├── paper-analyzer/SKILL.md        ← 实际文件
└── ...

~/.codex/skills/
  call_opencode_code → huxian_skills/call_opencode_code   ← symlink

~/.config/opencode/skills/
  call_opencode_code → huxian_skills/call_opencode_code   ← symlink

~/.claude/skills/
  paper-analyzer     → huxian_skills/paper-analyzer       ← symlink
```

各 CLI 的 skills 目录中创建 symlink 指向本仓库的实际文件。在任意 CLI 编辑 skill 等于直接编辑仓库文件，`git diff` 可直接看到变更；`git pull` 后 symlink 自动看到最新内容。

---

## Skills

### call_opencode_code

**用途**：OpenSpec + Trellis + OpenCode 协作开发工作流。

当用户希望 Codex 通过 OpenSpec 管理需求、Trellis 追踪任务、OpenCode 执行实现时使用。覆盖从起草 proposal 到最终 commit 的完整五阶段流程：

| 阶段 | 说明 |
|------|------|
| 1. Draft Change | Codex 根据用户需求编写 OpenSpec artifacts（proposal/design/specs/tasks） |
| 2. Await Approval | 暂停等待用户确认 proposal |
| 3. Auto Implement | 用户确认后，Codex 在 tmux 中启动 OpenCode 执行实现和验证 |
| 4. Codex Review | Codex 轮询 `opencode_status.json`，完成后审查 diff/notes/verification |
| 5. Prepare Commit | Codex 准备 commit，最终由用户确认提交 |

**适用场景**：
- 中大型代码变更，需要 formal spec 和 review
- 需要多个 agent 协作的任务（Codex 起草 + OpenCode 实现）
- 需要 git-tracked 需求文档和 review 记录的项目

**适用 CLI**：Codex（作为编排者的角色）

---

### paper-analyzer

**用途**：分析学术论文 PDF，生成中文解读 Markdown 笔记。

以"研究生导师"的视角将论文转化为通俗易懂的中文笔记，包含论文解读和 PlantUML 模型架构简图。支持单个 PDF 分析和批量文件夹递归分析。

**核心能力**：
- 提取 PDF 文字内容（扫描版 PDF 会提示用户使用 OCR）
- 生成结构化中文解读：研究背景 → 核心方法 → 实验结果 → 一句话总结
- 自动判断是否需要 PlantUML 模型架构图
- 生成 Obsidian 兼容的 PlantUML 代码（内置验证脚本确保渲染无问题）
- 输出目录自动镜像源文件夹的目录结构
- 批量处理时自动跳过已有解析记录的文件

**PlantUML 渲染保证**：skill 内置 `scripts/validate_plantuml.py` 验证脚本和 `scripts/plantuml.jar` 渲染引擎，生成 PlantUML 后必须先通过本地/在线验证才能写入文件，确保在 Obsidian 中正常显示。

**快捷指令**：
```
分析论文 {pdf文件路径}          → 单文件模式
分析论文文件夹 {文件夹路径}     → 文件夹批量模式
```

**前置交互**：使用前需要确认三个信息：分析模式（单文件/文件夹）、源路径、输出路径。

**适用 CLI**：Claude Code（有 Read PDF 能力）、Codex
