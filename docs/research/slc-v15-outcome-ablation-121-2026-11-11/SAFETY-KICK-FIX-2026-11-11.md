# SLC safety free-kick clock and source regression (2026-11-11)

**Status:** isolated new-code correction; the running V1.5 121-game ablation and its historical artifacts remain unchanged.

## End-of-regulation validation

The preserved failures are `2026_03_LA_DEN` (ablation seed 9, safety at Q4 0:06) and `2026_04_LAC_SEA` (control seed 16, safety at Q4 0:47). Both records show a safety free kick marked as expiring the fourth quarter. `game_legality._game_ending_kick` already recognized expiring halftime safety kicks elsewhere, but rejected this game-ending form. It now recognizes Q4 safety kicks ending regulation, and the final-drive path also verifies that it follows a safety, that the team conceding the safety kicks, and that kickoff timing matches the preceding drive. A non-expired kick, a Q3 kick or a safety kick in overtime does not qualify.

Rules: [Official NFL 2026 Rules 4 and 6](https://edge-operations.nfl.com/rules-officiating/2026-nfl-rulebook). The free-kick clock starts at legal touching and stops on the dead ball; it can run out during a real return.

## Source-data error and correction

The original 2022–2025 safety-kick fixture contains 57 observed safety plays and 46 marked usable. Of those, **six** are onside kicks. The 2025 CLE–NE onside kick was recovered by the kicking team, but the old fixture builder skipped its intervening offense and borrowed a later receiving-team snap, generating a fictitious **48-second kickoff interval**.

New model loads exclude all six old onside samples, yielding **40 ordinary receiving-team safety-kick samples**. The loader verifies the original fixture hash and reconciles the six exclusions with its historical manifest. The fixture and manifest remain immutable for old run provenance; the code version identifies the new sampling model. The builder now explicitly refuses onside safety kicks, never jumps past the first post-kick scrimmage possession, and rejects a second kick before the receiver's first snap.

The source Parquet was unavailable for a hash-verified fixture rebuild in this patch environment. A future versioned rebuild from original pinned 2022–2025 files can supersede the original fixture, but must never silently overwrite the historical file.

This fixes the identifiable onside-recovery contamination. A **29-second non-onside kick-to-next-snap** fixture remains and should be inspected at play level: the model's interval is not proof of 29 seconds of live-ball return. No arbitrary physical-runoff cap was introduced.

## Regression commands

```sh
python3 -m pytest scripts/nfl_sequence/test_game_legality.py scripts/nfl_sequence/test_safety_kick_outcomes.py
```

The original two failed seed records must be retained and source IDs inspected. Do not count any regraded run as the original model; reruns under this patch require a new code hash and a paired control/treatment cohort.
