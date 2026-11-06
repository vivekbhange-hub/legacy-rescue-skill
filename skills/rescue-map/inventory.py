#!/usr/bin/env python3
"""Take a first inventory of an unfamiliar repository.

Walks the tree (skipping vendored and generated folders) and reports facts a
newcomer needs before reading any code:

  * languages by file count and non-blank lines
  * top-level directories and their size (candidate module boundaries)
  * build / dependency manifests, CI files, container files
  * declared commands (package.json scripts, Makefile targets, Procfile)
  * likely entry points
  * environment variables read by the code or listed in .env examples
  * hints of data stores and external services (keyword matches, with files)

It only reads files. It never runs the project. Standard library only.

Examples:
  python3 inventory.py .
  python3 inventory.py path/to/repo --format json --output rescue/inventory.json
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Dict, List, Optional

SKIP_DIRS = {
    ".git", ".hg", ".svn", "node_modules", "vendor", "dist", "build", "out", "target",
    ".venv", "venv", "__pycache__", ".tox", ".mypy_cache", ".pytest_cache",
    ".idea", ".vscode", ".gradle", ".next", ".nuxt", "coverage", "bower_components",
    "Pods", ".terraform", "obj", "rescue",
}

LANGUAGES = {
    ".py": "Python", ".js": "JavaScript", ".jsx": "JavaScript", ".mjs": "JavaScript",
    ".cjs": "JavaScript", ".ts": "TypeScript", ".tsx": "TypeScript", ".java": "Java",
    ".kt": "Kotlin", ".kts": "Kotlin", ".scala": "Scala", ".groovy": "Groovy",
    ".go": "Go", ".rs": "Rust", ".rb": "Ruby", ".php": "PHP", ".cs": "C#", ".vb": "Visual Basic",
    ".fs": "F#", ".c": "C", ".h": "C/C++ header", ".cpp": "C++", ".cc": "C++", ".hpp": "C++",
    ".m": "Objective-C", ".swift": "Swift", ".dart": "Dart", ".ex": "Elixir", ".exs": "Elixir",
    ".erl": "Erlang", ".clj": "Clojure", ".hs": "Haskell", ".lua": "Lua", ".pl": "Perl",
    ".pm": "Perl", ".r": "R", ".sql": "SQL", ".sh": "Shell", ".bash": "Shell", ".ps1": "PowerShell",
    ".bat": "Batch", ".cmd": "Batch", ".cob": "COBOL", ".cbl": "COBOL", ".pas": "Pascal",
    ".f90": "Fortran", ".asp": "ASP", ".aspx": "ASP.NET", ".jsp": "JSP", ".vue": "Vue",
    ".svelte": "Svelte", ".html": "HTML", ".css": "CSS", ".scss": "SCSS", ".less": "LESS",
    ".erb": "ERB", ".twig": "Twig", ".cfm": "ColdFusion", ".tf": "Terraform",
}

MANIFESTS = {
    "package.json": "npm/Node", "requirements.txt": "pip", "pyproject.toml": "Python project",
    "setup.py": "setuptools", "setup.cfg": "setuptools", "Pipfile": "pipenv",
    "environment.yml": "conda", "go.mod": "Go modules", "Cargo.toml": "Cargo",
    "pom.xml": "Maven", "build.gradle": "Gradle", "build.gradle.kts": "Gradle",
    "build.sbt": "sbt", "Gemfile": "Bundler", "composer.json": "Composer",
    "mix.exs": "Mix", "pubspec.yaml": "Dart pub", "Package.swift": "SwiftPM",
    "CMakeLists.txt": "CMake", "Makefile": "make", "makefile": "make", "GNUmakefile": "make",
    "Dockerfile": "Docker", "docker-compose.yml": "Docker Compose",
    "docker-compose.yaml": "Docker Compose", "compose.yml": "Docker Compose",
    "compose.yaml": "Docker Compose", "Procfile": "Procfile", "Jenkinsfile": "Jenkins",
    ".gitlab-ci.yml": "GitLab CI", "azure-pipelines.yml": "Azure Pipelines",
    ".travis.yml": "Travis CI", "Vagrantfile": "Vagrant", "tox.ini": "tox",
    "serverless.yml": "Serverless", "app.yaml": "App Engine", "Rakefile": "rake",
}
MANIFEST_SUFFIXES = {".csproj": ".NET project", ".sln": ".NET solution", ".vbproj": ".NET project",
                     ".fsproj": ".NET project", ".gemspec": "RubyGem"}

ENTRY_NAMES = {
    "main.py", "__main__.py", "manage.py", "app.py", "wsgi.py", "asgi.py", "server.py",
    "run.py", "index.js", "server.js", "app.js", "main.js", "index.ts", "server.ts",
    "main.ts", "main.go", "Program.cs", "Startup.cs", "Main.java", "Application.java",
    "index.php", "artisan", "config.ru", "main.rs", "lib.rs", "main.c", "main.cpp",
}

ENV_PATTERNS = [
    re.compile(r"process\.env\.([A-Z][A-Z0-9_]+)"),
    re.compile(r"process\.env\[\s*['\"]([A-Za-z_][A-Za-z0-9_]*)['\"]\s*\]"),
    re.compile(r"import\.meta\.env\.([A-Z][A-Z0-9_]+)"),
    re.compile(r"os\.environ\s*\[\s*['\"]([A-Za-z_][A-Za-z0-9_]*)['\"]"),
    re.compile(r"os\.environ\.get\(\s*['\"]([A-Za-z_][A-Za-z0-9_]*)['\"]"),
    re.compile(r"\bgetenv\(\s*['\"]([A-Za-z_][A-Za-z0-9_]*)['\"]"),
    re.compile(r"\bENV(?:\.fetch\(\s*|\[\s*)['\"]([A-Za-z_][A-Za-z0-9_]*)['\"]"),
    re.compile(r"System\.getenv\(\s*\"([A-Za-z_][A-Za-z0-9_]*)\""),
    re.compile(r"GetEnvironmentVariable\(\s*\"([A-Za-z_][A-Za-z0-9_]*)\""),
    re.compile(r"os\.Getenv\(\s*\"([A-Za-z_][A-Za-z0-9_]*)\""),
    re.compile(r"env::var\(\s*\"([A-Za-z_][A-Za-z0-9_]*)\""),
    re.compile(r"\benv\(\s*['\"]([A-Z][A-Z0-9_]+)['\"]"),
]
ENV_FILE_NAMES = {".env.example", ".env.sample", ".env.template", ".env.dist", "example.env",
                  "sample.env", ".env.defaults"}

SERVICE_HINTS = {
    "PostgreSQL": r"\bpostgres(?:ql)?\b|\bpsycopg2?\b|\bpg_connect\b|jdbc:postgresql|['\"]pg['\"]",
    "MySQL/MariaDB": r"\bmysql\b|\bmariadb\b|jdbc:mysql",
    "SQLite": r"\bsqlite3?\b",
    "SQL Server": r"\bmssql\b|\bsqlserver\b|jdbc:sqlserver|\bSqlConnection\b",
    "Oracle": r"\boracle\b|jdbc:oracle|\bcx_Oracle\b",
    "MongoDB": r"\bmongo(?:db|ose)?\b",
    "Redis": r"\bredis\b",
    "Memcached": r"\bmemcache[d]?\b",
    "Elasticsearch/OpenSearch": r"\belasticsearch\b|\bopensearch\b",
    "Kafka": r"\bkafka\b",
    "RabbitMQ/AMQP": r"\brabbitmq\b|\bamqp\b",
    "AWS": r"\bboto3\b|\baws-sdk\b|@aws-sdk/|\bamazonaws\.com\b",
    "S3": r"\bs3\b|\bS3Client\b",
    "Google Cloud": r"\bgoogle-cloud\b|@google-cloud/|\bgoogleapis\.com\b",
    "Azure": r"\bazure\b",
    "Stripe": r"\bstripe\b",
    "Twilio": r"\btwilio\b",
    "SendGrid/Mailgun/SES": r"\bsendgrid\b|\bmailgun\b|\bses\b",
    "SMTP": r"\bsmtp\b",
    "GraphQL": r"\bgraphql\b",
    "gRPC": r"\bgrpc\b",
    "Sentry": r"\bsentry\b",
    "LDAP/AD": r"\bldap\b",
    "FTP/SFTP": r"\bs?ftp\b|\bparamiko\b",
    "SOAP": r"\bsoap\b|\bwsdl\b",
}
SERVICE_REGEX = {name: re.compile(pattern, re.IGNORECASE) for name, pattern in SERVICE_HINTS.items()}

TEXT_LIMIT = 1_000_000


def _read_text(path: Path) -> Optional[str]:
    try:
        if path.stat().st_size > TEXT_LIMIT:
            return None
        data = path.read_bytes()
    except OSError:
        return None
    if b"\x00" in data[:8192]:
        return None
    return data.decode("utf-8", errors="replace")


def iter_files(root: Path, extra_skip: Optional[set] = None):
    skip = SKIP_DIRS | (extra_skip or set())
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if d not in skip and not d.endswith(".egg-info"))
        for name in sorted(filenames):
            yield Path(dirpath) / name


def makefile_targets(text: str) -> List[str]:
    targets = []
    for line in text.splitlines():
        m = re.match(r"^([A-Za-z0-9][A-Za-z0-9_.\-/]*)\s*:(?!=)", line)
        if m and not m.group(1).startswith(".") and m.group(1) not in targets:
            targets.append(m.group(1))
    return targets


def scan(root: Path, extra_skip: Optional[set] = None) -> dict:
    root = root.resolve()
    lang_files: Counter = Counter()
    lang_lines: Counter = Counter()
    top_dirs: Dict[str, Dict[str, int]] = defaultdict(lambda: {"files": 0, "lines": 0})
    manifests: List[dict] = []
    commands: List[dict] = []
    entry_points: List[str] = []
    env_vars: Dict[str, set] = defaultdict(set)
    services: Dict[str, set] = defaultdict(set)
    tests: List[str] = []
    total_files = 0

    for path in iter_files(root, extra_skip):
        rel = path.relative_to(root).as_posix()
        name = path.name
        total_files += 1
        suffix = path.suffix.lower()
        lang = LANGUAGES.get(suffix)
        text = None
        if lang or name in MANIFESTS or suffix in MANIFEST_SUFFIXES or name in ENV_FILE_NAMES \
                or suffix in {".json", ".yml", ".yaml", ".toml", ".ini", ".cfg", ".xml",
                              ".properties", ".conf", ".config"}:
            text = _read_text(path)
        lines = sum(1 for l in text.splitlines() if l.strip()) if text else 0

        top = rel.split("/", 1)[0] if "/" in rel else "(root files)"
        top_dirs[top]["files"] += 1
        top_dirs[top]["lines"] += lines

        if lang:
            lang_files[lang] += 1
            lang_lines[lang] += lines

        kind = MANIFESTS.get(name) or MANIFEST_SUFFIXES.get(suffix)
        if kind:
            manifests.append({"path": rel, "kind": kind})
        if rel.startswith(".github/workflows/") and suffix in {".yml", ".yaml"}:
            manifests.append({"path": rel, "kind": "GitHub Actions"})

        if name == "package.json" and text:
            try:
                pkg = json.loads(text)
            except ValueError:
                pkg = {}
            if isinstance(pkg, dict):
                for script, cmd in sorted((pkg.get("scripts") or {}).items()):
                    commands.append({"source": rel, "name": script, "command": str(cmd)})
                main = pkg.get("main")
                if isinstance(main, str):
                    entry_points.append(f"{rel} -> main: {main}")
                bins = pkg.get("bin")
                if isinstance(bins, str):
                    entry_points.append(f"{rel} -> bin: {bins}")
                elif isinstance(bins, dict):
                    for b, target in sorted(bins.items()):
                        entry_points.append(f"{rel} -> bin {b}: {target}")
        elif name in {"Makefile", "makefile", "GNUmakefile"} and text:
            for target in makefile_targets(text):
                commands.append({"source": rel, "name": target, "command": f"make {target}"})
        elif name == "Procfile" and text:
            for line in text.splitlines():
                if ":" in line and not line.strip().startswith("#"):
                    proc, cmd = line.split(":", 1)
                    commands.append({"source": rel, "name": proc.strip(), "command": cmd.strip()})

        if name in ENTRY_NAMES:
            entry_points.append(rel)
        elif text and lang in {"Java", "C#"} and re.search(r"\bstatic\s+(?:async\s+)?(?:void|int|Task(?:<int>)?)\s+[Mm]ain\s*\(", text):
            entry_points.append(rel)
        elif text and lang == "Python" and "__name__" in text and \
                re.search(r"if\s+__name__\s*==\s*['\"]__main__['\"]", text):
            entry_points.append(rel)

        low = rel.lower()
        if lang and (re.search(r"(^|/)(tests?|spec|__tests__)/", low)
                     or re.search(r"(^|/)(test_[^/]+|[^/]+_test\.[a-z]+|[^/]+\.(test|spec)\.[a-z]+|[^/]+Tests?\.(java|cs|kt))$", rel)):
            tests.append(rel)

        if text:
            if name in ENV_FILE_NAMES:
                for line in text.splitlines():
                    m = re.match(r"^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=", line)
                    if m:
                        env_vars[m.group(1)].add(rel)
            elif lang:
                for pattern in ENV_PATTERNS:
                    for var in pattern.findall(text):
                        env_vars[var].add(rel)
            if lang or kind:
                for service, regex in SERVICE_REGEX.items():
                    if regex.search(text):
                        services[service].add(rel)

    languages = [
        {"language": l, "files": lang_files[l], "lines": lang_lines[l]}
        for l in sorted(lang_files, key=lambda k: (-lang_lines[k], -lang_files[k], k))
    ]
    directories = [
        {"path": d, "files": v["files"], "lines": v["lines"]}
        for d, v in sorted(top_dirs.items(), key=lambda kv: (-kv[1]["lines"], kv[0]))
    ]
    return {
        "root": root.name,
        "total_files": total_files,
        "languages": languages,
        "directories": directories,
        "manifests": sorted(manifests, key=lambda m: m["path"]),
        "commands": commands,
        "entry_points": sorted(set(entry_points)),
        "tests": {"count": len(tests), "sample": sorted(tests)[:15]},
        "env_vars": {k: sorted(v) for k, v in sorted(env_vars.items())},
        "services": {k: sorted(v) for k, v in sorted(services.items(), key=lambda kv: (-len(kv[1]), kv[0]))},
    }


def _short(paths: List[str], limit: int = 3) -> str:
    shown = ", ".join(f"`{p}`" for p in paths[:limit])
    return shown + (f" (+{len(paths) - limit} more)" if len(paths) > limit else "")


def to_markdown(inv: dict) -> str:
    out = [f"# Inventory: {inv['root']}", "",
           f"Files scanned (excluding vendored/generated folders): {inv['total_files']}", ""]
    out += ["## Languages", "", "| Language | Files | Non-blank lines |", "|---|---|---|"]
    out += [f"| {l['language']} | {l['files']} | {l['lines']} |" for l in inv["languages"]] or ["| none | | |"]
    out += ["", "## Top-level directories", "", "| Directory | Files | Lines |", "|---|---|---|"]
    out += [f"| `{d['path']}` | {d['files']} | {d['lines']} |" for d in inv["directories"]]
    out += ["", "## Manifests, CI and container files", ""]
    out += [f"- `{m['path']}` ({m['kind']})" for m in inv["manifests"]] or ["- none found"]
    out += ["", "## Declared commands", ""]
    if inv["commands"]:
        out += ["| Source | Name | Command |", "|---|---|---|"]
        for c in inv["commands"]:
            command = c["command"].replace("|", "\\|")
            out.append(f"| `{c['source']}` | {c['name']} | `{command}` |")
    else:
        out.append("- none declared; look at README, CI files and Dockerfile")
    out += ["", "## Likely entry points", ""]
    out += [f"- `{e}`" for e in inv["entry_points"]] or ["- none found by name; search for main/handler registration"]
    out += ["", "## Tests", "", f"Test-looking files: {inv['tests']['count']}"]
    out += [f"- `{t}`" for t in inv["tests"]["sample"]]
    out += ["", "## Environment variables", ""]
    if inv["env_vars"]:
        out += ["| Variable | Read in |", "|---|---|"]
        out += [f"| `{k}` | {_short(v)} |" for k, v in inv["env_vars"].items()]
    else:
        out.append("- none detected")
    out += ["", "## Data stores and external services (keyword hints, verify each)", ""]
    if inv["services"]:
        out += ["| Hint | Files |", "|---|---|"]
        out += [f"| {k} | {_short(v)} |" for k, v in inv["services"].items()]
    else:
        out.append("- none detected")
    return "\n".join(out) + "\n"


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Inventory an unfamiliar repository (read-only).")
    p.add_argument("root", nargs="?", default=".", type=Path, help="repository root (default .)")
    p.add_argument("--skip", action="append", default=[], help="extra directory name to skip (repeatable)")
    p.add_argument("--format", choices=["md", "json"], default="md")
    p.add_argument("--output", type=Path, help="write here instead of stdout")
    return p


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    if not args.root.is_dir():
        print(f"error: {args.root} is not a directory", file=sys.stderr)
        return 2
    inv = scan(args.root, set(args.skip))
    rendered = json.dumps(inv, indent=2) + "\n" if args.format == "json" else to_markdown(inv)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_bytes((rendered).encode("utf-8"))
        print(f"wrote {args.output}", file=sys.stderr)
    else:
        sys.stdout.write(rendered)
    return 0


if __name__ == "__main__":
    sys.exit(main())
