# Play-call model: reproduction, correction and uncertainty, 2026-10-28

Status: research only. The model is a play-call probability model (dropback or designed run, per play). It is not a player-prop
model, a game-winner model or a coaching-aware model. Nothing here is adopted or promoted into the simulator.

## Summary

- The committed report `PLAYCALL-EVAL-2026-10-28.json` (a9287a03) reproduces from the committed code (c77fd6ec) on an empty cache.
  Every value matches except the run-time fields.
- The scenario table in version 1 was scored with the no_team fit. That was a labelling error. Version 2 scores it with the
  hierarchical_full fit. Only the 27 scenario probabilities change (largest change 0.0054). Every metric, count, penalty and
  recency setting is identical.
- Paired, game-clustered uncertainty is reported for the comparisons against the league prior and the 24-cell baseline, and for
  the contribution of each feature group.
- Team-season residuals still show structure the model does not capture, and the era term cannot follow the league-level drift
  in 2024 and 2025. See the diagnostics section.

## Commits

| Commit | Content |
|---|---|
| a9287a03 | Committed version 1 report (`docs/research/PLAYCALL-EVAL-2026-10-28.json`) |
| c77fd6ec | Model, runner and tests |
| 628f2f91 | Cache fingerprint, real game identities, scenario coefficients from hierarchical_full (version 2), tests |
| (this commit) | Uncertainty and diagnostics, comparison script, version 2 report, this document |

## Commands

Run from `scripts/nfl_sequence` on commit 628f2f91 or later. Outputs go to a scratch directory `$S`.

```
# 1. Cold reproduction of the committed version 1 report (committed code c77fd6ec, empty cache)
python3 -u -I run_playcall_eval.py --out $S/repro/PLAYCALL-EVAL-repro.json --cache $S/repro/playcall-frame-repro.npz

# 2. Compare with the committed report (run-time fields excluded, tolerance 1e-9)
python3 compare_playcall_reports.py ../../docs/research/PLAYCALL-EVAL-2026-10-28.json $S/repro/PLAYCALL-EVAL-repro.json

# 3. Corrected version 2 report (fixed code, empty cache)
python3 -u -I run_playcall_eval.py --out $S/v2/PLAYCALL-EVAL-v2.json --cache $S/v2/playcall-frame-v2.npz

# 4. Paired, game-clustered uncertainty and diagnostics, using the version 2 frame and the committed penalties and recency
python3 -u -I playcall_uncertainty.py --cache $S/v2/playcall-frame-v2.npz --report ../../docs/research/PLAYCALL-EVAL-2026-10-28.json --out $S/v2/PLAYCALL-UNCERTAINTY-2026-10-28.json

# 5. Tests
python3 -m unittest test_playcall_model test_playcall_uncertainty test_playcall_observations test_holdout_2026
```

Results of the checks:
- Step 2: no differences in any value other than run-time fields. Exit 0.
- Step 5: 70 tests, all pass.

## Reproduction result (version 1, committed code, empty cache)

| Stage | Seconds |
|---|---|
| frame (raw join and cache write) | 93.75 |
| design | 1.03 |
| tune (67 fits) | 318.05 |
| tests (16 fits) | 197.69 |
| total | 610.53 |

83 fits and 8,253 L-BFGS iterations, the same counts as the committed run. Output: `$S/repro/PLAYCALL-EVAL-repro.json`,
sha256 `e37b97f9e89048b56e70b256219867b7f0df9db451dcef5002109f9fc9d4067c`. The committed report's sha256 is
`9878b6a136446973f7d595c907a4d7a3c34505ef36e4f00b42ea796c98db6df4`. The two files differ only in run-time fields.

## Correction (version 2)

Defect: `run_playcall_eval.py` passed the no_team ablation coefficients to the scenario table. The scenario probabilities
therefore were not predictions of the full model. The aggregate metrics were computed separately and were not affected.

Fix: the scenario table is scored with the hierarchical_full fit (`evaluate_tests`, tested with a spy that checks the width of
the coefficient vector passed in).

Effect on the committed version 1 report, compared value by value:
- 27 of the 28 scenario probabilities change, all in the 2024 and 2025 blocks. The largest change is 0.0054
  (2025 including flagged plays, tied, 2nd and 6 with 2 minutes left in Q4: 0.6706 to 0.6652).
- Five provenance fields are added (`report_version`, `frame_cache`, `frame_content_sha256`,
  `source_fingerprint_sha256`, `scenario_coefficients`).
- No other value changes. All metrics, slices, team tables, coverage, penalties and recency settings are identical.

Version 2 report: `docs/research/PLAYCALL-EVAL-v2-2026-10-28.json`, sha256
`2e738aeb94fcbfc0f989bbefef4b9b22a7363fac9b8b63c4e60cf801bb326610`. Version 1 stays as committed.

