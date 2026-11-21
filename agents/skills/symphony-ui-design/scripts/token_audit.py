#!/usr/bin/env python3
"""Audit a Symphony UI codebase against the SDS tokens.

    python3 token_audit.py <path> [<path> ...]          # warn-only report, exit 0
    python3 token_audit.py src/web --strict             # exit 1 on any finding
    python3 token_audit.py src/web --json               # machine-readable

Checks
  vendored   symphony-tokens.css is present and at the skill's current version
  raw-color  hex / rgb() / hsl() literals outside the vendored token files
             (each one is mapped to the matching SDS primitive when there is one)
  legacy     v1 variable names (--bg-midnight, --accent-cyan, ...) -> SDS replacement
  undefined  var(--x) that neither SDS nor the scanned code defines
  dialog     window.alert/confirm/prompt (blocked in sandboxed extension iframes)

Skips node_modules, build output, coverage, minified bundles and the vendored
token files themselves. Standard library only, so it runs from verify.sh anywhere.
"""

import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parent.parent
REGISTRY = SKILL_DIR / "references" / "tokens.json"

EXTS = {".css", ".scss", ".less", ".html", ".htm", ".js", ".jsx", ".mjs", ".ts", ".tsx", ".vue", ".svelte",
        ".j2", ".jinja", ".jinja2", ".hbs"}
SKIP_DIRS = {"node_modules", "dist", "build", "coverage", "htmlcov", ".git", ".next", "target", "__pycache__",
             ".venv", "venv"}
VENDORED = {"symphony-tokens.css", "symphony-tokens-legacy.css", "tailwind-preset.cjs"}
MINIFIED_LINE = 1500  # bundles (e.g. compiled ADK) have huge lines; skip them
# Custom properties that libraries set at runtime, so they are never defined in source.
RUNTIME_VAR_PREFIXES = ("--radix-", "--tw-", "--sonner-", "--vaul-")

HEX = re.compile(r"(?<![&\w])#(?:[0-9a-fA-F]{8}|[0-9a-fA-F]{6}|[0-9a-fA-F]{3,4})(?![0-9a-fA-F\w-])")
FUNC = re.compile(r"\b(?:rgba?|hsla?)\(\s*[\d.]+%?\s*[, ]\s*[\d.]+%?\s*[, ]\s*[\d.]+%?", re.I)
VAR_USE = re.compile(r"var\(\s*(--[\w-]+)")
VAR_DEF = re.compile(r"(?<![\w-])(--[\w-]+)\s*:")
DIALOG = re.compile(r"\b(?:window\.)?(?<![.\w])(alert|confirm|prompt)\s*\(")
# '#' + digits in JS/HTML that are not colors (ids, anchors, entities) are hard to tell apart;
# only count a hex as a color when it looks like one in context.
COLOR_CTX = re.compile(r"(color|background|border|fill|stroke|shadow|outline|gradient|:\s*$|['\"]\s*$)", re.I)


def norm_hex(h: str) -> str:
    h = h.lstrip("#").upper()
    if len(h) in (3, 4):
        h = "".join(c * 2 for c in h[:3])
    return "#" + h[:6]


def load_registry():
    reg = json.loads(REGISTRY.read_text(encoding="utf-8"))
    by_hex = defaultdict(list)
    for name, val in reg["primitives"].items():
        if val.startswith("#"):
            by_hex[val.upper()].append(name)
    semantic_by_hex = defaultdict(set)
    for role, spec in reg["semantic"].items():
        for theme in ("light", "dark"):
            semantic_by_hex[spec[theme]["hex"].upper()].add(f"--{role} ({theme})")
    defined = {"--" + n for n in reg["primitives"]} | {"--" + r for r in reg["semantic"]} | \
        {"--" + n for n in reg["shadows"]} | {"--font-sans", "--font-mono", "--radius"} | \
        {f"--{k}" for k in reg["spacing"]["spacious"]} | set("--" + k for k in reg["radius"]) | \
        set("--" + k for k in reg["control_height"]) | \
        {f"--text-{n}-{p}" for n in reg["typography"]["scale"] for p in ("size", "line", "weight")}
    return reg, by_hex, semantic_by_hex, defined


def nearest(hex_, by_hex):
    def rgb(h):
        return tuple(int(h[i:i + 2], 16) for i in (1, 3, 5))
    t = rgb(hex_)
    best = min(by_hex, key=lambda h: sum((a - b) ** 2 for a, b in zip(rgb(h), t)))
    dist = sum((a - b) ** 2 for a, b in zip(rgb(best), t)) ** 0.5
    return best, dist


