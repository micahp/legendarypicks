# FBS Phase 3 — increment (b): prior-play EPA, success, explosiveness, tempo

Result of the first ladder increment, run 2026-10-18 on `feat/fbs-archive`. Pre-registration:
`research/fbs/PHASE3-LADDER-20261018.md` (including the amendments recorded in §4a before the run).
Baseline: G2 chronological Elo, reproduced from the Phase 1 harness to 5.6e-17 on 2,748 shared games.

## Verdict

**ADOPTED.** All ten pre-registered gates pass. Adding the four prior-play differences to the G2 logit
lowers Brier by `-0.01068` on the 2023–2025 walk-forward with a 95% UTC-week-block interval of
`[-0.01444, -0.00650]`, by `-0.01279` on the 2025 frozen holdout `[-0.01768, -0.00763]`, and by
`-0.00971` on the 2026 development season `[-0.01557, -0.00188]`. The recalibration-only control (B1)
moves nothing, so the gain is information the Elo baseline did not have, not a rescaling of it.

## 1. What was tested

| model | definition |
|---|---|
| G2 | Phase 1 chronological Elo, unchanged, as the offset |
| B1 | `logit p = logit p_G2 + b0` — recalibration control, ridge on nothing but the intercept |
| B2 | `logit p = logit p_G2 + b0 + Σ b_j x_j` over `epa_diff`, `success_diff`, `explosive_diff`, `tempo_diff` |

Features are as-of team ratings from `cfbfastR_cfb_pbp` (2014-2026): exponentially weighted over a
team's prior team-games with half-life 6, shrunk toward the league mean with an effective-play prior of
K = 150. EPA and success are recomputed from play states by a ridge EP model fitted on strictly earlier
seasons; no publisher EPA, wp, ep_before, success or rating column is read, enforced by
`ALLOWED_COLUMNS` and `BANNED` in `backend/fbs_phase3_features.py`.

Population, embargo and walk-forward are the Phase 1 harness's own (imported read-only from
`/root/lp-fbs-audit/backend`, never modified). Features joined for 3,523 of 3,524 evaluation games
(100.0%); the one missing game is dropped from every model, so all comparisons are paired.

## 2. Headline scores

| period | model | games | Brier | BSS vs coinflip | log loss | reliability (10 bins) | resolution |
|---|---|---|---|---|---|---|---|
| walk-forward 2023–2025 | G2 | 2,397 | 0.2133 | 0.1469 | 0.6162 | 0.0097 | 0.0373 |
| walk-forward 2023–2025 | B1 G2+intercept | 2,397 | 0.2134 | 0.1465 | 0.6163 | 0.0102 | 0.0384 |
| walk-forward 2023–2025 | **B2 G2+features** | 2,397 | **0.2026** | 0.1897 | 0.5892 | 0.0003 | 0.0394 |
| 2025 frozen holdout | G2 (frozen) | 807 | 0.2208 | 0.1169 | 0.6324 | 0.0048 | 0.0243 |
| 2025 frozen holdout | B1 | 807 | 0.2207 | 0.1173 | 0.6322 | 0.0046 | 0.0241 |
| 2025 frozen holdout | **B2** | 807 | **0.2080** | 0.1681 | 0.5999 | 0.0020 | 0.0341 |
| 2026 development | G2 | 350 | 0.2051 | 0.1795 | 0.5994 | 0.0107 | 0.0357 |
| 2026 development | B1 | 350 | 0.2047 | 0.1812 | 0.5982 | 0.0092 | 0.0343 |
| 2026 development | **B2** | 350 | **0.1954** | 0.2183 | 0.5763 | 0.0056 | 0.0401 |

Reliability improves as well as Brier (0.0097 → 0.0003 pooled; 0.0048 → 0.0020 holdout), and
resolution rises slightly, so this is not a calibration trick: the forecasts separate winners better.

## 3. Paired differences, 95% UTC-week blocks

2,000 paired, season-stratified replicates over `season` × Monday-of-UTC-week blocks, as pre-registered
and as Phase 1 builds them. Negative favours the first model.