Run time for version 2 was inflated by CPU contention from another session's test run (load average about 12 on 4 cores).
Its stages were: frame 100.7 s, tune 754.6 s (the same 67 fits; all 67 tuning lines are identical to the cold reproduction),
tests 378.6 s, total 1,234.6 s.

## Fixes in 628f2f91

- **Cache fingerprint.** A cache is reused only when its fingerprint matches. The fingerprint covers the builder version, the
  SHA-256 of `playcall_model.py` and `playcall_observations.py`, the season and flag settings, the pinned raw score-source
  SHA-256 values, the score-exception file SHA-256, and the database's size and modification time. A cache without a
  fingerprint is rebuilt. The database is not hashed by content, because that would read every row, including the sealed 2026
  rows.
- **Game identity.** The frame stores real game codes (`Frame.games` maps each code to its `game_id`). Earlier frames stored
  zeros.
- **Scenario source.** As above.

## Provenance (version 2)

Fingerprint stored in the corrected cache, from `playcall-frame-v2.npz`:

- Source fingerprint sha256 `783ba65cbe76a726eb598f2b597b2a42a5ad2e9d452e09d40f5128866c6858c2`
- Frame content sha256 `fc7d65860d9fb2e0a26015455241bfe7ee88a58c9c6902cb05a55ea5fc485e0d` (522,302 scrimmage plays,
  32 teams, 4,175 games)
- Code: `playcall_model.py` `b472cb80eb4aa76f418a68cb3aaf5316ab99a2c694520fca8fdacc1f761acbec`;
  `playcall_observations.py` `5da5737d47f3e1ff1290a22dc06c12202e0ae97afcb020d3044145682d165ed4`
- Score-exception file `docs/fixtures/score-exceptions/score_continuity_exceptions_2010_2025.csv`:
  `77bbc9655929216bfb816bbbb8c044533e4b09bd9c84032088050585c6617b16`
- Database: `/root/legendarypicks/backend/data/picks.dev.db`, 3,432,919,040 bytes, mtime_ns 1793219136014144603 at the time of
  the run. Read-only (`mode=ro`). Not copied.

Raw score sources (pinned SHA-256; the loader checks each file against its pin on every read):

| Season | Source | SHA-256 |
|---|---|---|
| 2010 | `/root/lp-snapshots/nfl-pbp-2010-2021/pbp_2010.csv.gz` (MANIFEST.json) | 6d4f519b4821f06ffe2285faadad8cee718f464eeb9a310a8276753da10bee2e |
| 2011 | same, MANIFEST.json | ffa0bfb803f0c30a4b765af5e621b0f601d695efdba7d6d396fb067d6a0c89b2 |
| 2012 | same, MANIFEST.json | ff1cda2e26610ef8720324e442d1e5ebc24918e08fd1d2933590b7b91a7068cd |
| 2013 | same, MANIFEST.json | b4cd0dc48697ec44a2041d57dfc1c7210a792d1b5be497c161ef20a5b7fb9942 |
| 2014 | same, MANIFEST.json | 4ab286d2873a7eab28e11120f1fe1bd1f0a6bbb6be452f86a76092bd49b2ee4a |
| 2015 | same, MANIFEST.json | 837811471df06c43d55faede7a363274484da11e71f49d8e0801baede3a5965d |
| 2016 | same, MANIFEST.json | dc1703d9aae3ec697ac2787617f82b6f074d0c151e1a54f8217f570a63dcb5ed |
| 2017 | same, MANIFEST.json | 74032964ca6bdfc5bbe186253231a533d2d82aa531fac02b9382da01b3a8b34e |
| 2018 | same, MANIFEST.json | d37899610b397b96a90da6902827de5b46c5457b93e0e16d5f95a8eb524e4a7d |
| 2019 | same, MANIFEST.json | b764668137052be23745953cbc33fa17e537a70c81e9b73785a19a15e7288216 |
| 2020 | same, MANIFEST.json | bc954b5780e325df4faa255fac092585c981a4de5d2f553a8a4e0a3c8b3a3cf2 |
| 2021 | same, MANIFEST.json | e8743a568f99667a8bdcd29ba12224ee1782ad2b7916bee78ee335c099383739 |
| 2022 | `/root/gridiron-playbooks-research/data/raw/pbp_2022.csv.gz` (build_manifest.json) | 0c69a71eb39498956c7b1d5c1ca52ce7fe679934a95d1af249facb5ea9829ea4 |
| 2023 | same, build_manifest.json | 4649804ee0f0a40b41e51ec75a1ce921949d7fab5459213488656b92f78560e8 |
| 2024 | same, build_manifest.json | 23370d5d10f8104d80d46a1fc5e61f4f6f5a3263fe96fe2dd629913cfcb08c06 |
| 2025 | same, build_manifest.json | 2f135887790a013fd004e609e37096bb4816d5cc80b9f19122e1bad478961978 |

