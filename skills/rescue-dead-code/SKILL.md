---
name: rescue-dead-code
description: >-
  Finds code a legacy project probably no longer uses: unreferenced files, exports and
  functions, unused dependencies, feature flags stuck on or off, constant conditions and
  commented-out blocks. Rates each finding high, medium or low confidence with the evidence,
  writes rescue/dead-code.md, and proposes deletion in small, separately revertible batches.
  Never deletes anything without explicit confirmation. Use when the user says "find dead
  code", "what can we delete", "is this file still used", "remove unused code", "clean up
  old feature flags", "unused dependencies", or "shrink this codebase".
argument-hint: "[path, default .]"
---

# rescue-dead-code

Every line in a legacy codebase costs reading time, upgrade work and false leads during an
incident. Some of it does nothing. This skill finds the likely-dead parts, proves or disproves
each one with evidence, and proposes deletion in batches small enough that a wrong call is a
one-commit revert. It is conservative by design: a text search cannot see reflection, routing
by convention, templates or code called from outside the repo, so the default answer for
anything uncertain is "leave it and log it".

## Inputs

- `$ARGUMENTS`: path to scan, default `.`.
- `rescue/map.md` if present: entry points and frameworks change what "unreferenced" means.
- Production evidence if the user can share it: access logs, APM endpoint lists, job run logs.
  This is the only thing that turns "probably dead" into "dead".

## Output

- `rescue/dead-code.md`: findings by category with confidence and evidence, then a deletion
  proposal in batches.
- Code changes only after the user approves a specific batch, one batch per commit.

## Steps

1. **Run the scanner.**
   ```
   python3 "${CLAUDE_SKILL_DIR}/dead_code_scan.py" . --output rescue/dead-code-scan.md
   ```
   It reports commented-out code blocks (comment runs that look like code, not prose),
   constant conditions (`if (false)`, `if 0:`, `#if 0`, `if True:`; `while (true)` loops are
   ignored) and orphan files (source files whose name no other file mentions). Use
   `--min-block 5` for less noise and `--skip <dir>` for generated folders.

2. **Use the ecosystem's own tools when present** (check the lockfile or config first; do not
   install anything without asking):
   - JavaScript/TypeScript: `npx --no-install knip`, `npx --no-install ts-prune`,
     `npx --no-install depcheck`.
   - Python: `vulture <src> --min-confidence 80` if installed; `pip-autoremove` is not safe, skip it.
   - Go: `staticcheck ./...` (U1000) or `go vet`.
   - Java/C#: IDE "unused declaration" inspections are better than anything here; ask the user
     to export them.
   - Ruby: `debride` if installed. PHP: `phpstan` with dead-code rules if configured.
   If none are available, fall back to Grep, as below.

3. **Verify each candidate.** For every orphan file, unused export or function:
   - Grep the symbol and the file stem across the whole repo, including templates, configs,
     CI, Dockerfiles, docs and SQL (`rg -n "<name>" --hidden -g '!node_modules'`).
   - Check dynamic patterns: string-built imports, `getattr`, `require(variable)`,
     reflection, DI containers, routing by file path, plugin registries, cron/job configs.
   - Check public surface: is this a library whose users live outside the repo? If yes, every
     exported symbol is used until a deprecation cycle says otherwise.
   - Check history: `git log -1 --format='%ad %an %s' --date=short -- <file>`. Untouched for
     years and unreferenced is stronger evidence than either alone.

4. **Check dependencies.** For each declared dependency, Grep for its import name. A package
   with no import may still be a CLI tool used in scripts, a plugin loaded by config, a type
   package or a peer dependency; check package.json scripts, config files and CI first.

5. **Check feature flags.** Grep for the flag system in use (LaunchDarkly, Unleash, Flipper,
   a `features.yml`, env vars named `ENABLE_*` / `FEATURE_*`). A flag is stale when it has a
   single value in every environment config you can see, or when the user confirms it has been
   100% on or off in production. Its dead branch is the candidate, not the flag call alone.

6. **Rate confidence.**
   - **High**: no static reference, no dynamic pattern, not public API, untouched for 12+
     months, and (ideally) production logs show no use. Commented-out code is always high:
     git history keeps it.
   - **Medium**: no static reference but the framework could load it by convention, or it
     changed recently.
   - **Low**: referenced only from tests, docs, or by a name too generic to search
     (`utils`, `helpers`, `index`).

7. **Write `rescue/dead-code.md`:**
   ```markdown
   # Dead-code candidates
   Scanned <date> at <sha>. Nothing deleted yet.
   | # | Kind | Location | Confidence | Evidence | Risk if wrong |
   ## Proposed batches
   ### Batch 1 - commented-out code (high, zero runtime risk)
   - files..., expected diff: -N lines
   ### Batch 2 - orphan files, high confidence
   ### Batch 3 - unused dependencies
   ### Not proposed (log only)
   ```

8. **Ask before deleting.** Present batch 1 and wait for an explicit yes naming that batch.
   For an approved batch: create a branch if on the default branch, delete only what the batch
   lists, run the build and the full test suite, and commit with a message listing what was
   removed and the evidence. Then stop and offer the next batch.

## Batch rules

- One kind of deletion per batch, at most about 300 removed lines or 10 files.
- Commented-out code and stale flag branches are separate batches from file deletions.
- Never mix deletion with any other change: no renames, no formatting.
- Dependencies: remove one package per commit, regenerate the lockfile with the project's own
  package manager, run the tests.
- If a deleted item turns out to be used, revert that commit and move the item to
  "Not proposed" with the evidence you missed.

## What NOT to do

- Do not delete, move or rewrite any file without the user approving that exact batch.
- Do not treat "the scanner did not find a reference" as proof. It is a lead.
- Do not remove public API of a published library, database columns, migrations, or
  anything referenced from outside the repo (cron, other services, mobile clients).
- Do not delete tests to make the "unused" list shorter.
- Do not push, open PRs or post comments; leave that to the user.

## Hand-off

Smaller code makes `rescue-characterize` cheaper, so run this before or alongside it on the
hotspot modules. `rescue-plan` reads `rescue/dead-code.md` and schedules approved batches in
the first 30 days.
