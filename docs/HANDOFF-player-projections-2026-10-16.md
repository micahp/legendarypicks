# Handoff: NFL player projections, 2026-10-16

For the next session on this workstream. Read `docs/RESULTS-nfl-prop-baseline-2026-10-16.md` and
`docs/RESULTS-nfl-marcel-and-calibration-2026-10-16.md` next; this file only says where things are, what is
settled, and what is not.

## Where the work lives

- Branch `scratch/spec-b-rebase`, worktree `/root/lp-player-proj`, tip `86db0743`, **pushed**. Not merged, and
  nothing is served from it.
- Two docs already on `dev` and pushed: `docs/model-cards/nfl.md` (the player-projection section, the ordered
  next steps, the gap-to-market axis, the competitor marker, and the two v2s named) and
  `docs/CONTEXT-2026-10-16.md` (a section for this work, the dev DB changes, and three process notes).
- The database work is on the shared dev DB `picks.dev.db`, additively: 14 back-seasons of NFL per-game logs
  (2010 to 2023, 248,485 rows), a new `nfl_player_birth_dates` table, and 14 provenance rows in
  `nfl_hist_loads`. Growth was +134 MB. Nothing was deleted or updated, and `players` was not altered.
- The script list and the exact reproduce commands are at the end of the calibration results doc.

## The state in one line

v2 plus a forward-only Platt map scores 0.2488 against the market's 0.2460 on 33,519 graded 2026 prop items, and
the increment over the market is **not established**. On the passing markets it is negative.

## Established, with the numbers

1. **The served baseline is bad.** `analytics/projections.prob_over` scores Brier 0.3082 against the market's
   0.2463 on the 14,431 items it can serve, which is worse than a constant 0.5 (0.2500), and it serves nothing
   before week 4 because `project_stat` returns `None` below three games. 19,088 of 33,519 items (57%) have no
   live number at all.
2. **Calibration is nearly the whole measured gap and needs no new data.** A two-parameter logistic
   recalibration takes v2 from 0.2747 to 0.2488. Forward-only, fitted on earlier weeks only, it holds the same
   0.2488, so it is not look-ahead. Murphy decomposition: reliability 0.0260 to 0.0007, resolution barely moves
   (0.0016 to 0.0019 against the market's 0.0034). The gain is the removal of false confidence, not information.
3. **Full Marcel is not an upgrade.** Every added season makes the point estimate worse, monotonically
   (receiving yards MAE 19.494 at window 0 to 20.013 at window 5). Regression to the position mean is the only
   component that pays. The naive aging curve hurts. For the *probability* history helps a lot, 0.3064 to
   0.2658, and the first prior season is worth 0.0378 of that 0.0406.
4. **Discrimination is poor.** AUC 0.5241 against the market's 0.5619.
5. **The increment over the market is not established.** Forward-only stack of market log-odds plus ours:
   log loss +0.00153 clustered [-0.00092, +0.00380], Brier +0.00070 [-0.00049, +0.00182].
6. **Pass attempts, the one targeted change.** `K_T` 4.0 beats the fitted 8.0 directionally on MAE and on
   discrimination in every comparison including held-out 2026, but paired and clustered the market deltas span
   zero, and the increment is negative either way.

## Withdrawn during this session, do not re-assert

Four claims were made here and then retracted on better evidence. Each is recorded in the results doc.

- **"Calibration costs ranking power."** Withdrawn: the AUCs compared different samples. On identical items the
  refit-minus-raw AUC is -0.00813 [-0.02220, +0.00423]. Also, within a week Platt is monotone, so it cannot
  reorder anything; only the pooled figure can move, through the between-week slopes.
- **"The passing markets rank players backwards."** Withdrawn: with clustered intervals ours spans 0.5 on
  passing yards, completions and attempts. The defensible statement is that ours is consistent with no
  discrimination while the market's is not, and the market's completions interval also includes 0.5.
- **"The fitted `K_T` 8.0 is not even MAE-optimal."** Withdrawn: a regime mismatch. Over all weeks it is not,
  but restricted to weeks 2 to 5 it **is** the MAE optimum, 6.563 against 6.565.
- **"A 6.7% attempt volume bias."** Withdrawn as a model defect. In the fit seasons restricted to the same
  weeks, the level is unbiased, ratio 1.0031. The 2026 shortfall is a season-specific level shift, and a
  correction fitted on the fit seasons does not transfer.

## Three traps this session hit. Read before measuring anything here.

1. **Sample mismatch.** Two numbers compared on different populations. Before writing a comparison down, state
   the population both sides were measured on.
2. **Regime mismatch.** Fitting on all weeks and evaluating on weeks 2 to 5. Props exist only in the early-week
   regime, where shrinkage binds hardest, so a fit over all weeks selects for a regime nobody evaluates.
3. **A population selected on the outcome.** `grade_nfl_prop_probabilities.py` keeps the quarterback who led his
   team in attempts **in the finished game**. The pregame rebuild is `pregame_leader` in
   `audit_nfl_passing_projections.py`, and it should replace that filter.

## Open decisions, all Micah's

1. **Serve the forward Platt map?** Largest measured win available and no new data. Constraints: refit weekly on
   the weeks so far, and serve the raw number in week 1, where there is nothing to fit on (24% of items).
2. **Adopt `K_T` 4.0 for attempts?** Free on MAE and directionally consistent, but not established. The level
   correction is dropped and should stay dropped.
3. **Fix the passing grader's population?** Independent of everything else and every passing number quoted
   before it is from a population selected on the outcome.
4. **Merge decision for `scratch/spec-b-rebase`?** Unchanged from `docs/STATUS-spec-b-2026-10-12.md`: merging
   lets the installed availability timer's snap ingest create `nfl_snap_team_sources` on PROD.

## The next concrete step

The passing markets fail the increment test, so more tuning there is not the path. The narrow target is a
feature that moves the increment on a market where the market is beatable, and it is judged by the **two gates**
in section 4 of the calibration doc: against the incumbent with a paired clustered interval, and separately
against the market-only model. A larger stack coefficient is not evidence on its own, and neither is a lower
standalone Brier.

**Unused assets worth knowing about**, all already on the dev DB: snap counts 2013 to 2025
(`nfl_hist_snap_counts`), injuries 2009 to 2025 (`nfl_hist_injuries`), depth charts 2010 to 2024, participation
2016 to 2025, availability 67,179 rows, and play-by-play 2010 to 2026 (751,148 rows) whose play-level surface
has barely been touched. Snaps and availability are the obvious next features, with the caveat that the market
sees playing-time and injury information too, so the opportunity is modelling their effects better rather than
assuming the information is exclusive.

## Stranded session

`claude:8bd6a60c-fc96-4771-ad0d-1c1b0f68bec7` is rate limited on its monthly spend limit, last active about 12
hours before this handoff. Its player-projection work is **superseded** by this session: the passing audit it
was mid-way through when it stopped is done, and its earlier committed work (the baseline grader, the
NFL-DATA-INVENTORY section) is on `dev`. No need to resume it for this workstream.
