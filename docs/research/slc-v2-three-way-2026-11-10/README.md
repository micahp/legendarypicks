# SLC-v2 three-arm comparison: Week 9 grading update

Grading update date: 2026-11-10. The original grading attempt used the fast-host local database, which had no final Week 9 scores. This update uses the completed Week 9 scores returned by Legendary Picks at the source URL recorded in live-score-mapping.json. The exact API payload is preserved in live-schedule-week9.json.

## Observed scores used

| Game | Final score |
| --- | --- |
| ARI at SEA | 3–17 |
| DAL at IND | 27–23 |
| DEN at CAR | 21–26 |

The scoring script is score_season_batches.py, run with --weeks 9-9 --season 2026 --seed-rule valid_full_game. It received a temporary SQLite table built only from the three completed API results. The persistent simulator database was not changed.

The arms contain the same requested seed IDs (1,000 per arm across three games), including one failed seed per arm in DEN–CAR. The scorer excludes invalid games through the valid_full_game rule and uses all valid seeds for each game. See the two grader JSON files for paired metrics and the advance-rule verdicts.

The first attempt is preserved under initial-local-db-check/; it is NOT SCORED because that local DB had no final Week 9 scores.

## Grading results

Each arm requested 1,000 seeds. Seed 300786 failed in DEN–CAR in all three arms, so the scorer used 999 valid full games per arm across the three matchups.

| Comparison | Candidate Brier (default) | Candidate log loss (default) | Paired Brier difference (95% CI) | Paired log-loss difference (95% CI) | Advance rule |
| --- | ---: | ---: | ---: | ---: | --- |
| Default V2 vs C | 0.17793 vs 0.19430 | 0.54415 vs 0.57764 | −0.01637 [−0.05379, +0.01229] | −0.03349 [−0.10773, +0.02489] | Fail |
| Default V2 vs D1 | 0.19865 vs 0.19430 | 0.58641 vs 0.57764 | +0.00435 [0.00000, +0.01306] | +0.00877 [0.00000, +0.02632] | Fail |

C is directionally better than Default V2 on this three-game sample, but both paired intervals include zero. D1 is slightly worse on both mean metrics. Neither comparison passes the stated advance rule. Treat these as a small prospective comparison, not a release decision.

## Per-arm simulation reports

The `worker-reports/` directory was regenerated from the checksummed compressed worker artifacts. Each report covers one arm and matchup. Team, player, and quarter CSVs include mean, median, and central 10th/90th percentile summaries.

The archived boxscore artifacts use schema 4. Their `realism` block contains lineup summaries but no ordered play rows. They therefore cannot provide first-down sources, third- or fourth-down conversion counts, or a new play-clock reconciliation. The reported historical possession and drive-window totals remain the archived values. The updated simulator exporter can produce these play-derived metrics in future runs; this rerender does not reconstruct them for this run.
