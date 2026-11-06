#!/usr/bin/env python3
"""Rank the riskiest files in a repository: git churn x code complexity.

Reads `git log --numstat` output (from a file, stdin, or by running git), counts
how often each file changed and who changed it, estimates complexity from the
current file on disk (language-agnostic: lines, indentation depth, branch
keywords), and reports:

  * hotspots        - files that change often AND are complex
  * change coupling - pairs of files that keep changing in the same commits
  * knowledge risk  - busy files that only one person has touched

Standard library only, no network, deterministic output.

Examples:
  python3 hotspots.py --repo . --since "18 months ago" --output rescue/hotspots.md
  git log --numstat --no-merges > log.txt && python3 hotspots.py --log log.txt --root .
  python3 hotspots.py --repo . --format json --top 50
"""

from __future__ import annotations

import argparse
import fnmatch
import json
import re
import subprocess
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from itertools import combinations
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

COMMIT_MARKER = "--rescue-commit--"
GIT_FORMAT = COMMIT_MARKER + "%x09%H%x09%ad%x09%aN"

DEFAULT_EXCLUDES = [
    "*.lock", "package-lock.json", "yarn.lock", "pnpm-lock.yaml", "poetry.lock",
    "Cargo.lock", "Gemfile.lock", "composer.lock", "go.sum",
    "*.min.js", "*.min.css", "*.map", "*.svg", "*.png", "*.jpg", "*.jpeg", "*.gif",
    "*.ico", "*.pdf", "*.snap",
    "node_modules/*", "vendor/*", "dist/*", "build/*", "*/node_modules/*", "*/vendor/*",
    "*/dist/*", "*/build/*",
]

BRANCH_PATTERN = re.compile(
    r"\b(if|elif|elsif|else|for|foreach|while|do|case|when|catch|except|rescue|"
    r"unless|until|switch|select|guard)\b|&&|\|\||\?\?|\?(?=[^:\n]*:)"
)

NUMSTAT_LINE = re.compile(r"^(\d+|-)\t(\d+|-)\t(.+)$")
BRACE_RENAME = re.compile(r"^(.*)\{(.*) => (.*)\}(.*)$")


@dataclass
class Commit:
    sha: str = ""
    date: str = ""
    author: str = ""
    files: List[Tuple[str, int, int]] = field(default_factory=list)


@dataclass
class FileStats:
    path: str
    commits: int = 0
    added: int = 0
    deleted: int = 0
    authors: Counter = field(default_factory=Counter)
    last_changed: str = ""


@dataclass
class Complexity:
    loc: int
    mean_depth: float
    max_depth: int
    branches: int

    @property
    def score(self) -> float:
        # Lines weighted by how deeply nested they are, plus every decision point.
        return round(self.loc * (1.0 + self.mean_depth) / 10.0 + self.branches, 1)


# --------------------------------------------------------------------------- parsing

def normalize_path(raw: str) -> str:
    """Resolve git's rename notation to the new path.

    `src/{old => new}/a.py` -> `src/new/a.py`;  `old.py => new.py` -> `new.py`.
    """
    raw = raw.strip()
    if raw.startswith('"') and raw.endswith('"'):
        raw = raw[1:-1]
    match = BRACE_RENAME.match(raw)
    if match:
        prefix, _old, new, suffix = match.groups()
        path = prefix + new + suffix
        return re.sub(r"/{2,}", "/", path).lstrip("/")
    if " => " in raw:
        return raw.split(" => ", 1)[1].strip()
    return raw


def parse_log(text: str) -> List[Commit]:
    """Parse `git log --numstat` output.

    Understands both this script's own format (lines starting with the commit
    marker) and git's default format (`commit <sha>` / `Author:` / `Date:`).
    Binary files (`-\t-`) are skipped.
    """
    commits: List[Commit] = []
    current: Optional[Commit] = None
    for line in text.splitlines():
        line = line.rstrip("\r")
        if line.startswith(COMMIT_MARKER):
            parts = line.split("\t")
            current = Commit(
                sha=parts[1] if len(parts) > 1 else "",
                date=parts[2] if len(parts) > 2 else "",
                author=parts[3] if len(parts) > 3 else "",
            )
            commits.append(current)
            continue
        if re.match(r"^commit [0-9a-f]{7,40}\b", line):
            current = Commit(sha=line.split()[1])
            commits.append(current)
            continue
        if current is not None and line.startswith("Author:"):
            current.author = re.sub(r"\s*<[^>]*>\s*$", "", line[len("Author:"):]).strip()
            continue
        if current is not None and line.startswith("Date:"):
            current.date = line[len("Date:"):].strip()
            continue
        match = NUMSTAT_LINE.match(line)
        if match:
            if current is None:
                current = Commit()
                commits.append(current)
            added, deleted, path = match.groups()
            if added == "-" or deleted == "-":
                continue  # binary file
            current.files.append((normalize_path(path), int(added), int(deleted)))
    return commits


