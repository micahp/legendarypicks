# FBS Phase 3 — pre-registered model ladder — 2026-10-18

Written before any Phase 3 feature was built or scored. Once the increment is frozen, the protocol
below is not edited to fit the result: an increment that fails a gate is recorded as DISCARDED and the
next family starts.

Worktree `/root/lp-fbs-archive`, branch `feat/fbs-archive`. Baseline code is read from
`/root/lp-fbs-audit/backend/fbs_game_winner_baseline.py` (branch `feat/fbs-data-audit`, commit
`4f20e1fa`); that worktree is never written to.

## 1. Baseline this ladder extends

Reproduced today on the same inputs as Phase 1 (`--data-dir /root/lp-fbs-audit/research/fbs/parquet`),
and matching the Phase 1 report to four decimals:

| period | model | games | Brier | BSS vs coinflip | log loss |
|---|---|---|---|---|---|
| walk-forward 2023–2025 | G2 chronological Elo | 2,398 | 0.2133 | 0.1469 | 0.6162 |
| 2025 frozen holdout | G2 chronological Elo | 808 | 0.2207 | 0.1172 | 0.6323 |
| 2026 current forward | G2 chronological Elo | 350 | 0.2051 | 0.1795 | 0.5994 |

G2 is the reference for every increment because it is the Phase 1 winner (G3 margin strength lost to
G2 on Brier in both the pooled and the frozen holdout, 0.2155 vs 0.2133 and 0.2224 vs 0.2207). G3 is
not re-run as if untested.

## 2. Population and protocol (identical to Phase 1)

- **Population**: FBS-vs-FBS regular-season games, the harness's `evaluation_population` (`fbs_game`).
  2022 is warm-up only; evaluation is 2023, 2024, 2025 and the 2026 forward season.
- **As-of rule**: a game's forecast may use only games whose UTC kickoff was at least one full UTC
  calendar day earlier — the same conservative embargo as Phase 1, because the source has no final
  whistle timestamps. All games on a date share the same pregame state.
- **Walk-forward**: every model is refit on all prior eligible games and forecasts the next date block.
  No game is in its own fit.
- **2025 frozen holdout**: fit through the end of 2024 only, forecast 2025, never refit inside 2025.
- **2026**: walk-forward inside the season; development evidence only, never a confirmation set.
- **Primary metric**: one-outcome Brier, `mean((p - y)^2)` with `y` = home team won.
  Secondary: log loss, Brier skill vs 0.50, reliability and resolution on 10 bins.
- **Uncertainty**: 95% percentile intervals from 2,000 paired, season-stratified UTC calendar-week
  block bootstrap replicates, resampling within season and carrying all of a block's games so the
  pairing is preserved. Same construction as Phase 1.

## 3. Candidate feature families, in order

| order | family | status at Phase 3 start |
|---|---|---|
| (a) | opponent-adjusted team quality | **already tested and failed**: G3 margin strength lost to G2. Not re-run. |
| (b) | prior-play EPA / success / explosiveness / tempo from archived PBP | **this increment** |
| (c) | scoring / turnover / field-position splits from box scores | queued |
| (d) | home / rest / weather / travel | queued |
| (e) | coaching and roster continuity / talent | queued |
| (f) | form and time decay | queued |
| (g) | richer hierarchical models | only if (b)–(f) justify it |

Each family is tested alone against G2, in order. A family that fails is not combined with others and
not revisited with different hyperparameters.

## 4. Increment (b): the exact specification

**Source**: `cfbfastR_cfb_pbp` (CFBD-sourced, 2014–2026), chosen because section 11 of
`AUDIT-FBS-ARCHIVE-20261018.md` records CFBD as the only publisher in the archive that grants model
training and commercial use. `espn_cfb_pbp` is a research cross-check only.

**Play-state fields allowed** (the complete list — anything else is a leak):

    game_id, season, week, period, pos_team, def_pos_team, play_type, down, distance,
    yards_to_goal (or yard_line + yard_line_number), yards_gained, pass, rush,
    scoring_play, pos_score_diff_start, clock/start time, drive id

**Banned**, enforced by a guard that fails the build if read: every column matching
`(?i)^(epa|epa_|wpa|wp_|ep_before|ep_after|ppa|success|explosive|havoc|qbr)` and every
publisher rating or line column (`fpi|rating|rank|spread|total|win_prob|percent`).

**Expected points are recomputed, never joined.** A state model `EP(down, distance_bucket,
yards_to_goal_bucket)` is fitted on the offence's remaining scoring margin from that state, using only
seasons strictly earlier than the game being forecast:

- distance buckets: 1–3, 4–6, 7–10, 11–15, 16+
- field-position buckets: 10-yard bands from own 1 to opponent 1
- target: (offence final score − defence final score) at the end of the game, from the schedule's
  final score, minus the score difference at the start of the play

`EPA(play) = EP(next state, offence perspective) − EP(current state)` with the sign flipped when
possession changes. `success = 1 if EPA > 0`. `explosive = 1 if EPA >= 2.0`.

**Team ratings**, one per team per side (offence, defence), from that team's prior team-games only:

| feature | definition |
|---|---|
| `epa` | plays-weighted mean EPA per play (offence gained / defence allowed) |
| `success` | plays-weighted success rate |
| `explosive` | plays-weighted explosive rate |
| `tempo` | offensive plays per team-game |

