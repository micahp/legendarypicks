
## Formation-conditioned replay (added 2026-10-29)

Same replay, same seeds, with pre-event formation and personnel and outcomes conditioned on the formation
(`--formation`, branch `research/slc-layered-2026-10-29`). Raw output: `SLC-SCORING-CALIBRATION-2024-FORMATION-COMPARE-2026-10-29.json`.

| Measure | Baseline replay | Formation replay | Actual 2024 |
|---|---|---|---|
| Points per team-game | 19.47 | 19.70 | 22.91 |
| Touchdowns per team-game | 2.00 | 2.02 | 2.56 |
| Points per drive | 1.735 | 1.733 | 2.128 |
| Punts per team-game | 4.15 | 4.21 | 3.73 |

The formation layer moves points by +0.23 and touchdowns by +0.02. It does not close the gap, so the deficit is not in the formation
decision or the formation-conditioned outcome weights. The remaining candidates are the red-zone field-goal share and the outcome
draw inside trips, which need per-play red-zone decisions to split (see above).
