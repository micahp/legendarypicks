# SLC-CEG Phase 6: team and player differentiation

Date: 2026-11-24. Pre-registration: `PHASE6-PREREGISTRATION.md` (`42d821b1`, before any score). Code:
`scripts/nfl_sequence/ceg_team.py`, `scripts/nfl_sequence/ceg_opportunity.py` (the step 1 model with the tune and test
seasons as arguments). Results: `phase6/team_terms.json`, `phase6/opportunity_shares.json`.

## Result

1. **Two team terms beat arm C in 2025, by small amounts:** the offense term on the dropback outcome (sack, scramble,
   attempt: -0.0041, -0.0056 to -0.0027) and the defense term on the targeted outcome (-0.0007, -0.0012 to -0.0002;
   offense plus defense -0.0011). Both hold in 2026. These are the first team terms in this project to beat the league
   situation baseline.
2. **The other team terms do not count:** the offense term on the play call (+0.0003, n.s.), the defense term on the
   dropback outcome, and the offense term alone on the targeted outcome.
3. **The team signal is weak.** k = 1,000, the top of the grid, was chosen for most terms: the team rates are shrunk
   most of the way to the league.
4. **Arm D is confirmed.** Retuned on 2024 and scored once on 2025, the in-season opportunity model beats v1's
   prior-season share by 0.348 per opportunity (0.320 to 0.377) over 29,688 targets and carries: carries 0.386, targets
   0.317. The candidate-set caveat (players with an opportunity in that game) still holds.

## Team terms (log loss per opportunity, E minus C, 95% game bootstrap)

| component | term | k | 2025 | 2026 (examined) |
|---|---|---|---|---|
| dropback outcome | offense | 300 | -0.0041 (-0.0056 to -0.0027) | -0.0030 (-0.0047 to -0.0012) |
| dropback outcome | defense | 1,000 | -0.0001 (-0.0006 to +0.0004) | -0.0004 (n.s.) |
| dropback outcome | both | 1,000 | -0.0035 (-0.0045 to -0.0025) | -0.0032 (-0.0043 to -0.0020) |
| targeted outcome | offense | 1,000 | -0.0004 (-0.0010 to +0.0002) | +0.0001 (n.s.) |
| targeted outcome | defense | 1,000 | -0.0007 (-0.0012 to -0.0002) | -0.0009 (-0.0016 to -0.0002) |
| targeted outcome | both | 1,000 | -0.0011 (-0.0017 to -0.0004) | -0.0008 (-0.0017 to +0.0001) |
| intent | offense | 1,000 | +0.0003 (-0.0005 to +0.0011) | -0.0004 (n.s.) |

## Arm D (2025, tuned on 2024)

| model | all | targets | carries |
|---|---|---|---|
| M0 v1 prior-season share | 1.9736 | 2.3688 | 1.4716 |
| M1 + in-season counts (k 120) | 1.6611 | 2.0890 | 1.1176 |
| M2 + cross-team prior (k 160) | 1.6399 | 2.0583 | 1.1086 |
| M3 + situational group factor | 1.6261 | 2.0518 | 1.0855 |

## Used in Phase 7 (arm E)

The dropback-outcome offense term (k 300) and the targeted-outcome defense term (k 1,000), each computed from the
previous season and the target season's weeks before the game. Arm D is not yet wired into the game runtime (player
attribution is backlog E10), so Phase 7 evaluates team-level outcomes only.