| period | comparison | diff | 95% interval | games | blocks |
|---|---|---|---|---|---|
| walk-forward 2023–2025 | B1 − G2 | +0.00011 | [−0.00012, +0.00037] | 2,397 | 65 |
| walk-forward 2023–2025 | **B2 − G2** | **−0.01068** | **[−0.01444, −0.00650]** | 2,397 | 65 |
| walk-forward 2023–2025 | **B2 − B1** | **−0.01079** | **[−0.01456, −0.00660]** | 2,397 | 65 |
| 2025 frozen holdout | B1 − G2 | −0.00009 | [−0.00031, +0.00014] | 807 | 22 |
| 2025 frozen holdout | **B2 − G2** | **−0.01279** | **[−0.01768, −0.00763]** | 807 | 22 |
| 2025 frozen holdout | **B2 − B1** | **−0.01270** | **[−0.01781, −0.00745]** | 807 | 22 |
| 2026 development | B1 − G2 | −0.00042 | [−0.00174, +0.00065] | 350 | 8 |
| 2026 development | **B2 − G2** | **−0.00971** | **[−0.01557, −0.00188]** | 350 | 8 |

## 4. Gates

| gate | requirement | result |
|---|---|---|
| sample pooled | ≥ 1,500 | 2,397 — pass |
| sample holdout | ≥ 250 | 807 — pass |
| primary | B2 − G2 < 0, interval below zero | −0.01068 [−0.01444, −0.00650] — pass |
| information | B2 − B1 < 0, interval below zero | −0.01079 [−0.01456, −0.00660] — pass |
| holdout | not worse than +0.002, point negative | −0.01279 — pass |
| log loss pooled | same sign as Brier | 0.6162 → 0.5892 — pass |
| log loss holdout | same sign | 0.6324 → 0.5999 — pass |
| calibration pooled | reliability +0.005 at most | 0.0097 → 0.0003 — pass |
| calibration holdout | reliability +0.005 at most | 0.0048 → 0.0020 — pass |

## 5. Stability

Every season in the sample improves, not just the pooled total:

| season | games | G2 Brier | B2 Brier | B2 − G2 | 95% interval |
|---|---|---|---|---|---|
| 2022 (outside the primary pool) | 776 | 0.2309 | 0.2177 | −0.0132 | [−0.01959, −0.00614] |
| 2023 | 792 | 0.2138 | 0.1990 | −0.0148 | [−0.02097, −0.00630] |
| 2024 | 798 | 0.2179 | 0.2092 | −0.0087 | [−0.01703, −0.00037] |
| 2025 | 807 | 0.2082 | 0.1996 | −0.0086 | [−0.01277, −0.00382] |
| 2026 | 350 | 0.2051 | 0.1954 | −0.0097 | [−0.01557, −0.00188] |

Sensitivity to the two pre-registered weighting parameters (reported as robustness, not used to
choose): half-life 3 gives pooled `−0.01084 [−0.01455, −0.00670]`, holdout `−0.01511`; half-life 10
gives pooled `−0.00914 [−0.01289, −0.00506]`, holdout `−0.00919`. The result does not depend on the
half-life choice.

## 6. What the model leaned on

Coefficients from the frozen 2025 fit (standardised features):

| term | coefficient |
|---|---|
| intercept | +0.0550 |
| `epa_diff` | −0.0243 |
| `success_diff` | +0.4239 |
| `explosive_diff` | +0.2718 |
| `tempo_diff` | −0.0749 |

A home-side success-rate edge of one standard deviation is worth about 0.42 in the logit. The EPA
difference is nearly inert once success is present, which is expected: the two are strongly correlated
and Elo already captures much of the level. Tempo is mildly negative for the home side. These are the
coefficients of the increment on top of Elo, not a standalone model.

## 7. Construction notes and disclosure

