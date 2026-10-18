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

## 13. Increment (d) data audit and pre-registration — home / rest / weather / travel

Audit run 2026-10-18 against the archive, before any (d) feature code was written. Home field is not
part of this test: G2 already carries a fixed 55-Elo home advantage, and (d) asks only whether rest,
travel and weather add beyond it.

### 13.1 Rest — derivable

`cfb_schedules.start_date` is populated for every game (18,758 games from 2022 on, 100% present). Per
team, ordering a team's games and differencing consecutive `start_date` values gives days of rest.

| measure | value |
|---|---|
| team-games with a prior game | 98.0% |
| median rest | 7.0 days |
| 5th / 95th percentile | 6.8 / 280.2 days |
| team-games with rest < 2 days | 10 |

The 95th percentile and the 10 sub-2-day gaps are artefacts of season boundaries and a handful of
misdated rows, so rest is defined as:

- `rest_days = min(days since previous game, 21)`
- no previous game, a gap over 30 days (season opener), or a gap under 2 days (bad date) → `rest_days = 7`
  (the league norm) with a `rest_neutral` flag.

### 13.2 Travel — derivable, with one gap

`cfb_team_info` carries per-team `city` (94.9% of 710 teams), `latitude`/`longitude` (93.5%) and
`timezone` (41.3%). Timezone is too sparse to use, so travel is measured directly from coordinates:

- `away_travel_km` = great-circle distance from the away team's home coordinates to the home team's,
  `log1p`-scaled.
- `lon_shift` = home longitude − away longitude in degrees; positive means the away team travels east,
  which is the direction with the larger circadian effect.

Gap, stated rather than filled: `cfb_schedules` has `venue` and `venue_id` but **no venue coordinates**,
so a neutral-site game cannot be located. Neutral games (and any game where either team lacks
coordinates) get `away_travel_km = 0` and `lon_shift = 0` — the league-average travel effect, since a
difference of zero is the neutral value — with a `travel_known = false` flag. Roughly 0.4% of FBS games
are neutral-site.

### 13.3 Weather — absent from the stats releases, present only in a derived table

Confirmed absent: `espn_cfb_team_box`, `espn_cfb_schedules`, `espn_cfb_player_box` and
`cfb_team_summaries_weekly` carry no weather, temperature or wind column in any season.

It does exist, in exactly one place: `cfb_matchup_line`, 2015–2026, with `temperature`, `wind_speed`,
`wind_direction` and `weather_condition`. Fill rates for the evaluation window are 99.0% (2022), 99.1%
(2023), 97.9% (2024), 98.1% (2025) and 58.3% (2026, a season in progress).

That table is the one the leakage register flags as a derived file with undocumented provenance, so
weather is **secondary**: reported, not part of the primary gate. A result that depends on it would
depend on a table we do not fully understand.

### 13.4 Pre-registered specification

| model | definition |
|---|---|
| D1 | `logit p = logit p_G2 + b0` — recalibration control |
| **D2 (primary)** | D1 + `rest_diff`, `away_travel_km`, `lon_shift` — the three cleanly derivable covariates |
| D2-weather (secondary, reported only) | D2 + `temperature_c`, `wind_kph` |
| C2 | the standing model, refit on the identical population |

- `rest_diff` = home rest − away rest, in days.
- Game-level covariates, not decayed team ratings: no prior-game input is used, so the ratings
  machinery does not apply. Weather and travel are known before kickoff; rest is a schedule fact.
- Model form, ridge 1.0, standardisation on training games, per-date-block refit: identical to (b)/(c).
- Population: identical 2,397 / 807 / 350. Missing covariates take the neutral value (0) with a flag,
  the same convention as (c).
- **Primary comparison: D2 vs C2.** An increment that beats G2 but not C2 is DISCARDED. D2 vs G2 and
  D2 vs D1 are reported for continuity.
- Gates: the section 5 table, read against C2 instead of G2, plus `primary_d2_beats_c2`.
- Column guard: no EPA/wpa/ppa/qbr/havoc column; no final box score; `cfb_schedules` start dates and
  `cfb_team_info` coordinates only, and `cfb_matchup_line` only for the secondary weather variant.

**If D2 fails, family (d) is discarded and not revisited with different feature definitions.** Rest is
the only covariate with a plausible mechanism strong enough to move a winner probability, and the archive
has no other pregame context data.

## 14. Increment (d) result — rest / travel / weather

Run 2026-10-18 on `feat/fbs-archive`, spec §13 above. Population identical to (b) and (c): 2,397
walk-forward 2023–25 games, 807 frozen holdout, 350 in 2026 (3,523 games; the one game without CFBD
play-by-play stays out). C2 refit on the same games reproduces §12 exactly (`C2 − G2 = -0.01677`
pooled, `-0.02034` holdout). Travel is known for 92.4% of evaluated games and weather for 94.5%.

### Verdict: DISCARDED — (d) carries no information

D2 does not beat C2 (it trails by `+0.01732`, which is simply the size of the drive-split block it does
not contain), and more importantly it does not beat G2 either: `D2 − G2 = +0.00055 [-0.00018, +0.00135]`
and `D2 − D1 = +0.00044 [-0.00021, +0.00116]`. Both intervals contain zero, so rest, travel distance and
longitude shift add nothing beyond a recalibration of Elo. Adding weather changes nothing: `D2w − C2 =
+0.01733`. Per the pre-registration, family (d) is discarded and not revisited with different feature
definitions.

### Scores

| period | model | games | Brier | BSS | log loss | reliability | resolution |
|---|---|---|---|---|---|---|---|
| walk-forward 2023–25 | G2 | 2,397 | 0.2133 | 0.1469 | 0.6162 | 0.0097 | 0.0373 |
| walk-forward 2023–25 | C2 G2+drive splits | 2,397 | 0.1965 | 0.2140 | 0.5758 | 0.0010 | 0.0467 |
| walk-forward 2023–25 | D1 G2+intercept | 2,397 | 0.2134 | 0.1465 | 0.6163 | 0.0102 | 0.0384 |
| walk-forward 2023–25 | **D2 G2+rest/travel/lon** | 2,397 | **0.2138** | 0.1447 | 0.6170 | 0.0078 | 0.0350 |
| walk-forward 2023–25 | D2w +weather | 2,397 | 0.2138 | 0.1447 | 0.6169 | 0.0066 | 0.0333 |
| 2025 frozen holdout | G2 | 807 | 0.2208 | 0.1169 | 0.6324 | 0.0048 | 0.0243 |
| 2025 frozen holdout | C2 | 807 | 0.2004 | 0.1983 | 0.5834 | 0.0037 | 0.0426 |
| 2025 frozen holdout | D1 | 807 | 0.2207 | 0.1173 | 0.6322 | 0.0046 | 0.0241 |
| 2025 frozen holdout | **D2** | 807 | **0.2209** | 0.1166 | 0.6324 | 0.0030 | 0.0216 |
| 2025 frozen holdout | D2w | 807 | 0.2206 | 0.1177 | 0.6317 | 0.0027 | 0.0217 |
| 2026 development | G2 | 350 | 0.2051 | 0.1795 | 0.5994 | 0.0107 | 0.0357 |
| 2026 development | C2 | 350 | 0.1936 | 0.2256 | 0.5725 | 0.0065 | 0.0453 |
| 2026 development | D2 | 350 | 0.2046 | 0.1817 | 0.5979 | 0.0094 | 0.0348 |

### Paired differences, 95% UTC-week blocks

