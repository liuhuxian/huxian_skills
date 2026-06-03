# huxian_skills

个人 AI CLI skills 集合，通过 symlink 同步到多个 CLI 工具（OpenCode、Claude Code、Codex、CodeBuddy）。

## 快速开始

```bash
# 1. 克隆仓库
git clone git@github.com:liuhuxian/huxian_skills.git
cd huxian_skills

# 2. 交互式安装
./install.sh

# 3. 查看状态
./install.sh --list
```

## install.sh 使用说明

### 交互模式

```bash
./install.sh
```

运行后显示仓库中所有 skill 列表（具体功能见下方 [Skills](#skills) 章节），然后进入复选框界面：
- **空格** 勾选 / 取消，**方向键** 移动，**回车** 确认
- 已安装的 skill 和 CLI 标注 `(installed)`
- 选择 skill 时提示 `(see README.md for skill details)`，提醒先阅读下方功能说明

```bash
./install.sh --uninstall
```

同样交互式：展示已安装的 skill 及其所在 CLI，勾选后回车移除。

> 非终端环境（管道/脚本）自动退回数字输入模式（如 `1,3` 或 `all`），不影响自动化使用。

### 快捷命令

| 命令 | 说明 |
|------|------|
| `./install.sh <cli>` | 将仓库所有 skill 安装到指定 CLI（如 `./install.sh codex`） |
| `./install.sh <cli> <skill>` | 将单个 skill 安装到指定 CLI |
| `./install.sh --list` | 列出各 CLI 安装状态 |
| `./install.sh --check` | 检查所有 symlink 是否有效 |
| `./install.sh --uninstall` | 交互式选择要移除的 skill |
| `./install.sh --uninstall <name>` | 从所有 CLI 移除指定 skill |

### 添加新 skill

1. 在仓库根目录创建 skill 目录和 `SKILL.md`
2. 运行 `./install.sh`，勾选要安装的 skill 和 CLI

无需编辑配置文件 — 脚本自动扫描仓库目录发现所有 skill。

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

CLI 的 skills 目录中创建 symlink 指向本仓库实际文件：
- 在任意 CLI 编辑 skill = 直接编辑仓库文件 → `git diff` 可见变更
- `git pull` 后 symlink 自动看到最新内容

---

## Skills

> 交互安装时若不确定 skill 用途，请回到此处查阅后再勾选。

### call_opencode_code

**用途**：OpenSpec + Trellis + OpenCode 协作开发工作流。

Codex 编排、OpenCode 实现、Trellis 追踪的五阶段开发流程：

| 阶段 | 说明 |
|------|------|
| 1. Draft Change | Codex 编写 OpenSpec artifacts（proposal / design / specs / tasks） |
| 2. Await Approval | 暂停等待用户确认 proposal |
| 3. Auto Implement | Codex 在 tmux 中启动 OpenCode 执行实现和验证 |
| 4. Codex Review | 轮询 `opencode_status.json`，审查 diff / notes / verification |
| 5. Prepare Commit | Codex 准备 commit，用户最终确认 |

**适用场景**：中大型变更需 formal spec + review、多 agent 协作、需 git-tracked 文档的项目。

**适用 CLI**：Codex（编排角色）

---

### paper-analyzer

**用途**：分析学术论文 PDF，生成含模型架构图的中文解读笔记。

以"研究生导师"视角，将论文转为通俗中文笔记，含论文解读和 PlantUML 模型简图。

**核心能力**：
- 自动判断 PDF 类型（文本 / 扫描版），扫描版提示 OCR
- 结构化解读：研究背景 → 核心方法 → 实验结果 → 一句话总结
- 智能判断是否需要 PlantUML 架构图
- 内置验证脚本 + plantuml.jar，确保 Obsidian 渲染无问题
- 输出目录自动镜像源目录结构
- 批量处理自动跳过已有解析，逐篇保证质量

**快捷指令**：
```
分析论文 {pdf路径}
分析论文文件夹 {文件夹路径}
```

**适用 CLI**：Claude Code（Read PDF）、Codex