- **Day blocks first, then the pre-registered week blocks.** An earlier run of the same code used
  `season` × UTC date blocks and reported `-0.01068 [-0.01446, -0.00645]`. The verdict rests on the
  week-block run above, which is the pre-registered construction and is slightly wider, as expected.
  Both agree on direction and on every gate.
- **The frozen holdout was scored against a frozen G2.** The first run compared B2 against the
  walk-forward G2 probability for 2025, which carries 2025 information the increment never sees; that
  gave `-0.00842`. The reported holdout uses the harness's frozen G2 ledger (Brier 0.2208) as the
  baseline, which is the honest comparison and gives `-0.01279`.
- **EP estimator.** EP is a ridge regression on down, distance bucket and field position, fitted on
  strictly earlier seasons, with points taken from `pts_scored` and added explicitly. The resulting
  EPA scale is wider than the published one (SD ≈ 3.8 vs ≈ 1.5) because an EP fitted on remaining
  scoring margin absorbs team-quality differences; `explosive = EPA >= 2` is therefore roughly a
  top-quarter play, not a top-decile one. The model standardises features, so this affects the
  interpretation of the threshold, not the fit.
- **No prior history.** Teams with no prior plays receive the league mean and carry a `has_history`
  flag; no evaluated 2025 game had such a team, so this did not change the population.
- **Source.** Features come only from `cfbfastR_cfb_pbp`; no ESPN-derived table feeds the model.

## 8. Limits

- This family is raw, not opponent-adjusted. Opponent adjustment was family (a) and already lost to G2;
  nothing here revisits it.
- The features describe plays, not players: no injuries, availability, depth or transfers.
- 2026 is 350 games and inside-season; it is development evidence, not confirmation.
- The improvement is measured on the winner market only. It says nothing about totals or spreads, and
  Phase 4 must not inherit this result as a distribution claim.
- The EP surface is fitted per season on prior seasons; a change in offensive environment (for example
  the 2020 season) is absorbed only slowly.

## 9. Artifacts

| file | contents |
|---|---|
| `backend/fbs_phase3_features.py` | EP regression, per-play EPA, team-game aggregates, as-of ratings, feature table |
| `backend/fbs_phase3_increment.py` | B1/B2 walk-forward, frozen holdout, week-block bootstrap, gates |
| `research/fbs/phase3/game_features.csv` | 12,827 games × 4 features + history flags |
| `research/fbs/phase3/forecasts_walk_forward.csv` | per-game G2/B1/B2 probabilities, 2022–2026 |
| `research/fbs/phase3/forecasts_holdout_2025.csv` | frozen 2025 holdout |
| `research/fbs/phase3/metrics.csv`, `paired.csv`, `gates.csv` | the tables above |
| `research/fbs/phase3/hl3/`, `hl10/` | half-life sensitivity runs |

## 10. Next

Family (c) of the ladder: scoring, turnover and field-position splits from box scores, tested alone
against the same G2 baseline and the same gates. It should be judged against **B2** as well as G2, since
B2 is now the standing model.

## 11. Increment (c) pre-registration — scoring, turnover and field-position splits

Written before any (c) feature is built. Same population, embargo, walk-forward, holdout, metrics,
week-block bootstrap and gate table as section 5; only the feature block changes.

**Sources**, both already in the archive, both used only through observation columns:

- `espn_cfb_pbp` drive-level fields and `down_end`/`yards_to_goal_end` for drive outcomes and starting
  field position. As in (b), publisher EPA/WP/PPA columns are banned by the same guard; the guard list
  is extended with `EPA`, `wpa`, `ppa`, `qbr`, `havoc` for any box-score column too.
- `espn_cfb_team_box` for turnovers, penalties, third/fourth-down conversions and total yards.

**Team features**, one value per team per game, aggregated to a team rating with the same half-life 6
and K = 150 shrink as (b):

| feature | definition |
|---|---|
| `points_per_drive` | points scored / offensive drives |
| `turnovers_per_drive` | giveaways (interceptions + lost fumbles) / offensive drives |
| `start_field_position` | mean starting yards-to-goal of the team's drives |
| `rz_td_rate` | touchdowns / red-zone trips |
| `third_down_rate` | third-down conversions / attempts |
| `explosive_drive_rate` | share of drives gaining ≥ 30 yards |
| `penalties_per_play` | accepted penalties / scrimmage plays |

