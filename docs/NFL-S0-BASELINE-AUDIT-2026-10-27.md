# S0 baseline audit (2026-10-27)

Status: research, dev only. S0b is built and evaluated once on the fixed splits. S0a (replay of the existing Legendary
Picks model) is not started. No production output, forecast or simulator default is changed. The 2026 season is not read.

## 1. S0b: the simple chronological baseline

Definition (`scripts/nfl_sequence/splits/s0_baseline.py`):

- Regular-season games, 2010 to 2025, with final scores. Ties are excluded from the binary metrics and counted.
- A team's prior margin is its mean points margin in earlier weeks of the same season. Games in the same week never count.
- A game is scored only if both teams have at least 4 earlier games in the season. Other games are an unscored stratum.
- P(home win) = sigmoid(b0 + b1 * (home prior margin - away prior margin)). b0 and b1 are fitted once, by maximum
  likelihood, on 2010 to 2017 only.
- Validation: 2018 to 2020. Test: 2021 to 2025. The fitted model is not refitted or tuned on either window.
- Comparators: a constant 0.5 forecast, and a home-only forecast equal to the fit-window home win rate.

Fitted values: intercept +0.3025 (home advantage in logit), margin slope +0.0840 per point. Fit games 1,522.

### Coverage (regular season, scored share)

| Seasons | Scored share | Ties (per season) |
|---|---|---|
| 2010 to 2020 | 74.2% to 75.0% (256 games a season) | 0 to 2 |
| 2021 to 2025 | 76.4% to 76.5% (272 games a season, 17 weeks) | 0 to 2 |

The unscored share is the early season by rule (about the first four weeks for each team). It is reported, not filled.

### Results

| Window | Games (scored, no ties) | Model | Brier | Log loss | Calibration slope |
|---|---|---|---|---|---|
| Validation 2018 to 2020 | 573 | S0b | 0.2200 | 0.6304 | 0.964 |
| | | Home-only | 0.2487 | 0.6906 | undefined (constant) |
| | | Constant 0.5 | 0.2500 | 0.6931 | undefined (constant) |
| Test 2021 to 2025 | 1,037 | S0b | 0.2259 | 0.6431 | 0.862 |
| | | Home-only | 0.2480 | 0.6892 | undefined (constant) |
| | | Constant 0.5 | 0.2500 | 0.6931 | undefined (constant) |

Brier difference, S0b minus home-only, with a 95% interval from a bootstrap that resamples whole weeks (2,000 draws):

- Validation: -0.0287, interval [-0.0407, -0.0163].
- Test: -0.0222, interval [-0.0310, -0.0132].

Both intervals exclude zero, so the margin information improves on home-only in both windows.

### Calibration gate

The plan (section 6, rule 3) requires a calibration slope between 0.9 and 1.1 and no reliability bin with at least 30
games missing its mean by more than 0.10. S0b fails both parts on the test window: the slope is 0.862, and the 0.2 to 0.3
bin (61 games) misses by 0.115. Reliability on the test window, bins with at least 20 games (bin, n, mean forecast,
observed home win rate):

- 0.2 to 0.3: n 61, forecast 0.262, observed 0.377.
- 0.3 to 0.4: n 113, forecast 0.353, observed 0.336.
- 0.4 to 0.5: n 171, forecast 0.455, observed 0.380.
- 0.5 to 0.6: n 238, forecast 0.551, observed 0.563.
- 0.6 to 0.7: n 197, forecast 0.650, observed 0.619.
- 0.7 to 0.8: n 165, forecast 0.748, observed 0.703.
- 0.8 to 0.9: n 70, forecast 0.843, observed 0.829.

The forecasts are too spread out on the test window: the low bins are too confident, and the middle bin is too high.
This is a property of S0b, and it is the calibration the plan must correct before any situational variant is compared.

### Controls

- No leakage: prior margins use earlier weeks only. `test_s0_baseline.py` checks that a week 5 margin is not in the week 5
  forecast (the expected value is 5.25, and including the week 5 margin would give 5.7).
- The fit window does not include the validation or test seasons. The test window was not used to choose the splits or
  the model form.
- 2026 is not read. `load_games` filters to 2010 to 2025.

### Disclosure: prior exploration of 2022 to 2025

