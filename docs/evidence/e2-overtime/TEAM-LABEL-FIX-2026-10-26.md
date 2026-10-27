# Overtime team-label correction (2026-10-26)

## Defect and fix

The overtime reference table stores `next_offense` as a historical NFL club abbreviation, while simulated teams are labeled `A` and `B`. The reducer had passed the historical abbreviation into the simulated possession state. On some tied multi-possession paths, that could make the possession ledger count a third team and award later points outside the A/B score.

For non-scoring observed overtime drives, the next simulated offense is now the other team in the current game. The sampled historical club and next spot remain attached to the drive as source provenance. A regression test uses `SEA` as the historical next offense and verifies the simulated possession advances from A to B.

## Pinned-seed effect

The same pinned snapshot, reference, and seeds were used before and after the fix. The pre-fix method was loaded from commit `db2c4d87` for a direct comparison. All 12 seeds in the original 300-seed treatment that reached overtime were replayed; the other 288 rows were retained unchanged because they do not call the overtime sampler.

| Seed | Old score (A–B) | Corrected score (A–B) |
| ---: | ---: | ---: |
| 14 | 34–28 | 20–23 |
| 65 | 20–27 | 27–20 |
| 70 | 30–37 | 23–26 |
| 98 | 20–27 | 27–20 |
| 99 | 27–35 | 20–27 |
| 168 | 23–16 | 19–16 |
| 215 | 23–36 | 26–23 |

Seed 112 followed a different overtime drive sequence but remained tied 23–23. The other four overtime seeds retained their prior drive sequence and score. All 12 corrected records passed `validate_game`.

Coverage remained 293 valid games, 7 blocked games, and 0 simulation errors out of 300. The corrected valid-game mean is 20.89 home points, 19.68 away points, and 40.57 combined points. The exact 300-row result is in `validity-300-observed-overtime-team-label-fix.csv`; the per-seed replay comparison is in `team-label-fix-seed-deltas.json`.

## Provenance

- Pinned snapshot SHA-256: `53f5aafb9ce5a6142ac5c78d39ce3b3643272900be30d53faca83273896ed9a3`
- Run snapshot SHA-256: `83d258f3b8b490fdc78d85b50c4152613d385b5e678a9eab4bd6d67863e49357`
- Reference SHA-256: `5b0fcd076e78793dce3d3dc159a01f2700f163640efd0caca7039725988a0a3a`
- Corrected 300-row CSV SHA-256: `85e7cb0ffdb0b21cdab2043dc16e9a97584e1a6d036046ee587979af799d0d34`

The fixture and reference hashes did not change. Only overtime seeds were replayed because the correction is reached only when the observed overtime table is active.

## Rulebook note

The earlier overtime evidence lists the two-minute warning as an overtime gap. The 2026 rulebook defines that warning at the end of the second and fourth periods (Rule 3, Section 41); regular-season overtime is an extra period. Rule 16, Section 1, Article 3(e) applies the general fourth-quarter provisions, including timing rules, but does not turn overtime into the fourth period. The warning therefore is not missing from overtime. Source: [2026 NFL Rulebook](https://operations.nfl.com/rules-officiating/2026-nfl-rulebook), Rules 3 and 16.

Overtime outcomes are sampled and applied at observed-drive granularity. The reference retains points scored by the offense and defense, including defensive touchdowns, so the drive is resolved through its complete recorded outcome before Rule 16 advances the game. The table has no play-by-play, so it does not reconstruct player-level overtime statistics or condition the sample on the specific Article 5(a) situation.
