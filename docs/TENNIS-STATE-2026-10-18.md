# Tennis state audit, 2026-10-18

- **Scope:** each build-order item in [BRIEF-tennis-prediction-model.md](BRIEF-tennis-prediction-model.md) (dev revision
  2026-10-16), checked against code, artifacts, commits and the dev database.
- **Method:** read-only. The dev database was opened with `mode=ro` and `query_only`. Headline numbers were re-derived
  from artifacts or re-run from dev code. Nothing was written to a database, deployed, or pushed.
- **Branch:** `feat/tennis-track-b-2026-10-18`, worktree `/root/lp-tennis-track-b`, created from dev `7dd1b62b`.
- **Companion report:** [TENNIS-PROPS-CALIBRATION-2026-10-18.md](TENNIS-PROPS-CALIBRATION-2026-10-18.md) (Track B item 1).

## Summary

1. **Track B item 1 (direct ace and double-fault incumbent) is partial.** The Gamma-Poisson P1 beats P0 on identical rows
   in every cell, but both families still need a matched comparison, and the E2 family cannot be put on the same rows
   from persisted artifacts. No incumbent is selected.
2. **Track B item 2 (total games) is complete as development evidence.** The paired CRPS result reproduces from its JSON.
   It is not prospective confirmation.
3. **Prospective grading does not match the brief.** Nine of the 20 locks in the dev lock table were written after their
   match started. They are graded and counted. They must be excluded from any prospective metric, and must not be
   re-locked or backfilled.
4. **Two model versions now write to one lock table.** `tennis-global-surface-elo-blend-v2` (the 50/50 Elo logit blend,
   M2) has been locked since 2026-10-16. Nothing on dev records its validation. The brief said "one version".
5. **The "E2" experiment is mislabelled in the dev docs.** They call it the frozen simulator's exposure. The code is a
   negative-binomial regression on service-point counts, on another branch. The Gate A rejection of the simulator does
   not cover it.
6. **M1 reference verified independently:** ATP Brier 0.22802 (n = 11,777) and WTA 0.21596 (n = 13,066), matching the
   published 0.2280 and 0.2160.
7. **Much of the tennis work is not on dev.** Track A and Track B code sits on two unmerged feature branches and in
   uncommitted worktrees (section "Work outside dev").

## Build-order map

Status key: **done** = complete against the brief's own requirement; **partial** = some of it exists, with the gap named;
**not started** = no artifact that meets the requirement.

### Track B: player projections

| # | Build-order item (brief) | Status | Evidence | Missing against the brief |
|---|---|---|---|---|
| B1 | P0/P1 ace and DF results consolidated, including the E2 variants and the direct-exposure challenger. Frozen variants compared on identical dates. Calibration finished. One direct incumbent per tour. | **partial** | Consolidation note: `docs/TENNIS-PROPS-BASELINES-2026-10-14.md`, "Gate B disposition" (dev, `762a2201`). Gamma-Poisson replay: `backend/tennis_props_rate_backtest.py` (dev, `762a2201`). E2 aggregates: `research/tennis/props/2026-10-14/e2-count-mixtures.json` and `e2-exposure-diagnostics.json` (dev, `762a2201`). Today: `research/tennis/props/2026-10-18/` (identical-row calibration, GP family). | (a) E2 row-level predictions were never persisted. The E2 replay (`tennis_replay.py`, commit `26274d1b` on `feat/tennis-props-exposure`) and the count-mixture generator (`backend/tennis_props_count_mixtures.py`, uncommitted in `/root/lp-tennis-props`) are not on dev, so the E2 family cannot be scored on the GP family's rows. (b) PIT and calibration were finished only for the GP family. (c) No incumbent selected. |
| B2 | Total-games historical comparison, complete on the evaluated ATP/WTA best-of-three sample. Direct distributions beat the simulator on CRPS and MAE. Prospective confirmation to follow. | **done** (development evidence) | `backend/tennis_total_games_backtest.py` and `docs/TENNIS-TOTAL-GAMES-BACKTEST-2026-10-16.md` (dev, `762a2201`). Aggregates `research/tennis/total-games/2026-10-16/{atp,wta}.json` (dev, `762a2201`). | Verified today from the JSON (section "Verified numbers"). Still open: prospective confirmation; row-level CSVs were temporary `/tmp` files; the 10-point deciding-tiebreak rule for 2022-onward Grand Slam rows is cited to web pages that were not re-checked. |
| B3 | Prospective grading: immutable pre-match forecasts, per-target versions, full distributions, daily and cumulative reports. | **partial** | Dev lock table `tennis_model_locks` (PK `league, game_id`) and grades `tennis_model_grades` in `backend/data/picks.dev.db`, queried read-only. Separate ledger `backend/tennis_v2_research_ledger.py` (commit `26c8f6f3`, hardened `7cdf95fb`), scheduled in `backend/ingest_registry.py`, writing `backend/data/tennis_v2_research.sqlite3`: 6 forecasts with full total-games distributions, 4 grades, all forecasts locked before start. | See defects D1 to D4. No cumulative report; no Brier or log score for winners in the dev grader; no per-target version separation; no input snapshot in the lock table. An uncommitted grader (`tennis_forecast_ledger.py` in `/root/lp-tennis-forecast-grading`) is not on dev and was not run. |
| B4 | Diagnose total-games overprediction from the segment review. State a hypothesis before any change. | **partial** | Structural decomposition in `docs/TENNIS-TOTAL-GAMES-BACKTEST-2026-10-16.md` (sets per match, deciding-set gap, games per set, tiebreak frequency), dev `762a2201`; commit `76eceedd` "Diagnose tennis simulator match length bias" on dev. | No causal hypothesis and no test on verified point sequences. The point-event analysis in `research/tennis/point-events/2026-10-16/` exists on dev but was not reviewed for this audit. |
| B5 | Improved or event-labeled simulator, tested against predeclared direct baselines. Shared variation only if supported. | **not started** (as a gated test) | V2 research challenger (`26c8f6f3`): `research/tennis/point-events/2026-10-16/v2_incremental_comparison.{md,json}`. | No predeclared comparison for a changed simulator. V2 is a separate challenger scored on 2022 to 2024 (validation 2021). Shared variation (P3) has no code. |
| B6 | Sportsbook lines, after calibrated probabilities exist. Timestamped, one benchmark only. | **not started** | Display code only: `backend/tennis_bovada_odds.py`. | No timestamped line history is used for evaluation. |