def files_under(paths):
    for root in paths:
        root = Path(root)
        if root.is_file():
            yield root
            continue
        for p in root.rglob("*"):
            if p.is_file() and p.suffix.lower() in EXTS and not (set(p.parts) & SKIP_DIRS):
                yield p


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("paths", nargs="+")
    ap.add_argument("--strict", action="store_true", help="exit 1 when anything is found")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--top", type=int, default=12, help="rows per section in the text report")
    args = ap.parse_args()

    reg, by_hex, semantic_by_hex, sds_defined = load_registry()
    legacy = reg["legacy_aliases"]
    current = reg["version"]

    findings = defaultdict(list)
    app_defined, var_uses = set(), []
    vendored_versions = {}
    scanned = skipped = 0

    for f in files_under(args.paths):
        try:
            text = f.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if f.name in VENDORED:
            m = re.search(r"Symphony SDS tokens v([\d.]+)", text)
            vendored_versions[str(f)] = m.group(1) if m else "unknown"
            continue
        lines = text.splitlines()
        if lines and max(len(l) for l in lines) > MINIFIED_LINE:
            skipped += 1
            continue
        scanned += 1
        for i, line in enumerate(lines, 1):
            loc = f"{f}:{i}"
            for m in HEX.finditer(line):
                before = line[:m.start()]
                if f.suffix not in (".css", ".scss", ".less") and not COLOR_CTX.search(before[-40:]):
                    continue
                findings["raw-color"].append((loc, norm_hex(m.group())))
            for m in FUNC.finditer(line):
                findings["raw-color"].append((loc, m.group().split("(")[0].lower() + "(...)"))
            app_defined.update(VAR_DEF.findall(line))
            for v in VAR_USE.findall(line):
                var_uses.append((loc, v))
            if f.suffix in (".js", ".jsx", ".mjs", ".ts", ".tsx", ".html", ".htm", ".vue", ".svelte"):
                for m in DIALOG.finditer(line):
                    if "." in line[max(0, m.start() - 1):m.start()]:
                        continue
                    findings["dialog"].append((loc, m.group(1)))

    for loc, v in var_uses:
        if v in legacy:
            findings["legacy"].append((loc, f"{v} -> {legacy[v]}"))
        elif v not in sds_defined and v not in app_defined and not v.startswith(RUNTIME_VAR_PREFIXES):
            findings["undefined"].append((loc, v))

    if not vendored_versions:
        findings["vendored"].append(("-", "symphony-tokens.css not found: copy it from the skill's assets/"))
    for path, ver in vendored_versions.items():
        if Path(path).name == "symphony-tokens.css" and ver != current:
            findings["vendored"].append((path, f"v{ver} is behind the skill's v{current}: re-copy assets/"))

    if args.json:
        print(json.dumps({"tokens_version": current, "scanned_files": scanned, "skipped_minified": skipped,
                          "vendored": vendored_versions,
                          "findings": {k: [{"loc": l, "detail": d} for l, d in v] for k, v in findings.items()}},
                         indent=2))
    else:
        report(findings, by_hex, semantic_by_hex, scanned, skipped, vendored_versions, current, args.top)

    total = sum(len(v) for v in findings.values())
    sys.exit(1 if args.strict and total else 0)


def report(findings, by_hex, semantic_by_hex, scanned, skipped, vendored, current, top):
    print(f"SDS token audit (tokens v{current}): {scanned} files scanned, {skipped} minified bundles skipped")
    for path, ver in vendored.items():
        print(f"  vendored: {path} (v{ver})")

    v = findings.get("vendored", [])
    if v:
        print(f"\nWARN vendored token file ({len(v)})")
        for loc, d in v:
            print(f"  {loc}: {d}")

    raw = findings.get("raw-color", [])
    if raw:
        by_file = Counter(l.rsplit(":", 1)[0] for l, _ in raw)
        by_val = Counter(d for _, d in raw)
        print(f"\nWARN raw color literals: {len(raw)} in {len(by_file)} files")
        for path, n in by_file.most_common(top):
            print(f"  {n:5d}  {path}")
        print("  most used values -> SDS replacement:")
        for val, n in by_val.most_common(top):
            if val.startswith("#"):
                exact = semantic_by_hex.get(val)
                if exact:
                    hint = "use " + ", ".join(sorted(exact)[:2])
                elif val in by_hex:
                    hint = "= " + ", ".join("--" + p for p in by_hex[val])
                else:
                    best, dist = nearest(val, by_hex)
                    hint = f"not in SDS; nearest --{by_hex[best][0]} {best} (distance {dist:.0f})"
            else:
                hint = "replace with a token (use the -subtle tokens for tints)"
            print(f"  {n:5d}  {val:<9} {hint}")

    for key, title in (("legacy", "legacy v1 variables"), ("undefined", "undefined custom properties"),
                       ("dialog", "native dialogs (blocked in extension iframes)")):
        items = findings.get(key, [])
        if not items:
            continue
        print(f"\nWARN {title}: {len(items)}")
        for d, n in Counter(d for _, d in items).most_common(top):
            first = next(l for l, x in items if x == d)
            print(f"  {n:5d}  {d:<40} e.g. {first}")

    total = sum(len(v) for v in findings.values())
    print(f"\n{'No findings.' if not total else f'{total} findings (warn-only; pass --strict to fail).'}")


if __name__ == "__main__":
    main()
