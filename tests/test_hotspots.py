import io
import json
import shutil
import subprocess
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from _load import FIXTURES, load

hs = load("rescue-hotspots", "hotspots.py")

COMPLEX = """def total(items, region):
    result = 0
    for item in items:
        if item.taxable:
            if region == "EU":
                result += item.price * 1.2
            elif region == "US":
                result += item.price * 1.07
            else:
                result += item.price
        else:
            result += item.price
    return result
"""

SIMPLE = """RATE = 0.2


def rate():
    return RATE
"""


def fixture_text(name):
    return (FIXTURES / name).read_text(encoding="utf-8")


class ParseTests(unittest.TestCase):
    def test_parses_marker_format(self):
        commits = hs.parse_log(fixture_text("git-log-numstat.txt"))
        self.assertEqual(len(commits), 7)
        self.assertEqual(commits[0].author, "Alice")
        self.assertEqual(commits[0].date, "2025-01-10")
        self.assertIn(("src/billing/invoice.py", 12, 0), commits[0].files)

    def test_skips_binary_files(self):
        commits = hs.parse_log(fixture_text("git-log-numstat.txt"))
        paths = {p for c in commits for p, _a, _d in c.files}
        self.assertNotIn("docs/diagram.png", paths)

    def test_parses_default_git_format(self):
        commits = hs.parse_log(fixture_text("git-log-default.txt"))
        self.assertEqual(len(commits), 2)
        self.assertEqual(commits[0].author, "Dana Smith")
        self.assertEqual(commits[1].files[0][0], "lib/new_name.rb")

    def test_handles_crlf(self):
        text = fixture_text("git-log-numstat.txt").replace("\n", "\r\n")
        self.assertEqual(len(hs.parse_log(text)), 7)

    def test_rename_notation(self):
        self.assertEqual(hs.normalize_path("src/{old => util}/dates.py"), "src/util/dates.py")
        self.assertEqual(hs.normalize_path("src/{ => sub}/a.py"), "src/sub/a.py")
        self.assertEqual(hs.normalize_path("{lib => src}/a.py"), "src/a.py")
        self.assertEqual(hs.normalize_path("a.py => b.py"), "b.py")
        self.assertEqual(hs.normalize_path("plain/path.py"), "plain/path.py")


class AggregateTests(unittest.TestCase):
    def setUp(self):
        self.commits = hs.parse_log(fixture_text("git-log-numstat.txt"))
        self.stats = hs.aggregate(self.commits, hs.DEFAULT_EXCLUDES)

    def test_counts_commits_and_churn(self):
        invoice = self.stats["src/billing/invoice.py"]
        self.assertEqual(invoice.commits, 5)
        self.assertEqual(invoice.added, 78)
        self.assertEqual(invoice.deleted, 16)
        self.assertEqual(len(invoice.authors), 2)
        self.assertEqual(invoice.last_changed, "2025-06-11")

    def test_default_excludes_lockfiles(self):
        self.assertNotIn("package-lock.json", self.stats)

    def test_rename_counted_under_new_path(self):
        self.assertIn("src/util/dates.py", self.stats)

    def test_coupling(self):
        pairs = hs.coupling(self.commits, self.stats, hs.DEFAULT_EXCLUDES)
        self.assertEqual(len(pairs), 1)
        pair = pairs[0]
        self.assertEqual((pair["a"], pair["b"]), ("src/billing/invoice.py", "src/billing/tax.py"))
        self.assertEqual(pair["shared"], 4)
        self.assertEqual(pair["degree"], 1.0)
        self.assertTrue(pair["same_dir"])

    def test_coupling_ignores_huge_commits(self):
        pairs = hs.coupling(self.commits, self.stats, hs.DEFAULT_EXCLUDES, max_files=1)
        self.assertEqual(pairs, [])


