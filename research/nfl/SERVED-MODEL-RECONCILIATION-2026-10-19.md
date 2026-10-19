# NFL served-model reconciliation — 2026-10-19

## Finding

The production player-prop API serves the legacy, unversioned log-history estimator documented as Marcel-lite. It does not serve v2 or v2-platt. The production database does contain week 6 rows labeled v2, but the live route reads player_game_logs rather than player_projections. The v2-platt maps are in the development database only, and the production API returns 404 for the NFL-specific versioned route.

The v2-platt result is still useful research: on its map-applied sample it scores Brier 0.2486 against the market's 0.2463. The model is worse than the market. This is not a live production result and is not an established market edge.

The discrete-prop artifact contract reviewed here is docs/EVAL-CONTRACT-discrete-props.md from research/discrete-prop-eval-2026-10-18 at 186d95c740cbdba09deb831eb4f20b27e817ea5c. That file is not present in the starting tree of this task branch; the verdict below applies its requirements directly.

## Served-model inventory

### Production runtime

Read-only inspection on 2026-10-19 found the running backend container legendarypicks-backend-1 using image digest sha256:b63c0c5e6d93a6429fd5c820e1f351e44d4f736bd1d7b2d2f57e039d8cb76a1a, created 2026-10-17. Its container labels have no source revision. The exact source commit of that image therefore cannot be recovered from its metadata.

The container's live OpenAPI document exposes /api/projections/player/{player_id} as its only player-projection route. /api/nfl/projections/player/132?season=2026&week=6&market=receiving_yards&line=20.5 returns 404. A direct request to /api/projections/player/132?market=carries&line=10.5 returned 200 with six historical games, a 1.43 carry projection and P(over)=0. The response has no model field. This single-player response is a path check, not a performance measurement.

The checked-in serving path is backend/routers/players/projections.py, called by the Props Model tab in pages/props.tsx. It reads player_game_logs and calls backend/analytics/projections.py. That module identifies its baseline as Marcel-lite: the point estimate combines the last-five, last-ten and full-history averages; P(over) is the historical share strictly above the supplied line. The API does not assign a model-version string. It returns player-level history summaries, not a forecast ledger keyed to a specific upcoming game.

### Versioned writer and database rows

The task branch is feat/nfl-success-rate-and-distributions at 0440911980d5ed3f161fff7da274fc2e9f1554b8, tracking origin. Its NFL weekly writer is backend/nfl_player_projections_job.py; MODEL_VERSION is v2, and write_week stores the model version, run ID, game/player/stat keys, summary quantiles and as_of. The paired baseline rows are labeled marcel-lite. The separate v2-platt option adjusts a scalar P(over) at request time; it does not replace the stored v2 projection rows.

Read-only queries of the production database, /root/legendarypicks/backend/data/picks.db, found these latest 2026 week 6 rows:

| model_version | rows | latest as_of | run_id |
|---|---:|---|---|
| v2 | 1,160 | 2026-10-12 22:12:16 UTC | pp-2026-w06-20261012T221216 |
| marcel-lite | 1,160 | 2026-10-12 22:12:16 UTC | pp-2026-w06-20261012T221216 |
| espn-weekly | 936 | 2026-10-12 22:12:21 UTC | espn-2026-20261012T221221 |

The production database has no nfl_prop_calibration table. The separate picks.dev.db has v2-platt calibration rows for 2026 weeks 3–6, last fitted 2026-10-18. Those development rows do not establish production serving. The production API's live route and response confirm that the versioned v2/v2-platt endpoint is absent from the running image.

The v2-platt route was added to the development source at c71529cf00337b0ceba8244d65430d56e3057c4c on 2026-10-18, after the production image was created. The route is present in the task branch, where its default is v2 and v2-platt is an explicit model option. The task branch is not an ancestor of dev. No merge, deploy, service restart or database write was made for this task.

## Discrete-prop evaluation contract

**Verdict: the production player-prop output is outside the contract. The branch's v2 and v2-platt paths are also outside it.** The current response contains point summaries and, when a line is supplied, one P(over) value. It does not preserve the complete per-observation PMF/CDF, declared support and tail treatment, forecast cutoff, frozen input fingerprint or immutable forecast artifact. It also lacks an event-specific forecast row and a distinct outcome/settlement record. Percentiles and a line probability do not substitute for the PMF.

The verdict is the same across the live integer-stat market families:

| Prop markets | Production path | Contract verdict |
|---|---|---|
| Carries, rushing yards, rushing TDs | The generic history endpoint can return these stats from player_game_logs; the live carries example returned only summaries and a scalar line probability. | Fail: no event-level forecast or complete PMF/CDF. |
| Targets, receptions, receiving yards, receiving TDs | The generic history endpoint is served. The branch's v2 writer stores projection summaries; its optional v2-platt map transforms only P(over). | Fail: no frozen per-observation distribution artifact. |
| Pass attempts, completions, passing yards, passing TDs | The generic history endpoint is served. The branch's v2 writer and optional v2-platt path are not exposed by the production API. | Fail: no frozen per-observation distribution artifact. |

