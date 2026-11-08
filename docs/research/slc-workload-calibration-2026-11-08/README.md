# Player workload attribution: Michael Wilson and Zach Charbonnet, 2026-11-08

Game: ARI at SEA, 2026 week 9. Cutoff: play-by-play through week 8. Script: `scripts/nfl_sequence/attribute_player_workload.py`. Raw output: `attribution-wilson-targets.json`, `attribution-charbonnet-carries.json`.

This report uses one matchup. It does not show that either model is better overall. The game has not been played, so no real workload for it exists yet.

## Result

The workload layer is too high for both players, and the reason is not the same for each.

| Quantity | Wilson (ARI WR) targets | Charbonnet (SEA RB) carries |
|---|---:|---:|
| Real share, 2024 | 0.136 | 0.365 |
| Real share, 2025 (the layer's base) | 0.205 | 0.377 |
| Real share, 2022 to 2025 (the fixed adapter's base) | 0.110 | 0.260 |
| Real share, 2026 weeks 1 to 8 | 0.259 | 0.027 |
| Layer share among all eligible players (mean of 2,000 draws) | 0.275 | 0.584 |
| Layer 80% range (p10 to p90) | 0.169 to 0.387 | 0.353 to 0.793 |
| Simulated game, layers on (50 seeds): mean | 0.432 | 0.757 |
| Simulated game, layers on: median | 0.429 | 0.786 |
| Simulated game, layers on: p10 to p90 | 0.296 to 0.566 | 0.529 to 0.900 |
| Simulated game, layers off (50 seeds): mean | 0.206 | 0.359 |
| Simulated game, layers off: p10 to p90 | 0.139 to 0.293 | 0.263 to 0.462 |

The 50-seed values come from the control and `without-dirichlet_player_target_carry_shares` arms in `/root/ot-sim-out/slc-matrix-ari-sea-eb936b6e-50/` on the fast host. Target share is player targets over team targets. Carry share is player carries over team rush attempts.

## What the data shows

1. **Charbonnet: the base share is out of date.** He had 37.7% of Seattle's carries in 2025. In 2026 through week 8 he has 2.7%. The layer uses 2025 only, so it still gives him the largest weight. Neither simulated arm is close to his 2026 share. The layers-off value (0.359) matches his 2025 share, not his 2026 share.
2. **Players with no 2025 history get only the floor weight, and they now do most of the work.** Emanuel Wilson (Seattle RB4 on the depth chart) has 50% of Seattle's 2026 carries and gets a conditional share of 1.6%. Jadarian Price has 17.1% and gets 1.6%. Together, floor-weight players hold 67% of Seattle's real 2026 carries. In Arizona, floor-weight players hold 28% of the real 2026 targets. The largest are Kendrick Bourne (12.1%), Tyler Allgeier (7.0%) and Jeremiyah Love (4.5%). Each gets a conditional share of about 1.3%.
3. **Wilson: the layer is close; the simulation raises his share.** The layer gives him 0.275 among all eligible players. His real 2025 share is 0.205 and his real 2026 share is 0.259. In the simulated game he gets 0.432. Inside the wide-receiver group alone, his 2025 weight is 77% of the group, because the other Arizona receivers have little or no 2025 history. If the pre-event step picks a position group first and then draws inside it, that renormalization can explain the rise. This is an inference. I did not trace a single simulated play to confirm it.
4. **Availability is unknown.** Both snapshots have an empty injury report (0 entries). Charbonnet's 2.7% suggests he is hurt or restricted. The layer cannot know that. The roster check treats missing information as eligible.
5. **Concentration is low, so draws vary a lot.** The fitted phi is 24.8 for all Arizona targets and 8.4 for all Seattle carries. For wide receivers it is 8.2, and for running backs 3.1. Low phi gives wide game-to-game spread. Whether it is the right spread is a question for the calibration harness, not this report.

## What this says about the plan

- The proposed model D (blend of prior-season and current-season shares) addresses the two largest causes. Charbonnet's 2026 share and the floor-weight players are both visible in current-season data.
- Model B (fixed historical shares) uses a different window from the Dirichlet layer: 2022 to 2025 against 2025 only. The two models must use the same window before they are compared.
- The 42.7% to 20.5% comparison is a combined intervention (Dirichlet layer and its dependent fixed-share adapter both off). It does not separate Dirichlet from fixed shares.
- Do not use the layers-off value as the correct answer. It matches 2025 usage for both players. It is wrong for Charbonnet in 2026.

## Not measured here

- The step in the simulation where Wilson's 0.275 becomes 0.432 (position filter, lineup filter, or both).
- Real workload for the game itself (not yet played).
- Whether any model predicts better over many games. That needs the evaluation harness.
