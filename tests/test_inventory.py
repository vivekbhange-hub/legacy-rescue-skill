import io
import json
import shutil
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from _load import load

inv = load("rescue-map", "inventory.py")

FILES = {
    "package.json": json.dumps({
        "name": "shop", "main": "server.js",
        "scripts": {"start": "node server.js", "test": "jest | tee out.txt"},
    }),
    "server.js": "const db = require('pg');\nconst port = process.env.PORT || 3000;\n"
                 "const key = process.env['STRIPE_KEY'];\n",
    "src/orders/service.js": "const redis = require('redis');\nmodule.exports = {};\n",
    "src/orders/service.test.js": "test('x', () => {});\n",
    "worker/main.py": "import os\nURL = os.environ.get('DATABASE_URL')\nT = os.getenv(\"TIMEOUT\")\n"
                      "if __name__ == '__main__':\n    pass\n",
    "Makefile": "build:\n\tnpm run build\n.PHONY: build\ntest: build\n\tnpm test\nVAR := 1\n",
    ".env.example": "PORT=3000\nexport SECRET_TOKEN=changeme\n# comment\n",
    "Dockerfile": "FROM node:18\n",
    ".github/workflows/ci.yml": "on: push\n",
    "node_modules/lib/index.js": "process.env.SHOULD_NOT_APPEAR\n",
    "legacy/Billing.java": "public class Billing {\n  public static void main(String[] args) {}\n}\n",
}


class InventoryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp())
        for rel, text in FILES.items():
            path = cls.tmp / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")
        cls.inv = inv.scan(cls.tmp)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_languages(self):
        names = {l["language"] for l in self.inv["languages"]}
        self.assertEqual(names, {"JavaScript", "Python", "Java"})
        js = next(l for l in self.inv["languages"] if l["language"] == "JavaScript")
        self.assertEqual(js["files"], 3)  # node_modules skipped

    def test_manifests(self):
        kinds = {m["path"]: m["kind"] for m in self.inv["manifests"]}
        self.assertEqual(kinds["package.json"], "npm/Node")
        self.assertEqual(kinds["Dockerfile"], "Docker")
        self.assertEqual(kinds["Makefile"], "make")
        self.assertEqual(kinds[".github/workflows/ci.yml"], "GitHub Actions")

    def test_commands(self):
        names = {(c["source"], c["name"]) for c in self.inv["commands"]}
        self.assertIn(("package.json", "start"), names)
        self.assertIn(("Makefile", "build"), names)
        self.assertIn(("Makefile", "test"), names)
        self.assertNotIn(("Makefile", "VAR"), names)
        self.assertNotIn(("Makefile", ".PHONY"), names)

    def test_entry_points(self):
        entries = self.inv["entry_points"]
        self.assertIn("server.js", entries)
        self.assertIn("worker/main.py", entries)
        self.assertIn("legacy/Billing.java", entries)
        self.assertIn("package.json -> main: server.js", entries)

    def test_env_vars(self):
        env = self.inv["env_vars"]
        for var in ("PORT", "STRIPE_KEY", "DATABASE_URL", "TIMEOUT", "SECRET_TOKEN"):
            self.assertIn(var, env)
        self.assertNotIn("SHOULD_NOT_APPEAR", env)
        self.assertEqual(env["PORT"], [".env.example", "server.js"])

    def test_services_and_tests(self):
        self.assertIn("PostgreSQL", self.inv["services"])
        self.assertIn("Redis", self.inv["services"])
        self.assertEqual(self.inv["tests"]["count"], 1)

    def test_markdown_escapes_pipes(self):
        md = inv.to_markdown(self.inv)
        self.assertIn("## Environment variables", md)
        self.assertIn("jest \\| tee out.txt", md)

    def test_cli_json(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            self.assertEqual(inv.main([str(self.tmp), "--format", "json"]), 0)
        self.assertEqual(json.loads(buf.getvalue())["root"], self.tmp.name)

    def test_cli_rejects_missing_dir(self):
        with redirect_stderr(io.StringIO()):
            self.assertEqual(inv.main([str(self.tmp / "nope")]), 2)


if __name__ == "__main__":
    unittest.main()
