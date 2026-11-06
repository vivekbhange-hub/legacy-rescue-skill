---
name: rescue-strangler
description: >-
  Plans an incremental replacement of a legacy component instead of a big-bang rewrite, using
  strangler fig routing, branch by abstraction or parallel run, with milestones that each ship
  to production on their own and can each be rolled back. Finds the interception point in the
  real code, defines how old and new are compared, and writes rescue/strangler-<name>.md.
  Use when the user says "we want to rewrite this", "migrate off this framework", "replace
  this module", "strangler fig", "move this to a new service", "how do we migrate without
  downtime", or "branch by abstraction".
argument-hint: "<component to replace> [target, e.g. \"new pricing service\"]"
---

# rescue-strangler

Rewrites from scratch fail in a familiar way: two years in, the new system still lacks the
edge cases the old one learned the hard way, and the old one kept changing underneath. The
alternative is to grow the new thing around the old one, move traffic over a slice at a time,
and delete the old code only when nothing calls it. This skill produces that plan for one
component, grounded in the actual call sites, with every milestone shippable and reversible.

## Inputs

- `$ARGUMENTS`: the component to replace (file, module, endpoint group, table, library) and
  the target if known.
- `rescue/map.md`, `rescue/hotspots.md`, `rescue/characterization.md` if present.
- Constraints from the user: deadline, freeze windows, team size, whether two versions can
  run side by side, data ownership.

## Output

- `rescue/strangler-<component>.md`: the migration plan.
- No code changes. Implementation happens milestone by milestone through `rescue-refactor`
  and normal feature work.

## Steps

1. **Draw the current boundary.** Find every caller of the component: Grep for imports,
   class or function names, endpoint paths, table names, queue names. Group callers by entry
   point. Count them; this is the surface the migration has to cover. Note callers outside the
   repo (other services, mobile apps, cron, reports) from config and docs, and ask the user
   about ones you cannot see.

2. **Choose the pattern** with these rules:
   - **Strangler fig (routing)**: the component sits behind a protocol you can intercept
     (HTTP routes, RPC, message topics, CLI commands). Put a facade or proxy in front and route
     slice by slice (per endpoint, per tenant, per percentage).
   - **Branch by abstraction**: the component is called in-process. Introduce an interface at
     the call sites, implement it with the old code, add the new implementation behind a flag,
     switch callers over, then delete the old implementation.
   - **Parallel run (shadow)**: correctness is critical and outputs are comparable (pricing,
     tax, permissions, reports). Call both, serve the old result, log differences, switch only
     when the diff rate is at an agreed threshold.
   - **Expand / contract for data**: the change involves schema or storage. Add new structure,
     write to both, backfill, read from new, stop writing old, drop old. Each phase is its own
     deploy.
   Patterns combine; most plans use one routing pattern plus expand/contract for data.

3. **Find the interception point** in the code: the single place (or fewest places) where a
   switch can choose old or new. Cite file:line. If there is no single place, milestone 1 is
   creating one (a facade or interface) as a pure refactor under characterization tests.

4. **Define equivalence.** How will anyone know new behaves like old? Options: the existing
   characterization tests run against both implementations; a shadow comparison on live
   traffic with a diff log; reconciliation queries for data. Name which fields may differ
   (timestamps, IDs, ordering) and which must match exactly.

5. **Cut milestones.** Each milestone must:
   - ship to production on its own and leave the system working if the project stops there,
   - have a switch (flag, route config, env var) that rolls it back without a deploy where
     possible, otherwise a single revert commit,
   - have an exit check: a metric, a diff rate, a test suite, a count of remaining callers,
   - take days to a couple of weeks, not months.
   Typical sequence: seam and characterization; facade with old implementation only; new
   implementation for the smallest slice, dark or shadowed; slice by slice cut-over;
   remove the flag; delete the old code; remove the facade if it is no longer useful.

6. **Plan the data.** If both versions need the same data, decide the single owner per
   phase, the sync direction, and the backfill method. Never let both write the same record
   without a declared winner.

7. **List risks** with likelihood, impact, early signal and response. Always consider: hidden
   callers, behaviour the old code had that nobody documented, performance of the facade,
   doubled infrastructure cost during parallel run, the migration stalling halfway (plan
   says what a stable half-migrated state looks like).

8. **Write the plan:**
   ```markdown
   # Replacing <component> - plan <date>
   ## Why and what done looks like
   ## Current surface
   | Caller | Kind | File | In repo? |
   ## Pattern and interception point
   ## Equivalence check
   ## Milestones
   | # | Ships | Switch / rollback | Exit check | Est. size |
   ## Data plan
   ## Risks
   | Risk | Likelihood | Impact | Early signal | Response |
   ## Stopping safely
   <what the system looks like if work stops after each milestone>
   ```

## Decision rules

- If the component has no characterization tests, milestone 1 is `rescue-characterize`.
- If the honest estimate for a milestone is over a month, split it.
- If the old and new cannot run side by side at all, say so plainly and plan the shortest
  possible cut-over with a rehearsed rollback, rather than pretending it is incremental.
- Deleting the old code is a milestone with its own exit check, not a footnote.

## What NOT to do

- Do not write the new implementation in this skill.
- Do not plan a cut-over that has no rollback, and do not hide it if one is impossible.
- Do not propose a new framework or language unless the user asked; the plan is about how to
  move, not what to move to.
- Do not leave a flag or facade in place forever; every temporary thing gets a removal step.

## Hand-off

Milestones that restructure code are executed with `rescue-refactor`, one step at a time.
Dependency replacements found by `rescue-deps` can be planned here. `rescue-plan` places the
milestones on the 30/60/90-day plan and copies the risks into the risk register.
