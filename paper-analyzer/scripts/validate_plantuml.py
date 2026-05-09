#!/usr/bin/env python3
"""
PlantUML validation script for the paper-analyzer skill.

Validates PlantUML code in two steps:
1. Renders via local plantuml.jar (same engine as Obsidian plugin) to verify syntax
2. Checks for known Obsidian rendering incompatibilities

Usage:
    python validate_plantuml.py <markdown_file.md>
    python validate_plantuml.py --stdin  (reads plantuml from stdin)

Exit code: 0 = all plantuml blocks valid, 1 = issues found

Requires: Java runtime (java) and plantuml.jar (bundled in ../scripts/plantuml.jar)
"""

import sys, os, re, json, subprocess, tempfile, urllib.request, time


def find_plantuml_jar() -> str | None:
    """Find plantuml.jar: check env var, then skill scripts dir, then PATH."""
    paths = [
        os.environ.get('PLANTUML_JAR', ''),
        os.path.join(os.path.dirname(__file__), 'plantuml.jar'),
        os.path.expanduser('~/.claude/tools/plantuml.jar'),
    ]
    for p in paths:
        if p and os.path.isfile(p):
            return p
    # Also try 'plantuml' command (some package managers install it)
    try:
        subprocess.run(['plantuml', '-version'], capture_output=True, timeout=5)
        return 'plantuml'  # system command
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass
    return None


def validate_via_local_jar(uml: str) -> tuple[bool, str]:
    """
    Render PlantUML via local plantuml.jar — same engine as Obsidian's plugin.
    Returns (ok, detail_message).
    """
    jar = find_plantuml_jar()
    if not jar:
        return False, "plantuml.jar not found"

    # Ensure proper @enduml
    uml = uml.strip()
    if not uml.endswith('@enduml'):
        uml += '\n@enduml'
    if not uml.startswith('@startuml'):
        uml = '@startuml\n' + uml

    try:
        if jar == 'plantuml':
            cmd = ['plantuml', '-tsvg', '-pipe']
        else:
            cmd = ['java', '-jar', jar, '-tsvg', '-pipe']

        proc = subprocess.run(
            cmd,
            input=uml,
            capture_output=True,
            text=True,
            timeout=30
        )

        stdout = proc.stdout
        stderr = proc.stderr

        # Check for actual render errors (not just non-zero return code or version banners)
        is_error = (
            'Syntax Error' in stdout or
            'Syntax Error' in stderr or
            'Some diagram description contains errors' in stderr
        )

        if is_error:
            # Extract the error message
            error_lines = []
            for line in (stderr + '\n' + stdout).split('\n'):
                if 'Error' in line or 'ERROR' in line or 'line ' in line.lower():
                    error_lines.append(line.strip())
            error_msg = '; '.join(error_lines[:3]) if error_lines else 'Unknown render error'
            return False, f"Local render failed: {error_msg[:200]}"
        else:
            return True, f"Local jar rendered OK ({len(stdout)} bytes SVG)"

    except subprocess.TimeoutExpired:
        return False, "Local jar timed out after 30s"
    except FileNotFoundError:
        return False, "Java not found — install Java to use local validation"
    except Exception as e:
        return False, f"Local jar error: {e}"


def encode_for_plantuml(text: str) -> str:
    """Encode PlantUML source for the plantuml.com server URL."""
    import zlib, base64
    compressor = zlib.compressobj(9, zlib.DEFLATED, -zlib.MAX_WBITS)
    compressed = compressor.compress(text.encode('utf-8'))
    compressed += compressor.flush()
    b64 = base64.b64encode(compressed).decode('ascii')
    return b64.rstrip('=').replace('+', '-').replace('/', '_')