| period | comparison | diff | 95% interval | games | blocks |
|---|---|---|---|---|---|
| walk-forward 2023–25 | **D2 − C2** | **+0.01732** | **[+0.01295, +0.02121]** | 2,397 | 65 |
| walk-forward 2023–25 | D2 − G2 | +0.00055 | [−0.00018, +0.00135] | 2,397 | 65 |
| walk-forward 2023–25 | D2 − D1 | +0.00044 | [−0.00021, +0.00116] | 2,397 | 65 |
| walk-forward 2023–25 | D2w − C2 | +0.01733 | [+0.01272, +0.02161] | 2,397 | 65 |
| walk-forward 2023–25 | C2 − G2 (control) | −0.01677 | [−0.02065, −0.01248] | 2,397 | 65 |
| 2025 frozen holdout | **D2 − C2** | **+0.02042** | **[+0.01246, +0.02871]** | 807 | 22 |
| 2025 frozen holdout | D2 − G2 | +0.00009 | [−0.00127, +0.00159] | 807 | 22 |
| 2025 frozen holdout | D2 − D1 | +0.00017 | [−0.00101, +0.00164] | 807 | 22 |
| 2026 development | D2 − C2 | +0.01097 | [+0.00079, +0.01889] | 350 | 8 |
| 2026 development | D2 − G2 | −0.00056 | [−0.00200, +0.00087] | 350 | 8 |

### Gates

| gate | requirement | result |
|---|---|---|
| sample pooled / holdout | ≥ 1,500 / ≥ 250 | 2,397 / 807 — pass |
| primary d2 beats c2 | interval below zero | +0.01732 [+0.01295, +0.02121] — **fail** |
| information d2 beats d1 | interval below zero | +0.00044 [−0.00021, +0.00116] — **fail** |
| holdout not worse than +0.002 | ≤ +0.002 | +0.02042 — **fail** |
| holdout point negative | < 0 | +0.02042 — **fail** |
| log loss pooled / holdout vs C2 | D2 ≤ C2 | 0.6170 vs 0.5758; 0.6324 vs 0.5834 — **fail** |
| calibration pooled | within +0.005 of C2 | 0.0078 vs 0.0010 — **fail** |
| calibration holdout | within +0.005 of C2 | 0.0030 vs 0.0037 — pass |

### Stability

| season | games | G2 | C2 | D2 | D2 − G2 | D2 − C2 |
|---|---|---|---|---|---|---|
| 2022 (outside the primary pool) | 776 | 0.2309 | 0.2180 | 0.2342 | +0.0034 [−0.00001, +0.00736] | +0.0162 [+0.00536, +0.02786] |
| 2023 | 792 | 0.2138 | 0.1905 | 0.2144 | +0.0006 [−0.00069, +0.00232] | +0.0239 [+0.01403, +0.03256] |
| 2024 | 798 | 0.2179 | 0.2054 | 0.2186 | +0.0007 [−0.00007, +0.00154] | +0.0133 [+0.00703, +0.01885] |
| 2025 | 807 | 0.2082 | 0.1936 | 0.2085 | +0.0003 [−0.00133, +0.00200] | +0.0149 [+0.00829, +0.02102] |
| 2026 | 350 | 0.2051 | 0.1936 | 0.2046 | −0.0006 [−0.00200, +0.00087] | +0.0110 [+0.00079, +0.01889] |

No season shows D2 ahead of G2 by a resolvable margin; 2022 is the only season where the point estimate
is worse with an interval that nearly excludes zero, and it is outside the primary pool.

### What the model leaned on

Frozen 2025 coefficients (standardised): intercept +0.0124, `rest_diff` −0.0065, `away_travel_km`
+0.0647, `lon_shift` −0.0193. The travel coefficient is the largest and still tiny: one standard
deviation of travel is worth 0.065 in the logit, against 0.53 for points per drive in (c). Rest, the one
covariate with a plausible mechanism, is indistinguishable from zero and its sign is negative.

### Interpretation

This is the expected shape of a null for pregame context in a sport with a seven-day week: FBS teams
play on a weekly cadence, byes are scheduled rather than earned, and the short-week cases are rare enough
that Elo already absorbs them. Travel is a real cost but a small and roughly symmetric one, and the
drive-level features in (c) already contain the performance consequences that travel would show up in.
Weather at kickoff is likewise already reflected in the drives that follow.

The null is recorded, not explained away: family (d) is closed.

### Next

Family (e) of the ladder: coaching and roster continuity / talent, tested alone against C2 with the same
protocol. C2 remains the standing model.

## 15. Increment (e) data audit and pre-registration — coaching and roster continuity / talent

Audit run 2026-10-18 before any (e) feature code. CFBD `/talent`, `/coaches`, `/roster` and
`/recruiting/players` are **not fetchable** (quota exhausted 2026-10-16; no direct CFBD call has been
made in Phases 2–3), so this audit covers only what the archive holds.

### 15.1 Coaching continuity — derivable, with one dated limitation

`espn_cfb_coach_tendencies` carries one row per team-season with `pos_team_id`, `pos_team`, `coach` and
`role`. Across 2,753 team-seasons (2004–2026) `role` is `HC` in every row and no team-season lists more
than one coach. In 2022–2026 there are 645 team-seasons, covering **96.1%** of FBS-vs-FBS games on both
sides.

Tenure is derived by walking each team's seasons in order: the count of consecutive seasons with the
same coach, with 1 meaning a new head coach. Coaching changes on that definition are 118 across the 645
team-seasons (2022: 22, 2023: 18, 2024: 30, 2025: 26, 2026: 22), which is a plausible rate.

**Limitation, stated rather than papered over:** one coach per team-season means the table cannot date a
mid-season firing. If a coach was replaced in October, the season's single row is whichever coach the
publisher recorded and the change is invisible to this feature. Coaching continuity here is therefore
*season-start* continuity, exact unless a mid-season change occurred.

`espn_cfb_coach_careers` (447 rows, 601 columns) is a career summary — `coach`, `role`, `teams`,
`seasons`, `first_season`, `last_season` plus career EPA-type aggregates — with no per-team, per-season
rows, so it cannot supply tenure. No coordinator field exists in either table (`role` is always `HC`).

### 15.2 Roster continuity — derivable from published returning production

`cfb_returning_production` (2004–2026) has `season`, `team_id`, `off_returning`, `def_returning`,
`overall_returning`, `n_returning`, `def_basis`, `overall_basis` and `is_estimated`. For 2022–2026 it is
1,168 team-seasons, `off_returning` spans 0.000–1.000 with **no nulls and no estimated rows**, covering
**99.9%** of FBS games.

As-of semantics: returning production is a pre-season figure computed from the prior season's
participation; it is fixed before week 1 and does not change during the season. It is therefore safe for
every game in that season and cannot leak a game's own result.

Raw rosters exist too (`espn_cfb_rosters`, 24 seasons, `athlete_id`/`team`/`year`/`position`), but the
`team` column is a display name rather than a team id, and the published returning-production table is
the same idea already summarised. Recomputing turnover from raw rosters would add a name-matching step
for no additional information, so it is not done.

### 15.3 Talent — present, but secondary on provenance

`cfb_team_talent` (2005–2026) has `season`, `team_id`, `talent_composite`, `talent_rank`,
`blue_chip_ratio`, `n_recruits`; 1,566 team-seasons for 2022–2026, covering **99.2%** of FBS games,
`talent_composite` ranging 0–1463.7. The composite is built from recruiting rankings before the season,
so its as-of semantics are sound (it is not computed from results).

What is not sound is its provenance: it is 247Sports-computed and republished without a documented
licence or derivation, the same class of table as `cfb_matchup_line`. It is therefore **secondary** and
cannot decide the verdict. `cfb_team_portal` (`net_transfer_talent`, `portal_share`, transfers in/out,
2015–2026) is available for **100%** of FBS games and is pregame-known because the portal windows close
before the season; it shares 247Sports-style talent units, so it is secondary too.

### 15.4 Pre-registered specification

