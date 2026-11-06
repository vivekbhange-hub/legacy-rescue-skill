---
name: rescue-plan
description: >-
  Compiles everything the other rescue skills found (map, hotspots, dead code,
  characterization coverage, dependency path, migration plans, refactor log) into one
  rescue/PLAN.md: a 30/60/90-day rescue plan with owners to fill in, exit criteria per phase,
  a risk register, and a one-page summary for a manager. Every item links back to its
  evidence. Use when the user says "write the rescue plan", "put it all together", "what do
  we do in the first 90 days", "plan for this legacy system", "give me a risk register",
  "summarise the rescue for my manager", or "what is the roadmap for this codebase".
argument-hint: "[focus, e.g. \"security first\" or \"team of 2\"]"
---

# rescue-plan

The other skills each answer one question. This one turns the answers into a plan a team can
run on Monday: what to do in the first 30, 60 and 90 days, in what order, how each phase is
known to be done, and what could go wrong. It invents nothing. Every item traces to a file in
`rescue/`, and anything the evidence does not cover is listed as a gap rather than guessed.

## Inputs

Read whichever exist; note which are missing:

| File | From | Used for |
|------|------|----------|
| `rescue/map.md` | rescue-map | system summary, commands, critical paths, unknowns |
| `rescue/hotspots.md` | rescue-hotspots | what to protect first, coupling, knowledge risk |
| `rescue/dead-code.md` | rescue-dead-code | deletion batches |
| `rescue/characterization.md` | rescue-characterize | which hotspots are pinned |
| `rescue/deps.md` | rescue-deps | upgrade steps and runtime deadlines |
| `rescue/strangler-*.md` | rescue-strangler | migration milestones and risks |
| `rescue/refactor-log.md` | rescue-refactor | progress so far |

Plus `$ARGUMENTS` and anything the user says about team size, deadlines, freeze periods and
business priorities.

## Output

- `rescue/PLAN.md`.

## Steps

1. **Check the evidence.** List which inputs exist. If `map.md` or `hotspots.md` is missing,
   tell the user the plan will be thin and offer to run `rescue-map` / `rescue-hotspots` first.
   Continue only if they agree to a partial plan; mark it "partial" in the title.

2. **Ask for the constraints** you cannot read from the repo, in one message, with defaults:
   team size (default 2 engineers part-time on the rescue), hard deadlines (runtime end of
   life, contract dates), change freezes, the one business flow that must never break. Use the
   defaults if the user does not answer and say so in the plan.

3. **Collect candidate work items** from the inputs. Each item gets: a one-line description,
   the source file and line in `rescue/`, size (S under a day, M up to a week, L over a week),
   risk (low, medium, high) and dependencies on other items.

4. **Sequence by the rescue principle**: understand, then protect, then change.
   - **Days 1-30, Stabilise and see.** Reproducible build and lockfiles, CI running the
     existing tests, characterization tests on the top 3 to 5 hotspots on critical paths,
     zero-risk deletions (commented-out code), patch-level dependency batch, basic error
     monitoring if none exists, walkthroughs with single-author file owners.
   - **Days 31-60, Make change cheap.** More characterization coverage, refactor loops on the
     pinned hotspots, minor dependency batches, dev tooling upgrades, orphan file deletion
     batches, first strangler milestones (seam and facade).
   - **Days 61-90, Move.** Runtime and framework majors one at a time, strangler slices
     cut over, decoupling the worst change-coupling pairs, removal of temporary flags.
   Hard deadlines override the sequence: an end-of-life runtime with a near date moves up,
   with characterization of its blast radius first.

5. **Fit to capacity.** Estimate total size per phase against the team's time. If it does not
   fit, cut from the end of each phase and move it to "Later". Say what was cut.

6. **Write exit criteria per phase** that can be checked, e.g. "top 5 hotspots have
   characterization tests that catch 3 out of 3 mutations", "CI green on every merge for two
   weeks", "zero dependencies with known critical vulnerabilities". No vague criteria like
   "code is cleaner".

7. **Build the risk register** from: map risks and unknowns, hotspot knowledge risk and
   coupling, dependency high-risk steps and end-of-life dates, strangler risks, and gaps in
   test coverage. For each risk: likelihood (L/M/H), impact (L/M/H), early warning signal,
   mitigation already in the plan (item number) and owner (blank for the user to fill).
   Order by likelihood x impact.

8. **Write `rescue/PLAN.md`** with the template below. Then give the user the one-page summary
   in chat and the three decisions they need to make.

## Template

```markdown
# Rescue plan: <system> - <date>
Status: <complete | partial: missing X>. Built from: <list of rescue/ files>.
Assumptions: <team, deadlines, freezes; marked "default" where the user did not say>.

## One-page summary
- What this system is: <one sentence>
- Biggest risks: <three bullets>
- What the next 90 days buy: <three bullets of outcomes>
- Decisions needed: <three bullets>

## Principles for this rescue
Understand before changing. Pin behaviour before refactoring. Small, reversible steps.

## Days 1-30: Stabilise and see
| # | Item | Size | Risk | Depends on | Evidence | Owner |
Exit criteria: ...

## Days 31-60: Make change cheap
(same table) Exit criteria: ...

## Days 61-90: Move
(same table) Exit criteria: ...

## Later
## Risk register
| # | Risk | Likelihood | Impact | Early signal | Mitigation (item) | Owner |
## Gaps in the evidence
## How to update this plan
Rerun rescue-hotspots monthly and rescue-plan after each phase.
```

## Decision rules

- An item without a source in `rescue/` does not go in the plan; it goes in "Gaps".
- Nothing that changes production behaviour is scheduled before its area is characterized.
- No phase holds more than one high-risk migration step at a time.
- Owners are left blank; do not assign people.

## What NOT to do

- Do not run any other skill silently; offer it and let the user choose.
- Do not promise dates beyond the 90 days or estimate in hours.
- Do not soften findings in the summary; a manager reading only that page must see the
  real top risks.
- Do not send, post or share the plan anywhere. It is a local file.

## Hand-off

This is the last skill in the pack. After each phase, rerun `rescue-hotspots` to see whether
risk moved, update `rescue/characterization.md` and `rescue/refactor-log.md`, and rerun
`rescue-plan` to roll the plan forward.