Dependencies: Python 3.8.10, numpy 1.24.4, scipy 1.10.1. Random seeds: the model fits are deterministic. The bootstrap uses seed
20261028 with 2,000 replicates.

## Evaluation boundaries

- **Tuning.** Penalties and recency are chosen on 2023 only: fit 2010 to 2022, score 2023. This is 67 of the 83 fits. The
  tests show it: changing the 2024 and 2025 outcomes leaves the chosen penalties and recency unchanged, and changing the 2023
  outcomes changes the validation loss (`TuningIsolation`).
- **Test 2024.** Fit on 2010 to 2023, score 2024. **Test 2025.** Fit on 2010 to 2024, score 2025. Each test is one fit per
  ablation. Chronology is tested (`Chronology`): a test season never enters its own training rows.
- **Development block.** The uncertainty output includes 2023 as a development block, labelled as such. Its results are not
  independent of the penalty choice.
- **Selection history.** The model structure (bucket definitions, penalty groups, the penalty and recency grids, the ablations
  and the scenario list) was fixed before the first test output was printed. The transcript search found no 2024 or 2025
  results printed before the committed run. In that run the penalties were chosen during tuning, before any test output
  printed. No 2024 or 2025 outcome was used to choose a feature, bucket, penalty, recency setting or threshold. Each test season
  is reported from one run. This is a process statement. It is not a machine-enforced guarantee.

## Zero 2026 reads

- **Application level, verified.** The holdout guard refuses any season range that includes 2026 before any query
  (`holdout.refuse_if_holdout`). The observation query is issued once per season from 2010 to 2025, and a trace test records
  every bound parameter: no query asks for 2026, and no 2026 row is yielded (`SeasonBoundary`).
- **Page level, not verified.** The observation query scans `nfl_pbp` through `idx_pbp_game` (`EXPLAIN QUERY PLAN`:
  `SCAN TABLE nfl_pbp USING INDEX idx_pbp_game`). SQLite therefore reads every row, including 2026 rows, on each scan, and the
  `season` filter is applied afterwards. No research code receives or uses those rows. Page-level reads of 2026 rows cannot be
  ruled out with this database. Fixing that needs a 2010 to 2025 extract produced outside this path, or an index on `season`.
  Neither has been done, and the database has not been written to.
- `test_holdout_2026` passes. It builds temporary databases and refuses 2026 before any real read.

## Paired, game-clustered uncertainty

Differences are per-play paired losses averaged over the block. Intervals are 95% bootstrap percentiles over whole games within
the test season (272 games per season). Positive values favour the full model, or the component that is kept.

| Comparison | 2024 log loss | 2024 Brier | 2025 log loss | 2025 Brier |
|---|---|---|---|---|
| Full model vs league prior (reduction) | 0.1190 [0.1141, 0.1241] | 0.0509 [0.0489, 0.0530] | 0.1201 [0.1146, 0.1254] | 0.0513 [0.0492, 0.0533] |
| Full model vs 24-cell baseline (reduction) | 0.0452 [0.0412, 0.0492] | 0.0195 [0.0179, 0.0211] | 0.0437 [0.0397, 0.0479] | 0.0186 [0.0170, 0.0203] |
| Cost of removing score-by-clock interaction | 0.0184 [0.0159, 0.0209] | 0.0073 [0.0063, 0.0083] | 0.0192 [0.0165, 0.0218] | 0.0075 [0.0065, 0.0085] |
| Cost of removing score and clock (main effects and interaction) | 0.0420 [0.0381, 0.0461] | 0.0184 [0.0167, 0.0200] | 0.0395 [0.0357, 0.0436] | 0.0170 [0.0154, 0.0186] |
| Cost of removing team effects | 0.0011 [0.0003, 0.0021] | 0.0004 [0.0000, 0.0008] | 0.0008 [-0.0000, 0.0017] | 0.0003 [-0.0001, 0.0007] |
| Cost of removing season (era) effects | 0.0000 [0.0000, 0.0001] | 0.0000 [0.0000, 0.0000] | -0.0000 [-0.0000, 0.0000] | -0.0000 [-0.0000, 0.0000] |

The 2025 Brier reduction against the 24-cell baseline is about 9.0% (0.0186 of 0.2071), with an interval of 8.2% to 9.8%.

Metric values on the test seasons (primary plays): full model log loss 0.5527 (2024) and 0.5525 (2025); 24-cell 0.5979 and 0.5961;
league prior 0.6717 and 0.6726.