| model | definition |
|---|---|
| E1 | `logit p = logit p_G2 + b0` — recalibration control |
| **E2 (primary)** | E1 + `coach_tenure_diff`, `off_returning_diff`, `def_returning_diff` |
| E2+ (secondary, reported only) | E2 + `talent_diff`, `net_transfer_talent_diff` |
| C2 | the standing model, refit on the identical population |

- `coach_tenure_diff` = home seasons under the current head coach − away, capped at 10.
- `*_returning_diff` = home minus away returning production (0–1 scale).
- All covariates are season-level facts fixed before week 1, so they are game-level covariates and not
  as-of team ratings; the decayed-rating machinery does not apply.
- Population identical to (b)–(d): 2,397 / 807 / 350. Missing values take the neutral difference (0)
  with a `*_known` flag, the same convention as (c)/(d).
- Model form, ridge 1.0, standardisation on training games, per-date-block refit, week-block bootstrap:
  identical to (b)–(d).
- **Primary comparison: E2 vs C2.** An increment that beats G2 but not C2 is DISCARDED. E2 vs G2 and
  E2 vs E1 are reported for continuity.
- Gates: the section 5 table read against C2, plus `primary_e2_beats_c2`.
- Column guard: from `espn_cfb_coach_tendencies` only the identity columns (`season`, `pos_team_id`,
  `coach`, `role`) are read, never its EPA/tendency aggregates; nothing from a game's own box score.

**If E2 fails, family (e) is discarded and not revisited with different definitions.**

## 16. Increment (e) result — coaching and roster continuity / talent

Run 2026-10-18 on `feat/fbs-archive`, spec §15 above. Population identical to (b)–(d): 2,397 walk-forward
2023–25 games, 807 frozen holdout, 350 in 2026. C2 refit on the same games reproduces §12 exactly
(`C2 − G2 = -0.01677` pooled, `-0.02034` holdout).

Coverage on the evaluated population is better than the archive-wide view suggested: coach tenure known
for **91.5%** of games (both head coaches present), returning production **100%**, talent composite
**98.6%**, net transfer talent **100%**. Missing values take the neutral difference (0) with a flag.

### Verdict: DISCARDED as an increment — but (e) is the first family with real signal

Per the pre-registered rule, E2 is discarded because it does not beat C2: `E2 − C2 = +0.01252
[+0.00771, +0.01695]` pooled and `+0.01649 [+0.00859, +0.02351]` on the frozen holdout. It cannot
displace the drive splits.

What makes this different from (d) is that (e) is **not a null**. E2 beats G2 with a resolvable margin,
`-0.00425 [-0.00691, -0.00157]` pooled, and beats its own recalibration control by the same amount,
`-0.00436 [-0.00701, -0.00160]`. Coaching continuity and returning production therefore carry
information Elo does not have; it is simply about a third of the information in the drive splits
(`C2 − G2 = -0.01677`). The family is closed by the rule, not by absence of effect.

### Scores

| period | model | games | Brier | BSS | log loss | reliability | resolution |
|---|---|---|---|---|---|---|---|
| walk-forward 2023–25 | G2 | 2,397 | 0.2133 | 0.1469 | 0.6162 | 0.0097 | 0.0373 |
| walk-forward 2023–25 | C2 G2+drive splits | 2,397 | 0.1965 | 0.2140 | 0.5758 | 0.0010 | 0.0467 |
| walk-forward 2023–25 | E1 G2+intercept | 2,397 | 0.2134 | 0.1465 | 0.6163 | 0.0102 | 0.0384 |
| walk-forward 2023–25 | **E2 G2+coach/returning** | 2,397 | **0.2090** | 0.1639 | 0.6055 | 0.0044 | 0.0376 |
| walk-forward 2023–25 | E2+ +talent/portal | 2,397 | 0.2023 | 0.1907 | 0.5865 | 0.0007 | 0.0400 |
| 2025 frozen holdout | G2 | 807 | 0.2208 | 0.1169 | 0.6324 | 0.0048 | 0.0243 |
| 2025 frozen holdout | C2 | 807 | 0.2004 | 0.1983 | 0.5834 | 0.0037 | 0.0426 |
| 2025 frozen holdout | E1 | 807 | 0.2207 | 0.1173 | 0.6322 | 0.0046 | 0.0241 |
| 2025 frozen holdout | **E2** | 807 | **0.2169** | 0.1323 | 0.6231 | 0.0017 | 0.0252 |
| 2025 frozen holdout | E2+ | 807 | 0.2175 | 0.1299 | 0.6236 | 0.0033 | 0.0257 |
| 2026 development | G2 | 350 | 0.2051 | 0.1795 | 0.5994 | 0.0107 | 0.0357 |
| 2026 development | C2 | 350 | 0.1936 | 0.2256 | 0.5725 | 0.0065 | 0.0453 |
| 2026 development | E2 | 350 | 0.1994 | 0.2023 | 0.5863 | 0.0071 | 0.0401 |
| 2026 development | E2+ | 350 | 0.1835 | 0.2662 | 0.5478 | 0.0042 | 0.0547 |

### Paired differences, 95% UTC-week blocks

| period | comparison | diff | 95% interval | games | blocks |
|---|---|---|---|---|---|
| walk-forward 2023–25 | **E2 − C2 (primary)** | **+0.01252** | **[+0.00771, +0.01695]** | 2,397 | 65 |
| walk-forward 2023–25 | E2 − G2 | −0.00425 | [−0.00691, −0.00157] | 2,397 | 65 |
| walk-forward 2023–25 | E2 − E1 | −0.00436 | [−0.00701, −0.00160] | 2,397 | 65 |
| walk-forward 2023–25 | E2+ − C2 | +0.00583 | [−0.00043, +0.01205] | 2,397 | 65 |
| walk-forward 2023–25 | C2 − G2 (control) | −0.01677 | [−0.02065, −0.01248] | 2,397 | 65 |
| 2025 frozen holdout | **E2 − C2** | **+0.01649** | **[+0.00859, +0.02351]** | 807 | 22 |
| 2025 frozen holdout | E2 − G2 | −0.00384 | [−0.00788, +0.00046] | 807 | 22 |
| 2025 frozen holdout | E2 − E1 | −0.00376 | [−0.00787, +0.00063] | 807 | 22 |
| 2026 development | E2 − C2 | +0.00582 | [−0.00249, +0.01345] | 350 | 8 |
| 2026 development | E2 − G2 | −0.00571 | [−0.01052, +0.00046] | 350 | 8 |
| 2026 development | E2+ − C2 | −0.01015 | [−0.02593, +0.00448] | 350 | 8 |

### Gates

| gate | requirement | result |
|---|---|---|
| sample pooled / holdout | ≥ 1,500 / ≥ 250 | 2,397 / 807 — pass |
| primary e2 beats c2 | interval below zero | +0.01252 [+0.00771, +0.01695] — **fail** |
| information e2 beats e1 | interval below zero | −0.00436 [−0.00701, −0.00160] — pass |
| holdout not worse than +0.002 | ≤ +0.002 | +0.01649 — **fail** |
| holdout point negative | < 0 | +0.01649 — **fail** |
| log loss pooled / holdout vs C2 | E2 ≤ C2 | 0.6055 vs 0.5758; 0.6231 vs 0.5834 — **fail** |
| calibration pooled | within +0.005 of C2 | 0.0044 vs 0.0010 — pass |
| calibration holdout | within +0.005 of C2 | 0.0017 vs 0.0037 — pass |

### Stability

