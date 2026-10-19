# Discrete-prop learnings

## Frozen parameter summaries must retain full precision and distribution outputs

**Known:** B0 can be regenerated exactly from a frozen dispersion parameter and stable input snapshot;
v2 Zf cannot be reproduced to the required tolerance when its recent-form probabilities are stored at
four decimal places. The v3/v4 summaries omit required probability parameters, and v4 also stores rounded
interpolation centers. Aggregate tables cannot recover the original per-observation PMFs.

**Evidence:** B0 at source commit a9a46bd05ee75456ee906a6f1254ab5176084f13 matched all five stored
2025/2026 CRPS, MAE and central-coverage checks with maximum absolute difference below 5e-15 on 2,500
and 489 observations. The saved v2 Zf parameters missed CRPS by −4.51e-6 in 2025 and −2.55e-6 in
2026. See the recovery report and the universal discrete-prop artifact contract on branch
research/discrete-prop-eval-2026-10-18.

**Action:** Stop treating rounded fit summaries as sufficient frozen parameters. Preserve full-precision
parameters and observation-level PMFs/CDFs with checksums before scoring future experiments.

## v1–v4 rebuild the same keyed evaluation population

**Known:** The frozen population builders in all four source commits produce the same duplicate-free
player-game keys and game counts: 2,500 observations / 240 games for 2025 and 489 / 48 for 2026. The v2
candidate score mismatch therefore occurs despite matching reconstructed population counts; it does not
justify silently substituting another sample.

**Evidence:** check_frozen_population.py ran each source commit (v1 24d793c6, v2 a9a46bd0, v3 d7aaeb77,
v4 fc6dba4b) against input snapshot
6fd3d9ab55751108ab279f91aa7130d71c52c1352f7c83de798aef7d47395b45; output is summarized in the
recovery report on branch research/discrete-prop-eval-2026-10-18.

**Action:** Start recording and asserting population keys and counts independently from score reproduction
for every model version. Continue to stop candidate scoring whenever either check fails.

## The frozen 2026 retrospective population ends before the prospective v1 window

**Known:** All v1–v4 builders have the same keyed 2026 population, and this snapshot contains rows only
for weeks 3–6. No weeks 7–18 observations entered the retrospective rerun, preserving the prospective
v1 window's independence.

**Evidence:** check_frozen_population.py produced common 2026 key hash
6114bbcfea73df3cc6ed0a3cb310e9496cef7200c4800f16d906b4921b6cacbb, with weekly counts 156/169/155/9
for weeks 3/4/5/6 and none in weeks 7–18; see the recovery report on branch
research/discrete-prop-eval-2026-10-18.

**Action:** Keep prospective weeks outside retrospective score commands, and verify the realized week
range against the frozen plan before producing any forecast ledger.

## Near-nominal central coverage can be cancellation, while PIT and zero-event checks expose the miss

**Known:** For recovered 2025 B0, central-50 coverage is 0.5428, but the forecast mass inside those sets
averages 0.6578; a +0.1578 set-mass excess and −0.1150 empirical coverage residual combine to the
observed coverage. Mean P(0) is 0.1726 against a zero rate of 0.3788 (game-clustered gap 95% CI
[−0.2205, −0.1928]), while randomized-PIT KS D is 0.1335 (game-clustered 95% CI [0.1198, 0.1486]).

**Evidence:** The keyed B0 PMF/CDF exports, exact decomposition table and seeded PIT/bootstrap results
are in the recovery report and its checksummed external manifest on branch
research/discrete-prop-eval-2026-10-18.

**Action:** Stop reading near-nominal central coverage by itself as evidence of calibration. Start
reporting event reliability and PIT beside interval coverage, and show the predicted set-mass excess and
empirical coverage residual separately. Future experiments must preserve these inputs under the
discrete-prop artifact contract.

## The production NFL prop endpoint is not the v2-platt model

**Known:** On 2026-10-19 the production backend exposed the unversioned player-history projection route;
the NFL-specific v2/v2-platt route returned 404. Production player_projections rows were labeled v2,
marcel-lite and espn-weekly, but the served legacy route reads player_game_logs instead. The production
database had no v2-platt calibration table; those maps were present in picks.dev.db only. Neither the
legacy output nor the versioned candidate path preserved a full per-observation PMF/CDF artifact.

**Evidence:** See SERVED-MODEL-RECONCILIATION-2026-10-19.md for the container digest, live API checks,
production/development DB queries, contract verdict and market-specific scores.

**Action:** Establish the deployed reader and inspect its stored inputs before attributing any evaluation
score to the live site. Do not start prospective grading until the forecast, full PMF/CDF, cutoff,
provenance and outcome state are frozen per observation. Do not add a carries candidate until those
reproducible artifacts exist.
