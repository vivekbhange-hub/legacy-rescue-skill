# Contributing

Thanks for helping. This pack is for people who inherited code they did not write, so every
change should make a rescue safer, smaller or clearer.

## Ground rules

- Be kind and assume good intent. This project follows the spirit of the
  [Contributor Covenant](https://www.contributor-covenant.org/); please read it.
- Open an issue before a large change so we can agree on the shape first.
- One concern per pull request.

## Skills

- Each skill lives in `skills/rescue-<name>/SKILL.md`. The `name` in the frontmatter must
  equal the folder name.
- The `description` says what the skill does in plain words, then lists 5 to 8 phrases a
  user would really type. Keep it under about 900 characters.
- The body has: a purpose paragraph, numbered steps Claude can actually follow with its tools,
  the files it writes (under `rescue/` in the user's project), decision rules, a
  "What NOT to do" section and a hand-off to the next skill. Aim for 60 to 200 lines.
- Anything that deletes code, upgrades packages or writes to GitHub must be proposed first
  and executed only after the user confirms.

## Helper scripts

- Python 3.9 or newer, standard library only, no network access, deterministic output.
- A CLI built with `argparse` that supports `--help`.
- Open files with `encoding="utf-8"` and use `pathlib` so it works on Windows, macOS and Linux.
- Add tests in `tests/test_<script>.py`. Load the script with `tests/_load.py` (skill folders
  contain hyphens, so they are not importable packages).

## Agents

- One file per agent in `agents/`, with `name`, `description` and the least `tools` it needs.
  Read-only agents do not get `Write` or `Edit`.

## Running the tests

```
python -m unittest discover -s tests -v
```

All tests must pass before a pull request is merged. If `claude plugin validate .` is
available in your Claude Code version, run it too.

## Reporting a problem

Include the skill or script name, what you ran, what you expected and what happened. If a
script misread your repository, a minimal anonymised example (a few lines of `git log
--numstat`, a trimmed `npm outdated --json`) helps more than a description.
