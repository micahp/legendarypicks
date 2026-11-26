# Learnings for SLC v2: lead RB workload and the participation field

Source: `REPORT.md` and `results/final_six_arms.json` in this folder (commit `be93232f`). Same 14 Week 10 snapshots and seeds in every arm. Actual values are approximate. The simulated and actual snap rates use different denominators (see the report).

## 1. Leave hazards and snap counts materially improve lead RB workload

| Arm | Lead RB on-field rate | Lead RB carries per game | Departures per 100 on-field plays |
|---|---|---|---|
| B (field only) | 0.358 | 9.0 | 28.7 |
| C (PBV1) | 0.370 | 9.5 | 27.6 |
| H (leave hazards) | 0.460 | 11.4 | 24.3 |
| HS (plus snap counts) | 0.510 | 12.6 | 17.1 |
| HP (hazards plus PBV1) | 0.452 | 11.2 | 24.7 |
| HSP (snap counts plus PBV1) | 0.526 | 13.2 | 16.5 |
| Actual | about 0.64 | 14.7 | not measured |

HSP closes about 59% of the gap between B and the actual on-field rate. Carries rise from 9.0 to 13.2 against 14.7 actual.

This is progress on workload. It does not show that HSP predicts games better. Accuracy against actual games is not yet measured.

## 2. Initial lineup selection is a separate problem

The results JSON has a metric the main table does not show: how often the actual lead RB is on the field at the team's first simulated offensive play.

| Arm | Lead RB on the field at first play |
|---|---|
| B | 50.0% |
| C | 50.0% |
| H | 50.5% |
| HS | 45.2% |
| HP | 50.5% |
| HSP | 48.8% |

Even HSP leaves the actual lead RB off the field on about half of first plays.

At the first play, the lineup is empty. `Field.advance()` fills every slot from the bench through `Field._weighted()`. No earlier stint exists to end, so no leave hazard applies. The first-play gap therefore comes from slot availability and the entry draw, not from the leave step.

The leave step alone is not the whole problem.

## 3. Which change helps most

| Change | Lead RB on-field rate gain | Carries per game gain |
|---|---|---|
| Add individual leave hazards (B to H) | +10.2 points | +2.45 |
| Add snap counts on top (H to HS) | +5.0 points | +1.21 |
| Add PBV1 on top (HS to HSP) | +1.6 points | +0.57 |

Leave hazards have the larger effect on lead RB time and carries. Snap counts have the larger effect on departures (24.3 down to 17.1 per 100 on-field plays).

Snap counts change two things inside the field. They update the player weights (`snap_update.player_weights()`, which feeds `Field.rate()` and the leave hazard) and the grouping tilt (`snap_update.group_lambda()`). These effects are not yet separated.

## 4. Tests to run next

1. **First-play entry.** When an RB slot exists at the first play and the actual lead RB is on the bench, how often is he selected? Compare his weight with the backups' weights.
2. **Departure cause.** Split removals into hazard leavers (`leavers`) and forced personnel removals (`count_removed`), for H and HS. The advance-log re-runs of B and C will supply the B and C side.
3. **Weight against tilt.** Run HS with only the player-weight update, and separately with only the grouping tilt. Which one moves the lead RB's on-field rate?
4. **Re-entry.** When the lead RB is on the bench, how often is he eligible for `_weighted()`, what is his selection probability, and how often is he passed over?
5. **Accuracy.** Grade high-volume RB carries, signed workload error, all-player carry and target MAE, game Brier, and player-prop Brier. A more realistic snap share is not enough on its own.

Rule for all of these: the actual lead RB is used only to score the result. Any starter adjustment must come from cutoff-eligible depth charts and earlier playing-time evidence.

## 5. Where this leaves PBV1 and SLC v2

- PBV1 adds 1.6 points on top of HS. The shared participation model gives most of the gain. PBV1 is not the main source of the missing snaps.
- The SLC v2 full run is separate. It turns on season adaptation and loads a default kicker table, so it is not a clean PBV1 test.
- LA_ARI: LA had two active kickers in Week 10. The build keeps last week's kicker when he is one of them. This is a choice, not an official rule. It needs a review before the v2 results are interpreted.

## 6. Recommendation

Keep H and HS as the main diagnostic comparisons. The next target is the first-play entry decision, then forced versus hazard removals. There is no reason to change the play-call order.
