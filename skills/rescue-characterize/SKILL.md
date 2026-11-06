---
name: rescue-characterize
description: >-
  Writes characterization ("golden master") tests that pin what a legacy module does today,
  bugs included, before anyone changes it. Uses the repo's existing test framework, finds the
  seams where inputs and outputs can be captured, breaks dependencies with the smallest
  possible change, and records every surprising behaviour instead of fixing it. Use when the
  user says "add tests before I change this", "write characterization tests", "golden master
  this module", "pin the current behaviour", "there are no tests and I need to refactor",
  "safety net for this file", or "lock down how this works".
argument-hint: "<file, module or function to pin>"
---

# rescue-characterize

A characterization test does not ask "is this right?". It asks "what does it do?" and fails
the moment that changes. That is exactly the safety net a legacy rescue needs: once the
current behaviour is pinned, every later refactor can be checked in seconds, and every
intended behaviour change becomes visible in a diff. This skill writes those tests for one
module at a time, using the framework the project already has, and touches production code
only when there is no other way in, with the smallest change that could work.

## Inputs

- `$ARGUMENTS`: the target, e.g. `src/billing/invoice.py`, `OrderService.calculateTotal`.
  If empty, take the top hotspot from `rescue/hotspots.md` and confirm it with the user.
- `rescue/map.md` for the test command. If it is missing, find the test command from CI config
  or the manifest first.

## Output

- New test files next to the project's existing tests, following their naming and layout.
- Golden files (approved outputs) under the test tree, e.g. `tests/golden/<module>/`.
- `rescue/characterization.md`: what is pinned, how, the seams used, and the surprises found.

## Steps

1. **Run the existing suite first.** Use the project's own command. Record pass/fail counts and
   duration. If it is red, stop and tell the user: a safety net on top of red tests is noise.
   Offer to record the failing tests as known failures and carry on only with their consent.

2. **Read the target.** List its public entry points, inputs (arguments, globals, env vars,
   config, files, database rows, clock, randomness, network) and outputs (return values,
   exceptions, writes to DB/files/queues, HTTP calls, logs that someone depends on).

3. **Find the seams.** A seam is a place where behaviour can be observed or replaced without
   editing the code under test. In order of preference:
   1. Pure inputs and return values: just call it.
   2. Existing injection points: constructor or function parameters, config, env vars.
   3. Module-level replacement the language supports: monkeypatch / `unittest.mock.patch`,
      `jest.mock`, Mockito, test doubles registered in a DI container, link-time seams in C.
   4. The boundary: an in-memory or containerised database, a fake HTTP server, a temp dir.
   5. Only if none of these work: a minimal dependency-breaking edit (step 6).

4. **Choose the input set.** Cover each branch you can see, not each input you can imagine:
   - one typical case per public entry point,
   - boundaries (zero, empty, one, max, negative, null/None, unicode, long strings),
   - every error path you can trigger,
   - real-world shapes: if fixtures, seed data or logged requests exist, sample them
     (strip personal data first).
   If coverage tooling is available (`coverage run`, `jest --coverage`, JaCoCo, `go test -cover`),
   use it to find branches you missed. Aim for the branches in the hotspot, not a percentage.

5. **Write the tests in the project's style.** Two shapes:
   - **Assertion tests** for small outputs: the expected value is whatever the code returns
     now. Write it by running the code, never by reasoning about what it "should" return.
   - **Golden master** for large or structured outputs: run the target over the input set,
     serialise output deterministically (sorted keys, fixed float format, normalised line
     endings), store it as an approved file, and assert future runs match byte for byte.
     Provide an explicit, documented way to re-approve (an env var such as
     `UPDATE_GOLDEN=1`), never automatic.
   Freeze non-determinism: fixed clock, seeded random, stable ordering, fake IDs. Name tests
   after behaviour: `test_invoice_total_rounds_half_down_for_eu_customers`.

6. **Break dependencies minimally, only if step 3 failed.** Allowed edits, one at a time, each
   behaviour-preserving and committed separately before the tests that need it:
   - *Parameterise*: add an optional parameter defaulting to the current hard-coded value.
   - *Extract and override*: move the hard call (clock, HTTP, DB) into its own method or
     function that a test can replace.
   - *Wrap a global or singleton* behind a getter the test can swap.
   - *Introduce an interface* in a static language, implemented by the existing class.
   Show the user the diff of each such edit before applying it. Never change logic.

7. **Prove the net catches things.** Make three deliberate small mutations to the target
   (flip a comparison, change a constant, drop a branch), run the new tests, confirm each one
   fails, then revert every mutation and confirm the tree is clean (`git diff` shows only the
   new tests and approved seam edits). If a mutation survives, add the missing case.

8. **Run the full suite twice.** Both runs green and identical; a flaky characterization test
   is worse than none. Note the added run time.

9. **Write `rescue/characterization.md`:**
   ```markdown
   ## <module> - pinned <date>
   Tests: `<paths>` (<n> tests, <seconds>s). Golden files: `<path>`. Re-approve: `<command>`.
   Seams used: <list>. Production edits for testability: <none | commit sha + one line each>.
   Mutation check: <3/3 caught>.
   ### Surprising behaviour pinned as-is
   - <input> returns <output>; probably a bug because <reason>. Pinned by `<test name>`.
   ### Not covered
   - <paths you could not reach and why>
   ```

## Decision rules

- Current behaviour wins. If the code returns a wrong total, the test expects the wrong total
  and is named so the bug is obvious (`..._known_bug_double_discount`). Fixing it is a
  separate, later change with its own test update.
- Prefer the narrowest public entry point that covers the hotspot over testing private helpers.
- If the module needs a real database to be meaningful, use the project's existing test DB
  setup; if there is none, propose one (SQLite or a container) and ask before adding it.
- Stop at the hotspot's boundary. Pinning the whole system in one pass never finishes.

## What NOT to do

- Do not fix bugs, rename, reformat or refactor production code in this skill.
- Do not add a new test framework when one exists; do not upgrade the existing one.
- Do not write expected values by hand from reading the code; capture them by running it.
- Do not hit real external services, production data or paid APIs from tests.
- Do not commit personal data in golden files.
- Do not delete or weaken existing tests.

## Hand-off

With the module pinned, run `rescue-refactor` for small behaviour-preserving steps, or
`rescue-strangler` if the module is to be replaced. To keep production code untouched, you
can delegate the test writing to the `safety-net-builder` agent. `rescue-plan` reads
`rescue/characterization.md` to track which hotspots are covered.