The historical evaluator backend/grade_nfl_prop_probabilities.py can optionally write a row-level CSV containing IDs, line, market probability, outcome and the model's P(over). Its header states that these are walk-forward reconstructions, not captured pre-kickoff predictions. The CSV still has no full PMF/CDF, so it does not close the contract. The versioned projection table improves event/player identity and records as_of and model_version, but stores means and quantiles rather than the required outcome distribution.

## Market gates, kept separate

These scores come from different populations and are not pooled. The benchmark for each market is its own reference; the comparisons below do not establish that one market family can substitute for another.

| Market | Population | Model Brier | Its reference | Model minus reference | Gate result |
|---|---|---:|---:|---:|---|
| Winner | 719 games, 2023–2025 weeks 3–18 | 0.2243 | Constant 0.2474; market 0.2088 | −0.02316 vs constant; +0.01542 vs market, 95% CI [+0.01018, +0.02106] | Beats the constant, fails the market comparison. |
| Player props | v2-platt map applied, 24,558 items / 683 player-games, 2026 weeks 3–5 | 0.2486 | Constant 0.2500; market 0.2463 | +0.00227 vs market, clustered 95% CI [+0.00005, +0.00449] | Improves on raw v2 (0.2743), but the market scores better. Do not describe it as close or market-beating. |
| Spread | 704 games, 2023–2025 weeks 3–18; pushes excluded | 0.2646 | Constant 0.2498; no market probability available | +0.01477 vs constant, 95% CI [+0.00768, +0.02213] | Fails its constant baseline. Do not present as a forecast. |
| Total | 715 games, 2023–2025 weeks 3–18; pushes excluded | 0.2634 | Constant 0.2499; no market probability available | +0.01355 vs constant, 95% CI [+0.00573, +0.02111] | Fails its constant baseline. Do not present as a forecast. |

For props, the published two-gate rule remains separate: compare a new model with the incumbent using paired clustered uncertainty, then separately compare it with the market-only model. The v2-platt map lowers Brier from raw v2 on the reported sample, but it is still worse than the market. With the uncalibrated week 2 fallback included, the reported v2-platt path scores 0.2529 against the market's 0.2461 on 32,758 items; this is a different population from the map-applied row above.

For the game-level results, the winner market has a priced market comparator; spread and total do not. The database contains spread/total lines but not two-sided prices, so their market probability is unavailable. Their separate constant baselines are 0.2498 and 0.2499. Both model scores are worse, and neither may be presented as a forecast. No adoption threshold was selected or changed in this reconciliation.

## Prospective grading procedure

Start with the first eligible forecast captured before its information cutoff. Do not reconstruct a prospective record from postgame logs or current code. The current production endpoint alone is insufficient: capture must be extended to persist the complete distribution and its event-specific forecast record before scoring begins.

For each observation, freeze an immutable record containing:

1. Canonical league/season, event ID and scheduled start; player/team/opponent IDs and source IDs; market/stat, units, integer support, line, side, book and market-price snapshot.
2. Forecast creation time, information cutoff and lock time, with an assertion that the forecast predates the cutoff; the realized event date and exact population/stratum rule.
3. The complete PMF, or an exactly recoverable CDF, over declared support, including endpoint/tail mass, truncation or renormalization, and a stated normalization tolerance.
4. A separate post-event outcome and settlement state. Preserve a true zero, push, void, DNP, missing result and unresolved identity distinctly; record the authoritative outcome source and crosswalk version.
5. Model/version and source commit, patch checksum, byte-preserved full-precision parameter file and hash, frozen input snapshot/extract and hash, extraction query/version, runtime/library versions, seed and deterministic settings.
6. A versioned artifact schema and stable path, creation time, row count, unique-key checks, checksum, and the exact reproduction command. Never overwrite a frozen run; publish a new artifact version.

After settlement, grade the frozen rows per market: proper discrete distribution scores, line-event Brier/log loss, point error, reliability, randomized PIT and interval/set coverage. Compare on identical observations against that market's incumbent, market-only probability and declared constant baseline, with paired uncertainty clustered by game. Publish item and game counts and the precise line/outcome population. Keep winner, props, spread and total in separate score tables with their separate prices or constants.

Until the live path emits and freezes these artifacts, its outputs are not contract-grade prospective forecasts. This work did not add a carries candidate, refit, alternate gate, serving code or production data.

## Evidence references

- Runtime: production container image digest and read-only OpenAPI/API responses observed 2026-10-19; production DB query used picks.db in read-only mode.
- Source: backend/routers/players/projections.py, backend/analytics/projections.py, pages/props.tsx, backend/nfl_player_projections_job.py, backend/routers/players/nfl_projections.py and backend/grade_nfl_prop_probabilities.py.
- Market scores: docs/RESULTS-nfl-success-rate-and-distributions-2026-10-18.md and docs/RESULTS-nfl-decisions-2026-10-17.md.
- Contract: research/discrete-prop-eval-2026-10-18 at 186d95c740cbdba09deb831eb4f20b27e817ea5c, docs/EVAL-CONTRACT-discrete-props.md.