**Game features**: the same seven as home-minus-away differences in the direction that puts the home
offence against the away defence, exactly as (b) did for its four.

**Model**: identical form — `logit p = logit p_G2 + b0 + Σ b_j x_j`, ridge 1.0, standardised on training
games, refit at each date block. A B1 control is scored alongside.

**Gates**: the section 5 table, unchanged, plus one addition specific to (c): because (c) is correlated
with (b), the primary comparison is **C2 vs B2** (the standing model), with C2 vs G2 reported for
continuity. An increment that only beats G2 but not B2 is DISCARDED.

**Leakage controls**: box scores are final-game aggregates, so nothing from a game may enter its own
row; all ratings are computed from prior games only, with the same one-day embargo. No season-to-date
aggregate table is read.

## 12. Increment (c) result — drive and box-score splits

Run 2026-10-18 on `feat/fbs-archive`, spec §11 above. Population identical to (b): 2,397 walk-forward
2023–25 games, 807 in the 2025 frozen holdout, 350 in 2026; G2 reproduces 0.213263 exactly on the shared
games (max |p difference| 0.0 across 3,523 games). Primary comparison is **C2 vs B2**.

### Verdict: ADOPTED (all ten gates), with one caveat stated up front

C2 lowers Brier against B2 by `-0.00609 [-0.00925, -0.00258]` on the pooled walk-forward and by
`-0.00755 [-0.01234, -0.00262]` on the frozen holdout, and against G2 by `-0.01677` and `-0.02034`.
The caveat: the edge over B2 is smaller than B2's edge over G2 (`-0.01068`), and season by season it is
not significant in 2024 or 2026. C2 wins the pre-registered pooled gate; it does not win every season.

### Scores

| period | model | games | Brier | BSS | log loss | reliability | resolution |
|---|---|---|---|---|---|---|---|
| walk-forward 2023–25 | G2 | 2,397 | 0.2133 | 0.1471 | 0.6162 | 0.0098 | 0.0374 |
| walk-forward 2023–25 | B2 G2+prior-play | 2,397 | 0.2027 | 0.1891 | 0.5895 | 0.0003 | 0.0397 |
| walk-forward 2023–25 | C1 G2+intercept | 2,397 | 0.2134 | 0.1466 | 0.6163 | 0.0103 | 0.0387 |
| walk-forward 2023–25 | **C2 G2+drive splits** | 2,397 | **0.1965** | 0.2140 | 0.5758 | 0.0010 | 0.0467 |
| 2025 frozen holdout | G2 | 807 | 0.2208 | 0.1169 | 0.6324 | 0.0048 | 0.0243 |
| 2025 frozen holdout | B2 | 807 | 0.2080 | 0.1681 | 0.5999 | 0.0020 | 0.0341 |
| 2025 frozen holdout | **C2** | 807 | **0.2004** | 0.1983 | 0.5834 | 0.0037 | 0.0426 |
| 2026 development | G2 | 350 | 0.2051 | 0.1795 | 0.5994 | 0.0107 | 0.0357 |
| 2026 development | B2 | 350 | 0.1954 | 0.2183 | 0.5763 | 0.0056 | 0.0401 |
| 2026 development | **C2** | 350 | **0.1936** | 0.2256 | 0.5725 | 0.0065 | 0.0453 |

### Paired differences, 95% UTC-week blocks

