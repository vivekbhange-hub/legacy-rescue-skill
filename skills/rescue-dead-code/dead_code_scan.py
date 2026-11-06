#!/usr/bin/env python3
"""Find candidates for dead code without understanding any one language.

Three cheap, language-agnostic signals, each with a confidence level:

  * commented-out code  - runs of line comments that look like code, not prose
  * constant conditions - `if (false)`, `if 0:`, `if True:` and friends
  * orphan files        - source files whose name is never mentioned by any
                          other file (no import, require, include or path)

These are leads, not verdicts. Reflection, dependency injection, routing by
convention, templates and build config all reference code in ways a text scan
cannot see. The script only reads files; it never deletes anything.

Examples:
  python3 dead_code_scan.py .
  python3 dead_code_scan.py src --min-block 4 --format json --output rescue/dead-code.json
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Optional, Set

SKIP_DIRS = {
    ".git", ".hg", ".svn", "node_modules", "vendor", "dist", "build", "out", "target",
    ".venv", "venv", "__pycache__", ".tox", ".idea", ".vscode", ".gradle", ".next",
    "coverage", "bower_components", "Pods", "obj", "rescue", "migrations",
}

SOURCE_EXT = {
    ".py", ".js", ".jsx", ".mjs", ".cjs", ".ts", ".tsx", ".java", ".kt", ".scala", ".go",
    ".rs", ".rb", ".php", ".cs", ".vb", ".c", ".h", ".cpp", ".cc", ".hpp", ".m", ".swift",
    ".dart", ".ex", ".exs", ".lua", ".pl", ".pm", ".sh", ".bash", ".sql", ".groovy",
    ".vue", ".svelte", ".clj", ".erl", ".hs", ".r", ".ps1",
}
# Files that also count as "referrers" (they can mention a source file) but are not candidates.
REFERRER_EXT = SOURCE_EXT | {
    ".json", ".yml", ".yaml", ".toml", ".xml", ".html", ".htm", ".erb", ".ejs", ".hbs",
    ".twig", ".jsp", ".aspx", ".cshtml", ".gradle", ".cfg", ".ini", ".conf", ".properties",
    ".md", ".txt", ".csproj", ".sln", ".mk", ".cmake", ".config", ".env",
}
REFERRER_NAMES = {"Makefile", "Dockerfile", "Procfile", "Rakefile", "Gemfile", "Jenkinsfile",
                  "CMakeLists.txt", "BUILD", "WORKSPACE"}

COMMENT_PREFIX = {
    "#": {".py", ".rb", ".sh", ".bash", ".pl", ".pm", ".r", ".ex", ".exs", ".ps1", ".yml",
          ".yaml", ".toml", ".coffee"},
    "--": {".sql", ".lua", ".hs"},
    "'": {".vb"},
    ";": {".clj", ".el", ".lisp"},
    "%": {".erl"},
}
DEFAULT_PREFIX = "//"

# Names that are usually loaded by convention, not by an explicit reference.
CONVENTIONAL_STEMS = {
    "index", "main", "__init__", "__main__", "app", "server", "manage", "setup", "conftest",
    "wsgi", "asgi", "settings", "config", "program", "startup", "application", "mod", "lib",
    "build", "gulpfile", "gruntfile", "webpack.config", "vite.config", "jest.config",
    "babel.config", "rollup.config", "tsconfig", "next.config", "nuxt.config", "routes",
    "urls", "admin", "models", "views", "apps", "tasks", "celery", "middleware",
}
TEST_NAME = re.compile(
    r"(^|/)(tests?|spec|specs|__tests__|e2e)/|(^|/)test_[^/]+$|_test\.[a-z]+$|"
    r"\.(test|spec)\.[a-z]+$|Tests?\.(java|cs|kt|swift)$", re.IGNORECASE)

CODE_SIGNS = [
    re.compile(r"[;{}]\s*$"),
    re.compile(r"^\s*[\w.\[\]\"']+\s*(=|\+=|-=|:=|==)\s*\S"),
    re.compile(r"^\s*(return|if|else|elif|for|while|import|from|def|class|function|var|let|"
               r"const|public|private|protected|static|try|catch|except|switch|case|new|"
               r"print|echo|require|include|using|package|end|fi|done|then|await|async|"
               r"yield|throw|raise|self\.|this\.)\b"),
    re.compile(r"^\s*[\w.$]+\(.*\)\s*;?\s*$"),
    re.compile(r"^\s*[)\]}]+[;,]?\s*$"),
]
PROSE_SIGNS = re.compile(
    r"^\s*(TODO|FIXME|NOTE|HACK|XXX|@\w+|copyright|license|licensed|see |https?://|-{3,}|={3,}|\*)",
    re.IGNORECASE)

CONSTANT_CONDITION = re.compile(
    r"^\s*(?:}\s*else\s+)?(if|elif|elsif|while)\s*\(?\s*(!\s*|not\s+)?"
    r"(true|false|True|False|TRUE|FALSE|0|1|None|null|nil|undefined)\s*\)?\s*(?:[:{]|then\b|$)")
CONSTANT_IF_ZERO = re.compile(r"^\s*#\s*if\s+0\b")
TRUTHY = {"true", "True", "TRUE", "1"}

TEXT_LIMIT = 1_000_000


def _read(path: Path) -> Optional[str]:
    try:
        if path.stat().st_size > TEXT_LIMIT:
            return None
        data = path.read_bytes()
    except OSError:
        return None
    if b"\x00" in data[:8192]:
        return None
    return data.decode("utf-8", errors="replace")


def comment_prefix(suffix: str) -> str:
    for prefix, exts in COMMENT_PREFIX.items():
        if suffix in exts:
            return prefix
    return DEFAULT_PREFIX


def looks_like_code(body: str) -> bool:
    body = body.strip()
    if not body or PROSE_SIGNS.match(body):
        return False
    return any(sign.search(body) for sign in CODE_SIGNS)


def find_commented_blocks(text: str, suffix: str, min_block: int = 3,
                          min_code_ratio: float = 0.6) -> List[dict]:
    prefix = comment_prefix(suffix)
    blocks: List[dict] = []
    run: List[tuple] = []  # (line_no, body)

    def flush():
        if len(run) >= min_block:
            code = sum(1 for _n, body in run if looks_like_code(body))
            ratio = code / len(run)
            if ratio >= min_code_ratio:
                blocks.append({
                    "start": run[0][0],
                    "end": run[-1][0],
                    "lines": len(run),
                    "code_ratio": round(ratio, 2),
                    "confidence": "high" if ratio >= 0.85 and len(run) >= 5 else "medium",
                    "preview": run[0][1].strip()[:80],
                })
        run.clear()

    for number, line in enumerate(text.splitlines(), 1):
        stripped = line.lstrip()
        if stripped.startswith(prefix) and not stripped.startswith("#!") \
                and not stripped.startswith("///") and not stripped.startswith("#region") \
                and not stripped.startswith("# -*-"):
            run.append((number, stripped[len(prefix):]))
        else:
            flush()
    flush()
    return blocks


def find_constant_conditions(text: str) -> List[dict]:
    hits = []
    for number, line in enumerate(text.splitlines(), 1):
        m = CONSTANT_CONDITION.match(line)
        if m:
            keyword, negated, value = m.groups()
            truthy = (value in TRUTHY) != bool(negated)
            if keyword == "while" and truthy:
                continue  # `while (true)` is an intentional loop, not dead code
            hits.append({"line": number, "code": line.strip()[:100],
                         "always": "true" if truthy else "false"})
        elif CONSTANT_IF_ZERO.match(line):
            hits.append({"line": number, "code": line.strip()[:100], "always": "false"})
    return hits


def iter_files(root: Path, extra_skip: Set[str]):
    skip = SKIP_DIRS | extra_skip
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if d not in skip and not d.endswith(".egg-info"))
        for name in sorted(filenames):
            yield Path(dirpath) / name


TOKEN = re.compile(r"[A-Za-z_$][\w$\-]*")


def scan(root: Path, min_block: int = 3, extra_skip: Optional[Set[str]] = None) -> dict:
    root = root.resolve()
    extra_skip = extra_skip or set()
    commented: List[dict] = []
    constants: List[dict] = []
    sources: List[str] = []
    token_files: Dict[str, Set[str]] = defaultdict(set)

    for path in iter_files(root, extra_skip):
        suffix = path.suffix.lower()
        is_source = suffix in SOURCE_EXT
        if not (is_source or suffix in REFERRER_EXT or path.name in REFERRER_NAMES):
            continue
        text = _read(path)
        if text is None:
            continue
        rel = path.relative_to(root).as_posix()
        for token in set(TOKEN.findall(text)):
            token_files[token].add(rel)
            # `user-service` also matches a reference written `user_service` and vice versa
            if "-" in token:
                for part in token.split("-"):
                    token_files[part].add(rel)
        if not is_source:
            continue
        sources.append(rel)
        for block in find_commented_blocks(text, suffix, min_block):
            commented.append(dict(block, path=rel))
        for hit in find_constant_conditions(text):
            constants.append(dict(hit, path=rel))

    orphans: List[dict] = []
    for rel in sources:
        name = rel.rsplit("/", 1)[-1]
        stem = name.split(".", 1)[0]
        if stem.lower() in CONVENTIONAL_STEMS or name.split(".")[0].lower() in CONVENTIONAL_STEMS:
            continue
        if TEST_NAME.search(rel):
            continue
        candidates = {stem}
        if "-" in stem:
            candidates.add(stem.replace("-", "_"))
        if "_" in stem:
            candidates.add(stem.replace("_", "-"))
        referrers: Set[str] = set()
        for c in candidates:
            referrers |= token_files.get(c, set())
        referrers.discard(rel)
        if not referrers:
            depth = rel.count("/")
            orphans.append({
                "path": rel,
                "confidence": "medium" if depth >= 1 else "low",
                "reason": f"no other file mentions '{stem}'",
            })

    commented.sort(key=lambda b: (-b["lines"], b["path"], b["start"]))
    constants.sort(key=lambda h: (h["path"], h["line"]))
    orphans.sort(key=lambda o: o["path"])
    return {
        "root": root.name,
        "source_files": len(sources),
        "commented_out": commented,
        "constant_conditions": constants,
        "orphan_files": orphans,
    }


def to_markdown(report: dict, limit: int = 50) -> str:
    out = [
        f"# Dead-code candidates: {report['root']}",
        "",
        f"Source files scanned: {report['source_files']}. Every row is a lead to verify, "
        "not a verdict. Nothing has been deleted.",
        "",
        f"## Commented-out code ({len(report['commented_out'])} blocks)",
        "",
    ]
    if report["commented_out"]:
        out += ["| File | Lines | Size | Code-like | Confidence | First line |",
                "|---|---|---|---|---|---|"]
        for b in report["commented_out"][:limit]:
            preview = b["preview"].replace("|", "\\|").replace("`", "'")
            out.append(f"| `{b['path']}` | {b['start']}-{b['end']} | {b['lines']} | "
                       f"{int(b['code_ratio'] * 100)}% | {b['confidence']} | `{preview}` |")
    else:
        out.append("None found.")
    out += ["", f"## Constant conditions ({len(report['constant_conditions'])})", ""]
    if report["constant_conditions"]:
        out += ["| File | Line | Always | Code |", "|---|---|---|---|"]
        for h in report["constant_conditions"][:limit]:
            code = h["code"].replace("|", "\\|").replace("`", "'")
            out.append(f"| `{h['path']}` | {h['line']} | {h['always']} | `{code}` |")
    else:
        out.append("None found.")
    out += ["", f"## Orphan files ({len(report['orphan_files'])})", "",
            "No other file mentions these by name. Check for dynamic loading, routing by "
            "convention, reflection and build config before believing it.", ""]
    if report["orphan_files"]:
        out += ["| File | Confidence | Reason |", "|---|---|---|"]
        for o in report["orphan_files"][:limit]:
            out.append(f"| `{o['path']}` | {o['confidence']} | {o['reason']} |")
    else:
        out.append("None found.")
    return "\n".join(out) + "\n"


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="List dead-code candidates (read-only, never deletes).")
    p.add_argument("root", nargs="?", default=".", type=Path, help="directory to scan (default .)")
    p.add_argument("--min-block", type=int, default=3,
                   help="minimum consecutive comment lines for a block (default 3)")
    p.add_argument("--skip", action="append", default=[], help="extra directory name to skip")
    p.add_argument("--limit", type=int, default=50, help="max rows per markdown table")
    p.add_argument("--format", choices=["md", "json"], default="md")
    p.add_argument("--output", type=Path, help="write here instead of stdout")
    return p


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    if not args.root.is_dir():
        print(f"error: {args.root} is not a directory", file=sys.stderr)
        return 2
    report = scan(args.root, args.min_block, set(args.skip))
    rendered = (json.dumps(report, indent=2) + "\n") if args.format == "json" \
        else to_markdown(report, args.limit)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_bytes((rendered).encode("utf-8"))
        print(f"wrote {args.output}", file=sys.stderr)
    else:
        sys.stdout.write(rendered)
    return 0


if __name__ == "__main__":
    sys.exit(main())