### Track A: match outcomes

| # | Build-order item (brief) | Status | Evidence | Missing against the brief |
|---|---|---|---|---|
| A1 | M1 and M2 on rolling validation. Set the reference. Test cross-surface transfer. | **partial** | M1: `backend/tennis_match_backtest.py` (dev, first on `621d81df`). Re-derived today in `research/tennis/match/2026-10-18/elo_m1_independent.py`. M2 (50/50 logit average of global and surface Elo, `backend/tennis_daily_projections.py` near line 242) is the lock version `tennis-global-surface-elo-blend-v2`. An M2/M3 walk-forward script exists uncommitted in `/root/lp-tennis-props/backend/tennis_match_blends.py`. | M1 is verified on the 2023 to 2026 window only, with no rolling-origin table on dev. M2 has no rolling validation on dev and is already in the lock table (defect D4). |
| A2 | M3: M2 plus the point-model probability, weighted by serving history. Test the increment over M2. | **not started** on dev | Uncommitted `tennis_match_blends.py` (validation-fitted, history-weighted simulator logit; 2022 fit, 2023 onward scored once). Related dev analysis: `v2_incremental_comparison.json` (calibrated Elo base, 2022 to 2024, n = 2,749): overall Brier 0.20554 for V2 versus 0.20691 for calibrated Elo. The companion `.md` reports a pooled interval that includes zero (not re-verified from the JSON). | M3 as specified (history-weighted, on the M1/M2 base, fitted on rolling validation) is not on dev. The dev analysis uses a different baseline (calibrated Elo) and a different window, so it does not answer the M3 question. |
| A3 | M4: M3 plus pre-match context, only if M3 is stable across years. | **not started** | No M4 code found in the tennis files reviewed on dev or in the active worktrees. | Everything. |
| A4 | Simulator set, game and tiebreak outputs validated separately against historical outcomes. | **partial** | Structural section of the total-games backtest (sets per match, games per set, tiebreak frequency and deciding-set frequency against observed values, 2023 to 2026). | No proper score for set-score distributions, and no go or no-go decision for set, game or tiebreak outputs. |

## Verified numbers

Re-derived today. "Re-run" means the dev code was executed with read-only hooks. "Read" means the value was taken from the
named artifact and checked against the brief or the document.

