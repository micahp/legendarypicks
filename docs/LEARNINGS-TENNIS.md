# Tennis learnings

Append-only log for the tennis model work. Standing rule from Micah: document learnings as they are found.

Each entry has a one-line headline, what is now known, the evidence (artifact, commit and number), and what to stop or
start doing. Nulls and "not established" results are entries too, marked `[null]` or `[open]` in the headline.

Rules for this file:

- Never edit an entry after it is written. A correction is a new entry that names the entry it supersedes.
- A finding without evidence is not an entry. If the evidence is lost, say so inside the entry.
- Dates are absolute. Commits are the commit that holds the evidence on `feat/tennis-track-b-2026-10-18`.

---

## L1. 2026-10-18. The M1 Elo reference reproduces from an independent implementation.

- **Known:** An Elo implementation written from the protocol (start 1500, K = 32, no surface term, update after each
  event-start date group) gives the published M1 numbers on the 2023 to 2026 complete best-of-three main-tour sample.
  This is development data, not a holdout.
- **Evidence:** `research/tennis/match/2026-10-18/elo_m1_independent.py`, output ATP n = 11,777, Brier 0.22802, log loss
  0.64896; WTA n = 13,066, Brier 0.21596, log loss 0.62100. Published values in `docs/TENNIS-MATCH-BACKTEST-2026-10-14.md`
  (Elo 0.22802 and 0.21596). Commit `ce861c23`.
- **Stop:** Quoting the Elo reference from a document without a recomputation.
- **Start:** Citing `elo_m1_independent.py` as the source of the M1 reference. Re-run it after any change to the dev
  match table.

## L2. 2026-10-18. Nine dev locks were written after their matches started, and they are graded.

- **Known:** Nine of the 20 rows in `tennis_model_locks` have `locked_at` later than `start_time`. All nine are
  `tennis-free-daily-v1` for 2026-10-15, all locked at 18:21:44 UTC, 5 to 13 hours after their matches started (starts
  05:20 to 13:20 UTC). ATP 2, WTA 7. All nine are in `tennis_model_grades`: 8 correct, 1 incorrect. The cause is not
  established from the repository.
- **Evidence:** Read-only query on `backend/data/picks.dev.db` on 2026-10-18 comparing `locked_at` and `start_time`.
  Summary in `docs/TENNIS-STATE-2026-10-18.md`, defect D1, commit `ce861c23`.
- **Stop:** Counting dev locks or dev grades as prospective evidence, and computing prospective metrics without a timing
  check.
- **Start:** Marking post-start rows ineligible in the grader (a flag, not a deletion). Requiring `locked_at < start_time`
  before any prospective metric. Never re-lock or backfill a missed match.

## L3. 2026-10-18. The live lock table holds one version per match, and the version changed without a recorded decision.

- **Known:** `tennis_model_locks` has `PRIMARY KEY(league, game_id)`, so it cannot hold a challenger for the same match.
  Its version counts are 13 `tennis-free-daily-v1` (ATP 4, WTA 9) and 7 `tennis-global-surface-elo-blend-v2` (ATP 3,
  WTA 4). The last `free-v1` lock is 2026-10-16 09:22 UTC and the first `blend-v2` lock is 10:56 UTC the same day. The
  brief's snapshot of 2026-10-16 said "one version".
- **Evidence:** DDL and version counts from `backend/data/picks.dev.db`, read-only, 2026-10-18. Defects D2 and D4 in
  `docs/TENNIS-STATE-2026-10-18.md`, commit `ce861c23`.
- **Stop:** Running a second model version through the same table, and changing the live version without a record.
- **Start:** A separate immutable store per version with an input snapshot and hash, the shape the V2 ledger already uses
  (`backend/tennis_v2_research_ledger.py`).

## L4. 2026-10-18. "E2" is a negative-binomial regression, not the simulator, and the dev docs say otherwise.

- **Known:** The E2 model fits an opponent-adjusted negative-binomial regression on service-point counts with
  `scipy.optimize`, and does not import the simulator. Its exposure bias is −0.86 service points (ATP) and −0.30 (WTA).
  The simulator's bias in Gate A was +7.29 (ATP) and +9.23 (WTA). The dev documents
  (`docs/TENNIS-PROPS-BASELINES-2026-10-14.md`, "Reconciliation"; `docs/RESEARCH-tennis-player-projections-2026-10-14.md`,
  lines 109 to 110) call E2 the frozen simulator's exposure. So the Gate A rejection does not cover E2.
- **Evidence:** `backend/tennis_props_exposure.py` on `feat/tennis-props-exposure` (import list; `fit_regression` near
  line 163), with no `tennis_match_sim` import in that file or in `tennis_replay.py`. `research/tennis/props/2026-10-14/
  e2-exposure-diagnostics.json` (`e2_bias` −0.8616 ATP, −0.2971 WTA). Gate A numbers from the baselines document. Commit
  `ce861c23`, defect D5.
- **Stop:** Calling E2 results "simulator results", and applying Gate A to E2.
- **Start:** Naming each model by its version string (`tennis-props-e2-opponent-nb-v1`). Correcting the two dev documents
  in a separate change.

