# huxian_skills

A personal collection of AI CLI skills, synced via symlinks to multiple CLI tools (OpenCode, Claude Code, Codex, CodeBuddy).

## Quick Start

```bash
# 1. Clone the repo
git clone git@github.com:liuhuxian/huxian_skills.git
cd huxian_skills

# 2. Interactive install
./install.sh

# 3. Check status
./install.sh --list
```

## install.sh Usage

### Interactive Mode

```bash
./install.sh
```

Shows all skills in the repo (see [Skills](#skills) below for details), then opens a checkbox UI:
- **Space** to toggle, **arrow keys** to move, **Enter** to confirm
- Already-installed skills and CLIs are marked `(installed)`
- Skill selection prompts with `(see README.md for skill details)` as a reminder

```bash
./install.sh --uninstall
```

Same interactive flow: shows installed skills with their CLI locations, select and confirm to remove.

> In non-TTY environments (pipes/scripts), automatically falls back to numeric input (e.g. `1,3` or `all`).

### Quick Commands

| Command | Description |
|---------|-------------|
| `./install.sh <cli>` | Install all skills to a CLI (e.g. `./install.sh codex`) |
| `./install.sh <cli> <skill>` | Install a single skill to a CLI |
| `./install.sh --list` | Show install status per CLI |
| `./install.sh --check` | Verify all symlinks are valid |
| `./install.sh --uninstall` | Interactive: select skills to remove |
| `./install.sh --uninstall <name>` | Remove a skill from all CLIs |

### Adding a New Skill

1. Create a skill directory with `SKILL.md` in the repo root
2. Run `./install.sh` and select the new skill

No config files needed — the script auto-discovers skills by scanning the repo.

### How It Works

```
huxian_skills/ (git repo — single source of truth)
├── call_opencode_code/SKILL.md    ← actual file
├── paper-analyzer/SKILL.md        ← actual file
└── ...

~/.codex/skills/
  call_opencode_code → huxian_skills/call_opencode_code   ← symlink

~/.config/opencode/skills/
  call_opencode_code → huxian_skills/call_opencode_code   ← symlink

~/.claude/skills/
  paper-analyzer     → huxian_skills/paper-analyzer       ← symlink
```

Symlinks in each CLI's skills directory point to real files in this repo:
- Editing a skill in any CLI = editing the repo file → `git diff` shows changes
- `git pull` updates files → all symlinks see the latest content instantly

---

## Skills

> When choosing skills interactively, refer back here if you're unsure what each does.

### call_opencode_code

**Purpose**: OpenSpec + Trellis + OpenCode collaborative development workflow.

Codex orchestrates, OpenCode implements, Trellis tracks — a five-stage pipeline:

| Stage | Description |
|-------|-------------|
| 1. Draft Change | Codex writes OpenSpec artifacts (proposal / design / specs / tasks) |
| 2. Await Approval | Pause for user to confirm the proposal |
| 3. Auto Implement | Codex launches OpenCode in tmux for implementation and verification |
| 4. Codex Review | Poll `opencode_status.json`, review diffs / notes / verification |
| 5. Prepare Commit | Codex stages the commit, user gives final approval |

**Use when**: medium-to-large changes need formal specs and review, multi-agent collaboration, or git-tracked requirement docs.

**Target CLI**: Codex (orchestrator role)

---

### paper-analyzer

**Purpose**: Analyze academic PDF papers and generate Chinese-language Markdown notes with PlantUML architecture diagrams.

Reads PDFs through a "grad advisor's" lens, producing accessible Chinese notes with structured interpretation and PlantUML model diagrams.

**Key features**:
- Auto-detects PDF type (text vs. scanned); prompts for OCR on scanned files
- Structured interpretation: background → method → results → one-line summary
- Smart judgement on whether a PlantUML architecture diagram is needed
- Built-in validation script + plantuml.jar ensures Obsidian-compatible rendering
- Output directory structure mirrors source directory
- Batch mode auto-skips already-analyzed files; every paper gets full quality treatment

**Quick triggers**:
```
analyze paper {pdf path}
analyze paper folder {directory path}
```

**Target CLI**: Claude Code (PDF reading), Codex