| Quantity | Source | Check | Value | Sample |
|---|---|---|---|---|
| M1 Elo Brier, ATP, 2023 to 2026 | `research/tennis/match/2026-10-18/elo_m1_independent.py` | Independent Elo implementation from the protocol, shared tour filter only | 0.22802 (log loss 0.64896) | n = 11,777 complete best-of-three matches |
| M1 Elo Brier, WTA, 2023 to 2026 | same | same | 0.21596 (log loss 0.62100) | n = 13,066 |
| Gamma-Poisson P0 and P1 headline, all four cells | `research/tennis/props/2026-10-16/tennis-p0p1-{atp,wta}.json` | Re-run with `gp_calibration.py`; the totals match the CSV and the JSON to 4 dp | Section "Results" of the companion report | ATP 70,198 targets per count; WTA 77,274 aces, 77,256 DF |
| Total-games paired CRPS, simulator minus direct | `research/tennis/total-games/2026-10-16/{atp,wta}.json` | Read | ATP +0.1738 (95% event-cluster interval +0.1453 to +0.2036); WTA +0.3258 (+0.2990 to +0.3545) | 223 and 193 event clusters; 11,766 and 13,062 matches |
| Total-games simulator CRPS | same | Read | ATP 3.5327; WTA 3.5572 | same |
| E2 log score (mean log probability), ATP aces | `research/tennis/props/2026-10-14/e2-count-mixtures.json` | Read | P0 NB −2.6330; P1 NB −2.6231; X_bbin −2.6176 | 53,284 ATP sides (2019 to 2026) |
| E2 exposure bias | `research/tennis/props/2026-10-14/e2-exposure-diagnostics.json` | Read | −0.86 service points (ATP), −0.30 (WTA) | 2019 to 2026 |
| Lock table (dev) | `backend/data/picks.dev.db`, `tennis_model_locks` | Count, read-only | 20 locks: 13 `tennis-free-daily-v1`, 7 `tennis-global-surface-elo-blend-v2`; earliest 2026-10-15 | 20 locks |
| Grades (dev) | `tennis_model_grades` | Count | 18 grades; 18 of 20 locks graded, and all 9 post-start locks are among them | 18 |
| Post-start locks (dev) | `tennis_model_locks` where `locked_at > start_time` | Compare timestamps | 9, all `tennis-free-daily-v1`, all locked 2026-10-15 18:21:44 UTC, 5 to 13 hours after their starts | 9 |
| V2 research ledger | `backend/data/tennis_v2_research.sqlite3` | Count and compare timestamps | 6 forecasts, all locked before start, versioned `tennis-elo-informed-simulator-v2-research-2026-10-16`; 4 grades | 6 |

## Defects and conflicts

- **D1. Post-start locks counted as prospective.** Nine `tennis-free-daily-v1` locks for 2026-10-15 were written 5 to 13
  hours after their matches started (ATP 2, WTA 7). They are graded (8 correct, 1 incorrect). The cause is not established
  from the repo. Treat them as excluded from prospective scoring. Do not re-lock or backfill.
- **D2. One lock per match.** `tennis_model_locks` has `PRIMARY KEY(league, game_id)`. It cannot hold concurrent challengers
  for the same match. `tennis_projection_candidates` is deleted and rewritten for each league and day, so it is not an
  immutable record.
- **D3. Locks hold points, not distributions.** A lock stores `probability`, `homeAces`, `awayAces`, `totalGames` and a
  total-games interval. It stores no input snapshot or hash, and no full winner, total-games, ace or double-fault
  distribution. The V2 ledger does store the total-games distribution, but only 6 rows exist.
- **D4. A second version in the live lock table, with no validation record.** From 2026-10-16 the lock writer moved from
  `tennis-free-daily-v1` to `tennis-global-surface-elo-blend-v2`. The brief does not record a decision for this change, and
  no rolling validation of M2 exists on dev.
- **D5. "E2" is mislabelled.** `docs/TENNIS-PROPS-BASELINES-2026-10-14.md` ("Reconciliation with the earlier E2-based
  result") and `docs/RESEARCH-tennis-player-projections-2026-10-14.md` (lines 109 to 110) describe E2 as the frozen
  simulator's expected service-point exposure. The code (`feat/tennis-props-exposure`: `backend/tennis_props_exposure.py`,
  `backend/tennis_replay.py`; model version `tennis-props-e2-opponent-nb-v1`) is an opponent-adjusted negative-binomial
  regression fitted with `scipy.optimize`. It does not import the simulator. Its exposure bias (−0.86 ATP, −0.30 WTA) is far
  smaller than the simulator's (+7.3 ATP, +9.2 WTA in Gate A). So Gate A's rejection of the simulator does not apply to E2,
  and the dev text that treats them as one thing should be corrected.