The 2023 development block gives the same ordering (full 0.5516, 24-cell 0.5960, league prior 0.6680). Its cost of removing
the score-by-clock interaction is 0.0204 [0.0176, 0.0231] log loss.

## Feature contributions and why team and era add little

**Score and clock.** The score-by-clock interaction carries about 0.018 to 0.019 log loss and 0.007 Brier. Removing score and
clock together, main effects included, costs about 0.040 log loss. The score main-effect penalty chosen on 2023 is 300, which is
large enough to shrink that group close to zero (individual coefficients were not inspected). Score information therefore
enters mainly through the score-by-clock interaction (penalty 3) and the clock main effect (penalty 0.3). Score and clock are not ablated separately, so this split is not established directly.

**Team.** The team-by-down effect is small: its fitted standard deviation is about 0.15 on the logit scale, and its penalty of
30 was chosen on 2023. The team identity is fixed across 2010 to 2025, so a team's tendency can change only through recency
weighting (tau 3). Removing it costs about 0.001 log loss, and the interval for the 2025 Brier includes zero. The team-season
residual check below shows what the team term does not capture.

**Era (season).** The season effect for a test season is never fitted, because no training row carries that season. Its
coefficient therefore stays at exactly zero when predicting it. The era term can only affect the test season through the
intercepts of earlier seasons. Its measured contribution is zero, as expected. The observed league dropback rate is 0.595 to
0.620 across 2010 to 2025, and it is about 0.60 in 2024 and 2025 (0.603 and 0.601), below the level the model uses. This is the
mechanism, not a finding from the scores.

## Diagnostics: residuals by game

Each block's residual checks use the out-of-sample predictions of the full model. Under no unmodelled effect, the mean squared
team-season z and the league z should be near 1 and 0. Two variances are shown: one treats every play as independent, the other
takes the variance from the games themselves. The game-based version is calibrated when plays share a game effect
(`ClusteredCalibration`). The independent version is not: on the same simulated data it is inflated several-fold (the test
requires more than 2).

| Block | League z (by game) | League z (independent plays) | Mean z² across team-seasons (by game, full) | Share with abs(z) > 2 (by game, full) |
|---|---|---|---|---|
| 2023 development | +0.17 | +0.24 | 2.91 | 0.34 |
| 2024 test | -1.82 | -2.44 | 3.31 | 0.34 |
| 2025 test | -1.80 | -2.45 | 3.04 | 0.25 |

Mean z² by game without the team term: 3.44, 3.39 and 3.46. The team term reduces it slightly in every block.

Reading:
- **Team-season structure remains.** A mean z² near 3 and 25% to 34% of team-seasons beyond two standard deviations, against about
  1 and 5% expected. The model has no team-season term, so a team's play-calling in a particular season (for example after a
  change of play-caller) is not captured. This is the strongest unmodelled structure in these diagnostics. It is the question the
  coaching-aware work needs to answer. Those checks are descriptive, and no fit has been changed.
- **League level drifts in 2024 and 2025.** The league z of about -1.8 in both test seasons means the model predicts more
  dropbacks than were called. That matches the zero season term above. It is borderline by the game-based measure and clearer
  by the independent-plays measure. No correction is applied.

## Limits and unresolved issues

1. The team-season z uses about 17 games per team-season. Its variance estimate is noisy, so the share of team-seasons beyond
   two standard deviations is a rough measure.
2. Score and clock are ablated together and as the interaction. Separate score and clock main-effect ablations are not run.
3. Page-level reads of 2026 rows are not excluded (see Zero 2026 reads). This is the one open integrity issue in the pipeline.
4. The database is identified by size and modification time, not content. A write to it forces a cache rebuild, and the
   rebuilt frame is not compared with the old one.
5. The team, era and team-season results are descriptive. They are not corrected for multiple comparisons.
6. The model does not use coaches, quarterbacks, personnel or any pre-event decision. It does not produce team points or
   player props.
7. Nothing is promoted, and no large simulation has been run.

## Files

- `docs/research/PLAYCALL-EVAL-2026-10-28.json`: committed version 1 report (unchanged)
- `docs/research/PLAYCALL-EVAL-v2-2026-10-28.json`: corrected version 2 report
- `docs/research/PLAYCALL-UNCERTAINTY-2026-10-28.json`: paired, game-clustered uncertainty and diagnostics
  (sha256 `20b9bfbaaf4662c78572855bfb8e807280ecec3f4ce9123ed77cadd5a9151d69`)
- `scripts/nfl_sequence/compare_playcall_reports.py`, `scripts/nfl_sequence/playcall_uncertainty.py`,
  `scripts/nfl_sequence/test_playcall_uncertainty.py`
