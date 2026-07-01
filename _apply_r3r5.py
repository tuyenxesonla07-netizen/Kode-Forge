#!/usr/bin/env python3
"""Apply Fix A (R3: prints -> logger.info) and Fix B (R5: remove unused imports).

Fix B is driven by its own `python -m pyflakes agents/ tools/` output: it parses
each `imported but unused` / `redefinition of unused` diagnostic and removes ONLY
the specific (file, line, name) reported. This avoids wrongly removing a name
that is imported on multiple lines where only one is unused (e.g. `import yaml`
used in one function but not another).

Run from repo root: python _apply_r3r5.py
"""
import ast
import os
import re
import subprocess

ROOT = os.path.dirname(os.path.abspath(__file__))


# ---------------------------------------------------------------------------
# Fix A — R3: convert 2 executable prints in agents/pipeline_phase1.py
# ---------------------------------------------------------------------------
def fix_a():
    path = os.path.join(ROOT, "agents", "pipeline_phase1.py")
    with open(path, "r", encoding="utf-8") as f:
        content = f.read()
    if 'print(f"[MultiAgent] {summary}")' not in content and \
       'print(f"  {mod}: {code.count(chr(10)) + 1} lines")' not in content:
        print("[Fix A] already applied at HEAD; skipping")
        return
    lines = content.splitlines(keepends=True)
    out = []
    changed = 0
    for line in lines:
        s = line.rstrip("\n")
        if s.strip() == 'print(f"[MultiAgent] {summary}")':
            indent = s[: len(s) - len(s.lstrip())]
            out.append(f'{indent}logger.info("[MultiAgent] %s", summary)\n')
            changed += 1
            continue
        if s.strip() == 'print(f"  {mod}: {code.count(chr(10)) + 1} lines")':
            indent = s[: len(s) - len(s.lstrip())]
            out.append(
                f'{indent}logger.info("  %s: %s lines", mod, code.count("\\n") + 1)\n'
            )
            changed += 1
            continue
        out.append(line)
    assert changed == 2, f"Fix A expected 2 replacements, got {changed}"
    with open(path, "w", encoding="utf-8", newline="") as f:
        f.writelines(out)
    print(f"[Fix A] replaced {changed} print lines in {path}")


# ---------------------------------------------------------------------------
# Fix B — R5: remove unused imports, driven by pyflakes output
# ---------------------------------------------------------------------------
def _read(rel):
    with open(os.path.join(ROOT, rel), "r", encoding="utf-8") as f:
        return f.read()


def _write(rel, content):
    with open(os.path.join(ROOT, rel), "w", encoding="utf-8", newline="") as f:
        f.write(content)