| period | comparison | diff | 95% interval | games | blocks |
|---|---|---|---|---|---|
| walk-forward 2023–25 | **C2 − B2** | **−0.00609** | **[−0.00925, −0.00258]** | 2,397 | 65 |
| walk-forward 2023–25 | C2 − G2 | −0.01677 | [−0.02065, −0.01248] | 2,397 | 65 |
| walk-forward 2023–25 | C2 − C1 | −0.01688 | [−0.02086, −0.01248] | 2,397 | 65 |
| walk-forward 2023–25 | B2 − G2 | −0.01068 | [−0.01444, −0.00650] | 2,397 | 65 |
| 2025 frozen holdout | **C2 − B2** | **−0.00755** | **[−0.01234, −0.00262]** | 807 | 22 |
| 2025 frozen holdout | C2 − G2 | −0.02034 | [−0.02821, −0.01243] | 807 | 22 |
| 2025 frozen holdout | C2 − C1 | −0.02025 | [−0.02834, −0.01218] | 807 | 22 |
| 2026 development | C2 − B2 | −0.00182 | [−0.00560, +0.00245] | 350 | 8 |
| 2026 development | C2 − G2 | −0.01153 | [−0.01941, −0.00192] | 350 | 8 |

### Gates

| gate | requirement | result |
|---|---|---|
| sample pooled / holdout | ≥ 1,500 / ≥ 250 | 2,397 / 807 — pass |
| primary | C2 − B2 < 0, interval below zero | −0.00609 [−0.00925, −0.00258] — pass |
| information | C2 − C1 < 0, interval below zero | −0.01688 [−0.02086, −0.01248] — pass |
| holdout | not worse than +0.002, point negative | −0.00755 — pass |
| log loss pooled / holdout | C2 ≤ B2 | 0.5758 vs 0.5895; 0.5834 vs 0.5999 — pass |
| calibration pooled / holdout | reliability within +0.005 of B2 | 0.0010 vs 0.0003; 0.0037 vs 0.0020 — pass |

### Stability

| season | games | G2 | B2 | C2 | C2 − B2 | 95% interval |
|---|---|---|---|---|---|---|
| 2022 (outside the primary pool) | 776 | 0.2309 | 0.2177 | 0.2180 | +0.0003 | [−0.00615, +0.00713] |
| 2023 | 792 | 0.2138 | 0.1990 | 0.1905 | −0.0085 | [−0.01532, −0.00125] |
| 2024 | 798 | 0.2179 | 0.2092 | 0.2054 | −0.0038 | [−0.00911, +0.00244] |
| 2025 | 807 | 0.2082 | 0.1996 | 0.1936 | −0.0060 | [−0.00993, −0.00180] |
| 2026 | 350 | 0.2051 | 0.1954 | 0.1936 | −0.0018 | [−0.00560, +0.00245] |

### What the model leaned on

Frozen 2025 coefficients (standardised): intercept +0.0737, `points_per_drive_diff` **+0.5302**,
`turnovers_per_drive_diff` +0.0756, `start_field_position_diff` −0.0365, `rz_td_rate_diff` +0.1229,
`third_down_rate_diff` +0.0350, `explosive_drive_rate_diff` +0.1516, `penalties_per_play_diff` −0.0219.
Scoring per drive dominates; field position is mildly negative, which is what a scoring-rate feature
that already contains field position should look like once both are present.

### Construction notes

- **Source substitution, declared before the run.** §11 named `espn_cfb_pbp` drive fields plus
  `espn_cfb_team_box`. The drive table carries the same facts at a finer grain, so the box score was not
  needed; everything in (c) comes from `espn_cfb_pbp` behind one column guard.
- **Missing drive data is filled at the league mean, not dropped.** 50 of 3,524 evaluation games
  (20 inside the primary pool, none in the holdout) have no ESPN drive table. Their seven differences
  are set to 0.0, which is the league-average difference (a league-average offence against a
  league-average defence cancels), and they carry `has_drive_data = false`. That keeps the population
  identical to (b) instead of shrinking it to 2,377.
- **This is not a stack.** C2 is G2 + the seven (c) features; it does not contain the (b) features.
  "ADOPTED" therefore means (c) is the stronger single family and becomes the standing model. A
  combined B2 + C2 model is a different test and has not been run.

### Next

Family (d) of the ladder (home/rest/weather/travel) against C2, and — separately — a pre-registered
test of combining (b) and (c) as one feature block, which is the obvious question this result raises.