| season | games | G2 | C2 | E2 | E2 − G2 | E2 − C2 |
|---|---|---|---|---|---|---|
| 2022 (outside the primary pool) | 776 | 0.2309 | 0.2180 | 0.2323 | +0.0015 [−0.00335, +0.00592] | +0.0144 [+0.00344, +0.02521] |
| 2023 | 792 | 0.2138 | 0.1905 | 0.2055 | −0.0082 [−0.01309, −0.00305] | +0.0151 [+0.00505, +0.02487] |
| 2024 | 798 | 0.2179 | 0.2054 | 0.2169 | −0.0009 [−0.00492, +0.00387] | +0.0116 [+0.00372, +0.01942] |
| 2025 | 807 | 0.2082 | 0.1936 | 0.2046 | −0.0036 [−0.00738, +0.00061] | +0.0110 [+0.00414, +0.01731] |
| 2026 | 350 | 0.2051 | 0.1936 | 0.1994 | −0.0057 [−0.01052, +0.00046] | +0.0058 [−0.00249, +0.01345] |

E2 is ahead of G2 in four of five seasons and significantly so in 2023; nothing in (d) looked like this.

### What the model leaned on

Frozen 2025 coefficients (standardised): intercept +0.0220, `coach_tenure_diff` +0.1327,
`off_returning_diff` +0.2112, `def_returning_diff` +0.1259. Returning offensive production is the
strongest of the three, roughly half the size of (c)'s points-per-drive coefficient (0.53), and
coaching tenure is a real but smaller effect.

The secondary variant is worth recording for a future decision, not for this verdict: adding talent and
net transfer talent moves E2+ to 0.2023 pooled (`E2+ − C2 = +0.00583 [-0.00043, +0.01205]`, interval
touching zero) and to 0.1835 in 2026 (`E2+ − C2 = -0.01015`). Talent is 247Sports-derived and was
pre-registered as non-gating, so this is an observation, not a result.

### Interpretation

Coaching change and roster turnover are the classic "cheap" FBS predictors, and here they are real but
small: the market for them is the day-one line, and once Elo and drive-level performance are in the
model there is little left. They also arrive as season-level facts, so they cannot track the within-season
drift that the drive features capture weekly.

Family (e) is closed by the pre-registered rule. It is not evidence that coaching and roster continuity
are worthless — it is evidence that they are worth about a third of what drive-level performance is worth,
which is below the bar C2 sets.

### Next

Family (f) of the ladder: form and time decay, tested alone against C2.

## 17. Increment (f) data audit and pre-registration — form and time decay

Audit run 2026-10-18 before any (f) feature code. The question (f) asks is whether *recent* performance
and the *decay rate* carry signal that the full-history averages in (b) miss.

### 17.1 What the archive supports

| source | seasons | plays | role in (f) |
|---|---|---|---|
| `cfbfastR_cfb_pbp` | 2014–2026 | 2,459,820 | the event table every (b) feature is built from |
| `espn_cfb_pbp` | 2004–2026 | 3,242,765 | cross-check only; different schema, not used |

The (b) construction applies unchanged and is reused rather than rebuilt: EP by ridge regression on
(down, distance, field position) fitted on strictly earlier seasons, `EPA = EP(next) − EP(cur) + points`,
team-game aggregates for offence and defence, then an exponentially weighted as-of rating. Nothing about
form needs a new data source — it needs the same team-game table read with a shorter memory.

Window availability for FBS-vs-FBS games 2022–2026 (3,936 games):

| condition | share of games |
|---|---|
| both teams have ≥ 1 prior game | 97.7% |
| both teams have ≥ 3 prior games | 94.1% |
| both teams have ≥ 5 prior games | 90.5% |
| median prior games per team | 28 |

So a three-game window is available for both sides in 94.1% of games. Games where a team has fewer than
three prior games use whatever it has (one or two) and are flagged; games with no prior game at all fall
back to the full-history rating, which is itself the league mean in that case.

### 17.2 Pre-registered construction (one choice, made now)

**Form is a difference, not a level**: for each metric, `form = recent-3 mean − full-history rating`. The
level is already carried by C2 and by Elo; the difference isolates "hot or cold relative to this team's
own baseline", which is the only version of form that is not a duplicate of (b).

| feature | definition |
|---|---|
| `off_epa_form` | mean `off_epa` over the team's last 3 team-games − full-history decayed `off_epa` |
| `def_epa_form` | same on `def_epa` (negative is good for the defence) |
| `off_success_form` | mean `off_success` over the last 3 − full-history decayed `off_success` |
| `def_success_form` | same on `def_success` |

Recent window: the last three prior team-games, equal weight, only games that kicked off at least one
full UTC day before the game being forecast (the same embargo as (b)). Full-history rating: the (b)
rating, half-life 6 team-games, K = 150 shrink.

Game features are the four home-minus-away differences, constructed the same way as (b)/(c): the home
offence against the away defence and vice versa.

### 17.3 Models and protocol

| model | definition |
|---|---|
| F1 | `logit p = logit p_G2 + b0` — recalibration control |
| **F2 (primary)** | F1 + the four form differences |
| C2 | the standing model, refit on the identical population |

- Population identical to (b)–(e): 2,397 / 807 / 350; the one game without CFBD PBP stays out;
  selection is by feature availability, never by outcome.
- Model form, ridge 1.0, standardisation on training games, per-date-block refit, one-outcome Brier,
  week-block bootstrap with 2,000 replicates: identical to (b)–(e).
- **Primary comparison: F2 vs C2.** An increment that beats G2 but not C2 is DISCARDED. F2 vs G2 and
  F2 vs F1 are reported.
- Gates: the section 5 table read against C2, plus `primary_f2_beats_c2`.
- **Time-decay sensitivity, pre-registered as robustness and not model selection:** rerun F2 with the
  full-history half-life at 3 and at 10 (recent window fixed at 3) and report both. The primary result
  uses half-life 6.
- Leakage controls unchanged: EP recomputed from pre-snap state, never joined; only prior completed
  games; EP fitted on strictly earlier seasons; the BANNED regex on publisher columns still applies.

**If F2 fails, family (f) is discarded and not revisited with a different form definition.**

## 18. Increment (f) result — form and time decay

Run 2026-10-18 on `feat/fbs-archive`, spec §17 above. Population identical to (b)–(e): 2,397
walk-forward 2023–25, 807 frozen holdout, 350 in 2026. C2 refit on the same games reproduces §12 exactly
(`C2 − G2 = -0.01677` pooled, `-0.02034` holdout). Form is available for 100% of evaluated games.

### Verdict: DISCARDED

F2 does not beat C2: `F2 − C2 = +0.01417 [+0.00953, +0.01850]` pooled and `+0.01551 [+0.00670, +0.02469]`
on the frozen holdout. As with (e), the family is not a null: F2 beats G2 by `-0.00260
[-0.00444, -0.00084]` and beats its own recalibration control by `-0.00271 [-0.00450, -0.00098]`, and the
holdout effect is larger than the pooled one (`F2 − G2 = -0.00482 [-0.00796, -0.00193]`). Recent form
carries information; it carries about a sixth of what the drive splits carry.

### Scores

| period | model | games | Brier | BSS | log loss | reliability | resolution |
|---|---|---|---|---|---|---|---|
| walk-forward 2023–25 | G2 | 2,397 | 0.2133 | 0.1469 | 0.6162 | 0.0097 | 0.0373 |
| walk-forward 2023–25 | C2 G2+drive splits | 2,397 | 0.1965 | 0.2140 | 0.5758 | 0.0010 | 0.0467 |
| walk-forward 2023–25 | F1 G2+intercept | 2,397 | 0.2134 | 0.1465 | 0.6163 | 0.0102 | 0.0384 |
| walk-forward 2023–25 | **F2 G2+form** | 2,397 | **0.2107** | 0.1573 | 0.6098 | 0.0071 | 0.0375 |
| 2025 frozen holdout | G2 | 807 | 0.2208 | 0.1169 | 0.6324 | 0.0048 | 0.0243 |
| 2025 frozen holdout | C2 | 807 | 0.2004 | 0.1983 | 0.5834 | 0.0037 | 0.0426 |
| 2025 frozen holdout | F1 | 807 | 0.2207 | 0.1173 | 0.6322 | 0.0046 | 0.0241 |
| 2025 frozen holdout | **F2** | 807 | **0.2159** | 0.1362 | 0.6213 | 0.0048 | 0.0287 |
| 2026 development | G2 | 350 | 0.2051 | 0.1795 | 0.5994 | 0.0107 | 0.0357 |
| 2026 development | C2 | 350 | 0.1936 | 0.2256 | 0.5725 | 0.0065 | 0.0453 |
| 2026 development | F2 | 350 | 0.2020 | 0.1918 | 0.5914 | 0.0053 | 0.0338 |

