# TASK: FBS direct player-prop baseline (independent of Phase 4/5)

Worktree `/root/lp-fbs-props`, branch `research/fbs-direct-props-2026-10-20` (forked from
`origin/feat/fbs-phase5-2026-10-19` @ `4d3fc4ae`). Research only. Do not merge to `dev`,
do not touch production code, do not run npm/npx/yarn.

## Why this exists

The six-phase brief puts player props behind a validated play-by-play simulator (Phases 4
and 5, both currently NOT_ADOPTED / not started). That sequencing is being relaxed: the
archive already contains play-level history and player game logs, so a **direct**
player-distribution track can be prototyped now without claiming Phases 4–6 are complete.

This is a new parallel track. It must not pretend to be a simulator output, and it must not
change the status of Phases 4/5/6.

## Read first

- `research/fbs/AUDIT-FBS-BASELINE-20261017.md` (six-phase brief) — if absent here, read via
  `git show origin/feat/fbs-archive:research/fbs/AUDIT-FBS-BASELINE-20261017.md`.
- The Phase 4b result and this branch's Phase 5 work, plus `docs/LEARNINGS-fbs.md`.

## Goal

A direct, two-stage count model for four markets, each validated separately:

1. passing attempts
2. passing yards
3. rushing carries
4. rushing yards

Stage 1 is **usage** (attempts / carries): per-player per-game count distribution from
historical logs, with team and opponent context, shrinkage toward the player's own
multi-game rate, and an explicit statement of how players with little history are handled.
Stage 2 is **efficiency** (yards per attempt / per carry): a rate distribution, then the
product distribution for yards. State clearly whether stage 2 is modelled jointly or by
simulation, and why.

Scoring per market, out of sample (tune on earlier weeks/seasons, score later ones):
log score / CRPS, PIT summary, 50/80/90% interval coverage, threshold probabilities and
Brier at realistic lines (e.g. passing attempts 34.5, passing yards 249.5, carries 14.5,
rushing yards 59.5), and the share of observed values beyond the 99th percentile.

Baselines each market must beat: the player's trailing-5-game mean with a fixed spread, and
a position-level league distribution. A model that cannot beat the trailing mean is not a
model.

## Data honesty

Establish coverage before modelling: which seasons, teams, weeks are present; how many
player-games per market; whether the archive's play-level data reconciles to the box-score
player logs for a sample of games. Report the coverage table in RESULTS.md. If a market
cannot be supported, mark it `INSUFFICIENT_DATA` and stop that market — do not substitute a
different population.

## Deliverables

- `research/fbs/direct-props-2026-10-20/` — entry-point script reproducing every number,
  frozen per-player-game predictions for the winning variant of each market, and the
  coverage table.
- `research/fbs/direct-props-2026-10-20/RESULTS.md` — per-market verdict
  (`ADOPT_CANDIDATE` / `INCONCLUSIVE` / `NOT_ADOPTED` / `INSUFFICIENT_DATA`), scoring tables,
  the baselines compared, and the explicit note that Phases 4–6 status is unchanged.
- Nothing outside that directory.

## Completion — before you stop, in this order

1. `git status --short` — note which files are yours vs already dirty.
2. `git add` explicit paths only. NEVER `git add .`.
3. Commit: message states the verdict per market and the load-bearing numbers.
4. `git push -u origin research/fbs-direct-props-2026-10-20` — paste the output.
5. `git ls-remote origin research/fbs-direct-props-2026-10-20` — confirm it matches local
   `git rev-parse --short HEAD`.
6. Any failed step: say so plainly. Done = committed AND pushed.

Report: per-market verdicts, numbers, commit SHA, pushed or not, and what you could not measure.