def validate_syntax_via_server(uml: str) -> tuple[bool, str]:
    """
    Fallback: Submit to plantuml.com to verify basic parse-ability.
    Only used when local jar is unavailable.
    Returns (ok, detail_message).
    """
    # Strip trailing whitespace and ensure proper @enduml
    uml = uml.strip()
    if not uml.endswith('@enduml'):
        uml += '\n@enduml'

    encoded = encode_for_plantuml(uml)
    url = f"https://www.plantuml.com/plantuml/svg/{encoded}"

    for attempt in range(3):
        try:
            req = urllib.request.Request(url, headers={
                'User-Agent': 'Mozilla/5.0'
            })
            resp = urllib.request.urlopen(req, timeout=20)
            body = resp.read()
            content_start = body[:300].decode('utf-8', errors='replace')

            if body[:4] == b'<?xml' or body[:4] == b'<svg':
                return True, f"Syntax OK ({len(body)} bytes SVG)"
            elif 'Syntax Error' in content_start:
                return False, f"Syntax Error: {content_start[:200]}"
            elif 'Error' in content_start and '<svg' not in content_start:
                return False, f"Server Error: {content_start[:200]}"
            else:
                return True, f"Rendered ({len(body)} bytes)"

        except urllib.error.HTTPError as e:
            body = e.read()
            content_start = body[:300].decode('utf-8', errors='replace')
            if b'<?xml' in body[:50] or b'<svg' in body[:50]:
                # Check that the SVG is not actually an error page
                if b'Syntax Error' in body[:1000] or b'Error</text>' in body[:1000]:
                    return False, f"Server error in SVG (HTTP {e.code})"
                return True, f"Syntax OK ({len(body)} bytes, HTTP {e.code})"
            if e.code == 509:
                wait = (attempt + 1) * 5
                if attempt < 2:
                    time.sleep(wait)
                    continue
                return False, "Rate limited by plantuml.com after 3 retries"
            return False, f"HTTP {e.code}: {content_start[:150]}"

        except Exception as e:
            if attempt < 2:
                time.sleep(3)
                continue
            return False, f"Connection error: {e}"

    return False, "Max retries exceeded"


# Obsidian/kroki compatibility rules — patterns known to break rendering
OBSIDIAN_RULES = [
    {
        "pattern": r'!theme\s',
        "message": "'!theme' directive is not supported by Obsidian's PlantUML renderer",
        "severity": "error"
    },
    {
        "pattern": r'skinparam\s+componentStyle\s+rectangle',
        "message": "'skinparam componentStyle rectangle' causes text to disappear in Obsidian",
        "severity": "error"
    },
    {
        "pattern": r'skinparam\s+packageStyle\s+rectangle',
        "message": "'skinparam packageStyle rectangle' can cause rendering issues in Obsidian",
        "severity": "error"
    },
    {
        "pattern": r'skinparam\s+rectangle\s*\{',
        "message": "'skinparam rectangle {...}' block may cause rendering issues in Obsidian",
        "severity": "error"
    },
    {
        "pattern": r'\*\*[^*]+\*\*',
        "message": "Markdown '**bold**' is not valid PlantUML formatting. Use '<b>bold</b>' instead",
        "severity": "warning"
    },
    {
        "pattern": r'rectangle\s+\{[^}]*rectangle\s+\{',
        "message": "Nested 'rectangle { rectangle {...} }' causes text to not render in Obsidian. Use 'package { card ... }'",
        "severity": "error"
    },
    {
        "pattern": r'^(\s*)rectangle\s+',
        "message": "Standalone 'rectangle' element found. Use 'card' (for single module) or 'package' (for grouping) instead — rectangles often fail to display text in Obsidian",
        "severity": "error"
    },
    {
        "pattern": r'!include\s',
        "message": "'!include' directive used. Standard library includes (e.g., <C4/...>) are NOT available in Obsidian's kroki renderer. Remove all !include directives",
        "severity": "error"
    },
    {
        "pattern": r'\bas\s+input\b',
        "message": "'input' is a PlantUML reserved keyword — cannot be used as an alias (e.g., 'as input'). Rename to 'img', 'data_in', etc.",
        "severity": "error"
    },
    {
        "pattern": r'\bas\s+output\b',
        "message": "'output' is a PlantUML reserved keyword — cannot be used as an alias (e.g., 'as output'). Rename to 'result', 'out_data', etc.",
        "severity": "error"
    },
    {
        "pattern": r'\bas\s+node\b',
        "message": "'node' is a PlantUML reserved keyword — cannot be used as an alias",
        "severity": "error"
    },
    {
        "pattern": r'\bas\s+frame\b',
        "message": "'frame' is a PlantUML reserved keyword — cannot be used as an alias",
        "severity": "error"
    },
    {
        "pattern": r'\bas\s+database\b',
        "message": "'database' is a PlantUML reserved keyword — cannot be used as an alias",
        "severity": "error"
    },
    {
        "pattern": r'note\s+right\s+of\s',
        "message": "'note right of' can cause positioning conflicts with packages. Prefer 'note bottom of' for better Obsidian compatibility",
        "severity": "warning"
    },
    {
        "pattern": r'card\s+"[^"]*"\s+as\s+\w+\s*\{',
        "message": "card with '{...}' body block detected. This syntax works on plantuml.com but may fail in Obsidian kroki. Use inline text with \\n instead: card 'line1\\nline2\\nline3' as ID",
        "severity": "warning"
    },
    {
        "pattern": r'\bas\s+\w+"',
        "message": "Extra quote after alias (e.g., 'as ID\"'). This happens when card body flattening fails — check for garbled card labels",
        "severity": "error"
    },
    {
        "pattern": r'\bas\s+\w+\s*=',
        "message": "Garbage characters after alias (e.g., 'as ID = ...'). This happens when card body flattening fails — the body text leaked past the alias",
        "severity": "error"
    },
    {
        "pattern": r'card\s+"[^"]*\{[^}]*$',
        "message": "Unclosed '{' inside card label text. This triggers PlantUML body-block parsing and causes Syntax Error. Escape braces or remove them",
        "severity": "error"
    },
    {
        "pattern": r'^[ \t]*\([^)]*$',
        "message": "Use-case syntax '(text' without closing ')' on same line. Use 'card \"text\" as ID' instead for Obsidian compatibility",
        "severity": "error"
    },
    {
        "pattern": r'->\s*(input|output|node|frame|database|cloud|actor)\b',
        "message": "Arrow pointing to reserved keyword alias. The alias was likely renamed but arrow references were not updated",
        "severity": "error"
    },
]

