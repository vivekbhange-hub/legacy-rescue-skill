---
name: rescue-hotspots
description: >-
  Finds where the risk in a legacy codebase concentrates by crossing git history with code
  complexity: files that change often and are hard to read, pairs of files that always change
  together, and busy files only one person has touched. Runs a bundled script over git log
  and writes rescue/hotspots.md with a ranked table and a short reading of what it means.
  Use when the user says "where is the risky code", "find the hotspots", "what should we
  refactor first", "which files break the most", "show me code churn", "what changes
  together", or "who knows this code".
argument-hint: "[repo path] [--since \"18 months ago\"]"
---

# rescue-hotspots

Most of a legacy codebase is quiet. A small set of files gets changed every week and is also
the hardest to read; that is where bugs, slow reviews and production incidents come from, and
where a safety net pays back first. This skill finds that set with numbers instead of
opinions: change frequency from git, complexity measured from the current files, coupling
from files that are committed together. The output is a ranked list the team can argue with.

## Inputs

- `$ARGUMENTS`: repository path (default `.`) and an optional time window.
- Default window: the last 12 months. Use 18-24 months for slow-moving repos (fewer than
  about 100 commits in 12 months). Use the full history only if it is short.
- `rescue/map.md` if it exists, to name modules in the write-up.

## Output

- `rescue/hotspots.md`: the script's tables plus your interpretation at the top.
- `rescue/hotspots.json` (optional, with `--format json`) for `rescue-plan`.

## Steps

1. **Check history is usable.** Run `git rev-list --count HEAD` and
   `git log --format=%ad --date=short | tail -1`. If there are fewer than about 30 commits,
   tell the user churn will be thin and lean on complexity. If the repo is a shallow clone
   (`git rev-parse --is-shallow-repository` prints `true`), say the numbers only cover the
   fetched history.

2. **Run the analysis.**
   ```
   python3 "${CLAUDE_SKILL_DIR}/hotspots.py" --repo . --since "12 months ago" --top 25 --output rescue/hotspots.md
   ```
   Useful options:
   - `--path src/` limit to one sub-tree (monorepos).
   - `--exclude "*.generated.cs" --exclude "migrations/*"` drop generated code. Lockfiles,
     vendor/, dist/, build/, minified files and images are excluded by default.
   - `--min-shared 3 --min-degree 0.5` coupling thresholds; lower them on small histories.
   - `--format json --output rescue/hotspots.json` for machine-readable output.
   - `--log saved.txt --root .` analyse a saved `git log --numstat` instead of running git.
   On Windows use `python` if `python3` is missing.

3. **Sanity-check the top ten.** Open each of the top ten files briefly. Remove from your
   reading (not from the table) anything that is data, generated, a changelog or a config file
   that churns by design, and say why. Rerun with `--exclude` if they crowd the list.

4. **Read the coupling table.** For every pair in different directories, look at two shared
   commits (`git log --format='%h %s' -- <a> <b> | head`) and decide which of these it is:
   - hidden dependency (one reads the other's data shape, protocol or file format)
   - copy-paste twins (same logic in two places; fix one, forget the other)
   - feature split across layers (normal; say so and move on)
   Name the kind for each pair. Hidden dependencies and twins go into the risk list.

5. **Read the knowledge-risk table.** Single-author busy files are a bus-factor problem.
   If the author is still around (`git log -1 --format=%ad -- <file>`), recommend a walkthrough
   with them before anyone changes the file.

6. **Write the interpretation** at the top of `rescue/hotspots.md`, above the generated tables:

   ```markdown
   ## What this means
   1. `<file>` - <one sentence: why it is risky, what it does for the business>
   2. ...
   **Change these last, test these first:** <the 3-5 files to characterize before touching>
   **Coupling to untangle:** <pairs that are hidden dependencies or twins>
   **People to talk to:** <author - files>
   **Method and limits:** churn from <window>, complexity is a text-based estimate.
   ```

7. Tell the user the top three files and the recommended first module for
   `rescue-characterize`.

## How the score works

- **Commits**: distinct non-merge commits touching the file in the window.
- **Complexity**: non-blank lines x (1 + mean indentation depth) / 10 + count of branch
  keywords (`if`, `else`, `for`, `while`, `case`, `catch`, `&&`, `||`, ternaries). It works
  for any language and is deliberately rough; it ranks files, it does not grade them.
- **Score**: commits x complexity. A 3,000-line file nobody touches scores low; a 400-line
  file changed weekly scores high. That is the point.
- **Coupling degree**: shared commits / commits of the less-changed file. Commits touching
  more than 30 files are ignored so formatting sweeps do not couple everything.
- Without `--root` (log-only mode) complexity falls back to lines changed.

## Decision rules

- The top of the list is a candidate, not a verdict. A hotspot that is well tested and
  changes for good reasons (a pricing table, a feature registry) can stay as it is.
- Prefer files that are both high-score and on a critical path from `rescue/map.md`
  (payments, auth, data writes) when recommending what to characterize first.
- If two files are coupled at degree 1.0 across modules, treat them as one unit in later
  refactors.

## What NOT to do

- Do not use these numbers to rank people. Authors appear only to find who to ask.
- Do not refactor anything in this skill. It only measures and writes `rescue/` files.
- Do not paste the whole git log into the chat; summarise.
- Do not trust churn from the month of a big migration or reformat; exclude that range
  with `--since` or explain it.

## Hand-off

Next: `rescue-characterize` on the top hotspot you and the user pick, so it is pinned by tests
before anyone touches it. In parallel, `rescue-dead-code` can shrink the surface and
`rescue-deps` can check the toolchain. `rescue-plan` reads `rescue/hotspots.md`.
