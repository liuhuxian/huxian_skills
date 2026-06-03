#!/usr/bin/env bash
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

declare -A CLI_DIRS=(
    ["opencode"]="$HOME/.config/opencode/skills"
    ["claude"]="$HOME/.claude/skills"
    ["codex"]="$HOME/.codex/skills"
    ["codebuddy"]="$HOME/.codebuddy/skills"
)

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
CYAN='\033[0;36m'
GRAY='\033[0;90m'
BOLD='\033[1m'
NC='\033[0m'

usage() {
    cat <<'EOF'
Usage: install.sh [COMMAND | CLI [SKILL]]

Commands:
  (no args)          Interactive: pick CLIs and skills to install
  <cli>              Install ALL repo skills to a CLI (opencode|claude|codex|codebuddy)
  <cli> <skill>      Install a specific skill to a CLI
  --list             Show skills installed in each CLI
  --check            Verify all symlinks are healthy
  --uninstall        Interactive: select skills to remove
  --uninstall <name> Remove a skill's symlinks from all CLIs

EOF
    exit 0
}

# ── discovery functions ──

get_skills() {
    for d in "$REPO_DIR"/*/; do
        local name
        name="$(basename "$d")"
        [[ -f "${d}SKILL.md" && "$name" != ".git" ]] && echo "$name"
    done
}

get_clis() {
    for cli in "${!CLI_DIRS[@]}"; do
        echo "$cli"
    done | sort
}

installed_skills_for() {
    local cli="$1"
    local dir="${CLI_DIRS[$cli]}"
    if [[ ! -d "$dir" ]]; then
        return 0
    fi
    for link in "$dir"/*; do
        [[ -L "$link" ]] || continue
        local target
        target="$(readlink "$link")"
        if [[ "$target" == "$REPO_DIR"/* ]]; then
            basename "$link"
        fi
    done | sort
}

symlink_status() {
    local link="$1"
    local expected_target="$2"
    if [[ -L "$link" ]]; then
        local actual_target
        actual_target="$(readlink "$link")"
        if [[ "$actual_target" == "$expected_target" ]]; then
            echo "ok"
        elif [[ -e "$link" ]]; then
            echo "wrong"
        else
            echo "broken"
        fi
    elif [[ -e "$link" ]]; then
        echo "file"
    else
        echo "missing"
    fi
}

icon_for() {
    case "$1" in
        ok)     echo -e "${GREEN}✅${NC}" ;;
        missing) echo -e "${GRAY}⬚${NC}" ;;
        broken) echo -e "${RED}💀${NC}" ;;
        wrong)  echo -e "${YELLOW}⚡${NC}" ;;
        file)   echo -e "${YELLOW}⚠${NC}" ;;
        *)      echo "?" ;;
    esac
}

label_for() {
    case "$1" in
        ok)     echo "installed" ;;
        missing) echo "not installed" ;;
        broken)  echo "broken link" ;;
        wrong)   echo "wrong target" ;;
        file)    echo "regular file/dir (not a symlink)" ;;
    esac
}

# ── TUI multi-select (space toggle, arrows move, enter confirm) ──

has_tty() {
    ( stty -g < /dev/tty ) 2>/dev/null
}

multi_select() {
    local prompt="$1"
    shift
    local options=("$@")
    local num=${#options[@]}
    local tty="/dev/tty"

    # fallback to numeric input when no TTY
    if ! has_tty; then
        echo "$prompt" >&2
        for ((i = 0; i < num; i++)); do
            echo "  $((i + 1)). ${options[$i]}" >&2
        done
        echo "" >&2
        read -r -p "Select (e.g. 1,3 or all): " input
        input="${input// /}"
        input="${input,,}"
        if [[ "$input" == "all" || "$input" == "a" || -z "$input" ]]; then
            seq 1 "$num"
        else
            IFS=',' read -ra parts <<<"$input"
            for part in "${parts[@]}"; do
                if [[ "$part" =~ ^([0-9]+)-([0-9]+)$ ]]; then
                    for ((i = ${BASH_REMATCH[1]}; i <= ${BASH_REMATCH[2]} && i <= num; i++)); do
                        echo "$i"
                    done
                elif [[ "$part" =~ ^[0-9]+$ ]] && ((part >= 1 && part <= num)); then
                    echo "$part"
                fi
            done
        fi
        return
    fi

    # TUI mode
    local cursor=0
    local selected=()
    for ((i = 0; i < num; i++)); do
        selected[$i]=0
    done
    local old_stty
    old_stty=$(stty -g < "$tty" 2>/dev/null) || old_stty=""

    cleanup() {
        printf "\033[?1049l" > "$tty"
        stty "$old_stty" < "$tty" 2>/dev/null || stty echo icanon < "$tty" 2>/dev/null || true
        printf "\033[?25h" > "$tty"
        printf "\033[0m" > "$tty"
        trap - EXIT INT TERM
    }
    trap cleanup EXIT INT TERM

    stty -echo -icanon min 0 time 0 < "$tty" 2>/dev/null || true
    printf "\033[?25l" > "$tty"
    printf "\033[?1049h\033[H\033[J" > "$tty"

    while true; do
        printf "\033[H\033[J" > "$tty"
        printf "%s\n" "$prompt" > "$tty"
        printf "\n" > "$tty"
        for ((i = 0; i < num; i++)); do
            if [[ $i -eq $cursor ]]; then
                printf " ${GREEN}▸${NC} " > "$tty"
            else
                printf "   " > "$tty"
            fi
            if [[ ${selected[$i]} -eq 1 ]]; then
                printf "${GREEN}[✓]${NC} " > "$tty"
            else
                printf "[ ] " > "$tty"
            fi
            printf "%s\n" "${options[$i]}" > "$tty"
        done
        printf "\n" > "$tty"
        printf "${GRAY}↑↓ move  Space toggle  Enter confirm${NC}\n" > "$tty"

        local key=""
        IFS= read -rsn1 key < "$tty" 2>/dev/null || { break; }
        if [[ "$key" == $'\x1b' ]]; then
            local seq=""
            IFS= read -rsn2 -t 0.01 seq < "$tty" 2>/dev/null || true
            if [[ "$seq" == '[A' ]]; then
                ((cursor > 0)) && cursor=$((cursor - 1))
            elif [[ "$seq" == '[B' ]]; then
                ((cursor < num - 1)) && cursor=$((cursor + 1))
            fi
        elif [[ "$key" == ' ' ]]; then
            selected[$cursor]=$((1 - selected[$cursor]))
        elif [[ "$key" == '' || "$key" == $'\x0a' ]]; then
            break
        fi
    done

    cleanup

    for ((i = 0; i < num; i++)); do
        if [[ ${selected[$i]} -eq 1 ]]; then
            echo "$((i + 1))"
        fi
    done
}

# ── install ──

do_install() {
    local cli="$1"
    local skills_dir="$2"
    shift 2
    local skills=("$@")
    local did=0

    echo ""
    echo -e "${BOLD}[${cli}]${NC}  (${skills_dir})"

    if [[ ! -d "$skills_dir" ]]; then
        echo -e "  Creating ${skills_dir}"
        mkdir -p "$skills_dir"
    fi

    for skill in "${skills[@]}"; do
        local src="$REPO_DIR/$skill"
        local dst="$skills_dir/$skill"
        local expected="$REPO_DIR/$skill"

        if [[ ! -d "$src" ]]; then
            echo -e "  ${RED}✗${NC} ${skill}: source not found"
            continue
        fi

        local status
        status="$(symlink_status "$dst" "$expected")"

        case "$status" in
            ok)
                echo -e "  ${GREEN}✓${NC} ${skill} (already installed)"
                ;;
            missing)
                echo -e "  ${GREEN}→${NC} ${skill}"
                ln -s "$expected" "$dst"
                did=1
                ;;
            broken|wrong|file)
                echo -e "  ${YELLOW}⚠${NC} ${skill}: $(label_for "$status")"
                echo -e "    Run ./install.sh --uninstall ${skill} first, then retry"
                ;;
        esac
    done

    return 0
}

cmd_install_interactive() {
    local all_skills=($(get_skills))
    local all_clis=($(get_clis))

    if [[ ${#all_skills[@]} -eq 0 ]]; then
        echo -e "${RED}No skills found in ${REPO_DIR}${NC}"
        exit 1
    fi
    if [[ ${#all_clis[@]} -eq 0 ]]; then
        echo -e "${RED}No known CLIs detected${NC}"
        exit 1
    fi

    echo ""
    echo -e "${BOLD}Skills in this repo:${NC}"
    for i in "${!all_skills[@]}"; do
        echo "  $((i + 1)). ${all_skills[$i]}"
    done

    # Build CLI options with installed info
    local cli_options=()
    for i in "${!all_clis[@]}"; do
        local cli="${all_clis[$i]}"
        local dir="${CLI_DIRS[$cli]}"
        local installed
        installed=($(installed_skills_for "$cli"))
        local label="$cli  ($dir)"
        if [[ ${#installed[@]} -gt 0 ]]; then
            label+="  [installed: ${installed[*]}]"
        fi
        cli_options+=("$label")
    done

    mapfile -t cli_indices < <(multi_select "Select CLIs to install to:" "${cli_options[@]}" | grep -E '^[0-9]+$')

    if [[ ${#cli_indices[@]} -eq 0 ]]; then
        echo ""
        echo -e "${GRAY}No CLIs selected. Nothing to do.${NC}"
        return
    fi

    for idx in "${cli_indices[@]}"; do
        local cli="${all_clis[$((idx - 1))]}"
        local dir="${CLI_DIRS[$cli]}"

        local installed_arr=($(installed_skills_for "$cli"))
        local skill_options=()
        for s in "${all_skills[@]}"; do
            local label="$s"
            for ins in "${installed_arr[@]}"; do
                [[ "$ins" == "$s" ]] && label+=" (installed)" && break
            done
            skill_options+=("$label")
        done

        mapfile -t skill_indices < <(multi_select "Select skills for [${cli}] (see README.md for skill details):" "${skill_options[@]}" | grep -E '^[0-9]+$')
        if [[ ${#skill_indices[@]} -eq 0 ]]; then
            echo -e "  ${GRAY}No skills selected for ${cli}, skipped${NC}"
            continue
        fi

        local chosen=()
        for sidx in "${skill_indices[@]}"; do
            chosen+=("${all_skills[$((sidx - 1))]}")
        done
        do_install "$cli" "$dir" "${chosen[@]}"
    done

    echo ""
    echo -e "${GREEN}Done.${NC} Run './install.sh --list' to verify."
}

cmd_install_cli() {
    local cli="$1"
    local skills_dir="${CLI_DIRS[$cli]:-}"
    if [[ -z "$skills_dir" ]]; then
        echo -e "${RED}Unknown CLI: ${cli}${NC}"
        echo "Known: ${!CLI_DIRS[*]}"
        exit 1
    fi
    local all_skills=($(get_skills))
    do_install "$cli" "$skills_dir" "${all_skills[@]}"
}

cmd_install_skill() {
    local cli="$1"
    local skill="$2"
    local skills_dir="${CLI_DIRS[$cli]:-}"
    if [[ -z "$skills_dir" ]]; then
        echo -e "${RED}Unknown CLI: ${cli}${NC}"
        exit 1
    fi
    if [[ ! -d "$REPO_DIR/$skill" ]]; then
        echo -e "${RED}Skill not found: ${skill}${NC}"
        exit 1
    fi
    do_install "$cli" "$skills_dir" "$skill"
}

# ── list / check ──

cmd_list() {
    local all_clis=($(get_clis))
    local all_skills=($(get_skills))

    for cli in "${all_clis[@]}"; do
        local dir="${CLI_DIRS[$cli]}"
        local installed
        installed=($(installed_skills_for "$cli"))

        echo ""
        echo -e "${CYAN}${cli}${NC}  (${dir})"

        if [[ ${#installed[@]} -eq 0 ]]; then
            echo -e "  ${GRAY}(no skills from this repo installed)${NC}"
            continue
        fi

        for skill in "${all_skills[@]}"; do
            local dst="$dir/$skill"
            local expected="$REPO_DIR/$skill"
            local installed_here=0
            for ins in "${installed[@]}"; do
                [[ "$ins" == "$skill" ]] && installed_here=1 && break
            done
            if [[ "$installed_here" -eq 0 ]]; then
                printf "  %-30s %s %s\n" "$skill" "$(icon_for missing)" "not installed"
            else
                local status
                status="$(symlink_status "$dst" "$expected")"
                printf "  %-30s %s %s\n" "$skill" "$(icon_for "$status")" "$(label_for "$status")"
            fi
        done
    done
    echo ""
}

cmd_check() {
    local problems=0
    local all_clis=($(get_clis))
    local all_skills=($(get_skills))

    for cli in "${all_clis[@]}"; do
        local dir="${CLI_DIRS[$cli]}"
        for skill in "${all_skills[@]}"; do
            local dst="$dir/$skill"
            local expected="$REPO_DIR/$skill"
            if [[ -L "$dst" ]] || [[ -e "$dst" ]]; then
                local status
                status="$(symlink_status "$dst" "$expected")"
                case "$status" in
                    ok|missing) ;;
                    *)
                        echo -e "${YELLOW}[${cli}]${NC} ${skill}: $(label_for "$status")"
                        problems=$((problems + 1))
                        ;;
                esac
            fi
        done
    done

    if [[ "$problems" -eq 0 ]]; then
        echo -e "${GREEN}All symlinks are healthy.${NC}"
    else
        echo ""
        echo -e "${YELLOW}${problems} issue(s) found.${NC}"
    fi
}

# ── uninstall ──

cmd_uninstall() {
    local skill_name="$1"
    local removed=0
    local all_clis=($(get_clis))

    for cli in "${all_clis[@]}"; do
        local dir="${CLI_DIRS[$cli]}"
        local dst="$dir/$skill_name"
        local expected="$REPO_DIR/$skill_name"

        if [[ -L "$dst" ]]; then
            local target
            target="$(readlink "$dst")"
            if [[ "$target" == "$REPO_DIR"/*"$skill_name" ]]; then
                echo -e "  ${RED}✗${NC} [${cli}] Removing ${dst}"
                rm "$dst"
                removed=$((removed + 1))
            else
                echo -e "  ${GRAY}·${NC} [${cli}] ${skill_name} points elsewhere, skipping"
            fi
        elif [[ -e "$dst" ]]; then
            echo -e "  ${YELLOW}⚠${NC} [${cli}] ${dst} is not a symlink, skipping"
        fi
    done

    if [[ "$removed" -gt 0 ]]; then
        echo ""
        echo -e "${GREEN}Removed ${removed} symlink(s) for '${skill_name}'.${NC}"
    else
        echo -e "${GRAY}No symlinks found for '${skill_name}'.${NC}"
    fi
}

cmd_uninstall_interactive() {
    local all_clis=($(get_clis))

    # Collect all installed skills per CLI
    declare -A all_installed_map
    local all_installed_list=()
    for cli in "${all_clis[@]}"; do
        local installed
        installed=($(installed_skills_for "$cli"))
        for skill in "${installed[@]}"; do
            if [[ -z "${all_installed_map[$skill]:-}" ]]; then
                all_installed_map[$skill]="$cli"
                all_installed_list+=("$skill")
            else
                all_installed_map[$skill]="${all_installed_map[$skill]}, $cli"
            fi
        done
    done

    if [[ ${#all_installed_list[@]} -eq 0 ]]; then
        echo -e "${GRAY}No skills are currently installed.${NC}"
        return
    fi

    local options=()
    for skill in "${all_installed_list[@]}"; do
        options+=("$skill  (installed in: ${all_installed_map[$skill]})")
    done

    mapfile -t selected < <(multi_select "Select skills to uninstall:" "${options[@]}" | grep -E '^[0-9]+$')

    if [[ ${#selected[@]} -eq 0 ]]; then
        echo -e "${GRAY}Nothing selected.${NC}"
        return
    fi

    for idx in "${selected[@]}"; do
        cmd_uninstall "${all_installed_list[$((idx - 1))]}"
    done
}

# ── main ──

main() {
    case "${1:-}" in
        --help|-h|help)
            usage
            ;;
        --list|-l|list)
            cmd_list
            ;;
        --check|-c|check)
            cmd_check
            ;;
        --uninstall|-u|uninstall)
            if [[ -z "${2:-}" ]]; then
                cmd_uninstall_interactive
            else
                cmd_uninstall "$2"
            fi
            ;;
        "")
            cmd_install_interactive
            ;;
        *)
            if [[ "${1:0:1}" == "-" ]]; then
                echo -e "${RED}Unknown option: $1${NC}"
                usage
            fi
            if [[ -n "${2:-}" ]]; then
                cmd_install_skill "$1" "$2"
            else
                cmd_install_cli "$1"
            fi
            ;;
    esac
}

main "$@"