# Additional custom checks that can't be expressed as simple regex patterns

def check_raw_newlines_in_labels(uml: str) -> list[dict]:
    """Card/package labels MUST use \\n for line breaks, not raw newlines.
    Obsidian's kroki-based PlantUML renderer rejects raw newlines in labels."""
    issues = []
    lines = uml.split('\n')
    for i, line in enumerate(lines):
        s = line.strip()
        # card "text (no closing " → raw newline in label
        if re.match(r'^(card|package)\s+"[^"]*$', s):
            issues.append({
                "severity": "error",
                "message": f"Line {i+1}: raw newline in {re.match(r'^(card|package)', s).group(1)} label. Use \\\\n for line breaks, not actual newlines. Example: card \"line1\\\\nline2\" as ID"
            })
    return issues

# Custom check functions (not regex-based)
def check_forward_references(uml: str) -> list[dict]:
    """Check that all aliases are defined before being used in arrows.
    PlantUML auto-creates an element when an alias first appears in an arrow,
    so a later explicit 'card as X' becomes a duplicate definition error."""
    lines = uml.split('\n')
    defined_at = {}
    for i, line in enumerate(lines):
        m = re.search(
            r'(?:card|package|component|node|database|cloud|frame|actor)\s+"[^"]*"\s+as\s+(\w+)',
            line
        )
        if m:
            defined_at[m.group(1)] = i

    issues = []
    for i, line in enumerate(lines):
        if re.search(r'(?:card|package|component|node|database|cloud|frame|actor)\s+"', line):
            continue
        if re.search(r'(-->|\.\.>|<--|->)', line):
            refs = re.findall(r'\b(\w+)\b', line)
            for ref in refs:
                if ref in defined_at and defined_at[ref] > i:
                    issues.append({
                        "severity": "error",
                        "message": f"Alias '{ref}' used in arrow at line {i+1} but defined at line {defined_at[ref]+1}. Move the 'card as {ref}' definition BEFORE all arrows that reference it"
                    })
                    break
    return issues


def check_orphan_text(uml: str) -> list[dict]:
    """Detect lines that aren't any known PlantUML construct — likely leaked body text."""
    lines = uml.split('\n')
    issues = []
    in_note = False
    in_activity_node = False  # Track multi-line :activity text;
    for i, line in enumerate(lines):
        s = line.strip()
        if not s:
            continue
        # Track note blocks
        if re.match(r'^note\s+(right|left|top|bottom)\s+of\s', s) or s == 'note':
            in_note = True
            continue
        if in_note:
            if s == 'end note':
                in_note = False
            continue
        # Track multi-line activity nodes: :text\nmore text;
        if re.match(r'^:', s) and ';' not in s:
            in_activity_node = True
            continue
        if in_activity_node:
            if s.endswith(';'):
                in_activity_node = False
            continue
        # Valid PlantUML constructs — skip
        if re.match(r'^(card|package|note|title|skinparam|@start|@end|!|//|\'|#{1,6}\s|end\s+note|left\s|right\s|top\s|bottom\s)', s):
            continue
        if re.search(r'(-->|\.\.>|<--|->)', s):
            continue
        if re.match(r'^(database|cloud|frame|actor|node|interface|component|artifact|state|usecase|boundary|control|entity|collections|queue|stack|folder|storage|agent|archimate|rectangle)\s+"', s):
            continue
        if s in ('{', '}', ']', 'end', 'end note', 'start', 'stop', 'endif', 'endfork', 'endwhile', 'endrepeat'):
            continue
        # Activity diagram syntax
        if re.match(r'^\|[^|]+\|$', s):  # |partition|
            continue
        if re.match(r'^:[^;]*;', s):  # :activity node; (single or multi-line)
            continue
        if re.match(r'^(if|else|repeat|while|fork|split|elseif)\b', s, re.IGNORECASE):
            continue
        if re.search(r'-(\w*)->', s):  # activity flow arrows like -down->, -(text)->
            continue
        # Looks like orphan text
        issues.append({
            "severity": "error",
            "message": f"Line {i+1}: orphan text not inside any PlantUML element: '{s[:60]}'. This breaks rendering"
        })
    return issues


