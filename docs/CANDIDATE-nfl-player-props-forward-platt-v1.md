# NFL player props: Forward Platt v1 candidate and stopping gate

Status: **research candidate, not deployed**. Branch: `feat/nfl-props-forward-platt-candidate` (based on `scratch/spec-b-rebase`, after commit `86db074`). Date: 2026-10-17.

Verdict (2026-10-17): **RESEARCH_CANDIDATE_ONLY**; independent increment **NOT_ESTABLISHED**. See "Strict-cohort results and verdict".

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

If a command fails, capture the actual traceback and counts. **Do not substitute old scores for the strict cohort**. Run under the repo venv (`backend/venv/bin/python`), which carries pytz, numpy and scipy; the system `python3` does not. The branch also shipped with one broken synthetic test (`test_trains_only_on_prior_weeks`): it called `train()` directly with rows lacking the `"week"` key that `candidate_rows()` normally sets, so it raised `KeyError: 'week'`. The helper was fixed to carry the week and all 7 tests now pass.

## Strict-cohort results and verdict (run 2026-10-17, dev DB)

Both commands were run here against the shared dev DB (`/root/legendarypicks/backend/data/picks.dev.db`, read-only). Tests: 7 passed. Candidate run: exit 0, report `/tmp/nfl-forward-platt-v1.json`, scored rows `/tmp/nfl-forward-platt-v1-rows.csv`.

**Population.** 28,002 input items; 7,076 uncalibrated (week 2 has no earlier week); 20,926 calibrated on 628 player-games, weeks 3 to 5. Largest exclusions: quotes captured after kickoff 12,300; weeks outside the graded window 7,969; not played 5,658; not lead passer 1,019. 35 graded items where our outcome disagrees with the book's settlement.

**Forward Platt fits.** Positive slope that shrinks toward the mean as data accumulates: week 3 +0.160 (intercept +0.032), week 4 +0.066 (+0.056), week 5 +0.055 (+0.085). The same structural-overconfidence shape as the retrospective fit.

**Scores, calibrated items, weeks 3 to 5.**

| forecast | Brier | log loss | AUC |
|---|---:|---:|---:|
| Platt (`p_forward`) | 0.2502 | 0.6935 | 0.4991 |
| market | 0.2469 | 0.6868 | 0.5527 |
| raw v2 (`p_ours`) | 0.2743 | 0.7475 | 0.5229 |

**Gate results.**

1. Against the incumbent (raw v2). Platt improves both proper scores with intervals excluding zero: Brier +0.02415 [+0.01282, +0.03631], log loss +0.05409 [+0.02983, +0.08083]. Discrimination falls, AUC 0.5229 to 0.4991.
2. Against the price. Platt does not beat the market. Brier -0.00327 [-0.00469, -0.00169], entirely below zero, so the market is established ahead.
3. Independent increment over the market. Not established. Weeks 4 to 5, 14,214 items, 416 player-games: log loss +0.00007 [-0.00119, +0.00143], Brier +0.00004 [-0.00059, +0.00071]. No market is established; receiving yards is the closest positive (log loss +0.00037).
4. Full predictive distribution. Fails. Platt is worse than raw on every market, all intervals below zero (receiving yards -22.05 [-23.71, -20.48], passing yards -76.35 [-83.37, -68.76]). Mean bias flips from under-projection (receiving yards -8.06) to large over-projection (+53.16): the line-fitted map extrapolates the tail badly, exactly the failure mode gate 4 warns about.

**Verdict: `RESEARCH_CANDIDATE_ONLY`, increment `NOT_ESTABLISHED`.** Calibration is a real and significant improvement over raw v2 on Brier and log loss, but it does not beat the market, creates no increment over the price, and harms the full stat distribution. Stop tuning this candidate and do not promote it. The reasons recorded in the JSON stand: pre-kickoff snapshot provenance is unverified, the conditional-on-played subset is still observed-participation selection, and there is no positive paired clustered interval.

Per the stopping rule, tuning stops here and the next model moves to separately versioned player-distribution facets. Nothing in this branch changes schema or a production predictor.

## Release gate and stopping rule

1. Source/replay audit complete: quote capture time, kickoff, team and QB selection, availability provenance, player-game counts, and repeatability documented. If strict timing leaves too few items, stop with `insufficient pregame market sample`.
2. Accept a *calibration candidate* only if forward Platt improves incumbent probability scoring with a paired player-game clustered interval excluding zero **without a meaningful reduction in per-market resolution/discrimination**. An observed small point gain alone is not a confirmed improvement.
3. Accept any claim of *independent increment over the market* only when the forward stack beats market-only on identical eligible items with a paired confidence interval excluding zero. Do not treat this as a mandatory requirement for a research candidate.
4. Accept any *better predictive stat distribution* claim only after the per-player-game full-CDF test and held-out coverage tests support it. A line-trained Platt map does not automatically calibrate unquoted parts of a distribution.
5. Mark outcome explicitly `PROMOTE`, `RESEARCH_CANDIDATE_ONLY`, `NOT_ESTABLISHED`, or `REJECT`; **stop this round of tuning** and record the result. Negative/null results are valid stopping points.
6. Before model-page listing or production: implement immutable pre-kickoff candidate snapshots and independent live tracking. No schema or production predictor changes in this branch.

## After stop

Move to other, **separately versioned** football facets (plays per game, pass rate, QB drops/scrambles, rushing volume, defense, formations, participation) for the next independent model. Do not modify this frozen calibration candidate based on the 2026 outcomes it has just been graded against.
