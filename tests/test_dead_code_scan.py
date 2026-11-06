import io
import json
import shutil
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from _load import load

dc = load("rescue-dead-code", "dead_code_scan.py")

JS_WITH_OLD_CODE = """import { format } from './format-money';

// Formats the total for display.
// Uses the shop currency.
// Rounds half up.
export function total(items) {
  // const legacy = items.map(i => i.price);
  // if (legacy.length > 0) {
  //   return legacy.reduce((a, b) => a + b, 0);
  // }
  // return 0;
  if (false) {
    console.log('debug');
  }
  return format(items.reduce((a, i) => a + i.price, 0));
}
"""

PY_WITH_OLD_CODE = """import os

# x = compute()
# if x > 3:
#     print(x)
def run():
    if 0:
        pass
    return os.getcwd()
"""

FILES = {
    "src/total.js": JS_WITH_OLD_CODE,
    "src/format-money.js": "export const format = (n) => n.toFixed(2);\n",
    "src/old-report.js": "export const report = () => 1;\n",
    "src/index.js": "export * from './total';\n",
    "tools/run.py": PY_WITH_OLD_CODE,
    "tools/helpers.py": "def helper():\n    return 1\n",
    "tools/test_helpers.py": "def test_x():\n    assert True\n",
    "config/app.yml": "job: tools/run.py\n",
}


class CommentedCodeTests(unittest.TestCase):
    def test_finds_code_block_not_prose(self):
        blocks = dc.find_commented_blocks(JS_WITH_OLD_CODE, ".js")
        self.assertEqual(len(blocks), 1)
        self.assertEqual(blocks[0]["start"], 7)
        self.assertEqual(blocks[0]["lines"], 5)
        self.assertEqual(blocks[0]["confidence"], "high")

    def test_hash_comments_for_python(self):
        blocks = dc.find_commented_blocks(PY_WITH_OLD_CODE, ".py")
        self.assertEqual(len(blocks), 1)
        self.assertEqual(blocks[0]["confidence"], "medium")

    def test_shebang_and_license_ignored(self):
        text = "#!/usr/bin/env python\n# Copyright 2010 Someone\n# Licensed under X\n# See LICENSE\n"
        self.assertEqual(dc.find_commented_blocks(text, ".py"), [])

    def test_min_block(self):
        self.assertEqual(dc.find_commented_blocks(PY_WITH_OLD_CODE, ".py", min_block=4), [])

    def test_looks_like_code(self):
        self.assertTrue(dc.looks_like_code(" return total;"))
        self.assertTrue(dc.looks_like_code(" user.save()"))
        self.assertFalse(dc.looks_like_code(" This handles the refund case"))
        self.assertFalse(dc.looks_like_code(" TODO: remove after migration"))


class ConstantConditionTests(unittest.TestCase):
    def test_detects_constant_conditions(self):
        js = dc.find_constant_conditions(JS_WITH_OLD_CODE)
        self.assertEqual([h["line"] for h in js], [12])
        py = dc.find_constant_conditions(PY_WITH_OLD_CODE)
        self.assertEqual([h["line"] for h in py], [7])

    def test_ignores_real_conditions(self):
        self.assertEqual(dc.find_constant_conditions("if (enabled) {\nif x == 0:\n"), [])
        self.assertEqual(len(dc.find_constant_conditions("#if 0\nwhile (false) {\n")), 2)

    def test_infinite_loops_are_not_dead(self):
        self.assertEqual(dc.find_constant_conditions("while (true) {\nwhile True:\n"), [])

    def test_always_direction(self):
        hits = dc.find_constant_conditions("if (!false) {\nif False:\nif not None:\n")
        self.assertEqual([h["always"] for h in hits], ["true", "false", "true"])


class ScanTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp())
        for rel, text in FILES.items():
            path = cls.tmp / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")
        cls.report = dc.scan(cls.tmp)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_orphans(self):
        orphans = {o["path"] for o in self.report["orphan_files"]}
        self.assertIn("src/old-report.js", orphans)
        self.assertIn("tools/helpers.py", orphans)  # nothing imports it
        self.assertNotIn("src/format-money.js", orphans)  # imported by total.js
        self.assertNotIn("src/total.js", orphans)  # exported from index.js
        self.assertNotIn("src/index.js", orphans)  # conventional entry name
        self.assertNotIn("tools/run.py", orphans)  # referenced from YAML
        self.assertNotIn("tools/test_helpers.py", orphans)  # tests are never candidates

    def test_counts(self):
        self.assertEqual(self.report["source_files"], 7)
        self.assertEqual(len(self.report["commented_out"]), 2)
        self.assertEqual(len(self.report["constant_conditions"]), 2)

    def test_markdown(self):
        md = dc.to_markdown(self.report)
        self.assertIn("Nothing has been deleted", md)
        self.assertIn("`src/old-report.js`", md)

    def test_cli_json(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            self.assertEqual(dc.main([str(self.tmp), "--format", "json"]), 0)
        self.assertIn("orphan_files", json.loads(buf.getvalue()))

    def test_scan_does_not_modify_files(self):
        before = {p: p.read_bytes() for p in self.tmp.rglob("*") if p.is_file()}
        dc.scan(self.tmp)
        after = {p: p.read_bytes() for p in self.tmp.rglob("*") if p.is_file()}
        self.assertEqual(before, after)


if __name__ == "__main__":
    unittest.main()
