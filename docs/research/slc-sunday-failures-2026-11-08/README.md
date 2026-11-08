# Sunday validator failures, 2026-11-08 slate

Fourteen seeds refused by the validator across the 50-seed pass (1–50) and the 51–200 extension, all on the executed code in `exec-2026-11-08-sunday-smoke` (d6caadd3, base 9667cbc1 plus patch). Each row is one seed.

- `failures.csv`: game, seed, original run, original status and error, and the result of rerunning that seed alone with the same snapshot and flags.
- `original-ledger-rows/`: the original ledger row for each failing seed, exactly as the batch wrote it.
- `refused-records/`: the full refused game record (gzipped JSON) for each failure that reproduced when rerun alone. Six reproduced: ARI–SEA 196, 197; GB–NE 64, 96, 100, 190.
- `run_failures.sh`: the rerun script.

## Finding: the batch is not deterministic

Eight failures did not reproduce when their seed was rerun alone: CIN–ATL 50 and 69, CLE–NO 29, DAL–IND 47, DEN–CAR 186 and 198, DET–MIA 59 and 117. An exact rerun of the original CIN–ATL 50-seed command changed the outcome: seed 50 passed, and seed 17 failed with a new error. The same command on the same tree is therefore not reproducible. Possible causes not yet tested: process-level hash ordering, on-disk caches, or state carried between seeds in one process.

Repairs should start from the six reproduced records. The eight non-reproducing failures need the determinism question answered first, or they can't be tied to a specific cause.

## Repairs (validator)

All six reproducible records now pass the validator. Three rules the validator applied were narrower than the engine's own:

- A blocked field goal sets `field_goal_attempt` but leaves the ball live. It ends a drive only through a touchdown, turnover or change of hands (`_ends_drive_flag`). Fixes ARI-SEA 196, 197.
- A missed or blocked kick that expires the fourth quarter with the score untied ends the game (`_ends_the_game`). Fixes GB-NE 64, 96, 190.
- A safety free kick that expires the first half is followed by the second-half kickoff, as a post-score kick is (`_ends_first_half`). Fixes GB-NE 100.

A blocked kick no longer triggers the down-and-distance check, the same as a penalty. Unit tests cover each rule.

Not repaired: the eight failures that did not reproduce, and the overtime-kickoff defect in CLE-NO 29, which did not reproduce either. The determinism question is still open.

## Repairs (validator)

All six reproducible records now pass the validator. Three rules the validator applied were narrower than the engine's own:

- A blocked field goal sets `field_goal_attempt` but leaves the ball live. It ends a drive only through a touchdown, turnover or change of hands (`_ends_drive_flag`). Fixes ARI-SEA 196, 197.
- A missed or blocked kick that expires the fourth quarter with the score untied ends the game (`_ends_the_game`). Fixes GB-NE 64, 96, 190.
- A safety free kick that expires the first half is followed by the second-half kickoff, as a post-score kick is (`_ends_first_half`). Fixes GB-NE 100.

A blocked kick no longer triggers the down-and-distance check, the same as a penalty. Unit tests cover each rule.

Not repaired: the eight failures that did not reproduce, and the overtime-kickoff defect in CLE-NO 29, which did not reproduce either. The determinism question is still open.
