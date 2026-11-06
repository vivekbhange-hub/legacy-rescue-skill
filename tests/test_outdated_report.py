import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from _load import FIXTURES, load

od = load("rescue-deps", "outdated_report.py")


def packages():
    npm = od.load_npm((FIXTURES / "npm-outdated.json").read_text(encoding="utf-8"))
    pip = od.load_pip((FIXTURES / "pip-outdated.json").read_text(encoding="utf-8"))
    return npm + pip


class ClassifyTests(unittest.TestCase):
    def test_gaps_and_risk(self):
        self.assertEqual(od.classify("4.17.20", "4.17.21")["risk"], "low")
        self.assertEqual(od.classify("2.24.0", "2.30.1")["risk"], "medium")
        major = od.classify("2.2.28", "5.1.4")
        self.assertEqual((major["gap"], major["majors_behind"], major["risk"]), ("major", 3, "high"))

    def test_zero_x_is_risky(self):
        self.assertEqual(od.classify("0.23.0", "0.28.1")["risk"], "high")
        self.assertEqual(od.classify("0.0.3", "0.0.4")["risk"], "medium")
        self.assertIn("0.x", od.classify("0.9.0", "1.0.0")["why"])

    def test_unparseable_and_current(self):
        self.assertEqual(od.classify(None, "1.0.0")["risk"], "unknown")
        self.assertEqual(od.classify("MISSING", "1.0.0")["risk"], "unknown")
        self.assertEqual(od.classify("1.2.3", "1.2.3")["gap"], "none")

    def test_version_prefixes(self):
        self.assertEqual(od.parse_version("v1.2"), (1, 2, 0))
        self.assertEqual(od.parse_version("^3.4.5-beta.1"), (3, 4, 5))


class LoaderTests(unittest.TestCase):
    def test_npm(self):
        rows = od.load_npm((FIXTURES / "npm-outdated.json").read_text(encoding="utf-8"))
        jest = next(r for r in rows if r["name"] == "jest")
        self.assertTrue(jest["dev"])
        self.assertEqual(len(rows), 5)

    def test_csv_and_composer(self):
        rows = od.load_csv("name,current,latest,ecosystem\nrails,5.2.8,8.0.1,bundler\n,1,2,x\n")
        self.assertEqual(rows, [{"ecosystem": "bundler", "name": "rails", "current": "5.2.8",
                                 "wanted": None, "latest": "8.0.1", "dev": False}])
        comp = od.load_composer(json.dumps({"installed": [
            {"name": "laravel/framework", "version": "v8.83.0", "latest": "v11.0.0"}]}))
        self.assertEqual(comp[0]["ecosystem"], "composer")


class PlanTests(unittest.TestCase):
    def setUp(self):
        self.result = od.plan(packages())

    def test_counts(self):
        self.assertEqual(self.result["counts"], {"low": 2, "medium": 2, "high": 4, "unknown": 1})

    def test_step_order(self):
        titles = [s["title"] for s in self.result["steps"]]
        self.assertEqual(len(titles), 8)
        self.assertEqual(titles[0], "Patch upgrades (one batch)")
        self.assertTrue(titles[1].startswith("Minor upgrades, npm"))
        self.assertTrue(titles[2].startswith("Minor upgrades, pip"))
        # dev dependency majors first, then runtime ones by distance
        self.assertTrue(titles[3].startswith("jest 26.6.3 -> 29.7.0"))
        self.assertIn("one major at a time", titles[3])
        self.assertTrue(titles[4].startswith("httpx"))
        self.assertTrue(titles[5].startswith("express"))
        self.assertTrue(titles[6].startswith("Django"))
        self.assertTrue(titles[7].startswith("Investigate by hand"))

    def test_every_risky_package_is_its_own_step(self):
        for step in self.result["steps"]:
            if step["risk"] == "high":
                self.assertEqual(len(step["packages"]), 1)

    def test_markdown(self):
        md = od.to_markdown(self.result)
        self.assertIn("### Step 1: Patch upgrades (one batch) [low]", md)
        self.assertIn("| npm | `express` | 4.17.1 | 4.21.2 | 5.1.0 | major | 1 | high |", md)
        first_row = [l for l in md.splitlines() if l.startswith("| ") and "`" in l][0]
        self.assertIn("high", first_row)


class CliTests(unittest.TestCase):
    def test_cli_combines_sources(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "deps.json"
            with redirect_stderr(io.StringIO()):
                code = od.main(["--npm", str(FIXTURES / "npm-outdated.json"),
                                "--pip", str(FIXTURES / "pip-outdated.json"),
                                "--format", "json", "--output", str(out)])
            self.assertEqual(code, 0)
            data = json.loads(out.read_text(encoding="utf-8"))
            self.assertEqual(len(data["packages"]), 9)

    def test_cli_requires_a_source(self):
        with redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit):
                od.main([])

    def test_cli_reports_bad_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            bad = Path(tmp) / "bad.json"
            bad.write_text("{not json", encoding="utf-8")
            with redirect_stderr(io.StringIO()), redirect_stdout(io.StringIO()):
                self.assertEqual(od.main(["--npm", str(bad)]), 2)


if __name__ == "__main__":
    unittest.main()
