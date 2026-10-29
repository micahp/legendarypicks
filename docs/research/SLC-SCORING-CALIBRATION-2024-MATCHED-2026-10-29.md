# SLC 2024 scoring replay on a matched cohort

Status: exploratory retrospective check. The replay uses 2022 and 2023 play outcomes, an artifact fit through 2023, and a cutoff before Week 1 of 2024. It uses no 2026 outcomes.

## Cohort coverage

The regular-season schedule has 256 games in weeks 2 to 18. The replay built valid snapshots for 229 games, or 89.5 percent. The remaining 27 games failed historical depth-chart checks for exactly one RB1 or QB1. Sixteen of those missing games involve CIN. The other failed snapshots involve SF (3), JAX (3), KC, LV, DAL, LAC and CLE (one each). Sixteen Week 1 games were also skipped because no pre-Week 1 depth chart was available; those games are outside the 256-game denominator.

Both arms requested seeds 1 to 5 for each available game. The baseline produced 1,110 completed seeds and 35 blocked seeds. The formation arm produced 1,105 completed seeds and 40 blocked seeds. The direct comparison uses the 1,071 game and seed pairs that completed in both arms, grouped into 229 game clusters.

## Result

| points per team-game | score-clock baseline | formation-conditioned outcomes | actual 2024, same 229 games |
|---|---:|---:|---:|
| final points | 19.8595 | 20.1340 | 22.5590 |

The paired formation shift is +0.2745 points per team-game with a game-clustered standard error of 0.2572. This is about one standard error, so the replay does not establish a scoring change. The baseline gap to actual is 2.6995 points per team-game; formation reduces it to 2.4250 in this cohort.

Actual final scores include defense and special teams scoring. The matched 2024 data contain 0.616 points per team-game from return touchdowns, counting six points per touchdown and not counting extra points. This is a diagnostic, not a complete adjustment for scoring differences.

## Limits and next work

The cohort is incomplete and team-selective, especially for CIN. The nfl_pbp data has no row-level publication timestamp, so the retrospective cutoff is checked by season and week. Treat these values as results for the 229 available games, not a full-season estimate or calibration. The result supersedes the earlier formation comparison that included blocked partial games and used a different actual-score population.

The red-zone decomposition script was not run in the saved Claude session. This report makes no red-zone mechanism claim. The raw replay and summary hashes are pinned in docs/research/SLC-RESULTS-PIN-2026-10-29.json.
