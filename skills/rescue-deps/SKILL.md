---
name: rescue-deps
description: >-
  Audits a legacy project's runtimes, frameworks and packages: what is outdated, abandoned or
  past end of life, and in what order to upgrade with the risk of each step. Uses the
  ecosystem's own commands (npm outdated, pip list --outdated, mvn versions, go list -u,
  bundle outdated, composer outdated, dotnet list package --outdated), turns the output into a
  risk-rated path, and lists the breaking changes to check per step. Writes rescue/deps.md.
  Use when the user says "how outdated are our dependencies", "plan the upgrade", "are we on
  an end-of-life runtime", "upgrade Node/Python/Java", "dependency audit", or "what breaks if
  we upgrade".
argument-hint: "[path, default .]"
---

# rescue-deps

An old dependency tree is a slow-moving incident: security fixes you cannot take, a runtime
the host will drop, a framework nobody can hire for. Upgrading everything at once is how
rescues fail. This skill takes stock of what the project runs on, rates each gap, and lays out
an upgrade path where every step is small, tested by the characterization suite and revertible
on its own. It reads and plans; it changes nothing until the user approves a step.

## Inputs

- `$ARGUMENTS`: project path, default `.`.
- `rescue/map.md` for the list of deployables and manifests, if present.
- The production runtime version if the user knows it (Dockerfile base image, buildpack,
  `.nvmrc`, `.python-version`, `runtime.txt`, `global.json`, CI matrix).

## Output

- `rescue/deps.md`: runtime table, upgrade path with risk per step, breaking-change checklist.
- `rescue/deps-*.json`: raw tool output kept as evidence.

## Steps

1. **Find every manifest and lockfile.** Glob for package.json, requirements*.txt,
   pyproject.toml, Pipfile, go.mod, pom.xml, build.gradle*, Gemfile, composer.json, *.csproj,
   Cargo.toml, mix.exs. Note which have lockfiles. A manifest without a lockfile means
   builds are not reproducible: that is risk number one.

2. **Pin the runtimes.** Record the declared runtime for each deployable and where it is
   declared (Dockerfile `FROM`, engines field, `.nvmrc`, `python_requires`, `<java.version>`,
   `go` directive, `TargetFramework`, CI matrix). Mismatches between local, CI and production
   are findings. Compare against end-of-life dates you know; state the date of your knowledge
   and tell the user to confirm on endoflife.date before deciding.

3. **Ask the package manager what is outdated.** Only read-only commands, and only if the
   tool is installed and dependencies are already installed (do not run installs without asking):
   - npm: `npm outdated --json > rescue/deps-npm.json` (non-zero exit is normal when outdated).
     Yarn: `yarn outdated --json`; pnpm: `pnpm outdated --format json`.
   - pip: `pip list --outdated --format=json > rescue/deps-pip.json` inside the project's venv.
   - Composer: `composer outdated --direct --format=json > rescue/deps-composer.json`.
   - Bundler: `bundle outdated --parseable`; Maven: `mvn versions:display-dependency-updates`;
     Gradle: the versions plugin if configured; Go: `go list -m -u all`;
     .NET: `dotnet list package --outdated`; Cargo: `cargo outdated` if installed.
   Convert the last group to a CSV with columns `name,current,latest,ecosystem`.
   Security advisories: `npm audit --json`, `pip-audit`, `bundle audit`, `dotnet list package
   --vulnerable`, if available. Note that these call the network; ask first if the user is
   offline or in a restricted environment.

4. **Build the path.**
   ```
   python3 "${CLAUDE_SKILL_DIR}/outdated_report.py" --npm rescue/deps-npm.json --pip rescue/deps-pip.json --output rescue/deps-path.md
   ```
   It rates each package: patch = low, minor = medium, major = high, any change below 1.0 =
   high, unparseable = unknown, and orders steps: one batch of patches, minor upgrades as a
   batch per ecosystem, then every major jump as its own step, dev tooling before runtime
   libraries, smallest jumps first. Add `--csv other.csv` for other ecosystems.

5. **Spot abandoned packages.** For the high-risk and runtime-critical packages, check the
   last release date where the tool shows it, or ask the user to check the registry page.
   Signals: no release in 2+ years, archived repository, deprecation notice in `npm view
   <pkg> deprecated`, a named successor. Abandoned packages get a "replace" step, not an
   "upgrade" step, and usually belong in `rescue-strangler`.

6. **Order the work across layers.** General order, adjust to the evidence:
   1. Lockfile and reproducible build (if missing).
   2. Test and build tooling (dev dependencies) so the safety net runs on current tools.
   3. Patch and minor batches.
   4. Runtime upgrade to the next supported LTS, one major at a time.
   5. Framework majors, one at a time, following the framework's official upgrade guide.
   6. Remaining library majors, one per step.
   A framework major usually needs a runtime floor; place the runtime step before it.

7. **Write the breaking-change checklist** for every high-risk step: the official changelog or
   migration guide to read (name it; do not paste it), the APIs from it that this repo
   actually uses (Grep for them and cite file:line), and the characterization tests that cover
   those call sites. A step with no covering tests gets "characterize first" as its first task.

8. **Write `rescue/deps.md`:**
   ```markdown
   # Dependencies and runtimes - <date>
   ## Runtimes
   | Deployable | Runtime | Declared in | Production | Support status (verify) |
   ## Summary
   <n outdated: high / medium / low / unknown; vulnerabilities by severity; abandoned packages>
   ## Upgrade path
   | Step | Change | Risk | Covered by tests? | Breaking changes to check | Rollback |
   ## Abandoned or replace-instead
   ## Not upgrading (and why)
   ```

9. **Execute only on request.** If the user approves a step: branch, apply only that step with
   the package manager, regenerate the lockfile, run the build and full test suite, commit with
   the step number in the message, stop. One step per commit.

## What NOT to do

- Do not run `npm update`, `pip install -U`, `npm audit fix --force` or any bulk upgrade.
- Do not upgrade the runtime and a framework in the same step.
- Do not state end-of-life dates as fact without telling the user to verify them.
- Do not remove a lockfile or switch package managers as a side effect.
- Do not upgrade anything on the critical path that has no characterization tests yet.

## Hand-off

High-risk steps without coverage go to `rescue-characterize` first. Packages to replace go to
`rescue-strangler`. `rescue-plan` places the steps on the 30/60/90-day plan. For a second
opinion on a large tree, delegate to the `upgrade-planner` agent.
