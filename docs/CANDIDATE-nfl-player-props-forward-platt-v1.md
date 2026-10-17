# NFL player props: Forward Platt v1 candidate and stopping gate

Status: **research candidate, not deployed**. Branch: `feat/nfl-props-forward-platt-candidate` (based on `scratch/spec-b-rebase`, after commit `86db074`). Date: 2026-10-17.

## Decision

Freeze **v2 raw player-stat generator + pooled, two-parameter forward-only Platt** as a named *experimental candidate*: `nfl-player-props-v2-forward-platt-v1`. Do **not** silently make it the default or claim it sees information the market does not.

Our objective is an independent **forecast distribution** that captures what the market may miss. Forward Platt is a calibration layer on `P(stat > line)`; it is **not** a new player opportunity/efficiency model and alone cannot inject matchup information absent from v2. A fitted monotone map preserves ranking within its fitted week. It may improve probabilistic honesty; it cannot invent incremental signal.

The work is eligible for a research stopping point **once the reproducible tests below run on the development DB and the outcomes are recorded, even if the answer is negative**. Promotion to an active model is a separate decision.

## Already measured (previous, non-strict retrospective population)

See `RESULTS-nfl-marcel-and-calibration-2026-10-16.md`, through `86db074`:

- v2 raw Brier: 0.2779; forward v2 + Platt: 0.2488 on weeks 3–5; independent market: around 0.2462 on the comparable forward sample. Confirm item inclusion before asserting exact equivalence of those figures; separate ladders use different counts.
- Forward market-plus-v2 stack versus forward market-only: Brier improvement about +0.00070 with clustered interval [-0.00049,+0.00182]; log-loss improvement +0.00153 [-0.00092,+0.00380]. **Neither is established.**
- Pass-attempt `K_T=4` refit improves incumbent point estimates but its clustered intervals overlap zero; market increment is negative even with the refit.
- `grade_nfl_prop_probabilities.py` previously selected the QB from **the completed game's attempts**. `collect()` selected each side's latest odds with **no cutoff relative to kickoff**. These invalidate prospective claims even if they do not necessarily make the retrospective numbers look better.

None of these are claimed as fresh scores from the new strict population.

## Research-only candidate contract

**Raw candidate:** `nfl_player_projection_v2.py` produces player-level statistical draws given pregame history/roles. The probability for a sportsbook line is the fraction of draws strictly greater than that line.

**Forward Platt:** for a given season/week w, fit an intercept b and a **positive** slope a using only *eligible*, settled player-market rows from weeks less than w, and apply `sigmoid(a*logit(p_raw)+b)` to the current week's raw probability. No market price enters this map.

**Week without history:** report raw v2 as *uncalibrated fallback*, not a trained forecast. Require at least 500 earlier items to fit. Those fallback items are excluded from the calibrated model's scorecard.

**Population:**
- Grader is conditional on observed played/settled box-score samples, not yet an unconditional availability model. Always report missing players.
- For passing, choose the quarterback who led that team in **prior weeks** (no reading current-game attempt leader).
- Sportsbook over + under must both be timestamped with explicit timezone and captured **before** that game's scheduled kickoff (not equal or later); latest eligible side per book/line, and opposing-side timestamps at most 30 minutes apart.
- Schedule missing kickoff time, naive/invalid timestamps, late quotes, unpaired prices and missing player projections are excluded and counted. Never backfill an unknown cutoff with the completed game's result or an arbitrary midnight timestamp.
- The snapshot provenance of the projection features and injury inputs still needs verification. Reconstructed walk-forward models are not immutable pregame locks.

**Two mutually independent research questions:**

1. Against the incumbent v2 raw: paired forward-week Brier/log loss and AUC; cluster by player-game, report confidence intervals and each market separately.
2. Against the market: does an **earlier-week-fitted** market-plus-candidate stack beat an earlier-week-fitted market-only comparator *on precisely the same items*? Report paired clustered intervals, by-market coverage and held weeks. A positive fitted coefficient alone is not evidence.

**Third separate test: are the *statistical distributions* any better?**
Platt was trained on sportsbook thresholds, which disproportionately represent actively quoted players and alternate lines. Use `--distribution` to compute a half-integer, discrete-CRPS-style CDF error for each unique (game, player, market) rather than granting every alternate line an independent observation. Compare raw v2 with Platt-implied tails/means per market. It approximates integer support for continuous yardage draws; it is a diagnostic and not a full continuous CRPS. Tail extrapolation is specifically a failure mode to measure.

The odds used in the benchmark are not features of this independent Platt model. The market-plus-candidate stack is a separate *diagnostic*, not the candidate's served output.

## New code in this branch

- `backend/grade_nfl_prop_probabilities.py`: opt-in `pregame_only=True` and `qb_selection="pregame"`. The legacy defaults remain unchanged for reproduccing older published result tables. **Do not use the defaults for any new promotional evaluation.**
- `backend/nfl_prop_forward_platt_candidate.py`: candidate ID, strict eligibility, forward fit/apply, paired independent and market-increment comparisons, optional full-CDF diagnostics; read-only DB access.
- `backend/test_nfl_prop_forward_platt_candidate.py`: synthetic guards on week exclusion, quote timestamps, fallback and pregame QB selection.

## Required execution (development DB only)

```bash
cd backend
export LP_DB_PATH=/root/legendarypicks/backend/data/picks.dev.db
python3 -m unittest test_nfl_prop_forward_platt_candidate test_grade_nfl_prop_probabilities
python3 nfl_prop_forward_platt_candidate.py --season 2026 --boot 400 --distribution \
    --json-report /tmp/nfl-forward-platt-v1.json --csv /tmp/nfl-forward-platt-v1-rows.csv
```

If a command fails, capture the actual traceback and counts. **Do not substitute old scores for the strict cohort**. This research branch contains code and synthetic tests; results for the strict cohort remain **not run here** because the remote development DB is not accessible in this environment.

## Release gate and stopping rule

1. Source/replay audit complete: quote capture time, kickoff, team and QB selection, availability provenance, player-game counts, and repeatability documented. If strict timing leaves too few items, stop with `insufficient pregame market sample`.
2. Accept a *calibration candidate* only if forward Platt improves incumbent probability scoring with a paired player-game clustered interval excluding zero **without a meaningful reduction in per-market resolution/discrimination**. An observed small point gain alone is not a confirmed improvement.
3. Accept any claim of *independent increment over the market* only when the forward stack beats market-only on identical eligible items with a paired confidence interval excluding zero. Do not treat this as a mandatory requirement for a research candidate.
4. Accept any *better predictive stat distribution* claim only after the per-player-game full-CDF test and held-out coverage tests support it. A line-trained Platt map does not automatically calibrate unquoted parts of a distribution.
5. Mark outcome explicitly `PROMOTE`, `RESEARCH_CANDIDATE_ONLY`, `NOT_ESTABLISHED`, or `REJECT`; **stop this round of tuning** and record the result. Negative/null results are valid stopping points.
6. Before model-page listing or production: implement immutable pre-kickoff candidate snapshots and independent live tracking. No schema or production predictor changes in this branch.

## After stop

Move to other, **separately versioned** football facets (plays per game, pass rate, QB drops/scrambles, rushing volume, defense, formations, participation) for the next independent model. Do not modify this frozen calibration candidate based on the 2026 outcomes it has just been graded against.