- **D6. E2 results cannot be regenerated from durable artifacts.** No E2 run directory was found (searched `/tmp` and the
  worktrees by name). The E2 row-level
  predictions were not saved. The count-mixture generator that produced the X_thin and X_bbin results is uncommitted.
  Only aggregates survive, in `research/tennis/props/2026-10-14/`.
- **D7. Row-level replay files live only in `/tmp`.** `/tmp/tennis-p0p1-{atp,wta}.csv` (146 MB and 161 MB) and the total-games
  row CSVs are temporary. Their JSON summaries are now kept under `research/tennis/props/2026-10-16/` (copied, not moved).
  The row CSVs must be regenerated with the commands in the source documents before any further row-level work.
- **D8. The Gamma-Poisson P0 comparator is poorly calibrated for aces.** Its PIT distribution is U-shaped on ATP aces (the
  lowest decile holds 22% of outcomes; 80% coverage is 68.5%). P1 improves on it but stays U-shaped. Part of the P1 gain may
  therefore reflect a weak P0. The brief requires each Track B score to be compared against the best direct baseline, and
  this P0 may not be that baseline. See the companion report.
- **D9. 2022 to 2024 has been used as test and as calibration data.** The cross-market Brier comparison in the baselines
  document ("2022 to 2024 date-block holdout") and the V2 incremental comparison (2021 validation, 2022 to 2024 test) use
  this window. Neither is an untouched holdout. The 2023 to 2026 window is inspected development data, as the brief states.
- **D10. Branch divergence.** The dev brief is the 2026-10-16 revision and is authoritative. The copy on
  `docs/tennis-prediction-brief` is the 2026-10-14 revision (22 commits not on dev). `feat/tennis-props-exposure` (7 commits
  not on dev: props replay, E2, official-model spec, Flashscore points) and `feat/tennis-point-model` (43 commits not on dev:
  point model, simulator, match backtest) hold code the dev documents cite. A `git grep` on 2026-10-18 found no conflict
  markers in tennis docs, backend or research on dev. The conflict repair `0cdad734` is in the tree. Its line-count claims
  were not re-checked.
- **D11. Count-band calibration is outcome-selected in the first draft of the calibration script.** Corrected today:
  calibration bands use the predicted P1 mean quartiles, not the observed count. Recorded here because the first version
  of the script was run and its bands were discarded.

## Work outside dev

| Location | Branch and state | Tennis content | Status for this audit |
|---|---|---|---|
| `/root/lp-tennis-props` | `feat/tennis-props-exposure`, uncommitted files | `backend/tennis_props_count_mixtures.py` (E2 X_thin and X_bbin), `backend/tennis_match_blends.py` (M1, M2, M3 walk-forward), `backend/tennis_props_diagnostics.py`, `backend/tennis_daily_grade.py`, backfill scripts | Headers read. Not run. Not committed by this work. |
| `/root/lp-tennis-forecast-grading` | `feat/tennis-forecast-grading` (its commits are on dev), uncommitted files | `backend/tennis_forecast_ledger.py` (per-target append-only locks and proper-score grading), tests | Header read. Not run. |
| `/root/lp-nhl-tennis-distributions` | `codex/nhl-tennis-distributions-2026-10-18`, uncommitted edits | Edits to `backend/tennis_daily_projections.py`, `backend/grade_tennis_model.py`, tests, `components/Leagues/TennisModelTab.tsx` | Another agent's active work. Not touched. It overlaps the projection and grading code. |
| `/root/legendarypicks` (dev checkout) | `dev`, uncommitted | `__tests__/leagues-tennis.test.tsx` (modified), `backend/promote_tennis_match_stats.py` (untracked), `backend/data/tennis_point_archives/` (untracked; includes `match_charting_project.db`), `backend/data/backups-tennis-20261013/` | Not mine. Left as is. |
| `feat/tennis-point-model` | 43 commits not on dev | Point model, simulator, match backtest (`01b680c6`) | Not reviewed in detail. |
| `feat/tennis-props-exposure` | 7 commits not on dev | Props replay (`26274d1b`), E2 (`418dea5d`, `b73aa49e`), official model spec (`4e68351f`, `83606a71`) | Not merged. The E2 code used for D5 and D6 is here. |

## Licensing

Sackmann-derived match tables and the Match Charting Project data are CC BY-NC-SA 4.0. Decision D1 is still open. Every
output named here stays research-only. Nothing in this audit or in the companion report is cleared for commercial use.