def _run_pyflakes():
    """Run pyflakes and return list of (rel_path, lineno, name, kind) for
    unused-import diagnostics. kind is 'unused' or 'redef'."""
    result = subprocess.run(
        ["python", "-m", "pyflakes", "agents/", "tools/"],
        cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    items = []
    # Match: agents/foo/bar.py:12:1: 'name' imported but unused
    #         agents/foo/bar.py:12:1: redefinition of unused 'Name' from line 6
    pat = re.compile(
        r"^(.+?):(\d+):\d+:\s+(?:redefinition of unused|imported but unused) '([^']+)'"
    )
    for line in result.stdout.splitlines():
        m = pat.match(line.strip())
        if m:
            rel = os.path.normpath(m.group(1)).replace(os.sep, "/")
            lineno = int(m.group(2))
            name = m.group(3)
            kind = "redef" if "redefinition" in line else "unused"
            items.append((rel, lineno, name, kind))
    return items


def _is_module_level_try_import(lines, stmt_line):
    """Return True if the import at stmt_line is the sole statement in a
    `try:` block body (so removing just the import would empty the block)."""
    stmt_indent = re.match(r"^(\s*)", lines[stmt_line - 1]).group(1)
    # Find header above.
    header_line = None
    base_indent = None
    for cand in range(stmt_line - 1, 0, -1):
        txt = lines[cand - 1].rstrip()
        if txt == "":
            continue
        ind = re.match(r"^(\s*)", txt).group(1)
        if len(ind) >= len(stmt_indent):
            break
        if re.match(r"^(\s*)(if\s+TYPE_CHECKING\s*:|try\s*:|with\s+.*?:)\s*$", txt):
            header_line = cand
            base_indent = ind
        break
    if header_line is None:
        return False
    # Body = contiguous lines more indented than header.
    body_el = header_line
    j = header_line + 1
    while j <= len(lines):
        t = lines[j - 1]
        if t.strip() == "":
            j += 1
            continue
        if len(re.match(r"^(\s*)", t).group(1)) > len(base_indent):
            body_el = j
            j += 1
        else:
            break
    body_non_blank = [
        ln for ln in range(header_line + 1, body_el + 1) if lines[ln - 1].strip() != ""
    ]
    return body_non_blank == [stmt_line]


def _remove_import_at(rel, stmt_line, name):
    """Remove the single import name `name` from the import statement at
    stmt_line in file rel. Handles `import X.Y`, `from X import A, B`, and
    parenthesized multi-line forms. Removes the whole statement if it becomes
    empty, collapsing blank lines."""
    src = _read(rel)
    lines = src.splitlines(keepends=True)

    # Determine the full span of the import statement.
    def stmt_end(start):
        depth = 0
        i = start
        comb = ""
        while i <= len(lines):
            txt = lines[i - 1]
            comb += txt.rstrip("\n").rstrip("\r")
            depth += txt.count("(") - txt.count(")")
            if not txt.rstrip().endswith("\\") and depth <= 0:
                return i
            i += 1
        return len(lines)

    el = stmt_end(stmt_line)
    # Use ast to confirm this statement imports `name` and to get kept names.
    # Parse just the statement region.
    stmt_src = "".join(lines[ln - 1] for ln in range(stmt_line, el + 1))
    try:
        tree = ast.parse(stmt_src)
    except SyntaxError:
        tree = None

    kept_parts = []
    stmt_node = None
    if tree and tree.body:
        stmt_node = tree.body[0]
        if isinstance(stmt_node, ast.ImportFrom):
            for alias in stmt_node.names:
                bound = alias.asname if alias.asname else alias.name
                if bound == name:
                    continue
                kept_parts.append(
                    f"{alias.name} as {alias.asname}" if alias.asname else alias.name
                )
        elif isinstance(stmt_node, ast.Import):
            for alias in stmt_node.names:
                bound = alias.asname if alias.asname else alias.name.split(".")[0]
                if bound == name:
                    continue
                kept_parts.append(
                    f"{alias.name} as {alias.asname}" if alias.asname else alias.name
                )

    if kept_parts:
        # Reconstruct statement with kept names.
        base_indent = re.match(r"^(\s*)", lines[stmt_line - 1]).group(1)
        if isinstance(stmt_node, ast.ImportFrom):
            new_stmt = f"from {stmt_node.module} import {', '.join(kept_parts)}"
        else:
            new_stmt = f"import {', '.join(kept_parts)}"
        m = re.match(r"^(\s*)", lines[stmt_line - 1])
        indent = m.group(1)
        # Preserve trailing comment on last line.
        last = lines[el - 1].rstrip("\n").rstrip("\r")
        comment = ""
        for idx, ch in enumerate(last):
            if ch == "#":
                comment = "  " + last[idx:]
                break
        new_line = indent + new_stmt + (comment if comment else "") + "\n"
        lines[stmt_line - 1] = new_line
        for ln in range(stmt_line + 1, el + 1):
            lines[ln - 1] = ""
    else:
        # Whole statement removed. If it's the sole statement in an enclosing
        # try/if/with block, remove the entire block (incl trailers).
        if _is_module_level_try_import(lines, stmt_line):
            base_indent = re.match(r"^(\s*)", lines[stmt_line - 1]).group(1)
            # find header
            header_line = None
            h_indent = None
            for cand in range(stmt_line - 1, 0, -1):
                txt = lines[cand - 1].rstrip()
                if txt == "":
                    continue
                ind = re.match(r"^(\s*)", txt).group(1)
                if len(ind) >= len(base_indent):
                    break
                if re.match(r"^(\s*)(if\s+TYPE_CHECKING\s*:|try\s*:|with\s+.*?:)\s*$", txt):
                    header_line = cand
                    h_indent = ind
                break
            # body extent
            body_el = header_line
            j = header_line + 1
            while j <= len(lines):
                t = lines[j - 1]
                if t.strip() == "":
                    j += 1
                    continue
                if len(re.match(r"^(\s*)", t).group(1)) > len(h_indent):
                    body_el = j
                    j += 1
                else:
                    break
            # absorb trailer clauses (except/else/finally + their bodies)
            trailer_re = re.compile(r"^(\s*)(except\s.*:|else\s*:|finally\s*:)\s*$")
            k = body_el + 1
            while k <= len(lines):
                txt = lines[k - 1].rstrip()
                if txt == "":
                    k += 1
                    continue
                tm = trailer_re.match(txt)
                if tm and len(tm.group(1)) == len(h_indent):
                    body_el = k
                    k += 1
                    while k <= len(lines):
                        body = lines[k - 1]
                        if body.strip() == "":
                            k += 1
                            continue
                        if len(re.match(r"^(\s*)", body).group(1)) > len(h_indent):
                            body_el = k
                            k += 1
                        else:
                            break
                else:
                    break
            for ln in range(header_line, body_el + 1):
                lines[ln - 1] = ""
        else:
            for ln in range(stmt_line, el + 1):
                lines[ln - 1] = ""

    new_src = "".join(lines)
    new_src = re.sub(r"\n[ \t]*\n[ \t]*\n", "\n\n", new_src)
    ast.parse(new_src)
    _write(rel, new_src)


def fix_b():
    items = _run_pyflakes()
    print(f"[Fix B] pyflakes reports {len(items)} unused-import diagnostics")
    # For redef, the original import line is the one to remove (the redef line
    # is flagged; the earlier line is the original unused — but removing the
    # redef line is enough to clear the diagnostic, and if the original is also
    # flagged as unused we'll hit it separately). Process bottom-to-top per file.
    by_file = {}
    for rel, lineno, name, kind in items:
        by_file.setdefault(rel, []).append((lineno, name))

    for rel, entries in by_file.items():
        # Sort by line descending so removals don't shift later line numbers.
        # Deduplicate identical (line, name).
        seen = set()
        unique = []
        for ln, nm in sorted(entries, key=lambda x: -x[0]):
            key = (ln, nm)
            if key in seen:
                continue
            seen.add(key)
            unique.append((ln, nm))
        for stmt_line, name in unique:
            _remove_import_at(rel, stmt_line, name)
        print(f"[Fix B] processed {len(unique)} removal(s) in {rel}")


if __name__ == "__main__":
    fix_a()
    fix_b()
    print("Done.")