## L5. 2026-10-18. E2 row-level predictions were never saved, so E2 cannot be paired with the Gamma-Poisson rows.

- **Known:** The only E2 outputs are aggregates: `research/tennis/props/2026-10-14/e2-count-mixtures.json`, with 53,284
  ATP sides and 51,018 WTA sides per target over 2019 to 2026. No E2 run directory was found by name in `/tmp` or the
  worktrees. The generator for the X_thin and X_bbin results is uncommitted in
  `/root/lp-tennis-props/backend/tennis_props_count_mixtures.py`. The Gamma-Poisson replay covers 46,216 ATP aces rows for
  2019 to 2026, so the samples differ.
- **Evidence:** The search and file listing recorded in `docs/TENNIS-STATE-2026-10-18.md` (defect D6), commit `ce861c23`.
  The decision section of `docs/TENNIS-PROPS-CALIBRATION-2026-10-18.md`.
- **Stop:** Reporting E2 against Gamma-Poisson as a comparison. Choosing a direct incumbent from aggregates.
- **Start:** Regenerating E2 row-level predictions into `research/` with a manifest, from committed code, before any
  matched comparison.

## L6. 2026-10-18. The Gamma-Poisson replay reproduces from dev code, and the read-only hooks change no score.

- **Known:** All eight published headline values (CRPS and negative log score for P0 and P1 in the four cells) reproduce
  at four decimals when `backend/tennis_props_rate_backtest.py` is re-run with two hooks. The earlier /tmp CSVs are not
  needed to reproduce the headline numbers. A full run takes about 1.5 to 2 minutes per tour.
- **Evidence:** `research/tennis/props/2026-10-16/tennis-p0p1-{atp,wta}.json` against
  `research/tennis/props/2026-10-18/gp_calibration_{atp,wta}.json` (`replay_totals`). Example: ATP aces P1 CRPS 1.9934 and
  NLL 2.6152 in both. Wall time `real 1m35s` ATP and `real 1m46s` WTA, measured with `time`. Peak memory was not measured.
  Commit `d66eafb3`.
- **Stop:** Treating the /tmp row CSVs as the record. Regenerating CSVs without a stated command.
- **Start:** Keeping the JSON summaries in `research/` as the record, and regenerating row files with the command in
  `docs/TENNIS-PROPS-CALIBRATION-2026-10-18.md`.

## L7. 2026-10-18. P1 Gamma-Poisson beats P0 on identical rows in all four cells and in every slice (development evidence).

- **Known:** Paired P1 minus P0 CRPS, with tournament-clustered 95% intervals: ATP aces −0.0571 [−0.0595, −0.0548]
  (n = 70,198, 711 events); ATP double faults −0.0092 [−0.0101, −0.0084]; WTA aces −0.0216 [−0.0228, −0.0205] (n = 77,274,
  609 events); WTA double faults −0.0137 [−0.0149, −0.0122]. The negative log score intervals are also below zero in all
  four cells. The CRPS interval is below zero in 23 of 23 slices per cell, and the negative log score interval in 23 of 23.
  The slices overlap, so the counts describe consistency and are not separate tests.
- **Evidence:** `research/tennis/props/2026-10-18/gp_calibration_{atp,wta}.json`, `slices` and `p1_minus_p0`. Commit
  `d66eafb3`. P1 also has the lowest CRPS of the four replay candidates (P0 and P1, Poisson and Gamma-Poisson) in all four
  cells, checked against `/tmp/tennis-p0p1-{atp,wta}.csv`.
- **Caveat:** The P1 variant was added after earlier outcomes were inspected (`docs/TENNIS-PROPS-BASELINES-2026-10-14.md`).
  This is development evidence, not confirmation.
- **Stop:** Naming P1 the incumbent on this evidence alone. Quoting the intervals without the window and the sample.
- **Start:** Comparing P1 against the best direct baseline on the same rows, which is blocked by L5 and qualified by L8.

## L8. 2026-10-18. The P0 comparator is badly calibrated for ATP aces, so the size of the P1 gain is not yet an estimate of exposure value. [open]

- **Known:** P0 Gamma-Poisson ATP aces has a U-shaped randomized PIT: the lowest decile holds 22.2% of outcomes and the
  highest holds 17.6%. Its 80% coverage is 68.5% and its PIT KS distance is 0.132. P1 is still U-shaped on this target
  (deciles 17.0% and 14.2%, KS 0.080). At 10 or more aces, P0 predicts 10.5%, and 16.0% occur. Whether a better-calibrated
  direct P0 would beat P1 has not been measured.
- **Evidence:** `research/tennis/props/2026-10-18/gp_calibration_atp.json`, `slices.all.p0_gamma_poisson.pit` and
  `threshold_reliability`. For a different sample and possibly a different PIT method, the E2 P0 negative-binomial deciles
  in `research/tennis/props/2026-10-14/e2-count-mixtures.json` are 9.4% to 10.5%. Commit `d66eafb3`.
- **Stop:** Calling the P0 comparator "the best direct baseline" before a matched check.
- **Start:** Including E2 P0 and X_bbin on identical rows before any incumbent claim (see L5).

