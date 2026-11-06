#!/usr/bin/env python3
"""Turn "what is outdated" output into an ordered, risk-rated upgrade path.

Reads the JSON that package managers already produce, saved to files:

  npm outdated --json            > npm-outdated.json      (--npm)
  pip list --outdated --format=json > pip-outdated.json   (--pip)
  composer outdated --format=json > composer.json.out     (--composer)
  a CSV with name,current,latest[,ecosystem]              (--csv, any other tool)

For every package it works out how far behind it is (patch / minor / major,
how many majors) and a risk level, then orders the work so that the safe,
boring upgrades land first and every major jump is its own step.

It never runs a package manager and never touches the network.

Examples:
  npm outdated --json > rescue/npm-outdated.json
  python3 outdated_report.py --npm rescue/npm-outdated.json --output rescue/deps-path.md
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import re
import sys
from pathlib import Path
from typing import List, Optional, Tuple

VERSION = re.compile(r"(\d+)(?:\.(\d+))?(?:\.(\d+))?")
RISK_ORDER = {"low": 0, "medium": 1, "high": 2, "unknown": 3}


def parse_version(text: Optional[str]) -> Optional[Tuple[int, int, int]]:
    if not text:
        return None
    match = VERSION.search(str(text).lstrip("v^~=<> "))
    if not match:
        return None
    return tuple(int(g) if g is not None else 0 for g in match.groups())  # type: ignore[return-value]


def classify(current: Optional[str], latest: Optional[str]) -> dict:
    """Return the gap between two versions and the risk of jumping it."""
    cur, new = parse_version(current), parse_version(latest)
    if cur is None or new is None:
        return {"gap": "unknown", "majors_behind": None, "risk": "unknown",
                "why": "version could not be parsed or package is not installed"}
    if new <= cur:
        return {"gap": "none", "majors_behind": 0, "risk": "low", "why": "already current"}
    if new[0] > cur[0]:
        n = new[0] - cur[0]
        why = f"{n} major version{'s' if n > 1 else ''} behind; expect breaking changes"
        if cur[0] == 0:
            why = "leaving 0.x; the API was never promised stable"
        return {"gap": "major", "majors_behind": n, "risk": "high", "why": why}
    if new[1] > cur[1]:
        if cur[0] == 0:
            return {"gap": "minor", "majors_behind": 0, "risk": "high",
                    "why": "0.x minor bumps are allowed to break the API"}
        return {"gap": "minor", "majors_behind": 0, "risk": "medium",
                "why": "new features; deprecations possible"}
    if cur[0] == 0 and cur[1] == 0:
        return {"gap": "patch", "majors_behind": 0, "risk": "medium",
                "why": "0.0.x: every release may break"}
    return {"gap": "patch", "majors_behind": 0, "risk": "low", "why": "bug fixes only, in theory"}


def load_npm(text: str) -> List[dict]:
    data = json.loads(text or "{}")
    rows = []
    for name, info in sorted(data.items()):
        if isinstance(info, list):  # workspaces can report one entry per location
            info = info[0] if info else {}
        rows.append({"ecosystem": "npm", "name": name, "current": info.get("current"),
                     "wanted": info.get("wanted"), "latest": info.get("latest"),
                     "dev": info.get("type") == "devDependencies"})
    return rows


def load_pip(text: str) -> List[dict]:
    data = json.loads(text or "[]")
    return [{"ecosystem": "pip", "name": d.get("name"), "current": d.get("version"),
             "wanted": None, "latest": d.get("latest_version"), "dev": False}
            for d in sorted(data, key=lambda d: str(d.get("name", "")).lower())]


def load_composer(text: str) -> List[dict]:
    data = json.loads(text or "{}")
    items = data.get("installed", []) if isinstance(data, dict) else data
    return [{"ecosystem": "composer", "name": d.get("name"), "current": d.get("version"),
             "wanted": None, "latest": d.get("latest"), "dev": False}
            for d in sorted(items, key=lambda d: str(d.get("name", "")))]


def load_csv(text: str) -> List[dict]:
    reader = csv.DictReader(io.StringIO(text))
    rows = []
    for d in reader:
        d = {(k or "").strip().lower(): (v or "").strip() for k, v in d.items()}
        if not d.get("name"):
            continue
        rows.append({"ecosystem": d.get("ecosystem") or "other", "name": d["name"],
                     "current": d.get("current"), "wanted": d.get("wanted") or None,
                     "latest": d.get("latest"), "dev": d.get("dev", "").lower() in {"1", "true", "yes"}})
    return sorted(rows, key=lambda r: (r["ecosystem"], r["name"].lower()))


def plan(packages: List[dict]) -> dict:
    """Classify every package and order the upgrade path.

    Order: one batch of low-risk patch upgrades, then minor upgrades as one
    batch per ecosystem, then every high-risk jump as its own step (dev
    dependencies before runtime ones, fewest majors first), unknowns last.
    """
    rows = []
    for p in packages:
        info = classify(p.get("current"), p.get("latest"))
        if info["gap"] == "none":
            continue
        rows.append(dict(p, **info))

    steps: List[dict] = []
    patches = [r for r in rows if r["gap"] == "patch" and r["risk"] == "low"]
    if patches:
        steps.append({"title": "Patch upgrades (one batch)", "risk": "low", "packages": patches})
    minors = [r for r in rows if r["gap"] == "minor" and r["risk"] == "medium"]
    for eco in sorted({r["ecosystem"] for r in minors}):
        group = [r for r in minors if r["ecosystem"] == eco]
        steps.append({"title": f"Minor upgrades, {eco} (one batch, split if tests fail)",
                      "risk": "medium", "packages": group})
    risky = [r for r in rows if r["risk"] == "high" or (r["risk"] == "medium" and r["gap"] == "patch")]
    risky.sort(key=lambda r: (not r["dev"], r["majors_behind"] or 0, r["ecosystem"], r["name"].lower()))
    for r in risky:
        label = f"{r['name']} {r['current']} -> {r['latest']}"
        if (r["majors_behind"] or 0) > 1:
            label += " (go one major at a time)"
        steps.append({"title": label, "risk": r["risk"], "packages": [r]})
    unknown = [r for r in rows if r["risk"] == "unknown"]
    if unknown:
        steps.append({"title": "Investigate by hand (version unknown or not installed)",
                      "risk": "unknown", "packages": unknown})

    counts = {k: sum(1 for r in rows if r["risk"] == k) for k in RISK_ORDER}
    return {"packages": rows, "steps": steps, "counts": counts}


def to_markdown(result: dict) -> str:
    c = result["counts"]
    out = [
        "# Dependency upgrade path",
        "",
        f"Outdated packages: {len(result['packages'])} "
        f"(high risk {c['high']}, medium {c['medium']}, low {c['low']}, unknown {c['unknown']}).",
        "",
        "Run the characterization tests after every step. One step = one commit = one revert.",
        "",
        "## Steps",
        "",
    ]
    if not result["steps"]:
        out.append("Nothing to upgrade.")
    for i, step in enumerate(result["steps"], 1):
        out.append(f"### Step {i}: {step['title']} [{step['risk']}]")
        out.append("")
        for r in step["packages"]:
            dev = " (dev)" if r["dev"] else ""
            out.append(f"- `{r['name']}`{dev} {r['current'] or '?'} -> {r['latest'] or '?'} "
                       f"({r['ecosystem']}, {r['gap']}): {r['why']}")
        out.append("")
    out += ["## All outdated packages", "",
            "| Ecosystem | Package | Current | Wanted | Latest | Gap | Majors behind | Risk |",
            "|---|---|---|---|---|---|---|---|"]
    table_order = {"high": 0, "medium": 1, "unknown": 2, "low": 3}
    ordered = sorted(result["packages"],
                     key=lambda r: (table_order[r["risk"]], r["ecosystem"], r["name"].lower()))
    for r in ordered:
        mb = "-" if r["majors_behind"] is None else r["majors_behind"]
        out.append(f"| {r['ecosystem']} | `{r['name']}` | {r['current'] or '-'} | {r['wanted'] or '-'} | "
                   f"{r['latest'] or '-'} | {r['gap']} | {mb} | {r['risk']} |")
    return "\n".join(out) + "\n"


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Build a risk-ordered upgrade path from package-manager 'outdated' JSON.")
    p.add_argument("--npm", action="append", default=[], help="file with `npm outdated --json` output")
    p.add_argument("--pip", action="append", default=[],
                   help="file with `pip list --outdated --format=json` output")
    p.add_argument("--composer", action="append", default=[],
                   help="file with `composer outdated --format=json` output")
    p.add_argument("--csv", action="append", default=[],
                   help="CSV with columns name,current,latest[,ecosystem,dev] for any other tool")
    p.add_argument("--format", choices=["md", "json"], default="md")
    p.add_argument("--output", type=Path, help="write here instead of stdout")
    return p


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    sources = [(f, load_npm) for f in args.npm] + [(f, load_pip) for f in args.pip] + \
              [(f, load_composer) for f in args.composer] + [(f, load_csv) for f in args.csv]
    if not sources:
        build_parser().error("give at least one of --npm, --pip, --composer, --csv")
    packages: List[dict] = []
    for filename, loader in sources:
        text = Path(filename).read_text(encoding="utf-8-sig", errors="replace")
        try:
            packages += loader(text)
        except (ValueError, AttributeError) as exc:
            print(f"error: could not parse {filename}: {exc}", file=sys.stderr)
            return 2
    result = plan(packages)
    rendered = (json.dumps(result, indent=2) + "\n") if args.format == "json" else to_markdown(result)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_bytes((rendered).encode("utf-8"))
        print(f"wrote {args.output}", file=sys.stderr)
    else:
        sys.stdout.write(rendered)
    return 0


if __name__ == "__main__":
    sys.exit(main())