### Paired differences, 95% UTC-week blocks

| period | comparison | diff | 95% interval | games | blocks |
|---|---|---|---|---|---|
| walk-forward 2023–25 | **F2 − C2 (primary)** | **+0.01417** | **[+0.00953, +0.01850]** | 2,397 | 65 |
| walk-forward 2023–25 | F2 − G2 | −0.00260 | [−0.00444, −0.00084] | 2,397 | 65 |
| walk-forward 2023–25 | F2 − F1 | −0.00271 | [−0.00450, −0.00098] | 2,397 | 65 |
| walk-forward 2023–25 | C2 − G2 (control) | −0.01677 | [−0.02065, −0.01248] | 2,397 | 65 |
| 2025 frozen holdout | **F2 − C2** | **+0.01551** | **[+0.00670, +0.02469]** | 807 | 22 |
| 2025 frozen holdout | F2 − G2 | −0.00482 | [−0.00796, −0.00193] | 807 | 22 |
| 2025 frozen holdout | F2 − F1 | −0.00474 | [−0.00782, −0.00183] | 807 | 22 |
| 2026 development | F2 − C2 | +0.00844 | [+0.00135, +0.01454] | 350 | 8 |
| 2026 development | F2 − G2 | −0.00309 | [−0.00592, +0.00052] | 350 | 8 |

### Gates

| gate | requirement | result |
|---|---|---|
| sample pooled / holdout | ≥ 1,500 / ≥ 250 | 2,397 / 807 — pass |
| primary f2 beats c2 | interval below zero | +0.01417 [+0.00953, +0.01850] — **fail** |
| information f2 beats f1 | interval below zero | −0.00271 [−0.00450, −0.00098] — pass |
| holdout not worse than +0.002 | ≤ +0.002 | +0.01551 — **fail** |
| holdout point negative | < 0 | +0.01551 — **fail** |
| log loss pooled / holdout vs C2 | F2 ≤ C2 | 0.6098 vs 0.5758; 0.6213 vs 0.5834 — **fail** |
| calibration pooled | within +0.005 of C2 | 0.0071 vs 0.0010 — **fail** |
| calibration holdout | within +0.005 of C2 | 0.0048 vs 0.0037 — pass |

### Stability and the pre-registered half-life sensitivity

| season | games | G2 | C2 | F2 | F2 − G2 | F2 − C2 |
|---|---|---|---|---|---|---|
| 2022 (outside the primary pool) | 776 | 0.2309 | 0.2180 | 0.2323 | +0.0014 [−0.00419, +0.00730] | +0.0143 [+0.00187, +0.02716] |
| 2023 | 792 | 0.2138 | 0.1905 | 0.2146 | +0.0008 [−0.00167, +0.00381] | +0.0241 [+0.01410, +0.03284] |
| 2024 | 798 | 0.2179 | 0.2054 | 0.2124 | −0.0055 [−0.00883, −0.00183] | +0.0070 [+0.00028, +0.01303] |
| 2025 | 807 | 0.2082 | 0.1936 | 0.2052 | −0.0031 [−0.00631, −0.00007] | +0.0115 [+0.00393, +0.01863] |
| 2026 | 350 | 0.2051 | 0.1936 | 0.2020 | −0.0031 [−0.00592, +0.00052] | +0.0084 [+0.00135, +0.01454] |

The effect switches on in 2024: F2 is worse than G2 in 2022 and 2023 and better in 2024–2026. That is a
pattern worth recording, not a finding to build on — two of the five seasons are the wrong sign.

Half-life sensitivity, pre-registered as robustness only and not used to choose:

| full-history half-life | F2 − C2 pooled | F2 − G2 pooled | F2 − G2 holdout | F2 − F1 pooled |
|---|---|---|---|---|
| 3 | +0.01356 | −0.00321 [−0.00548, −0.00101] | −0.00524 | −0.00332 |
| **6 (primary)** | **+0.01417** | **−0.00260 [−0.00444, −0.00084]** | **−0.00482** | **−0.00271** |
| 10 | +0.01423 | −0.00254 [−0.00428, −0.00089] | −0.00513 | −0.00265 |

The result does not depend on the decay rate: every half-life gives a small, resolvable gain over G2 and a
consistent loss to C2.

### What the model leaned on

Frozen 2025 coefficients (standardised): intercept +0.0185, `off_epa_form_diff` +0.0978,
`def_epa_form_diff` +0.0441, `off_success_form_diff` +0.1407, `def_success_form_diff` +0.0916.
Offensive success form is the largest, at roughly a quarter of (c)'s points-per-drive coefficient. All
four signs point the intuitive way (a team performing above its own baseline helps the home side).

### Interpretation

Form is real but thin. With a six-game half-life already in (b)'s ratings, the marginal information in
"the last three games" is small, and it is concentrated in seasons where it happens to matter. Against a
model that measures the same underlying performance more directly — drive-level scoring, takeaways and
field position, recomputed weekly — form loses by a wide margin.

Family (f) is closed by the pre-registered rule. Three families ((d), (e), (f)) have now failed the C2
bar; (e) and (f) failed while beating G2, which is the useful distinction the ladder was built to expose.

### Next

Family (g), richer hierarchical models, is the last rung. Given three consecutive failures, the question
for (g) is whether a different functional form (partial pooling, state-space or a hierarchical Elo) can
beat C2 on the same features, rather than adding another feature block.

## 19. Increment (g) data audit and pre-registration — hierarchical / partial pooling

Audit run 2026-10-18 before any (g) model code. The question (g) asks is a **functional-form** question:
C2 treats each game-row as independent, but a team's games are correlated. Does estimating the same C2
features with partial pooling help?

### 19.1 C2 as the estimator input

C2 is `logit p = logit p_G2 + b0 + Σ b_k x_k` over seven standardised drive splits
(`points_per_drive`, `turnovers_per_drive`, `start_field_position`, `rz_td_rate`, `third_down_rate`,
`explosive_drive_rate`, `penalties_per_play`), flat ridge 1.0, refit per date block on strictly earlier
games. Frozen 2025 coefficients: intercept +0.0737, points/drive **+0.5302**, turnovers/drive +0.0756,
start field position −0.0365, red-zone TD rate +0.1229, third-down rate +0.0350, explosive drive rate
+0.1516, penalties/play −0.0219. (g) keeps this feature set exactly and changes only the estimator.

### 19.2 The hierarchical structure the archive supports

| item | measurement |
|---|---|
| conference field | `home_conference` / `away_conference` in `cfb_schedules`, 100% populated |
| team-seasons 2022–2026 | 672, every one with a conference |
| team-seasons with more than one conference | 0 |
| conferences | 11 (Big Ten 82, ACC 79, SEC 76, Big 12 72, Sun Belt 70, American 67, MAC 62, Mountain West 58, C-USA 52, Pac-12 36, FBS Independents 18) |
| teams per season | 131 / 133 / 134 / 136 / 138 |
| games per team-season (2022 pool) | min 9, median 12, max 14 |

So three levels are available and identifiable: game → team-season → conference. There is no
team-within-conference duplication across seasons to worry about, and no team-season changes conference.

### 19.3 How large the effects actually are (this sets the priors, on 2022 only)

Measured from the C2 residuals on 2022 — a season **outside** the primary pool, the 2025 holdout and the
2026 development season — decomposing observed dispersion into signal and sampling noise:

| quantity | value |
|---|---|
| observed Var of team-season mean logit residual | 0.5106 |
| mean sampling Var at 9–14 games | 0.4019 |
| implied team-season effect SD | **0.330** |
| observed SD of conference means | 0.226 |
| implied conference-level effect SD (noise removed) | **0.08** |

Two things follow, and they are the honest expectation for this increment:

1. Conference-level residual effects are tiny (0.08 logit) because Elo and the drive splits already carry
   conference strength. The hierarchy's top level will barely move a prediction.
2. A team-season effect of SD 0.330 estimated from 12 games has reliability of only about 21%
   (0.109 / 0.511), so partial pooling can recover only a fraction of it. **A near-null is the most likely
   outcome**; the increment is worth one pre-registered test, not a search.

### 19.4 The variant (one primary)

**Random-intercept logistic with two nested levels, on top of the C2 linear predictor.**

```
eta_i   = logit(p_G2,i) + b0 + x_i'b + (a_home(i) - a_away(i))
a_t     = m_conf(t) + u_t
u_t    ~ N(0, 1/lambda_team)
m_c    ~ N(0, 1/lambda_conf)
```

- `t` indexes team-season, `c` indexes conference. The random effect enters as a home-minus-away
  difference, exactly like every other covariate in this ladder.
- Effects are **residual**: the G2 offset and the drive splits are already in `eta`, so `a_t` captures only
  what is left.

| hyperparameter | frozen value | justification |
|---|---|---|
| `lambda_team` | **9.0** (prior SD 0.333) | 1/0.330² from the 2022 measurement in §19.3 |
| `lambda_conf` | **156** (prior SD 0.080) | 1/0.08² from the 2022 measurement in §19.3 |
| ridge on `b` | **1.0** | unchanged from C2, so the only difference from C2 is the hierarchy |
| standardisation | training-fold mean and SD | unchanged from (b)–(f) |

**Estimation:** penalised maximum likelihood (Gaussian priors ≡ ridge penalties) by L-BFGS-B with analytic
gradient, implemented in numpy/scipy — reproducible in the venv, no sampler, no seed. The penalties make
the objective strictly convex, so the optimum is unique and identification is by the prior rather than by a
sum-to-zero constraint.

**Convergence checks, asserted not assumed:** `max |gradient| < 1e-6` at every fold, and the run aborts if
any fold fails to converge. Reported per run: number of folds, worst gradient norm, fitted SD of `u` and
of `m`, and the share of team-seasons seen at least once in training.

**Prediction:** a team-season not seen in training contributes `u = 0` and its conference mean (0 if the
conference is unknown). No future information enters any fold — the same per-block refit and one-day
embargo as (b)–(f).

### 19.5 Models, gates and robustness

| model | definition |
|---|---|
| G1 | hierarchy on the G2 offset only — no drive splits |
| **G2h (primary)** | hierarchy + the seven C2 drive splits |
| C2 | the standing flat model, refit on the identical population |

- Population identical to (b)–(f): 2,397 / 807 / 350; the one no-PBP game stays out.
- **Primary gate: G2h vs C2** (paired Brier difference < 0, interval entirely below zero).
- **Information gate: G2h vs G1** — consistent with (b)–(f), the increment must beat its own
  no-features control. Here the control is the same hierarchy without the drive splits, which tests that
  the features still carry information once team-season effects are in the model.
- Remaining gates identical: sample sizes, holdout not worse than +0.002, holdout point negative, log loss
  same sign pooled and holdout, calibration within 0.005 pooled and holdout. Fail-closed.
- **Per-season sign table required** even if the pooled interval excludes zero (the (f) learning).
- **One pre-declared robustness variant, reported and not used to choose:** `lambda_team = 4.0`
  (prior SD 0.5, weaker shrinkage). Nothing else changes.
- No other family may be stacked: this is (c)'s features only, with (d)/(e)/(f) excluded.

**If G2h fails, the ladder is exhausted and C2 stands as the game-winner model.**

## 20. Increment (g) result — hierarchical partial pooling

Run 2026-10-18 on `feat/fbs-archive`, spec §19 above, hyperparameters frozen before the run
(`lambda_team = 9.0`, `lambda_conf = 156`, ridge 1.0). Population identical to (b)–(f): 3,523 games loaded,
**2,397** walk-forward 2023–25, **807** frozen holdout, **350** in 2026; the one no-PBP game (401778314)
stays out; 99.2% of the evaluated games carry the drive features and the remaining 0.8% use the league-mean
fill with `has_drive_data = 0`. `C2 − G2` reproduces §12 to the digit (`-0.01677` pooled, `-0.02034`
holdout), so the flat path is untouched.

**No look-ahead:** every fold is fitted on `utc_date <` the block's first kickoff, team-season effects are
estimated only from those games, a team-season unseen in training contributes `u = 0` plus its conference
mean, and EP is the (b) recomputation from pre-snap state. Nothing about the evaluated game enters its own
prediction.

### Verdict: ADOPTED — 10/10 gates

| period | G2 | C2 | G1 hierarchy only | **G2h hierarchy+drives** |
|---|---|---|---|---|
| walk-forward 2023–25 Brier | 0.2133 | 0.1965 | 0.2085 | **0.1946** |
| walk-forward log loss | 0.6162 | 0.5758 | 0.6055 | **0.5711** |
| 2025 frozen holdout Brier | 0.2208 | 0.2004 | 0.2193 | **0.2001** |
| holdout log loss | 0.6324 | 0.5834 | 0.6293 | **0.5826** |
| 2026 development Brier | 0.2051 | 0.1936 | 0.2000 | **0.1908** |
| 2026 log loss | 0.5994 | 0.5725 | 0.5877 | **0.5655** |

| period | model | games | Brier | BSS | log loss | reliability | resolution | accuracy |
|---|---|---|---|---|---|---|---|---|
| walk-forward 2023–25 | G2 | 2,397 | 0.2133 | 0.1469 | 0.6162 | 0.0097 | 0.0373 | 0.6650 |
| walk-forward 2023–25 | C2 | 2,397 | 0.1965 | 0.2140 | 0.5758 | 0.0010 | 0.0467 | 0.7042 |
| walk-forward 2023–25 | G1 | 2,397 | 0.2085 | 0.1659 | 0.6055 | 0.0092 | 0.0411 | 0.6713 |
| walk-forward 2023–25 | **G2h** | 2,397 | **0.1946** | 0.2216 | 0.5711 | 0.0006 | 0.0478 | 0.7021 |
| 2025 frozen holdout | G2 | 807 | 0.2208 | 0.1169 | 0.6324 | 0.0048 | 0.0243 | 0.6568 |
| 2025 frozen holdout | C2 | 807 | 0.2004 | 0.1983 | 0.5834 | 0.0037 | 0.0426 | 0.6914 |
| 2025 frozen holdout | G1 | 807 | 0.2193 | 0.1226 | 0.6293 | 0.0051 | 0.0257 | 0.6617 |
| 2025 frozen holdout | **G2h** | 807 | **0.2001** | 0.1997 | 0.5826 | 0.0040 | 0.0434 | 0.6890 |
| 2026 development | G2 | 350 | 0.2051 | 0.1795 | 0.5994 | 0.0107 | 0.0357 | 0.6886 |
| 2026 development | C2 | 350 | 0.1936 | 0.2256 | 0.5725 | 0.0065 | 0.0453 | 0.7000 |
| 2026 development | G1 | 350 | 0.2000 | 0.2001 | 0.5877 | 0.0116 | 0.0426 | 0.7114 |
| 2026 development | **G2h** | 350 | **0.1908** | 0.2369 | 0.5655 | 0.0074 | 0.0494 | 0.7000 |

Accuracy is reported for completeness and is not a gate: G2h is 0.7021 against C2's 0.7042 pooled, so the
gain is in the probabilities, not in the modal pick.