def is_excluded(path: str, patterns: Sequence[str]) -> bool:
    name = path.rsplit("/", 1)[-1]
    for pattern in patterns:
        if fnmatch.fnmatchcase(path, pattern) or fnmatch.fnmatchcase(name, pattern):
            return True
    return False


def aggregate(commits: Iterable[Commit], excludes: Sequence[str]) -> Dict[str, FileStats]:
    stats: Dict[str, FileStats] = {}
    for commit in commits:
        seen = set()
        for path, added, deleted in commit.files:
            if is_excluded(path, excludes):
                continue
            entry = stats.setdefault(path, FileStats(path=path))
            entry.added += added
            entry.deleted += deleted
            if path not in seen:
                entry.commits += 1
                if commit.author:
                    entry.authors[commit.author] += 1
                if commit.date and (not entry.last_changed or commit.date > entry.last_changed):
                    entry.last_changed = commit.date
                seen.add(path)
    return stats


def _dirname(path: str) -> str:
    return path.rsplit("/", 1)[0] if "/" in path else ""


def coupling(
    commits: Iterable[Commit],
    stats: Dict[str, FileStats],
    excludes: Sequence[str],
    max_files: int = 30,
    min_shared: int = 3,
    min_degree: float = 0.5,
) -> List[dict]:
    """Pairs of files that change together.

    degree = shared commits / commits of the less-frequently changed file.
    Commits touching more than `max_files` files (mass renames, formatting
    sweeps) are ignored because they couple everything to everything.
    """
    shared: Counter = Counter()
    for commit in commits:
        files = sorted({p for p, _a, _d in commit.files if not is_excluded(p, excludes)})
        if len(files) < 2 or len(files) > max_files:
            continue
        for pair in combinations(files, 2):
            shared[pair] += 1
    rows = []
    for (a, b), count in shared.items():
        if count < min_shared:
            continue
        base = min(stats[a].commits, stats[b].commits)
        degree = count / base if base else 0.0
        if degree < min_degree:
            continue
        rows.append({"a": a, "b": b, "shared": count, "degree": round(degree, 2),
                     "same_dir": _dirname(a) == _dirname(b)})
    rows.sort(key=lambda r: (-r["shared"], -r["degree"], r["a"], r["b"]))
    return rows


# --------------------------------------------------------------------------- complexity

