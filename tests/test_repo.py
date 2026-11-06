"""Structural checks for the pack: skills, agents, manifests, README, license."""

import json
import re
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
REPO_NAME = "legacy-rescue-skill"
PREFIX = "rescue-"


def frontmatter(path: Path) -> dict:
    """Parse simple YAML frontmatter by hand: `key: value` and folded `key: >-` blocks."""
    text = path.read_text(encoding="utf-8").replace("\r\n", "\n")
    if not text.startswith("---\n"):
        return {}
    end = text.find("\n---", 4)
    if end == -1:
        return {}
    data, key = {}, None
    for line in text[4:end].split("\n"):
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        match = re.match(r"^([A-Za-z][\w-]*):\s*(.*)$", line)
        if match and not line.startswith(" "):
            key, value = match.group(1), match.group(2).strip()
            if value in (">", ">-", "|", "|-"):
                value = ""
            data[key] = value.strip('"').strip("'") if value else ""
        elif key is not None and line.startswith(" "):
            data[key] = (data[key] + " " + line.strip()).strip()
    return data


def skill_dirs():
    return sorted(p for p in (REPO / "skills").iterdir() if p.is_dir())


class SkillTests(unittest.TestCase):
    def test_has_seven_or_eight_skills(self):
        self.assertIn(len(skill_dirs()), (7, 8))

    def test_skill_frontmatter(self):
        for d in skill_dirs():
            with self.subTest(skill=d.name):
                skill = d / "SKILL.md"
                self.assertTrue(skill.is_file(), f"{skill} missing")
                fm = frontmatter(skill)
                self.assertEqual(fm.get("name"), d.name)
                self.assertTrue(d.name.startswith(PREFIX))
                self.assertRegex(d.name, r"^[a-z0-9]+(-[a-z0-9]+)*$")
                desc = fm.get("description", "")
                self.assertTrue(desc, "description is empty")
                self.assertLessEqual(len(desc), 1024)
                self.assertIn("Use when", desc)

    def test_skill_length_and_sections(self):
        for d in skill_dirs():
            with self.subTest(skill=d.name):
                text = (d / "SKILL.md").read_text(encoding="utf-8")
                lines = text.splitlines()
                self.assertGreaterEqual(len(lines), 60)
                self.assertLessEqual(len(lines), 200)
                self.assertIn("What NOT to do", text)

    def test_referenced_scripts_exist(self):
        for d in skill_dirs():
            text = (d / "SKILL.md").read_text(encoding="utf-8")
            for script in re.findall(r"\$\{CLAUDE_SKILL_DIR\}/([\w.-]+)", text):
                with self.subTest(skill=d.name, script=script):
                    self.assertTrue((d / script).is_file())

    def test_every_script_has_a_test(self):
        for script in (REPO / "skills").glob("*/*.py"):
            with self.subTest(script=script.name):
                self.assertTrue((REPO / "tests" / f"test_{script.stem}.py").is_file())


class AgentTests(unittest.TestCase):
    def test_agent_frontmatter(self):
        agents = sorted((REPO / "agents").glob("*.md"))
        self.assertGreaterEqual(len(agents), 1)
        for agent in agents:
            with self.subTest(agent=agent.name):
                fm = frontmatter(agent)
                self.assertEqual(fm.get("name"), agent.stem)
                self.assertTrue(fm.get("description"))
                self.assertTrue(fm.get("tools"))

    def test_read_only_agents_cannot_write(self):
        for name in ("legacy-cartographer", "upgrade-planner"):
            tools = frontmatter(REPO / "agents" / f"{name}.md")["tools"]
            self.assertNotIn("Write", tools)
            self.assertNotIn("Edit", tools)


class ManifestTests(unittest.TestCase):
    def load(self, name):
        return json.loads((REPO / ".claude-plugin" / name).read_text(encoding="utf-8"))

    def test_marketplace(self):
        data = self.load("marketplace.json")
        self.assertEqual(data["name"], REPO_NAME)
        self.assertEqual(data["owner"]["name"], "Vivek Bhange")
        plugin = data["plugins"][0]
        self.assertEqual(plugin["name"], REPO_NAME)
        self.assertEqual(plugin["source"], "./")
        self.assertEqual(plugin["category"], "development")
        self.assertEqual(plugin["homepage"], f"https://github.com/vivekbhange-hub/{REPO_NAME}")

    def test_plugin(self):
        data = self.load("plugin.json")
        self.assertEqual(data["name"], REPO_NAME)
        self.assertEqual(data["version"], "1.0.0")
        self.assertEqual(data["license"], "MIT")
        self.assertEqual(data["author"]["name"], "Vivek Bhange")
        self.assertIn("claude-code", data["keywords"])
        self.assertIn("claude-skills", data["keywords"])
        self.assertTrue(6 <= len(data["keywords"]) <= 10)
        self.assertEqual(data["repository"], f"https://github.com/vivekbhange-hub/{REPO_NAME}")


class DocsTests(unittest.TestCase):
    def test_readme_mentions_every_skill_and_agent(self):
        readme = (REPO / "README.md").read_text(encoding="utf-8")
        for d in skill_dirs():
            with self.subTest(skill=d.name):
                self.assertIn(d.name, readme)
        for agent in (REPO / "agents").glob("*.md"):
            with self.subTest(agent=agent.stem):
                self.assertIn(agent.stem, readme)
        self.assertIn(f"/plugin marketplace add vivekbhange-hub/{REPO_NAME}", readme)

    def test_license(self):
        text = (REPO / "LICENSE").read_text(encoding="utf-8")
        self.assertIn("MIT", text)
        self.assertIn("Copyright (c) 2026 Vivek Bhange", text)

    def test_changelog_and_contributing(self):
        self.assertIn("1.0.0", (REPO / "CHANGELOG.md").read_text(encoding="utf-8"))
        self.assertIn("2026-11-07", (REPO / "CHANGELOG.md").read_text(encoding="utf-8"))
        self.assertTrue((REPO / "CONTRIBUTING.md").is_file())
        ignore = (REPO / ".gitignore").read_text(encoding="utf-8")
        for entry in (".DS_Store", "__pycache__/", "*.pyc", ".venv/", "*.tmp"):
            self.assertIn(entry, ignore)


if __name__ == "__main__":
    unittest.main()