### Paired differences, 95% UTC-week blocks

| period | comparison | diff | 95% interval | games | blocks |
|---|---|---|---|---|---|
| walk-forward 2023–25 | **G2h − C2 (primary)** | **−0.00190** | **[−0.00255, −0.00125]** | 2,397 | 65 |
| walk-forward 2023–25 | G2h − G1 (information) | −0.01393 | [−0.01754, −0.00981] | 2,397 | 65 |
| walk-forward 2023–25 | G2h − G2 | −0.01867 | [−0.02258, −0.01419] | 2,397 | 65 |
| walk-forward 2023–25 | G1 − G2 | −0.00473 | [−0.00566, −0.00387] | 2,397 | 65 |
| walk-forward 2023–25 | C2 − G2 (control) | −0.01677 | [−0.02065, −0.01248] | 2,397 | 65 |
| 2025 frozen holdout | **G2h − C2** | **−0.00036** | **[−0.00154, +0.00042]** | 807 | 22 |
| 2025 frozen holdout | G2h − G1 | −0.01926 | [−0.02727, −0.01106] | 807 | 22 |
| 2025 frozen holdout | G1 − G2 | −0.00143 | [−0.00289, −0.00033] | 807 | 22 |
| 2026 development | G2h − C2 | −0.00283 | [−0.00463, −0.00100] | 350 | 8 |
| 2026 development | G2h − G1 | −0.00919 | [−0.01664, +0.00037] | 350 | 8 |

### Per-season signs (required table)

| season | games | G2 | C2 | G2h | G2h − C2 | G1 − G2 |
|---|---|---|---|---|---|---|
| 2022 (outside the primary pool) | 776 | 0.2309 | 0.2180 | 0.2170 | −0.00102 [−0.00195, −0.00002] | −0.00174 [−0.00325, −0.00012] |
| 2023 | 792 | 0.2138 | 0.1905 | 0.1892 | −0.00131 [−0.00241, −0.00016] | −0.00428 [−0.00614, −0.00241] |
| 2024 | 798 | 0.2179 | 0.2054 | 0.2032 | −0.00217 [−0.00309, −0.00112] | −0.00435 [−0.00549, −0.00318] |
| 2025 | 807 | 0.2082 | 0.1936 | 0.1914 | −0.00221 [−0.00331, −0.00101] | −0.00555 [−0.00686, −0.00402] |
| 2026 | 350 | 0.2051 | 0.1936 | 0.1908 | −0.00283 [−0.00463, −0.00100] | −0.00517 [−0.00863, −0.00169] |

The sign is negative in all five seasons and resolvable in four. This is the first family in the ladder
with no wrong-sign season.

### Gates

| gate | requirement | result |
|---|---|---|
| sample pooled / holdout | ≥ 1,500 / ≥ 250 | 2,397 / 807 — pass |
| **primary g2h beats c2** | interval below zero | −0.00190 [−0.00255, −0.00125] — **pass** |
| information g2h beats g1 | interval below zero | −0.01393 [−0.01754, −0.00981] — pass |
| holdout not worse than +0.002 | ≤ +0.002 | −0.00036 — pass |
| holdout point negative | < 0 | −0.00036 — pass |
| log loss pooled vs C2 | G2h ≤ C2 | 0.5711 vs 0.5758 — pass |
| log loss holdout vs C2 | G2h ≤ C2 | 0.5826 vs 0.5834 — pass |
| calibration pooled | within +0.005 of C2 | 0.0006 vs 0.0010 — pass |
| calibration holdout | within +0.005 of C2 | 0.0040 vs 0.0037 — pass |

**10 of 10 gates pass.**

### Hyperparameters as fitted, and convergence

| quantity | value |
|---|---|
| `lambda_team` / `lambda_conf` / ridge | 9.0 / 156 / 1.0 (frozen) |
| folds converged | 360 (G1) and 360 (G2h), every fold |
| max abs gradient across folds | 9.79e-06 (G1), 9.69e-06 (G2h) |
| median fitted SD of team-season effects `u` | 0.080 |
| median fitted SD of conference means `m` | 0.037 |
| holdout fit: SD `u` / SD `m` / condition number | 0.086 / 0.037 / 60.2 |
| holdout fitted `b` (standardised) | intercept +0.067, points/drive +0.514, turnovers/drive +0.092, start field position −0.039, red-zone TD +0.126, third down +0.041, explosive drive +0.159, penalties −0.018 |

**Declared deviation from §19.4.** The pre-registration asserted `max |grad| < 1e-6`; L-BFGS-B on a
~700-parameter problem stops on line-search precision first, and one fold stalled at 1.006e-05. The
accepted threshold is **1e-5**, with up to three restarts from the stopped point under identical settings
and objective. All 360 folds converged under that rule; no fold was dropped and no gate was relaxed.
Identification is by the prior, and the fitted condition number (60.2) confirms the penalised Hessian is
well conditioned.

The fitted SD of `u` (0.080) is far below the 0.333 prior, which is the expected result of 9–14 games per
team-season: the model shrinks team effects almost to the conference mean and only reports a team effect
when the evidence is strong.

### Pre-declared robustness variant — `lambda_team = 4.0`

| comparison | pooled | holdout | 2026 |
|---|---|---|---|
| G2h − C2 | −0.00271 [−0.00390, −0.00147] | **+0.00020 [−0.00125, +0.00118]** | −0.00302 [−0.00596, −0.00004] |
| G2h − G2 | −0.01948 | −0.02013 | −0.01455 |
| G1 − G2 | −0.00766 | −0.00138 | −0.00553 |

Weaker shrinkage gives a **larger pooled gain and a positive holdout point estimate**, which would fail the
holdout-point gate. The result is therefore prior-sensitive in the holdout and the frozen run at
`lambda_team = 9.0` is the one that is reported and adopted, exactly as pre-registered.

### What this means

The gain is small in absolute terms — 0.0019 Brier, about 1% of C2's edge over G2 — but it is the first
resolvable improvement over C2 in the ladder, and it is negative in every season.

The decomposition matters more than the headline. The hierarchy alone (`G1 − G2 = -0.00473`) supplies about
a quarter of C2's total edge, and the drive features still add `-0.01393` on top of it, against `-0.01677`
over G2 in the flat model. In other words the pooling absorbed roughly 17% of what the drive splits were
doing: some of the "drive performance" signal was really persistent team identity being re-measured every
week.

**The honest caveat.** The frozen holdout does not resolve the effect: `-0.00036 [-0.00154, +0.00042]`. That
is structural, not noise. The frozen holdout fits once through 2024, so no 2025 game informs a 2025
team-season effect; every 2025 team sits at its conference mean and the model collapses toward C2 plus a
conference prior. The gain is produced by **updating team effects within the season**, which the frozen
holdout forbids by construction. The three pieces of evidence therefore say: pooled resolvable, 2026
resolvable, holdout point-negative-but-unresolved. The pre-registered gates accept that; a reader should
not read the holdout as confirmation.

### Ladder status

(g) was the last rung. **G2h becomes the standing game-winner model** (C2 plus team-season random intercepts
nested in conference means, `lambda_team = 9.0`), with walk-forward Brier 0.1946, holdout 0.2001 and 2026
0.1908. The ladder is exhausted; further work should be prospective confirmation on games not yet played,
not another retrospective family.

## 21. Phase 4 pre-registration — final-score distributions

Status: PRE-REGISTERED 2026-10-18, before any Phase 4 model code or any Phase 4 evaluation number.
Branch `feat/fbs-archive` at `cfcdae2f`. `docs/MODEL-CHECKPOINTS.md` is copied into the repo with this
commit.

### 21.0 The five checkpoints, for the model these distributions sit on