Weighting: exponential decay with half-life 6 team-games, plus Kish effective-count shrinkage toward
the league mean with `K = 150` plays. A team with no prior plays gets the league mean and is flagged.
Both sides are opponent-raw: this family is *not* opponent-adjusted, because that is family (a).

**Game features**: four differences, home minus away, each putting the home offence against the away
defence and vice versa:

    epa_diff       = (home_off_epa + away_def_epa) − (away_off_epa + home_def_epa)
    success_diff   = same construction on success
    explosive_diff = same construction on explosive
    tempo_diff     = home_off_tempo − away_off_tempo

**Model form**: logistic regression with the G2 logit as a fixed offset, so the increment can only
explain what G2 did not:

    logit p = logit p_G2 + b0 + Σ b_j x_j

Ridge penalty 1.0 on `b` (not on the offset), features standardised on training games only, refit at
each date block on all prior games.

**Two models are scored, not one:**

- **B1** — G2 + intercept only. A recalibration control. If B2 does not beat B1, the features carry no
  information beyond rescaling G2.
- **B2** — G2 + intercept + the four differences.

**Fixed before the run** (not tuned afterwards): half-life 6, `K = 150`, ridge 1.0, EPA > 0 success,
EPA >= 2.0 explosive, distance and field-position buckets as above.

## 4a. Amendments made before the run (no result had been seen)

Recorded here rather than edited into the sections above, so the change history is visible:

1. **EP is fitted by ridge regression, not by state-cell means.** Cell means over 215 states gave a
   noisy surface (EPA SD 4.0 per play, explosive rate 30%) because adjacent cells were estimated from
   disjoint small samples. EP is now a ridge regression on (down dummies, distance-bucket dummies,
   field position, field position squared, fourth-down × field), accumulated as normal equations per
   season and solved on strictly earlier seasons only.
2. **Points per play come from `pts_scored`.** `offense_score_play` is a 0/1 scoring flag, not points
   (season value counts: only 0 and 1), so using it as points flattened the EP surface to a range of
   ±2. `pts_scored` takes only {-7, -2, 0, 3, 7}; the per-game sum is 52.0 points, matching the
   schedule.
3. **EPA includes the points on the play**: `EPA = EP(next state) − EP(current state) + points on the
   play`, with possession flipped only for non-scoring plays (after a score the next play is the
   scoring team's kickoff). This makes EPA invariant to any constant shift in the EP surface, which
   the earlier form was not.
4. **Teams with no prior plays get the league mean and a `has_history` flag** (section 4), instead of
   a NaN rating that silently dropped their games.
5. **The bootstrap uses UTC calendar-week blocks** (`season` + Monday week start), matching Phase 1's
   harness, rather than day blocks. Day blocks ignore within-week correlation.

The EPA scale here is not the published scale: an EP fitted on remaining scoring margin absorbs
team-quality differences, so EPA SD is about 3.8 rather than about 1.5. `explosive = EPA >= 2` is
therefore roughly a top-quarter play rather than a top-decile one. The model standardises features, so
the scale does not affect the fit; only the interpretation of the explosive threshold changes.

## 5. Gates

An increment is ADOPTED only if every gate passes; otherwise it is DISCARDED and recorded.

| gate | requirement |
|---|---|
| sample | ≥ 1,500 matched pooled games 2023–2025 and ≥ 250 in the 2025 frozen holdout |
| primary | paired Brier B2 − G2 < 0 on the 2023–2025 walk-forward, 95% week-block interval entirely below zero |
| information | paired Brier B2 − B1 < 0 with the interval entirely below zero (otherwise the gain is recalibration, not new information) |
| holdout | paired Brier B2 − G2 on the 2025 frozen holdout not worse than +0.002, and negative in point estimate |
| log loss | same sign as Brier on both the pooled and the holdout comparison |
| calibration | 10-bin reliability error must not rise by more than 0.005 on either period |

Reported but not gating: per-season differences, excluding 2020, and the sensitivity grid
(half-life 3 and 10, `K` 50 and 400). Sensitivity results are reported as robustness, never used to
select a configuration after seeing the primary result.

## 6. Leakage controls, checked mechanically

1. The feature builder declares the exact PBP columns it reads; a guard raises if any column outside
   that list is requested, and a unit test scans the list against the banned regexes.
2. Only games whose kickoff precedes the target date are aggregated, using the harness's own
   `utc_date` and the same one-day embargo.
3. No feature uses any play from the game being forecast.
4. The EP model is fitted on seasons strictly earlier than the forecast game's season, so week 1 of a
   season cannot see that season at all.
5. Publisher `EPA`, `wpa`, `ep_before`, `ep_after`, `success`, `ppa`, ratings, spreads and totals are
   never read, even for comparison.

## 7. Deliverables

- `backend/fbs_phase3_features.py` — EP model, team ratings, feature builder, with the guard.
- `backend/fbs_phase3_increment.py` — walk-forward fit of B1 and B2, gates, CSV outputs.
- `research/fbs/RESULT-FBS-PHASE3-B-20261018.md` — the result, the gate table, and the verdict.
- Machine-readable: `research/fbs/phase3/*.csv` (per-game forecasts, paired comparisons, metrics).