## L9. 2026-10-18. P1 double faults are close to calibrated on both tours. P1 aces are not.

- **Known:** P1 double faults: PIT KS 0.021 (ATP) and 0.013 (WTA). Tail shares below 0.05 and above 0.95 are 5.9% and 6.0%
  (ATP) and 5.7% and 5.6% (WTA), against 5% nominal. P1 aces: ATP KS 0.080 with tails 10.1% and 9.0%; WTA KS 0.078 with
  tails 8.0% and 7.9%. On WTA aces, P1 predicts 1.35% at 10 or more and 2.77% occur. On ATP aces, P1 predicts 66.4% at
  4 or more and 60.1% occur.
- **Evidence:** `research/tennis/props/2026-10-18/gp_calibration_{atp,wta}.json`, `slices.all.p1_gamma_poisson.pit` and
  `threshold_reliability`. Commit `d66eafb3`.
- **Stop:** Choosing a model from the replay's coverage numbers alone.
- **Start:** Treating PIT and the threshold table as the calibration test. Next work on the ace targets, one change at a
  time, with the hypothesis written first (the brief's rule).

## L10. 2026-10-18. [open] Discrete central-interval coverage disagrees with PIT on double faults. The discreteness explanation is untested.

- **Known:** P1 double-fault coverage at 50, 80 and 90% is 63.6, 87.8 and 95.1 (ATP) and 62.7, 86.3 and 94.1 (WTA). Both
  PIT tests are close to uniform on double faults. Coverage over-states the mismatch because the intervals are discrete
  and must contain at least the nominal mass. I did not isolate this effect (for example, with a continuous
  interpolation), so it remains a hypothesis.
- **Evidence:** `coverage_*` and `pit` fields for the double-fault slices in `gp_calibration_{atp,wta}.json` (commit
  `d66eafb3`), and the reading in `docs/TENNIS-PROPS-CALIBRATION-2026-10-18.md`.
- **Stop:** Reading coverage above nominal as a sign that double-fault intervals are too wide.
- **Start:** Adding a continuous check (interpolated coverage, or coverage from randomized PIT) before drawing that
  conclusion.

## L11. 2026-10-18. Calibration bands must come from the forecast, not the outcome.

- **Known:** The first draft of `gp_calibration.py` banded rows by the observed count. That selects on the outcome, so PIT,
  coverage and paired scores inside a band are not calibration checks. The draft's output was overwritten and is not kept.
  The corrected script bands by quartiles of the predicted P1 mean, with the edges stored in the JSON.
- **Evidence:** Commit `d66eafb3`, `research/tennis/props/2026-10-18/gp_calibration.py` (the comment above the forecast
  quartile code; `forecast_mean_q1` to `forecast_mean_q4` in the JSON). Edges for ATP aces are 3.96, 5.05 and 6.51.
- **Stop:** Any diagnostic that bands on the realized count, including "count size" bands.
- **Start:** Naming every band by the variable it uses, and checking that it is known before the outcome.

## L12. 2026-10-18. Bootstrap interval bounds depended on the random stream. Per-slice seeds fix that, and the effect is small.

- **Known:** The first version drew all slice bootstraps from one random stream, so bounds depended on slice order. Point
  estimates are unchanged. In a session comparison, ATP aces CRPS bounds moved from [−0.05935, −0.05475] to
  [−0.05946, −0.05481], about 0.0001. The superseded JSON was overwritten, so the first version's numbers survive only in
  the session output.
- **Evidence:** Commit `d66eafb3`: `summarise()` seeds each interval with `zlib.crc32` of the slice name. Current
  `gp_calibration_atp.json`, `slices.all.p1_minus_p0.crps` gives [−0.05946, −0.05481].
- **Stop:** One random stream shared across slices.
- **Start:** Name-keyed seeds, and state the seed in the report.

## L13. 2026-10-18. The total-games simulator loses on CRPS in every reported segment (development evidence).

- **Known:** Simulator minus direct CRPS (format, surface and competitiveness): ATP +0.1738 [+0.1453, +0.2036] over 223
  event clusters (11,766 matches); WTA +0.3258 [+0.2990, +0.3545] over 193 clusters (13,062 matches). The simulator's mean
  total is 1.89 games high (ATP) and 2.42 high (WTA). Its deciding-set probability is 47.8% against 36.2% observed (ATP). Those two
  figures come from the table in the document, not from a re-derivation.
- **Evidence:** `research/tennis/total-games/2026-10-16/{atp,wta}.json`, `paired_event_bootstrap_crps_simulator_minus_direct_surface_competitive`
  and `scores.models` (values read today). Commit `762a2201` for the JSON and `76eceedd` for the diagnosis.
- **Stop:** Using the simulator as the total-games incumbent on this population.
- **Start:** Using the direct format distribution as the total-games comparator. Stating the primary score before the
  comparison (see L14).

## L14. 2026-10-18. No direct total-games variant wins every score, so the primary score must be declared first.

- **Known:** The format-only direct distribution has the best negative log score on both tours (ATP 3.0554, WTA 3.0329).
  The format, surface and competitiveness distribution has the best CRPS (ATP 3.3589, WTA 3.2314). The gap in CRPS between
  the two is 0.004 on ATP and 0.015 on WTA. The format-only CRPS is 3.3633 on ATP.
- **Evidence:** `research/tennis/total-games/2026-10-16/{atp,wta}.json`, `scores.models` for `direct_format` and
  `direct_surface_competitive` (read today). Commit `ce861c23`.
- **Stop:** Choosing a "best" direct variant from one score.
- **Start:** Declaring CRPS (or log score) as primary in the document before the run, and reporting the other as secondary.

## L15. 2026-10-18. [null] The standalone point simulator adds no winner information over calibrated Elo on 2022 to 2024.

- **Known:** Raw point-simulator winner Brier is 0.22370, against 0.20691 for calibrated Elo (n = 2,749 matches, 300
  tournament clusters). The paired difference (simulator minus Elo) is +0.0168 with interval [+0.0103, +0.0226]. The
  Elo-informed V2 model is discussed in L16.
- **Evidence:** `research/tennis/point-events/2026-10-16/v2_incremental_comparison.json`, `winner.overall` and
  `winner.paired_vs_elo.raw_point_sim` (read today). Commit `26c8f6f3` on dev.
- **Stop:** Treating the standalone simulator as a winner candidate.
- **Start:** Keeping it as a diagnostic only. Its winner result (this entry) and its total-games result (L13) are both
  negative on this data, so a changed simulator needs a predeclared test before it is used for either.

## L16. 2026-10-18. [open] The Elo-informed V2 winner gain is not established on the pooled sample.

- **Known:** V2 minus calibrated Elo Brier is −0.00137, with 95% tournament-cluster interval [−0.00393, +0.00108]
  (n = 2,749, test years 2022 to 2024, validation 2021). The interval includes zero. The ATP-only point estimate is more
  negative than WTA, but I have not checked its interval against the JSON.
- **Evidence:** `research/tennis/point-events/2026-10-16/v2_incremental_comparison.json`, `winner.paired_vs_elo.v2`
  (read today). Commit `26c8f6f3`.
- **Stop:** Quoting V2's Brier of 0.2055 as an improvement over Elo.
- **Start:** Reporting the pooled interval with every quote. Checking the per-tour intervals in the JSON before saying
  anything about one tour.

## L17. 2026-10-18. The M2 blend is in the live lock table with no validation record on dev.

- **Known:** `backend/tennis_daily_projections.py` at line 242 computes `p = logistic(0.5 * (logit(p_global) + logit(p_surface)))`.
  That is M2, the 50/50 logit average of global and surface Elo. It writes the `tennis-global-surface-elo-blend-v2` locks
  (7 rows since 2026-10-16). Dev has no rolling-validation record for it. The brief's A1 requires that record.
- **Evidence:** The line in `backend/tennis_daily_projections.py` on dev; the version counts in `picks.dev.db`
  (read today); defect D4 in `docs/TENNIS-STATE-2026-10-18.md`, commit `ce861c23`.
- **Stop:** Letting a version write locks before its validation exists.
- **Start:** Writing the rolling-validation record for M2 (A1) before its locks are counted anywhere.

## L18. 2026-10-18. Snapshot counts in the brief decayed within two days.

- **Known:** The brief's dev snapshot of 2026-10-16 said 12 locks, 11 grades and one version. On 2026-10-18 the same
  database has 20 locks, 18 grades and two versions.
- **Evidence:** The counts in `docs/TENNIS-STATE-2026-10-18.md` ("Verified numbers"), read from
  `backend/data/picks.dev.db` on 2026-10-18.
- **Stop:** Quoting a count without its date.
- **Start:** Re-querying counts before any quote, and dating every count in a document.

## L19. 2026-10-18. Code that dev documents cite can exist only on other branches.

- **Known:** Commits not on dev: `feat/tennis-point-model` 43, `feat/tennis-props-exposure` 7, and `docs/tennis-prediction-brief`
  22 (an older brief, 2026-10-14). The E2 replay and the match-simulator backtest, which the dev documents cite, are on
  those branches. The dev brief (2026-10-16) is the authoritative copy.
- **Evidence:** `git rev-list --count dev..<branch>` for each branch, run 2026-10-18. Defect D10 in
  `docs/TENNIS-STATE-2026-10-18.md`, commit `ce861c23`.
- **Stop:** Writing "on dev" for a file without checking.
- **Start:** Checking ancestry (`git merge-base --is-ancestor <commit> dev`) before a document cites a commit or file.

## L20. 2026-10-18. [null] No conflict markers remain in tennis docs, backend or research on dev.

- **Known:** `git grep` for conflict markers across `docs`, `backend` and `research` on dev returns no matches. This
  confirms that commit `0cdad734` (the conflict repair) is in the tree. I did not re-check its line-count claims.
- **Evidence:** `git grep -n -E "^(<<<<<<<|=======|>>>>>>>)" dev -- docs backend research`, run 2026-10-18. Commit `0cdad734`
  (an ancestor of dev).
- **Stop:** Treating the repair as unverified.
- **Start:** Running the same grep before any merge that touches tennis docs.

## L21. 2026-10-18. [null] The first-serve-in gate on ace history removes no rows in this snapshot.

- **Known:** P1 ace history is updated only inside the branch that requires a valid first-serve-in count. In the dev
  database every best-of-three main-tour row with both service-point counts above zero also has both first-serve-in counts
  present: ATP 36,055 of 36,055 and WTA 39,734 of 39,734 (2015 to 2026). So the presence check removes no rows here. The
  range check (0 to service points) was not tested separately. I did not measure any effect on scores.
- **Evidence:** `backend/tennis_props_rate_backtest.py` on dev (the `if valid_count(first) and 0 <= first <= svpt` block
  that contains the `p1["aces"].add` call); the query on `backend/data/picks.dev.db` run 2026-10-18.
- **Stop:** Listing this as an open risk to the aces result.
- **Start:** Re-running the query whenever the match table is reloaded, because the answer depends on the source.

## L22. 2026-10-18. [open] Decile shares suggest the E2 variants are flatter on aces than P1. That is a signal, not a result.

- **Known:** On ATP aces, the E2 X_bbin decile shares run from 8.9% to 10.9%. GP P1 is 17.0% in the first decile and 14.2% in the
  last, with a minimum of 7.7% in the middle. On WTA aces, E2 P0 is 9.6% to 10.5%, and GP P1 runs from 7.7% to 15.3%. On double faults the two families are
  similar. The E2 samples and PIT method differ from the GP replay, and the E2 PIT definition is not in dev.
- **Evidence:** `research/tennis/props/2026-10-14/e2-count-mixtures.json` (`pit.decile_share`) and
  `research/tennis/props/2026-10-18/gp_calibration_{atp,wta}.json`, both read 2026-10-18. Table in
  `docs/TENNIS-PROPS-CALIBRATION-2026-10-18.md`, commit `d66eafb3`.
- **Stop:** Writing that E2 is better calibrated, or that P1 is worse, on this comparison.
- **Start:** Scoring E2 and GP with the same PIT code on the same rows (see L5).

## L23. 2026-10-18. Timing and budget for a full Gamma-Poisson calibration run.

- **Known:** A full run with hooks takes about 1.5 to 2 minutes per tour. The box had 1.5 GB available at the 11:54 check
  and 2.1 GB available just before the ATP run. Peak memory of the script was not measured.
- **Evidence:** `time` output for `gp_calibration.py`, 2026-10-18 (ATP 1m35s, WTA 1m46s). Free memory from `free -h`
  before and during the run.
- **Stop:** Starting several tour runs at once on the shared box.
- **Start:** Running one tour at a time, and measuring peak memory (for example with `/usr/bin/time -v`) before any batch
  job that grows.

## L24. 2026-10-18. The deployed M2 (Elo history from 2020-01-01) is worse than M1 on the rolling table. It is unvalidated in production.

- **Known:** Pooled Brier difference against M1 is +0.01660 [+0.01565, +0.01755] over 79,058 matches, and it is better
  than M1 in only 2 of 12 years (2025 and 2026). ATP +0.01385 [+0.01236, +0.01529]; WTA +0.01905 [+0.01770, +0.02035].
  It fails the pre-declared rule. This confirms defect D4 in the state audit.
- **Evidence:** `research/tennis/rolling/2026-10-18/rolling_summary.json`, `winner`, `paired.both_pooled.M2_live` and
  `years_negative`; `research/tennis/rolling/2026-10-18/ROLLING-TABLES.md`. Protocol in
  `research/tennis/rolling/2026-10-18/PROTOCOL.md`.
- **Stop:** Treating presence in `tennis_model_locks` as validation, which L17 already named.
- **Start:** Pinning each lock version to its history start and to a validation record before it writes locks.

## L25. 2026-10-18. The same blend formula, with Elo history from 2000-01-01, beats M1 pooled, but the gain is ATP only.

- **Known:** Pooled Brier difference against M1 is −0.00120 [−0.00155, −0.00084] over 79,058 matches, better in 12 of 12
  years. Tour split: ATP −0.00218 [−0.00272, −0.00162]; WTA −0.00032 [−0.00081, +0.00014], which is not clear. The
  absolute gain is about 0.12 Brier points. The 50/50 weight is fixed, as specified in the live code, and nothing is
  fitted, so no parameter was tuned on the rolling data.
- **Evidence:** `research/tennis/rolling/2026-10-18/rolling_summary.json`, `winner.paired.both_pooled.M2_2000`;
  `research/tennis/rolling/2026-10-18/diagnostics.json`, `tour_check.winner`.
- **Stop:** Quoting the pooled winner gain as a two-tour result.
- **Start:** Reporting every winner claim with its tour split and interval.

## L26. 2026-10-18. The whole gap between the deployed and validated M2 is the Elo history start. The update population has no effect.

- **Known:** On identical rows, the start effect (2020 minus 2000) is +0.0178 [+0.0169, +0.0187] pooled and +0.00175
  [+0.0011, +0.0024] on 2023 to 2026. The update-population effect (all rows minus rows with a surface) is exactly zero,
  because the 2000 to 2026 main-tour window has no rows with a null surface: 0 of 104,106 ATP and 0 of 105,882 WTA rows
  have a null surface.
- **Evidence:** `research/tennis/rolling/2026-10-18/diagnostics.json`, `winner_effects`; the count query was run on
  `backend/data/picks.dev.db` read-only on 2026-10-18.
- **Stop:** Checking update populations first when a live blend underperforms its backtest.
- **Start:** Checking the history start first. It is the cheapest explanation and, here, the complete one.

## L27. 2026-10-18. [null] The deployed M2 is not clearly worse than M1 on 2023 to 2026, and its gap closes with each year of history.

- **Known:** Against M1, the deployed M2's per-year difference is +0.0375 in 2015, falling to +0.0034 in 2023, +0.0014 in
  2024, then −0.0007 in 2025 and −0.0031 in 2026. On 2023 to 2026 pooled it is +0.00081 [−0.00007, +0.00170], which is not
  a clear loss. The version is not validated because the pooled test over 2015 to 2026 fails, not because 2023 to 2026
  is clearly worse.
- **Evidence:** `research/tennis/rolling/2026-10-18/ROLLING-TABLES.md`, the winner paired table; `diagnostics.json`,
  `winner_vs_M1.M2_2020_all_rows`.
- **Stop:** Calling the deployed M2 "validated after warm-up" on two years of data.
- **Start:** Requiring the full pooled test before any version status is given.

## L28. 2026-10-18. Total games: the competitiveness model is the CRPS incumbent on 2015 to 2026, and its log score is not the best.

- **Known:** Against format-only, the format, surface and competitiveness model is −0.01123 [−0.01333, −0.00887] pooled,
  better in 12 of 12 years. The point simulator is +0.23867 [+0.22687, +0.25142] and is worse in all 12 years. Against the
  format and surface model, the competitiveness model's margin is −0.00936 [−0.01144, −0.00737]. Its log score is
  3.0545, against 3.0498 for format-only, which has the best log score.
- **Evidence:** `research/tennis/rolling/2026-10-18/rolling_summary.json`, `games`; `ROLLING-TABLES.md`, the secondary
  metrics table.
- **Stop:** Choosing a total-games model by log score when CRPS was declared primary before the run.
- **Start:** Showing the secondary metric next to the primary in every table, as the renderer now does.

## L29. 2026-10-18. Aces and double faults: the P1 Gamma-Poisson beats P0 in every year and on both tours.

- **Known:** Pooled margins over P0 Gamma-Poisson are −0.03850 [−0.03930, −0.03774] for aces and −0.01152 [−0.01217,
  −0.01093] for double faults, each better in 12 of 12 years. By tour, aces: ATP −0.05708 [−0.05854, −0.05570], WTA
  −0.02162 [−0.02231, −0.02092]. Double faults: ATP −0.00918 [−0.00979, −0.00856], WTA −0.01365 [−0.01461, −0.01268].
  Selection is not calibration. L8 and L9 still hold.
- **Evidence:** `research/tennis/rolling/2026-10-18/rolling_summary.json`, `counts_aces` and `counts_double_faults`;
  `research/tennis/rolling/2026-10-18/diagnostics.json`, `tour_check`.
- **Stop:** Reading the incumbent selection as calibration.
- **Start:** Doing CP3 (PIT and threshold reliability on the rolling rows) before any count distribution is promoted.

## L30. 2026-10-18. The C0 reference is weak, so a clear win over it says little about exposure.

- **Known:** Every model with player information beats C0 by a wide margin: P0 Gamma-Poisson by −0.31 CRPS on aces and P1
  by −0.35. That makes the reference test easy to pass. The decisive comparisons are among the candidates: P0 against
  P1 is −0.039 on aces and −0.012 on double faults.
- **Evidence:** `research/tennis/rolling/2026-10-18/rolling_summary.json`, `counts_aces.paired.both_pooled` and
  `counts_double_faults.paired.both_pooled`.
- **Stop:** Treating a clear win over C0 as evidence that exposure has value.
- **Start:** Using P0 as the reference when the question is whether exposure adds value.

## L31. 2026-10-18. The rolling pipeline reproduces the published anchors before it reports anything.

- **Known:** The run reproduces M1 Brier on 2023 to 2026 (ATP 0.22802, WTA 0.21596), the simulator's total-games CRPS on
  2023 to 2026 (ATP 3.5327, WTA 3.5572), and the eight Gamma-Poisson CRPS values on 2015 to 2026. It stops on any
  mismatch. None mismatched.
- **Evidence:** the `verification` field for each target in `rolling_summary.json`; the run log in the scratch directory.
- **Stop:** Trusting a new evaluation table before its anchors pass.
- **Start:** Keeping published anchors in every new evaluation script.

## L32. 2026-10-18. [exclusion] E2 cannot be scored on the rolling table. Its count generators exist only uncommitted.

- **Known:** The published E2 aggregates come from two generators that exist only uncommitted, in
  `/root/lp-tennis-props/backend/tennis_props_count_mixtures.py` and `tennis_props_diagnostics.py`. No backend file on any
  of the 104 local branches mentions `X_bbin`, `X_thin` or `e2_mae`. Under the E2 rule the count distributions cannot be
  recomputed from committed code, so E2 is excluded. I did not refit it.
- **Evidence:** `git grep -E "X_bbin|e2_mae|X_thin" <104 local branches> -- backend`, which returned no matches, run
  2026-10-18; the two uncommitted files listed above.
- **Stop:** Citing the E2 aggregates as reproducible.
- **Start:** Committing a generator, with its frozen parameters, before any E2 comparison.

## L33. 2026-10-18. Moving the total-games histogram start from 2022 to 2000 shifts the old window by at most 0.003 CRPS.

- **Known:** On 2023 to 2026, the direct results move from the earlier document to this run: ATP format 3.363 to 3.366, ATP
  competitiveness 3.359 to 3.360, WTA format 3.246 to 3.247, WTA competitiveness 3.231 to 3.229. The simulator is unchanged
  at 3.5327 and 3.5572. The selection margins (0.009 and up) are larger than these shifts.
- **Evidence:** `research/tennis/rolling/2026-10-18/rolling_summary.json` (records for 2023 to 2026), against
  `research/tennis/total-games/2026-10-16/{atp,wta}.json` and `docs/TENNIS-TOTAL-GAMES-BACKTEST-2026-10-16.md`.
- **Stop:** Changing a history start without measuring its effect on the window already reported.
- **Start:** Stating the old-window sensitivity in the report, as the rolling report does.

## L34. 2026-10-18. A verifier that has not passed on a known-good case can report false failures. Check it first.

- **Known:** My first integrity check reported mixed years in every target, including the winner rows, where each cluster
  has exactly one row. The bug was in the check: the minimum was initialised to zero, so it could never rise. With the
  check corrected, 0 of 79,058 winner clusters, 0 of 70,216 total-games clusters, and 0 of 73,736 and 73,727 count clusters
  mix years or tours.
- **Evidence:** the corrected integrity check, run on the saved arrays under the scratch records directory, 2026-10-18.
- **Stop:** Reading the output of a verifier that has not been run on a case where the answer is known.
- **Start:** Running every new check on a case with a known answer first, such as singleton clusters, before reading it.

## L35. 2026-10-18. The total-games simulator is the slow stage of the rolling build. Run it in the background.

- **Known:** The process had used 5 minutes 42 seconds of CPU at the first check, about 5 minutes after launch, and 12
  minutes 13 seconds at the second, with the total-games stage still running. The full build ran for roughly 25 to 30
  minutes of wall time. That is approximate, because the run was not timed. The count stage is fast, because it streams
  the replay instead of holding its rows in memory.
- **Evidence:** `ps` CPU readings during the run on 2026-10-18; the run log.
- **Stop:** Running the full build in the foreground.
- **Start:** Running it in the background and polling the log, and writing per-row arrays to a scratch directory.

## L36. 2026-10-18. The selected margins survive tournament clustering, and the rebuild with tournament clusters reproduced the first run exactly.

- **Known:** The winner margin, the one with the narrowest interval, is −0.00120 [−0.00161, −0.00080] with 1,355
  tournament clusters, against [−0.00155, −0.00084] with match clusters. The total-games margin is [−0.01159, −0.00723]
  with tournament clusters, the aces margin [−0.04023, −0.03686] and the double-faults margin [−0.01235, −0.01079]. The
  second build, which added tournament ids, reproduced every pooled, per-year and selection number of the first build,
  and every verification anchor passed.
- **Evidence:** `research/tennis/rolling/2026-10-18/rolling_summary.json`, `paired_tournament` and
  `selection.margin_top_minus_runner_up.tournament_ci95`; a comparison of the first and second summaries, both in the
  scratch directory, showed no difference above 1e-12.
- **Stop:** Assuming that the match-clustered interval is the conservative one. Tournament clustering is wider here.
- **Start:** Computing the tournament interval beside every match-clustered interval, as the protocol already requires.

## L37. 2026-10-19. [null] On WTA, M2 on 2000 history does not clearly beat M1. The winner incumbent is ATP only.

- **Known:** On WTA, M2 on 2000 history minus M1 is −0.00032 [−0.00079, +0.00016] over 2015 to 2026 (41,862 matches),
  negative in 9 of 12 years. For 2020 to 2026 it is −0.00014 [−0.00085, +0.00055], negative in 4 of 7 years. On ATP
  the same margin is −0.00218 [−0.00273, −0.00164], negative in 12 of 12 years. WTA keeps M1 by rule 4. That is a
  default, not a validation.
- **Evidence:** `research/tennis/rolling/2026-10-19/a1_per_tour.json`, `tours.wta.paired_vs_M1` and `tours.wta.windows`
  (commit `ad582786`); `docs/RESULTS-tennis-incumbent-a1-2026-10-19.md`.
- **Stop:** Reading the pooled winner incumbent of 2026-10-18 as applying to both tours.
- **Start:** Reporting the incumbent per tour for every target, with the same thresholds.

## L38. 2026-10-19. The lock label `tennis-global-surface-elo-blend-v2` now covers two surface rules.

- **Known:** All 15 resolved v2 lock rows (prod 8, dev 7) reproduce the 50/50 logit blend with a Hard surface, to 1e-9.
  Through 2026-10-18 every v2 row is on Shanghai (315) or Wuhan (381). The first row on another event, Ningbo (963),
  was locked on 2026-10-19 at 09:38:33 UTC in prod and 10:56:05 UTC in dev. It uses a surface that only `ae5cb074`
  adds. The label did not change in `ab0080b7` or `ae5cb074`, so one label now names two forecasts.
- **Evidence:** `research/tennis/lock-audit/2026-10-19/lock_audit.json`; `git show ab0080b7 -- backend/tennis_daily_projections.py`
  and `ae5cb074` (no `modelVersion` line changed in either).
- **Stop:** Treating a label as the identity of a forecast rule.
- **Start:** Changing `modelVersion` in the same commit as any change to the winner rule, and checking a lock's rule with
  `research/tennis/lock-audit/2026-10-19/lock_audit.py` before calling it a version.

## L39. 2026-10-19. The rolling "M2 as deployed" is not the rule that wrote the locks through 2026-10-18.

- **Known:** `rolling_origin.py` gives deployed M2 a surface term on every main-tour row. The live rule through
  2026-10-18 applied one only on Shanghai and Wuhan. Sackmann rows carry no ESPN event id, so the narrow rule could not
  be scored. Neither form passes rule 1. Deployed M2 minus M1 is +0.01385 on ATP and +0.01905 on WTA.
- **Evidence:** `docs/RESULTS-tennis-incumbent-a1-2026-10-19.md`, "Lock table" section; `research/tennis/rolling/2026-10-19/a1_per_tour.json`.
- **Stop:** Assuming the rolling M2 matches the live rule before `ae5cb074`, or scoring a model by its label.
- **Start:** Writing the live rule's surface coverage into the protocol before scoring it.

## L40. 2026-10-19. [open] A dev lock carries the v2 label before any committed v2 code, and its rule cannot be checked.

- **Known:** Dev game 185369 (WTA, Wuhan), locked 2026-10-16 at 10:56:06 UTC, carries the v2 label. The first commit with
  the label, `396d78d6`, is 2026-10-16 20:22 UTC, and no committed backend code has it earlier. The row stores no
  player identity, so its rule cannot be tested. The probability matches the prod v1 row for the same match.
- **Evidence:** `research/tennis/lock-audit/2026-10-19/lock_audit.json` (dev records);
  `git log -S 'tennis-global-surface-elo-blend-v2' --all -- backend`.
- **Stop:** Assuming every v2 lock came from committed code.
- **Start:** Recording the code state (commit or working tree) with each lock, or a rule hash.

## L41. 2026-10-19. [open] Adding ATP and WTA 500 coverage left the winner population unchanged, and its counts are not reconciled.

- **Known:** The winner population is 37,196 ATP and 41,862 WTA matches, the same as the 2026-10-18 run. The Sackmann
  `A` level holds both the 250 and the 500 events, so 500s were already in the history. The 500 commits (`ae5cb074`,
  `745549da`) store draws and scoreboards, and none of their files is a match-table loader. Reconciling the ESPN 500
  draws with the Sackmann 500 rows is not done.
- **Evidence:** `research/tennis/rolling/2026-10-19/a1_per_tour.json`, `population`; `git show --stat ae5cb074 745549da`.
- **Stop:** Adding draw-level 500 rows to any match table before the counts are reconciled.
- **Start:** Reconciling the two 500 sources (ESPN draws and Sackmann `A` rows) by tournament before any 500 row is used.

## L42. 2026-10-19. [null] A well-calibrated forecast can still lose on Brier, so calibration does not select the incumbent.

- **Known:** Deployed M2 has a calibration slope of 1.00 on ATP for 2020 to 2026 (interval 0.95 to 1.05), which is
  better than M1 (0.72) and M2 on 2000 history (0.81). On WTA its slope is 1.18, so it is underconfident, and its Brier
  is the worst of the three. The protocol does not use calibration for selection, and it does not change any margin.
- **Evidence:** `research/tennis/rolling/2026-10-19/a1_per_tour.json`, `tours.*.calibration`; table "Calibration" in
  `docs/RESULTS-tennis-incumbent-a1-2026-10-19.md`.
- **Stop:** Reading a good calibration slope as evidence that a model should be the incumbent.
- **Start:** Reporting calibration beside every paired margin, as this run did, and keeping it out of selection.

## L44. 2026-10-19. [open] On this branch, shadow M2 and M1 agree on every upcoming match, because the surface map covers two events.

- **Known:** All seven upcoming tennis matches in the store are BNB Ningbo Open (event 963), which the surface map does not
  cover. For them, the m2-2000 and m1-elo forecasts agree to about 1e-16, so the shadow comparison is uninformative until
  the map covers the tour's events. The dev branch's broader map (`ab0080b7`, `ae5cb074`) is not on this branch.
- **Evidence:** `docs/TENNIS-SHADOW-2026-10-19.md`, row table; `research/tennis/shadow/2026-10-19/acceptance_write.json`.
- **Stop:** Reading the shadow m2-2000 row as independent evidence on unmapped events.
- **Start:** Settling the surface coverage for the shadow before the first graded comparison, and counting only mapped
  matches as evidence for m2-2000.