class ComplexityTests(unittest.TestCase):
    def test_nested_code_scores_higher(self):
        hard, easy = hs.measure_text(COMPLEX), hs.measure_text(SIMPLE)
        self.assertGreater(hard.score, easy.score)
        self.assertEqual(hard.max_depth, 4)
        self.assertGreaterEqual(hard.branches, 5)
        self.assertEqual(easy.branches, 0)

    def test_tabs_and_empty(self):
        self.assertEqual(hs.measure_text("").loc, 0)
        tabbed = hs.measure_text("if x {\n\tif y {\n\t\tz()\n\t}\n}\n")
        self.assertEqual(tabbed.max_depth, 2)

    def test_binary_file_is_skipped(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "blob.bin"
            path.write_bytes(b"\x00\x01\x02")
            self.assertIsNone(hs.measure_file(path))


class AnalyzeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        (self.tmp / "src" / "billing").mkdir(parents=True)
        (self.tmp / "src" / "util").mkdir(parents=True)
        (self.tmp / "src" / "billing" / "invoice.py").write_text(COMPLEX, encoding="utf-8")
        (self.tmp / "src" / "billing" / "tax.py").write_text(SIMPLE, encoding="utf-8")
        (self.tmp / "src" / "util" / "strings.py").write_text(SIMPLE, encoding="utf-8")
        self.commits = hs.parse_log(fixture_text("git-log-numstat.txt"))

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_ranks_churn_times_complexity(self):
        report = hs.analyze(self.commits, self.tmp, hs.DEFAULT_EXCLUDES)
        paths = [r["path"] for r in report["hotspots"]]
        self.assertEqual(paths[0], "src/billing/invoice.py")
        self.assertEqual(paths[1], "src/billing/tax.py")
        self.assertEqual(report["summary"]["files_ranked"], 3)
        # README.md, dates.py and removed.py are not on disk any more
        self.assertEqual(report["summary"]["files_gone"], 3)

    def test_without_root_uses_lines_changed(self):
        report = hs.analyze(self.commits, None, hs.DEFAULT_EXCLUDES)
        top = report["hotspots"][0]
        self.assertEqual(top["path"], "src/billing/invoice.py")
        self.assertIsNone(top["loc"])
        self.assertEqual(top["complexity"], 94.0)

    def test_knowledge_risk(self):
        commits = [hs.Commit(sha=str(i), author="Solo", files=[("core.py", 1, 1)]) for i in range(4)]
        (self.tmp / "core.py").write_text(COMPLEX, encoding="utf-8")
        report = hs.analyze(commits, self.tmp, [])
        self.assertEqual(report["knowledge_risk"][0]["path"], "core.py")
        self.assertEqual(report["knowledge_risk"][0]["top_author"], "Solo")

    def test_markdown_and_csv(self):
        report = hs.analyze(self.commits, self.tmp, hs.DEFAULT_EXCLUDES)
        md = hs.to_markdown(report)
        self.assertIn("# Hotspots", md)
        self.assertIn("`src/billing/invoice.py`", md)
        self.assertIn("## Change coupling", md)
        csv_text = hs.to_csv(report)
        self.assertTrue(csv_text.startswith("path,commits"))
        self.assertEqual(len(csv_text.strip().splitlines()), 4)

    def test_deterministic(self):
        a = hs.analyze(self.commits, self.tmp, hs.DEFAULT_EXCLUDES)
        b = hs.analyze(self.commits, self.tmp, hs.DEFAULT_EXCLUDES)
        self.assertEqual(json.dumps(a, sort_keys=True), json.dumps(b, sort_keys=True))


class CliTests(unittest.TestCase):
    def test_cli_with_log_file_json(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = hs.main(["--log", str(FIXTURES / "git-log-numstat.txt"), "--format", "json"])
        self.assertEqual(code, 0)
        data = json.loads(buf.getvalue())
        self.assertEqual(data["summary"]["commits"], 7)

    def test_cli_writes_output_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "rescue" / "hotspots.md"
            with redirect_stderr(io.StringIO()):
                hs.main(["--log", str(FIXTURES / "git-log-numstat.txt"), "--output", str(out)])
            self.assertIn("# Hotspots", out.read_text(encoding="utf-8"))

    @unittest.skipUnless(shutil.which("git"), "git not installed")
    def test_runs_git_itself(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)

            def git(*args):
                subprocess.run(["git", "-c", "user.name=Tester", "-c", "user.email=t@example.com",
                                "-c", "commit.gpgsign=false", *args],
                               cwd=repo, check=True, capture_output=True)

            git("init", "-q")
            for i in range(3):
                (repo / "busy.py").write_text(COMPLEX + f"# rev {i}\n", encoding="utf-8")
                (repo / "calm.py").write_text(SIMPLE, encoding="utf-8")
                git("add", ".")
                git("commit", "-q", "-m", f"change {i}")
            buf = io.StringIO()
            with redirect_stdout(buf):
                hs.main(["--repo", str(repo), "--format", "json"])
            data = json.loads(buf.getvalue())
            self.assertEqual(data["summary"]["commits"], 3)
            self.assertEqual(data["hotspots"][0]["path"], "busy.py")
            self.assertEqual(data["hotspots"][0]["commits"], 3)


if __name__ == "__main__":
    unittest.main()
