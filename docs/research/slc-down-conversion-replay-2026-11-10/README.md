# SLC-v2 third-down replay audit — 2026-11-10

## Result

The ordered play export now answers the question the archived summaries could not: simulated third-down conversions are directly countable from each play's before/after state. This is a bounded replay of 40 games, not a new full-slate run.

- **40/40 games validated; 0 simulation errors.**
- **40/40 replayed final scores match** the corresponding archived seed results.
- ARI–SEA Default V2, C, and D1 have identical RNG-v2 stream roots for all 10 matched seeds.
- Every exported play has an increasing, unique sequence number and includes `state_before` and `state_after`.
- All 40 outputs have `status=valid_complete`. Both frozen snapshots were taken before the roster-finalization window opened. This is the intended forecast-time snapshot; it does not make a completed game invalid. BUF–MIN is tagged `exploratory_replay` in its output metadata, while ARI–SEA is tagged `verified_forecast`; that label difference does not change the per-game completion or score-match checks above.
- Replay outputs use `--slc-profile v1_full_stack --slc-v2`, RNG v2, the frozen snapshots and inputs, the same five ordinary blocker fixes, and both box-score and play exports.

## Down metrics

Third-down attempts count credited scrimmage attempts only. Conversions require a scrimmage-earned first down or an offensive touchdown. Punt and field-goal decisions are not fourth-down go-for-it attempts. “Game-rate p10/median/p90” summarizes each game's conversion rate across these 10 replays; it is descriptive, not a calibrated confidence interval.

| Replay arm | Team | Third-down conversions | Attempts/game | First downs/game | Fourth-down conversions/attempts | Game-rate p10/median/p90 |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| BUF–MIN D1 | MIN | 56/131 (42.7%) | 13.1 | 17.8 | 10/21 | 32.9/41.7/53.4% |
| BUF–MIN D1 | BUF | 70/140 (50.0%) | 14.0 | 20.6 | 13/25 | 29.1/52.3/67.1% |
| ARI–SEA Default V2 | ARI | 65/139 (46.8%) | 13.9 | 18.4 | 10/18 | 37.4/42.3/58.9% |
| ARI–SEA Default V2 | SEA | 66/140 (47.1%) | 14.0 | 20.3 | 14/24 | 30.2/44.5/59.1% |
| ARI–SEA C | ARI | 69/136 (50.7%) | 13.6 | 18.3 | 10/18 | 37.9/48.1/63.9% |
| ARI–SEA C | SEA | 65/136 (47.8%) | 13.6 | 18.9 | 14/21 | 30.2/46.2/59.1% |
| ARI–SEA D1 | ARI | 65/139 (46.8%) | 13.9 | 18.4 | 10/18 | 37.4/42.3/58.9% |
| ARI–SEA D1 | SEA | 66/140 (47.1%) | 14.0 | 20.3 | 14/24 | 30.2/44.5/59.1% |


The per-distance counts below use the yards-to-go recorded before each credited third-down attempt.

| Replay arm | Team | 1–3 yards | 4–6 yards | 7–10 yards | 11+ yards |
| --- | --- | ---: | ---: | ---: | ---: |
| BUF–MIN D1 | MIN | 19/38 (50.0%) | 21/41 (51.2%) | 14/40 (35.0%) | 2/12 (16.7%) |
| BUF–MIN D1 | BUF | 39/59 (66.1%) | 17/32 (53.1%) | 12/41 (29.3%) | 2/8 (25.0%) |
| ARI–SEA Default V2 | ARI | 28/44 (63.6%) | 19/48 (39.6%) | 16/40 (40.0%) | 2/7 (28.6%) |
| ARI–SEA Default V2 | SEA | 36/57 (63.2%) | 14/30 (46.7%) | 14/38 (36.8%) | 2/15 (13.3%) |
| ARI–SEA C | ARI | 29/41 (70.7%) | 24/53 (45.3%) | 14/36 (38.9%) | 2/6 (33.3%) |
| ARI–SEA C | SEA | 35/52 (67.3%) | 14/32 (43.8%) | 14/36 (38.9%) | 2/16 (12.5%) |
| ARI–SEA D1 | ARI | 28/44 (63.6%) | 19/48 (39.6%) | 16/40 (40.0%) | 2/7 (28.6%) |
| ARI–SEA D1 | SEA | 36/57 (63.2%) | 14/30 (46.7%) | 14/38 (36.8%) | 2/15 (13.3%) |


First-down sources and success rates by down are in [`metrics.json`](metrics.json). No replayed game had a zero-conversion third-down result. No accepted penalties or penalty-awarded first downs occurred in these samples.

## What this says about the model

Minnesota converted 56 of 131 third-down attempts (42.7%) in the 10 D1 replays, versus its 36.0% pregame 2026 rate through Week 8. Buffalo converted 70 of 140 (50.0%), versus 44.2% on offense through Week 8. These small replay samples are above those team-level benchmarks. They do not show that every matchup is over-converting, and they do not establish a cause.

In ARI–SEA, the replay rates were also above the teams’ Week 8 offensive rates: Arizona 46.8% in Default V2 and D1, 50.7% in C, versus 38.7% actual; Seattle 47.1% in Default V2 and D1, 47.8% in C, versus 35.6% actual. The ten-game sample is too small to calibrate from. It is a useful diagnostic signal consistent with the broader concern about offensive efficiency.

These comparisons do not isolate completion yardage, third-down distance, defense suppression, or fourth-down policy. The distance breakdown is preserved so the next analysis can separate easier situations from conversion execution.

Pregame Week 8 comparators: [team offense third-down rate](https://www.matchuplabsports.com/nfl/stats/teams/third-down-conversion/) and [opponent third-down rate allowed](https://www.matchuplabsports.com/nfl/stats/teams/third-down-defense/?highlight=tb%2Cchi&season=2026&sort=thirdDownAllowedPct&week=9). These are team rates before Week 9; the simulator replays are model outputs, not observed outcomes.

## Penalty rule

A penalty-awarded first down is recorded in the first-down totals. A penalty-only first down is **not** a third- or fourth-down conversion. The conversion rule already present in SLC-v2 commit `09a794f0` counts a scrimmage-earned first down or an offensive touchdown, and uses the penalty record to decide whether the scrimmage attempt is credited. Focused tests cover penalty-only awards and an independently earned scrimmage first down. No penalty events occurred in the 40 games here.

## Reproduction and artifacts

- [`run-manifest.json`](run-manifest.json): seed identities, input hashes, score-match checks, and per-seed RNG roots.
- [`metrics.json`](metrics.json): per-team totals, first-down source counts, rates by down and third-down distance, plus game-level values.
- [`ordered-play-transitions.jsonl.gz`](ordered-play-transitions.jsonl.gz): compressed ordered transitions for every play in all 40 replays, including before/after state.

The original 10K and three-arm archives were not modified. The BUF–MIN scores were checked against the original D1 `seed-results.csv.gz`; ARI–SEA scores were checked against the corresponding original three-arm box-score archives.