The research has already looked at situational relationships on 2022 to 2025 data. The validation and test windows
therefore are not untouched confirmation samples for any situational variant. S0b itself was specified before these
results and fitted only on 2010 to 2017, so its numbers are independent of that exploration, but a situational variant
tested on 2021 to 2025 is not.

## 2. S0a: replay of the existing model (LP v1 points, feasible and run)

The existing model with a historical replay is the frozen v1 walk-forward: `backend/nfl_backtest.py` with
`nfl_ratings.py` and `nfl_ratings_data.py` (read-only). `backtest_season` projects each week 2 onward using only scored
regular-season games of earlier weeks in the same season, plus a prior from the final fit of the previous season
(`prior_for_season`). Audit results:

- **Training.** `training_games(scored, before_week)` keeps only rows with week below the target week. Same-week games are
  excluded.
- **Prior.** `prior_for_season(season)` fits season minus one in full. That season is past, so no future results enter.
- **Team list.** `teams_in_season` reads the season's schedule to list team codes. It is identity, not results.
- **Market.** The de-vigged moneyline is attached to each row for evaluation only. It is not a model input.
- **Caveats.** Stored schedule scores are assumed not revised after kickoff (not verifiable here). v1's parameters (half-life
  6, cap 14, sigma 13.295) were set earlier on this 2010 to 2020 history, so its score there is not fully independent.
  The first week with a forecast is week 2, and 2010 has no prior.

The replay was run in this pass with `s1_s2_models.py`. On the 2010 to 2020 ladder cohort it reproduces the existing
benchmark numbers exactly (LP v1 0.2217, closing market 0.2104, 538 Elo 0.2193, home only 0.2467). Results are in
`NFL-S1-S2-RESULTS-2026-10-27.md`.

Not audited in this pass: `backend/nfl_epa_model.py` (LP v2 EPA, which needs play-level EPA with its own time basis) and
`backend/nfl_sim.py` and related simulator files (the season simulator, which is not a single-game winner model). A replay
of v2 needs its inputs listed and dated first. Until then, no v2 number is reported as a historical replay.

## 3. Data licensing for the nflverse backfill (staged, research only)

The reviewer's note said most nflverse datasets are CC BY 4.0 and FTN data is separately licensed. A search in this pass
found a different picture, so the claim was not used:

- FTN charting data: CC-BY-SA 4.0 with attribution to FTN Data via nflverse, credited for 2023 onward in the nflreadr release
  notes. The ShareAlike term applies to derivative works. Source: the nfl_data_py documentation (https://github.com/nflverse/nfl_data_py)
  and the nflreadr release notes (https://github.com/nflverse/nflreadr/releases).
- The nflversedata package, which stores the nflverse data releases, lists CC BY 4.0 (R-universe listing,
  https://nflverse.r-universe.dev/api/packages/nflversedata).
- The R code and the Python package are MIT licensed. The league data they access remains under the rights holders' terms.
- No search result gave a license for the play-by-play dataset itself.

Status: staged for research. The user has found the licence and confirmed that FTN data may proceed. The extract covers
penalty and return fields for 2010 to 2026, with hashes pinned in `NFL-PBP-BACKFILL-STAGING-2026-10-27.md`. Nothing from the
backfill goes into a production database, and no team box score has been rebuilt from it yet.

## 4. What these numbers do not answer

- Whether situational conditions lower the Legendary Picks game-winner Brier score on the identical games. The
  answer for the first situational groups is in `NFL-S1-S2-RESULTS-2026-10-27.md`: none of them improved out of sample.
- Margin distribution scores (CRPS). Computed for S0b, S1, S2 and the LP v1 replay on the same games (same document).
- A comparison with the market as an input. Market prices are evaluation benchmarks, never model inputs.

## 5. Next steps

1. Calibrate S0b on the validation window only (for example a recalibration map fitted on 2010 to 2017 and checked on 2018 to 2020), then re-run the test window once with the fixed recalibration.
2. Audit the LP v2 EPA model (`backend/nfl_epa_model.py`) for historical replay: its inputs and their time basis.
3. Done in this pass: S1 (opponent-adjusted strength) and S2 (calendar, rest, travel, division) on the same splits and metrics, see `NFL-S1-S2-RESULTS-2026-10-27.md`.
4. Validate the staged penalty fields against the team box score rebuild (done for penalties, `NFL-PBP-BACKFILL-STAGING-2026-10-27.md`), then rebuild as a new store version.