def measure_text(text: str) -> Complexity:
    """Language-agnostic complexity estimate from source text."""
    lines = [l.expandtabs(4) for l in text.splitlines() if l.strip()]
    if not lines:
        return Complexity(loc=0, mean_depth=0.0, max_depth=0, branches=0)
    indents = [len(l) - len(l.lstrip(" ")) for l in lines]
    nonzero = [i for i in indents if i > 0]
    unit = min(nonzero) if nonzero else 4
    unit = max(2, min(unit, 8))
    depths = [i // unit for i in indents]
    branches = sum(len(BRANCH_PATTERN.findall(l)) for l in lines)
    return Complexity(
        loc=len(lines),
        mean_depth=round(sum(depths) / len(depths), 2),
        max_depth=max(depths),
        branches=branches,
    )


def measure_file(path: Path, max_bytes: int = 2_000_000) -> Optional[Complexity]:
    try:
        if not path.is_file() or path.stat().st_size > max_bytes:
            return None
        data = path.read_bytes()
    except OSError:
        return None
    if b"\x00" in data[:8192]:
        return None  # binary
    return measure_text(data.decode("utf-8", errors="replace"))


# --------------------------------------------------------------------------- analysis

def analyze(
    commits: List[Commit],
    root: Optional[Path],
    excludes: Sequence[str],
    top: int = 25,
    max_files: int = 30,
    min_shared: int = 3,
    min_degree: float = 0.5,
) -> dict:
    stats = aggregate(commits, excludes)
    rows = []
    missing = 0
    for path, entry in stats.items():
        cx = measure_file(root / path) if root is not None else None
        if root is not None and cx is None:
            missing += 1
            continue  # deleted, moved, or binary: not a hotspot any more
        complexity = cx.score if cx else float(entry.added + entry.deleted)
        top_author, top_count = (entry.authors.most_common(1)[0] if entry.authors else ("", 0))
        rows.append({
            "path": path,
            "commits": entry.commits,
            "added": entry.added,
            "deleted": entry.deleted,
            "authors": len(entry.authors),
            "top_author": top_author,
            "top_author_share": round(top_count / entry.commits, 2) if entry.commits else 0.0,
            "last_changed": entry.last_changed,
            "loc": cx.loc if cx else None,
            "mean_depth": cx.mean_depth if cx else None,
            "max_depth": cx.max_depth if cx else None,
            "branches": cx.branches if cx else None,
            "complexity": complexity,
            "score": round(entry.commits * complexity, 1),
        })
    rows.sort(key=lambda r: (-r["score"], -r["commits"], r["path"]))
    pairs = coupling(commits, stats, excludes, max_files, min_shared, min_degree)
    knowledge = [
        r for r in rows[: max(top * 2, 10)]
        if r["authors"] == 1 and r["commits"] >= 3
    ]
    return {
        "summary": {
            "commits": len(commits),
            "files_changed": len(stats),
            "files_ranked": len(rows),
            "files_gone": missing,
            "complexity_source": "files on disk" if root is not None else "lines changed (no --root)",
            "authors": len({c.author for c in commits if c.author}),
        },
        "hotspots": rows[:top],
        "coupling": pairs[:top],
        "knowledge_risk": knowledge[:top],
    }


# --------------------------------------------------------------------------- git

def run_git_log(repo: Path, since: Optional[str], path_filter: Optional[str]) -> str:
    cmd = [
        "git", "-C", str(repo), "-c", "core.quotepath=off", "log", "--numstat",
        "--no-merges", "--date=short", "--format=" + GIT_FORMAT,
    ]
    if since:
        cmd.append("--since=" + since)
    if path_filter:
        cmd += ["--", path_filter]
    try:
        result = subprocess.run(cmd, capture_output=True, check=False)
    except FileNotFoundError:
        raise SystemExit("error: git is not installed or not on PATH")
    if result.returncode != 0:
        message = result.stderr.decode("utf-8", errors="replace").strip()
        raise SystemExit("error: git log failed: " + message)
    return result.stdout.decode("utf-8", errors="replace")


# --------------------------------------------------------------------------- output

def _cell(value) -> str:
    if value is None:
        return "-"
    return str(value).replace("|", "\\|")


def to_markdown(report: dict) -> str:
    s = report["summary"]
    out = [
        "# Hotspots",
        "",
        f"Commits analysed: {s['commits']} | files changed: {s['files_changed']} | "
        f"ranked (still on disk): {s['files_ranked']} | gone since: {s['files_gone']} | "
        f"authors: {s['authors']}",
        "",
        f"Complexity source: {s['complexity_source']}. Score = commits x complexity, where "
        "complexity = non-blank lines x (1 + mean nesting depth) / 10 + branch keywords. "
        "It is a ranking aid, not a quality grade.",
        "",
        "## Top hotspots",
        "",
        "| # | File | Commits | Authors | +/- lines | LOC | Max depth | Branches | Complexity | Score |",
        "|---|------|---------|---------|-----------|-----|-----------|----------|------------|-------|",
    ]
    for i, r in enumerate(report["hotspots"], 1):
        out.append(
            f"| {i} | `{_cell(r['path'])}` | {r['commits']} | {r['authors']} | "
            f"+{r['added']}/-{r['deleted']} | {_cell(r['loc'])} | {_cell(r['max_depth'])} | "
            f"{_cell(r['branches'])} | {r['complexity']} | {r['score']} |"
        )
    if not report["hotspots"]:
        out.append("| - | no files matched | | | | | | | | |")
    out += ["", "## Change coupling", ""]
    if report["coupling"]:
        out += [
            "Files that keep changing in the same commit. Coupling across directories often "
            "means a hidden dependency or copy-pasted logic.",
            "",
            "| File A | File B | Shared commits | Degree | Same directory |",
            "|--------|--------|----------------|--------|----------------|",
        ]
        for p in report["coupling"]:
            out.append(
                f"| `{_cell(p['a'])}` | `{_cell(p['b'])}` | {p['shared']} | {p['degree']} | "
                f"{'yes' if p['same_dir'] else 'no'} |"
            )
    else:
        out.append("No pairs passed the thresholds.")
    out += ["", "## Knowledge risk", ""]
    if report["knowledge_risk"]:
        out += [
            "Busy files only one person has changed. Talk to them before touching these.",
            "",
            "| File | Commits | Only author | Last changed |",
            "|------|---------|-------------|--------------|",
        ]
        for r in report["knowledge_risk"]:
            out.append(f"| `{_cell(r['path'])}` | {r['commits']} | {_cell(r['top_author'])} | "
                       f"{_cell(r['last_changed'])} |")
    else:
        out.append("No single-author hotspots found.")
    return "\n".join(out) + "\n"


def to_csv(report: dict) -> str:
    cols = ["path", "commits", "authors", "added", "deleted", "loc", "mean_depth",
            "max_depth", "branches", "complexity", "score"]
    lines = [",".join(cols)]
    for r in report["hotspots"]:
        cells = []
        for c in cols:
            v = "" if r[c] is None else str(r[c])
            if any(ch in v for ch in ',"\n'):
                v = '"' + v.replace('"', '""') + '"'
            cells.append(v)
        lines.append(",".join(cells))
    return "\n".join(lines) + "\n"


# --------------------------------------------------------------------------- cli

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Rank risky files by git churn x complexity, plus change coupling.")
    src = p.add_mutually_exclusive_group(required=True)
    src.add_argument("--repo", type=Path, help="run git log in this repository")
    src.add_argument("--log", help="read git log --numstat output from this file ('-' = stdin)")
    p.add_argument("--root", type=Path,
                   help="working tree to measure complexity in (defaults to --repo)")
    p.add_argument("--since", help='only commits after this date, e.g. "12 months ago"')
    p.add_argument("--path", dest="path_filter", help="limit git log to this sub-path")
    p.add_argument("--top", type=int, default=25, help="rows per table (default 25)")
    p.add_argument("--exclude", action="append", default=[],
                   help="extra glob to ignore (repeatable)")
    p.add_argument("--no-default-excludes", action="store_true",
                   help="do not ignore lockfiles, vendor/, dist/, images")
    p.add_argument("--max-files-per-commit", type=int, default=30,
                   help="ignore larger commits for coupling (default 30)")
    p.add_argument("--min-shared", type=int, default=3,
                   help="minimum shared commits for a coupled pair (default 3)")
    p.add_argument("--min-degree", type=float, default=0.5,
                   help="minimum coupling degree 0-1 (default 0.5)")
    p.add_argument("--format", choices=["md", "json", "csv"], default="md")
    p.add_argument("--output", type=Path, help="write here instead of stdout")
    return p


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    if args.repo is not None:
        text = run_git_log(args.repo, args.since, args.path_filter)
        root = args.root or args.repo
    else:
        if args.log == "-":
            text = sys.stdin.read()
        else:
            text = Path(args.log).read_text(encoding="utf-8", errors="replace")
        root = args.root
    excludes = ([] if args.no_default_excludes else list(DEFAULT_EXCLUDES)) + args.exclude
    report = analyze(parse_log(text), root, excludes, args.top,
                     args.max_files_per_commit, args.min_shared, args.min_degree)
    if args.format == "json":
        rendered = json.dumps(report, indent=2, sort_keys=True) + "\n"
    elif args.format == "csv":
        rendered = to_csv(report)
    else:
        rendered = to_markdown(report)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_bytes((rendered).encode("utf-8"))
        print(f"wrote {args.output}", file=sys.stderr)
    else:
        sys.stdout.write(rendered)
    return 0


if __name__ == "__main__":
    sys.exit(main())
