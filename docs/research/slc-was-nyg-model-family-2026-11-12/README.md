# WAS–NYG TNF model-family comparison

**Game:** Washington Commanders at New York Giants, November 12, 2026  
**Final:** Washington 24, New York 21  
**Forecast inputs:** Frozen before kickoff at 2026-11-13 01:15 UTC.  
**Scope:** Seven game forecasts: four completed SLC batches (V1, V1.5, V1.6, and V2) and three recorded Legendary Picks game model projections. Player props cover the four SLC batches. The EPA game projection is a development lock; its public availability is unverified.

CBS lists the final as WAS 24–21 NYG, with no overtime period. The game box score reports 340 Washington yards, 399 New York yards, and 45 total points. [CBS final box score](https://www.cbssports.com/nfl/gametracker/boxscore/NFL_20261112_WAS%40NYG/)

## Results at a glance

- Three models gave Washington a higher win probability; V1.5 gave New York a slight edge. Washington won.
- V1.5 had the closest expected total (45.46 vs. 45 actual). V1 had the lowest combined absolute team-score error (2.50 points).
- Winner Brier scores were tightly grouped: 0.194–0.250 for this single result. V2 is numerically lowest, by a negligible margin over V1.6. That does not establish a model ranking.
- Player-prop probabilities were scored against pre-kickoff lines in the API database. On 323 matched player/market/line items, V1.6 was the strongest of the four batches (0.261), but the de-vigged market reference scored 0.248. All four model batches were worse than that market reference; all were also worse than the 0.25 constant-probability reference on this sample.
- These are one-game results, not evidence of season-long calibration or betting value.
- The later V1.7 candidate run completed its requested 1,000 seeds, but none passed the full-game validity gate; it contributes no forecast or Brier result.

## Game winner and Brier score

The NFL model card defines binary winner Brier as the squared difference between predicted **home-win** probability and the observed result. A perfect score is 0; lower is better; a 50/50 probability gives 0.25. There is no universal “good” cutoff: compare on the same games and, where available, against the contemporaneous de-vigged market. Historical values in the card (such as the 2025 V1 holdout at 0.2288 and closing moneylines at 0.2137) are context only, not a like-for-like benchmark for this one game. [NFL model card](../../model-cards/nfl.md)

Here the home team was New York, which lost, so the binary outcome is `y_home_win = 0`. The Brier contribution is therefore `(P(NYG win) − 0)²`. Simulated ties are shown separately and are not counted as NYG wins, consistent with the model card’s instruction to handle ties separately.

| Model | Valid games | P(WAS win) | P(NYG win) | P(tie) | Home-win Brier |
|---|---:|---:|---:|---:|---:|
| V1 | 100 | 54.0% | 46.0% | 0.0% | 0.212 |
| V1.5 | 100 | 49.0% | 50.0% | 1.0% | 0.250 |
| V1.6 | 999 | 55.8% | 44.1% | 0.1% | 0.195 |
| V2 | 100 | 53.0% | 44.0% | 3.0% | 0.194 |

V1.6 had one failed seed (20261204), so its denominator is 999 rather than 1,000. Same-numbered seeds are not paired random draws across these model versions: V2 uses a different RNG protocol. The 99 seeds valid in all four batches provide a useful sensitivity check, but not a paired model test. On those 99, Washington win rates ranged from 49.5% (V1.5) to 60.6% (V1.6), illustrating the Monte Carlo variation in the smaller batches.

## Points

The score ranges below are marginal team-score 10th–90th percentiles, not an interval for the combined total. Mean-score errors are against the actual 24 Washington and 21 New York points.

| Model | WAS mean (median; P10–P90) | NYG mean (median; P10–P90) | Expected total | Total error | WAS / NYG absolute score error | Combined team-score error |
|---|---|---|---:|---:|---:|---:|
| V1 | 22.02 (21; 10–31) | 21.52 (23; 10–33) | 43.54 | 1.46 | 1.98 / 0.52 | **2.50** |
| V1.5 | 21.84 (22; 13–31) | 23.62 (24; 10–34) | 45.46 | **0.46** | 2.16 / 2.62 | 4.78 |
| V1.6 | 21.34 (21; 10–33) | 19.39 (20; 7–31) | 40.73 | 4.27 | 2.66 / 1.61 | 4.27 |
| V2 | 21.12 (20; 13–29) | 18.39 (19; 6–30) | 39.51 | 5.49 | 2.88 / 2.61 | 5.49 |

V1 had the smallest combined absolute error in the two team means; V1.5 had the closest total. These are different summaries of one realized score.

## Published game models alongside the SLC family

The local API development database (`/root/legendarypicks/backend/data/picks.dev.db`) contains all three locked pregame projections for `2026_10_WAS_NYG`, locked at 2026-11-12 23:45:01 UTC. The local production database contains matching points and Elo projections; its EPA row was absent, so the EPA forecast below is documented from the development database and its presence on the production site is unverified. Final: WAS 24, NYG 21; actual home margin −3 and total 45. SLC margin and total use the simulated mean scores.

| Model | NYG win probability | Winner Brier | WAS points | NYG points | NYG margin | Total | Absolute total error |
|---|---:|---:|---:|---:|---:|---:|---:|
| Published v1 points | 57.3% | 0.328 | 21.35 | 23.79 | +2.44 | 45.14 | 0.14 |
| Published v2 EPA (development lock) | 63.2% | 0.400 | 21.67 | 26.09 | +4.42 | 47.77 | 2.77 |
| Published v1 + Elo | 62.0% | 0.385 | 20.52 | 24.62 | +4.10 | 45.14 | 0.14 |
| SLC V1 | 46.0% | 0.212 | 22.02 | 21.52 | −0.50 | 43.54 | 1.46 |
| SLC V1.5 | 50.0% | 0.250 | 21.84 | 23.62 | +1.78 | 45.46 | 0.46 |
| SLC V1.6 | 44.1% | 0.195 | 21.34 | 19.39 | −1.95 | 40.73 | 4.27 |
| SLC V2 | 44.0% | 0.194 | 21.12 | 18.39 | −2.73 | 39.51 | 5.49 |

Brier uses the unrounded stored probability for the published models and the game-count probability for SLC. All three published models favored NYG, while the points and Elo models projected the total closest to 45. On this single game the SLC winner probabilities scored better; 100-game SLC batches have considerable simulation noise. The three published models supply game forecasts, not player-prop forecasts, so the player-prop section evaluates the four SLC models.

The model card reports historical winner Brier scores of 0.2288 for v1 points and 0.2291 for v2 EPA on the same 255-game 2025 holdout, and 0.2197 for v1 + Elo over the 2011–2023 retrospective. Those different evaluation periods are context, not directly comparable standings.

## Player props

### API lines and Brier results

I used the NFL game row `prop_games.id=30217` and its `props` records from the API’s `picks.dev.db`. The selected player lines and odds were captured before the 01:15 UTC kickoff; the latest included capture was 2026-11-12 23:42:37 UTC. Of 1,811 paired source/line quotes in the API, 1,545 matched a modeled stat and final player record; these collapse to 323 unique player/market/line items across 15 players and 13 markets. Over and under prices were paired by player, market, exact line, and source, then de-vigged. For each exact player/market/line, the reference is the mean de-vigged over probability across captured sources. Model probabilities are the empirical share of valid simulated games over that line. Pushes and unsupported or unmatched markets are excluded. The matched source-line snapshot is preserved in [pregame-prop-quotes.csv](./pregame-prop-quotes.csv), and the deduplicated scoring items are in [graded-player-props.csv](./graded-player-props.csv).

The Brier scale is 0 to 1: 0 is perfect, lower is better, and a constant 50% forecast contributes 0.25 per item. The table gives scores on the **same 323 exact player/market/line items**. Values below 0.25 beat that simple reference on this sample; the market score is the stronger reference. Do not compare these directly with the NFL card’s season-level prop Briers: this is one game, with multiple correlated lines for the same player. V1/V1.5/V2 also have only 100 Monte Carlo draws each, so their per-line probabilities are coarser than V1.6’s 999-draw estimates.

| Forecast | Brier (323 items) | Difference from market |
|---|---:|---:|
| V1 | 0.291 | +0.043 |
| V1.5 | 0.290 | +0.042 |
| V1.6 | **0.261** | +0.013 |
| V2 | 0.298 | +0.051 |
| Constant 50% | 0.250 | +0.002 |
| De-vigged market average | **0.248** | — |

V1.6 was the best of these four empirical distributions on the sampled prop thresholds, but did not beat the market or the constant 50% baseline. The difference from 0.25 is very small; the 323 rows are not 323 independent games. Do not interpret the apparent V1.6 advantage as evidence it is a better general prop model.

| Market | Items | V1 | V1.5 | V1.6 | V2 | De-vigged market |
|---|---:|---:|---:|---:|---:|---:|
| Passing yards | 31 | 0.082 | 0.080 | 0.123 | 0.143 | 0.251 |
| Passing + rushing yards | 30 | 0.103 | 0.093 | 0.170 | 0.199 | 0.250 |
| Pass attempts | 8 | 0.168 | 0.134 | 0.160 | 0.144 | 0.258 |
| Pass completions | 6 | 0.072 | 0.099 | 0.113 | 0.067 | 0.247 |
| Rushing yards | 63 | 0.233 | 0.263 | **0.205** | 0.269 | 0.250 |
| Rushing + receiving yards | 33 | 0.491 | 0.474 | 0.383 | **0.308** | 0.250 |
| Receiving yards | 88 | 0.323 | 0.302 | **0.282** | 0.344 | 0.249 |
| Receptions | 19 | 0.430 | 0.432 | **0.356** | 0.410 | 0.229 |
| Targets | 16 | 0.380 | 0.382 | **0.301** | 0.375 | 0.250 |
| Rush attempts | 22 | 0.491 | 0.533 | **0.417** | 0.498 | 0.246 |
| Passing touchdowns | 2 | 0.260 | **0.208** | 0.262 | 0.266 | 0.271 |
| Interceptions thrown | 2 | 0.455 | 0.487 | 0.585 | 0.564 | 0.257 |
| Total touchdowns | 3 | 0.213 | 0.214 | **0.192** | 0.219 | 0.172 |

Small market rows have too few items for a useful model-level conclusion. At the larger samples, results vary by prop type: for example, V1.6 is best among these candidates on rushing yards, receiving yards, receptions, targets, and rush attempts, while V2 is best on rushing-plus-receiving yards. The market still leads on most larger groups.

### Notable player projections

These are simulated means in yards and the actual box-score yards. Model order is V1 / V1.5 / V1.6 / V2. Actuals are from the [CBS final box score](https://www.cbssports.com/nfl/gametracker/boxscore/NFL_20261112_WAS%40NYG/). They illustrate the individual forecast spread; the complete empirical distributions for **all 125 roster players in each model**, including P10/P90, probabilities above zero, and integer histograms, are in [player-projections.csv](./player-projections.csv).

| Player / statistic | Actual | V1 | V1.5 | V1.6 | V2 |
|---|---:|---:|---:|---:|---:|
| Jayden Daniels passing yards | 249 | 245 | 248 | 224 | 210 |
| J.J. McCarthy passing yards | 293 | 244 | 229 | 237 | 247 |
| Rachaad White rushing yards | 47 | 29 | 23 | 23 | 16 |
| Austin Ekeler rushing yards | 26 | 17 | 18 | 22 | 30 |
| Cam Skattebo rushing yards | 78 | 31 | 29 | 47 | 41 |
| Jayden Daniels rushing yards | 28 | 21 | 21 | 22 | 21 |
| J.J. McCarthy rushing yards | 34 | 31 | 36 | 27 | 29 |
| Stefon Diggs receiving yards | 83 | 15 | 20 | 17 | 7 |
| Ben Sinnott receiving yards | 42 | 16 | 14 | 12 | 16 |
| Antonio Williams receiving yards | 42 | 17 | 24 | 17 | 7 |
| Malik Nabers receiving yards | 44 | 62 | 57 | 80 | 100 |
| Isaiah Likely receiving yards | 127 | 3 | 3 | 41 | 31 |
| Malachi Fields receiving yards | 62 | 10 | 14 | 30 | 23 |

The largest misses among these examples were receiving production: Diggs and Likely both substantially exceeded all four means, while Nabers fell below all four. The complete CSV permits review of the roster-wide distribution rather than selecting only these examples after the game.

### Reconstructed Legendary Picks player models

I replayed Marcel-lite, Spec B v2 and Forward Platt using the frozen finalized WAS–NYG roster package from the fast host. Its snapshot was captured at 2026-11-13 00:10:12 UTC, about 65 minutes before kickoff. I used its full-depth roster and frozen `injuries_2026.parquet`; the snapshot marks 125 unique players and contains no unresolved player identities. The Week 10 injury report therefore comes from the preserved pregame artifact, not the current injury table. Historical player logs were cut off after Week 9. Predictions are **retrospectively reconstructed**, not forecasts saved before kickoff.

Marcel-lite is a point-estimate model. Its supported code does not produce player-stat distributions, so I report its point estimates but no invented over probabilities or Brier score. Spec B v2 generates 4,000 draws for receiving stats and quarterback passing stats. Its implementation has point estimates for rushing stats, but no frozen rushing simulation distribution; combined yards, total touchdowns and interceptions also lack a supported distribution here. Those 153 lines have no Spec B or Platt probability. Forward Platt applies the existing two-parameter logistic map to Spec B probabilities. I refit that map only on pre-kickoff sportsbook line captures from Weeks 2–9: 55,467 eligible line/book items over 1,591 player-games. The fit was `a=0.430564`, `b=0.236316`; no Week 10 outcome or line entered the fit.

| Player-stat model | Probability coverage | Brier on its covered lines | Brier on common 170 supported lines |
|---|---:|---:|---:|
| SLC V1 | 323 / 323 | 0.291 | 0.280 |
| SLC V1.5 | 323 / 323 | 0.290 | 0.268 |
| SLC V1.6 | 323 / 323 | 0.261 | 0.251 |
| SLC V2 | 323 / 323 | 0.298 | 0.298 |
| Spec B v2 | 170 / 323 (52.6%) | 0.285 | 0.285 |
| Forward Platt on Spec B v2 | 170 / 323 (52.6%) | **0.228** | **0.228** |
| Marcel-lite | 0 / 323 | Not produced | Not produced |
| De-vigged market | 323 / 323 | 0.248 | 0.248 |

The common-coverage column scores every listed probability model on the same 170 player/market/line items that Spec B supports. Forward Platt is the lowest Brier on this one-game subset; it also beats the de-vigged market there. That is a small, correlated, single-game evaluation of a map reconstructed from the preceding eight weeks, not evidence of a durable advantage. On the full 323-line cohort, the existing de-vigged market score remains 0.248. Use the Brier scale above: 0 is perfect, lower is better, and 0.25 is the constant 50% reference.

The forecasts below show the reconstructed point estimates beside the four frozen SLC means and actual results. Marcel-lite and Spec B v2 are conditional player-stat projections; their point estimates do not encode the chance that a player is inactive. The SLC columns are simulation means, so they are not necessarily the same estimand.

| Player-stat | Actual | Marcel-lite | Spec B v2 | SLC V1 | SLC V1.5 | SLC V1.6 | SLC V2 |
|---|---:|---:|---:|---:|---:|---:|---:|
| Jayden Daniels passing yards | 249 | 212.8 | 210.9 | 244.6 | 248.4 | 224.4 | 210.4 |
| J.J. McCarthy passing yards | 293 | 155.5 | 161.4 | 244.0 | 229.0 | 237.0 | 247.0 |
| Rachaad White rushing yards | 47 | 32.6 | 35.7 | 29.0 | 23.0 | 23.0 | 16.0 |
| Cam Skattebo rushing yards | 78 | 68.5 | 35.1 | 31.0 | 29.1 | 47.1 | 41.2 |
| Stefon Diggs receiving yards | 83 | 41.7 | 38.6 | 15.0 | 20.0 | 17.0 | 7.0 |
| Malik Nabers receiving yards | 44 | 95.7 | 58.7 | 62.0 | 57.0 | 80.0 | 100.0 |
| Isaiah Likely receiving yards | 127 | 60.4 | 45.7 | 3.0 | 3.0 | 41.0 | 31.0 |

Point-estimate errors should be compared within the same stat because yards, attempts, receptions and touchdowns have different scales. `player-model-comparison.csv` includes by-stat MAE rows for Marcel-lite and Spec B. The full player-level forecast rows include the actual, absolute error, distribution summaries where supported, identity and provenance.

Coverage exclusions from Spec B: 63 rushing-yard lines, 22 rush-attempt lines, 33 rushing-plus-receiving-yard lines, 30 passing-plus-rushing-yard lines, two interception lines and three total-touchdown lines. Marcel-lite has point forecasts for the supported stats but no probability coverage by design. Unsupported probabilities are blank, never zero.

The replay manifest records the local database path and SHA-256 of its SQLite backup, all frozen snapshot hashes, model source hashes and parameters, calibration sample and exclusions. The frozen injury parquet was acquired at 2026-11-13 00:10:06 UTC; its source file timestamp is 2026-11-12 15:56:22 UTC. Historical training forecasts use Week 2–9 game logs only. Historical as-of injury versions were not preserved for every training week, so the calibration replay omitted historical injury-based share redistribution; the Week 10 reconstruction uses the saved pregame injury artifact. No postgame-built availability table was used. Reproduce from the repository root with:

```bash
python docs/research/slc-was-nyg-model-family-2026-11-12/replay-player-models.py \
  --db /path/to/picks.dev.db
python -m unittest discover \
  -s docs/research/slc-was-nyg-model-family-2026-11-12 \
  -p 'test_replay_player_models.py' -v
```

The generated files are [reconstructed-player-projections.csv](./reconstructed-player-projections.csv), [reconstructed-player-prop-probabilities.csv](./reconstructed-player-prop-probabilities.csv), [player-model-comparison.csv](./player-model-comparison.csv) and [player-model-replay-manifest.json](./player-model-replay-manifest.json). The small frozen source files used by this reconstruction are under [evidence/](./evidence/).

### What these prop scores do and do not say

The lines are real pre-kickoff API captures, so prop Brier can be calculated here. It is a **single-game retrospective check**. Several lines for one player share the same actual stat and are highly correlated; no independent-game uncertainty interval is meaningful. A decisive prop-model evaluation needs the same frozen line-selection rule over many games and must group uncertainty by player-game, as the NFL model card specifies. No prop model should be promoted from these results.

## Other game-level behavior

Team averages across simulations help explain the score outputs, but a single realized game cannot establish situational calibration. The actual game had 2 turnovers by each team (WAS threw two interceptions; NYG threw one and lost one fumble), 7/14 vs. 4/12 on third down, 0/2 vs. 1/1 on fourth down, and 4 vs. 5 punts. Those are useful descriptive checks, not standalone release gates. [CBS team and player statistics](https://www.cbssports.com/nfl/gametracker/boxscore/NFL_20261112_WAS%40NYG/)

The saved family summary reports simulated sacks, giveaways, touchdowns, punts, drives, plays, yards per rush, and yards per pass attempt by team. These matchup-specific outputs are retained in [summary.json](./summary.json). V1.6 also has ordered-play third-/fourth-down counts in that file; the corresponding detailed sidecars were not retained for V1, V1.5, and V2, so I do not present unmatched situational comparisons as a family-wide ranking.

## Run coverage and provenance

| Model | Requested | Valid completed | Failed / excluded |
|---|---:|---:|---:|
| V1 | 100 | 100 | 0 |
| V1.5 | 100 | 100 | 0 |
| V1.6 | 1,000 | 999 | 1 engine exception |
| V2 | 100 | 100 | 0 |
| V1.7 candidate (PR 43) | 1,000 | 0 | 46 errors; 1 additional blocked seed |

### V1.7 candidate batch (PR 43)

The five 200-seed batches finished on the fast host by 2026-11-13 18:11 UTC. The runner marked **0/1,000 as valid full games**, so V1.7 has no winner probability, score forecast, or player-prop grade in this comparison. The batch outputs contain 953 mechanically complete simulations, but those are diagnostic only and do not pass the full-game gate.

Across the batches, 46 seeds ended in errors: 33 `ILLEGAL_STATE`, 10 `STAT_ACCOUNTING`, and 3 `UNSUPPORTED_RULE`. Two seeds were flagged as blocked before regulation ended: `20261255` (unsupported run outcome on second-and-short in the own 1–9 yard zone) and `20261424` (accepted roughing-the-passer penalty after a possession-changing play could not be resolved). Seed `20261255` is also counted among the 46 errors, leaving 47 distinct affected seeds in total.

The producer source was based on commit `984751d5746b6943a119a89b5d45271a67b9c4c2`, with a dirty worktree. The reproducibility artifact records the run configuration, all producer file hashes, input and model manifests, all 47 per-seed failure payloads, and hashes of the original compressed failure files where present. It is [v1.7-1000-pr43-errors.jsonl.gz](./v1.7-1000-pr43-errors.jsonl.gz); the first JSONL record is the run manifest, followed by one record per affected seed. No aggregate V1.7 forecast should be inferred from its mechanically complete subset.

The common input snapshot is `slc-was-nyg-tnf-2026-11-12-final-0013Z/snapshot.json`, SHA-256 `fdc71aeb316e7dc10294c3d6581e1c331fe49637ab68fc71b9b406c55a8449b4`. It was built at 18:10:12 CST; roster feeds were last updated around 09:57 CST that morning. The snapshot’s internal `verified` flag does **not** establish that final inactives were known, so player-role/availability error remains a limitation.

The pregame PBP input was the 2026 data through Week 9, SHA-256 `6555b925b9507d3f803092f20b06f2c015588e6562918d37027cd386d2607cc3`. Five blocker fixes were enabled in the model runs. The database file SHA-256 when this report was generated was `67eae58674c30b6e9ea8b7c4fae34c084b88ffd1e24585a4f4fb12ff5ffafebc`; the scored API prop rows are separately retained in `pregame-prop-quotes.csv` and filtered to captures before kickoff.

Exact model commits:

- V1: `6895c2e309e9a0de1339fe9829a0bcb21cba9355`
- V1.5: `77162c0172b56a9d9ffcc34ae85911fb5aa6b3d4`
- V1.6: `58e7eee04decb7e4d1ffc3f47f28bb49f47b5b87`
- V2: `3dab14525926f0dec47c1e613e72f69f6050bd57`

V1, V1.5, and V2 were run from exported tracked code; all 25 recorded producer-file hashes per model matched their Git commits. V1.6 ran from the clean source checkout. Inputs were frozen before kickoff, though the full V1.6 batch finished after kickoff; no claim is made that its 999-game result was published before the game.

V1.6 seed `20261204` failed at Q4 7:54 on a NYG second-and-10 from its own 1: a lost sack fumble with −3 yards crossed the goal line and raised `ILLEGAL_STATE`. The exact replay was deterministic. It is excluded from V1.6 scores; this is an unresolved engine exception, not a zero-score or a forecast result. The reproducible failure report is [here](https://github.com/micahp/legendarypicks/tree/slc-v1.6/docs/research/slc-v16-was-nyg-seed-20261204).

V1.7 PR 43's full-game batch completed, but produced zero valid full-game simulations and is not included in the forecast tables. Optional V2+C and V2+D1 experiments were not run.

## Reproduction artifacts

- [summary.json](./summary.json): game, score, team and down-distance aggregates.
- [player-projections.csv](./player-projections.csv): 8,000 model/player/stat distribution rows (125 players × 4 models × 16 stats), including histograms.
- [actual-player-stats.json](./actual-player-stats.json): final player statistics extracted from the completed box score.
- [pregame-prop-quotes.csv](./pregame-prop-quotes.csv): exact matched prop quotes, odds, capture times, outcomes and model probabilities.
- [graded-player-props.csv](./graded-player-props.csv): deduplicated player-market-line grades.
- [graded-player-props-summary.json](./graded-player-props-summary.json): aggregate proper scores and per-market results.
- [player-projections.py](./player-projections.py) and [grade-player-props.py](./grade-player-props.py): aggregation and grading scripts.
- [collect-actual-player-stats.py](./collect-actual-player-stats.py): box-score stat extraction script.

The prop grader can be rerun against the current read-only API database with:

```bash
python grade-player-props.py \
  --db /root/legendarypicks/backend/data/picks.dev.db \
  --forecasts player-projections.csv \
  --actuals actual-player-stats.json \
  --out graded-player-props.csv \
  --quotes-out pregame-prop-quotes.csv \
  --summary-out graded-player-props-summary.json
```
