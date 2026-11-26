# Model comparison

[Evaluation](README.md) · [Registry](../model-cards/README.md)

Do not create a single leaderboard by mixing cohorts, targets, quote timing or seed counts. These are source-reported snapshots, not new reruns.

## Week 11 2026: 13 games, 40 seeds per CEG game

[Phase 7 report](https://github.com/micahp/legendarypicks/blob/8d86d430/docs/research/slc-ceg-2026-11-24/PHASE7-EVALUATION-REPORT.md) identifies this examined cohort; lower is better.

| Model | Home-win Brier | Margin MAE | Total MAE |
|---|---:|---:|---:|
| Market | .183 | 7.8 | 10.8 |
| Frozen V2 | .205 | 9.9 | 12.3 |
| Frozen V1.6 | .230 | 10.0 | 13.1 |
| CEG-SEL+E | .245 | 12.1 | 11.2 |
| Coin | .250 | — | — |

CEG realism (300 league-average games vs 2025): points 20.11 vs 23.01; plays 67.6 vs 65.9 (including no-play fouls); drives 20.7 vs 21.1/game. 300/300 realism and 1,160/1,160 forecast games reported complete; not comprehensive rule verification. Later Phase 9 held-out drive comparison did not establish a strength term beating CEG C. See [Phase 9](https://github.com/micahp/legendarypicks/blob/8d86d430/docs/research/slc-ceg-2026-11-24/PHASE9-TEAM-STRENGTH-REPORT.md).

## Other evidence

- [NFL model card](../model-cards/nfl.md) contains separate 2025 game baseline and player-prop experiments; do not compare directly to the table above.
- [V1 Complete passing audit](https://github.com/micahp/legendarypicks/blob/50c15508/docs/research/V1-COMPLETE-LIQUID-AI-ARCHITECTURE-AUDIT-2026-11-26.md): controlled mechanism diagnosis, not full-game forecast.
- [Portable pack evidence](https://github.com/micahp/legendarypicks/blob/e0d3f603/docs/research/SLC-PORTABLE-MODEL-PACK-2026-11-18.md): smoke/parity, not accuracy.
- Other weekly grade results must be added from exact archived grading artifacts, with denominators and model pins verified. No claim that this page includes every historic result.
