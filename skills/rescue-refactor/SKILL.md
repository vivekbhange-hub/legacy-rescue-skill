---
name: rescue-refactor
description: >-
  Changes legacy code one small, behaviour-preserving step at a time inside a strict loop:
  tests green before, one named refactoring, tests green after, commit, repeat. Refuses to
  start without a safety net, never mixes refactoring with behaviour changes, and stops at
  the first red test to revert rather than debug forward. Keeps a log in
  rescue/refactor-log.md. Use when the user says "refactor this safely", "clean up this
  function", "break up this god class", "untangle this module", "make this readable without
  breaking it", "extract this into a service", or "simplify this mess".
argument-hint: "<file or function> [goal, e.g. \"split pricing out of OrderController\"]"
---

# rescue-refactor

Refactoring legacy code fails when steps are big: three changes at once, a red test, an
afternoon of debugging, and nobody can tell which change broke what. This skill does the
opposite. Each step is one named refactoring (extract function, rename, move, inline,
introduce parameter) small enough to review in a minute and revert in a second. Tests run
before and after every step. Behaviour does not change; if it must, that is a separate,
explicit commit outside this loop.

## Inputs

- `$ARGUMENTS`: the target and the goal.
- `rescue/characterization.md`: which tests pin the target. If the target is not listed and
  has no meaningful existing tests, stop and run `rescue-characterize` first.
- The test command from `rescue/map.md` or CI config. Prefer the fastest command that runs
  the pinning tests (a single file or tag), and the full suite at the end of the session.

## Output

- A series of small commits on a branch, one refactoring each.
- `rescue/refactor-log.md`: one line per step with result.

## Before the loop

1. **Branch.** If on the default branch, create `rescue/refactor-<target>`. Confirm the working
   tree is clean (`git status --short`); if not, ask the user to commit or stash.
2. **Baseline.** Run the pinning tests and record the result and duration. Red baseline: stop.
3. **Plan the route.** Write a numbered list of 3 to 10 named steps from the current code to
   the goal, e.g. "1. Extract `applyDiscounts` from `total` (lines 40-88). 2. Move
   `applyDiscounts` to `pricing/discounts.js`. 3. Replace the `type` switch in `rate()` with a
   lookup table." Show the route to the user and adjust if they object. The route can change
   as you learn; the step size cannot.

## The loop (one step per pass)

1. **Name the step.** Use a known refactoring name (Fowler's catalogue or the language's IDE
   name) and say exactly which code it touches.
2. **Make only that change.** Keep the diff small: as a guide, under about 50 changed lines
   and one concern. Mechanical changes across many files (a rename) are fine if they are a
   single refactoring.
3. **Run the pinning tests.** Then the type checker or compiler and linter if the project has
   them.
4. **Green:** commit with message `refactor(<area>): <refactoring name> - <what>` and add a line
   to the log. Go to the next step.
5. **Red:** revert the step at once (`git checkout -- <files>` or `git restore`). Do not debug
   forward. Then make the step smaller (split it in two) and try again. After two failed
   attempts at the same step, stop and report what you learned to the user.
6. **Every 3 to 5 steps,** run the full test suite, not just the pinning tests.

## Rules for behaviour-preserving

- Same inputs, same outputs, same side effects, same exceptions, same order of writes. A
  refactoring that "fixes" a bug is a behaviour change.
- Keep public signatures stable. When one must change, add the new one, delegate the old one
  to it, migrate callers in later steps, and delete the old one last.
- Moving code between files counts as a step on its own; do not edit it in the same step.
- Performance-sensitive paths (loops over large data, queries): do not change the number of
  database calls or network calls as part of a refactoring.
- If a test needs to change for a refactoring to pass, the refactoring changed behaviour or the
  test was coupled to implementation. Stop and ask the user which.

## When a behaviour change is really needed

Leave the loop. Write the change as its own commit with message `fix:` or `feat:`, update the
characterization test that pinned the old behaviour in the same commit, and say in the commit
body which pinned behaviour changed and why. Then return to the loop.

## Log format (rescue/refactor-log.md)

```markdown
## <target> - <date> - branch rescue/refactor-<target>
Goal: <goal>. Pinning tests: `<command>` (<n> tests, baseline green, <s>s).
| # | Refactoring | Files | Result | Commit |
|---|-------------|-------|--------|--------|
| 1 | Extract Function `applyDiscounts` | orders/total.js | green | abc1234 |
| 2 | Move Function to pricing/discounts.js | 2 files | red, reverted, split | - |
Full suite at end: <pass/fail counts>. Remaining route: <steps not done>.
```

## Stopping

Stop when the goal is reached, when the user says so, or after two failed attempts at a step.
At the end: run the full suite, summarise what changed in plain words, list the commits, and
remind the user that nothing has been pushed.

## What NOT to do

- Do not start without a green baseline of tests that cover the target.
- Do not combine refactorings, or a refactoring and a fix, in one commit.
- Do not reformat whole files; formatting noise hides real changes. If the project has an
  auto-formatter, run it as its own commit before the loop.
- Do not edit or delete characterization tests to make a step pass.
- Do not push, merge, or open a pull request; draft the PR description if asked and let the
  user open it.

## Hand-off

Work that needs a new implementation side by side with the old belongs to
`rescue-strangler`. When the session ends, `rescue-plan` can read `rescue/refactor-log.md`
to update progress on the 30/60/90-day plan.