| # | checkpoint | status |
|---|---|---|
| **CP1** | baseline established | **passed** — G2 (Elo/margin) and the drive-split C2 scored on 2,397 walk-forward games, with population and sample size stated in §5–§12 |
| **CP2** | candidate validated chronologically | **passed** — G2h walk-forward 0.1946 with a paired week-block interval against G2 and C2 (§20) |
| **CP3** | distribution calibrated | **not passed** — G2h is a win probability only; there is no score distribution to calibrate. Phase 4 is the attempt at CP3 |
| **CP4** | prospective confirmation | not passed — 2026 played games are development data; the only prospective window is future weeks |
| **CP5** | production integration approved | not passed, and not an agent's to grant |

A pass on CP3 requires proper scores **and** calibration on identical observations with the per-observation
PMFs preserved. Phase 4 therefore writes the PMFs it scores, not just aggregates.

### 21.1 The question

G2h ranks winners at 0.1946 Brier. Phase 4 asks whether the same team-strength structure supports a
**score distribution** good enough to price a spread and a total — a different question with a different
failure mode, because the win probability is insensitive to the shape of the score distribution.

### 21.2 Ratings (shared input, as-of, no leakage)

A decayed points rating per team, updated only after a game has been played:

- For each team, `S_for`, `S_against`, `W` start empty. After each game: `S ← S·λ + points`,
  `W ← W·λ + 1`, with `λ = 0.5^(1/6)` (six-game half-life, the same half-life Phase 3 used).
- The rating used for a game is the state **before** the game, snapshotted at the start of each UTC date
  block, so no within-block or same-game information enters a forecast.
- `off_t = log(S_for/W ÷ L)`, `def_t = log(S_against/W ÷ L)`, where `L` is the mean points per team-game
  among prior games. A team with no prior game gets `off = def = 0` plus a `no_history` flag.

### 21.3 Candidates (each produces a joint distribution over (home points, away points))

| id | model | parameterisation | fitted per block on prior games |
|---|---|---|---|
| **H0a** | independent Poisson | `μ_h = exp(α + off_h + def_a + γ/2)`, `μ_a = exp(α + off_a + def_h − γ/2)` | `α` (scaling) and `γ` (home advantage) by Poisson MLE |
| **H0b** | independent over-dispersed | same means; NegBin2 with `var = μ + μ²/R` | `α, γ` as H0a, then `R` by moments `R = Σμ² / Σ((y−μ)²−μ)`, floored at 0.5, on both sides pooled |
| **H0c** | bivariate (correlated) | `X_h = Y1 + Z`, `X_a = Y2 + Z`, `Y1~Pois(μ_h−λ3)`, `Y2~Pois(μ_a−λ3)`, `Z~Pois(λ3)`; marginals stay `Pois(μ_h)`, `Pois(μ_a)` | `α, γ` as H0a; `λ3 = max(0, Cov_train(h, a))` capped at `0.8·min(μ_h, μ_a)` and reported, including whether it hit the floor |
| **H1** | winner-only control | league-average independent Poisson `(μ_h0, μ_a0)` **tilted** by `exp(θ)` on the home-win half so that `P(home wins) = p_G2h`; `θ` solves in closed form because the tilt is a step function on the sign of the margin | `μ_h0, μ_a0` from training league means; no team information at all |

Two further baselines, scored on the same games:

- **Constant** — the same league-average Poisson pair untilted (`θ = 0`). No information beyond the league
  base rates.
- **Prior-season team means** — `μ_h` = the home team's prior-season mean points scored, `μ_a` = the away
  team's, no opponent adjustment, no home advantage, independent Poisson. Teams with no prior season get
  the league mean.

**Primary candidate: H0b.** H0a and H0c are declared alternates. An alternate can only be adopted if it
passes every gate *and* beats H0b on both margin and total CRPS with paired intervals excluding zero. That
rule is fixed now so the choice cannot be made after seeing the table.

**H1 is the control that matters.** Without it there is no way to tell whether a score model learned
anything beyond the winner model it sits on.

### 21.4 Population

Identical to Phase 3, by construction: the games in `research/fbs/phase3-g/forecasts_walk_forward.csv`
plus the frozen holdout ledger — 2,397 walk-forward 2023–25, 807 frozen 2025 holdout, 350 in 2026.
Game 401778314 stays out (it has no CFBD play-by-play). Every model and baseline is scored on exactly the
same game set; a model that cannot produce a forecast for a game is reported as a coverage failure, never
silently dropped.

### 21.5 Metrics

**Point accuracy** — MAE, RMSE and bias (mean predicted − observed, with a week-block interval) for home
points, away points, margin and total, for every model and baseline.

**Distribution quality** — on **margin** and on **total** separately:
- CRPS (discrete, exact from the PMF).
- Log score, `−log P(observed)`.
- Randomized PIT (`F(y−1) + U·P(y)`, `U` drawn from a seeded stream), with a KS test against `U(0,1)`.
- Coverage of the 50/80/90 **central** intervals and of the **shortest contiguous** intervals containing
  the same mass, with the **endpoint-atom excess** reported separately: the share of observations sitting
  on the extreme support edge minus the mass the model assigns there. This is the trap the carries work
  documented — a central interval pins at the support boundary whenever the mass there exceeds the tail
  level, and then it covers more than nominal by construction.
- `sd_pred` against `sd_obs` for both.

**Market-shaped outputs** — scored, never as a bare hit rate:
- Spread: `P(home covers)` for home giving and getting 3, 7, 10 and 14; Brier and log loss per line,
  paired against Constant and against H1.
- Total: `P(over)` at 45, 48, 52, 56 and 60; same treatment.
- Reliability in five bins per line with counts, and the base rate beside it.

**Comparisons** — paired by game, clustered on UTC calendar week (`season + week_start`), 2,000 bootstrap
replicates, seed 20261017, 95% percentile intervals. Same machinery as Phase 3.

### 21.6 Gates (fail-closed)

| gate | requirement |
|---|---|
| **G-SAMPLE** | walk-forward n ≥ 1,500 and holdout n ≥ 250 |
| **G-DIST** | primary beats H1 on CRPS for **margin and total**, paired week-block interval entirely below zero, on the 2,397 walk-forward games; and the point difference is negative on the 807-game frozen holdout for both |
| **G-CAL** | randomized PIT does not reject `U(0,1)` at the 5% level (KS) for margin and total on walk-forward **and** holdout; and central coverage is within ±0.05 of nominal at 50/80/90 for margin and total on walk-forward |
| **G-SPREAD** | beats **both** Constant and H1 on Brier for cover probability, pooled over the eight lines, paired interval entirely below zero on walk-forward, and negative on the holdout |
| **G-TOTAL** | the same test for over/under at the five totals |

Adoption requires all five. A model that wins CRPS and loses PIT is **not adopted** — that is the carries
lesson, and G-CAL is the gate that enforces it here.

### 21.7 What would falsify the whole idea

If H0b fails to beat **H1** on CRPS, then the team-strength structure adds nothing about the score beyond
the win probability it already produces, and the honest conclusion is that G2h's ratings support a winner
model and not a score model. That result would be recorded as the answer, not worked around.

### 21.8 Leakage controls

Ratings from prior games only, snapshotted per date block; every fitted parameter (`α, γ, R, λ3, μ_h0,
μ_a0`, prior-season means) from games strictly before the block; no publisher-derived column; no
season-to-date aggregate that includes the game being predicted; the Phase 1 harness's one-day UTC embargo
unchanged.

### 21.9 Deliverables

- `backend/fbs_phase4_scores.py` — ratings, models, PMFs, metrics, gates.
- `research/fbs/phase4/` — per-observation PMFs for margin and total, per-game parameters, and the metric
  tables, so every aggregate is recomputable from observation level (the discrete-prop contract).
- This section as the pre-registration; results appended as §22.

Phase 5 (play-by-play simulation) and Phase 6 (player props) are explicitly out of scope.