def check_obsidian_compat(uml: str) -> list[dict]:
    """Check PlantUML against known Obsidian rendering incompatibilities."""
    issues = []
    for rule in OBSIDIAN_RULES:
        if re.search(rule["pattern"], uml, re.MULTILINE | re.DOTALL):
            issues.append({
                "severity": rule["severity"],
                "message": rule["message"]
            })
    # Add custom checks
    issues.extend(check_forward_references(uml))
    issues.extend(check_orphan_text(uml))
    issues.extend(check_raw_newlines_in_labels(uml))
    return issues


def validate_plantuml_block(uml: str, block_index: int, label: str = "") -> dict:
    """
    Full validation of a PlantUML block.
    Returns dict with 'ok', 'syntax_errors', 'compat_issues'.
    """
    result = {"ok": True, "syntax_errors": [], "compat_issues": []}

    # Step 1: Syntax check — try local jar first (same engine as Obsidian plugin)
    jar_path = find_plantuml_jar()
    if jar_path:
        ok, msg = validate_via_local_jar(uml)
        if not ok:
            result["ok"] = False
            result["syntax_errors"].append(msg)
        else:
            result["syntax_ok"] = f"[local jar] {msg}"
    else:
        # Fallback to plantuml.com server
        if block_index > 0:
            time.sleep(2)
        ok, msg = validate_syntax_via_server(uml)
        if not ok:
            result["ok"] = False
            result["syntax_errors"].append(msg)
        else:
            result["syntax_ok"] = f"[plantuml.com] {msg}"

    # Step 2: Obsidian compatibility check
    compat_issues = check_obsidian_compat(uml)
    if compat_issues:
        errors = [i for i in compat_issues if i["severity"] == "error"]
        if errors:
            result["ok"] = False
        result["compat_issues"] = compat_issues

    return result


def extract_plantuml_blocks(content: str) -> list[tuple[int, str]]:
    """Extract all plantuml code blocks from markdown content."""
    pattern = r'```plantuml\n(.*?)```'
    matches = re.findall(pattern, content, re.DOTALL)
    return list(enumerate(matches))


def main():
    if len(sys.argv) < 2:
        print("Usage: validate_plantuml.py <markdown_file.md>")
        print("       validate_plantuml.py --stdin < plantuml.txt")
        sys.exit(1)

    if sys.argv[1] == '--stdin':
        content = sys.stdin.read()
        label = "(stdin)"
    else:
        filepath = sys.argv[1]
        if not os.path.exists(filepath):
            print(f"ERROR: File not found: {filepath}")
            sys.exit(1)
        with open(filepath, 'r') as f:
            content = f.read()
        label = os.path.basename(filepath)

    blocks = extract_plantuml_blocks(content)

    if not blocks:
        print("INFO: No PlantUML blocks found")
        sys.exit(0)

    print(f"Validating {len(blocks)} PlantUML block(s) from {label}...")
    print()

    all_ok = True
    for idx, uml in blocks:
        print(f"--- Block {idx + 1}/{len(blocks)} ---")
        result = validate_plantuml_block(uml, idx)

        # Syntax check
        if result.get("syntax_ok"):
            print(f"  [PASS] server: {result['syntax_ok']}")
        else:
            for err in result["syntax_errors"]:
                print(f"  [FAIL] server: {err}")
                all_ok = False

        # Compatibility check
        if result["compat_issues"]:
            for issue in result["compat_issues"]:
                tag = "FAIL" if issue["severity"] == "error" else "WARN"
                print(f"  [{tag}] obsidian: {issue['message']}")
                if issue["severity"] == "error":
                    all_ok = False
        else:
            print(f"  [PASS] obsidian: no compatibility issues")

        # Summary line for this block
        print(f"  => {'ALL PASSED' if not result.get('syntax_errors') and not [i for i in result.get('compat_issues', []) if i['severity'] == 'error'] else 'ISSUES FOUND'}")
        print()

    if all_ok:
        print("RESULT: All PlantUML blocks validated successfully")
        sys.exit(0)
    else:
        print("RESULT: Issues found — fix before writing file")
        sys.exit(1)


if __name__ == '__main__':
    main()
