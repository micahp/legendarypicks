# Blocked-kick classification: evidence (2026-10-26)

## What changed

Blocked kicks from the observed 2022-2025 table are classified from observed plays, not refused.

- **Untouched blocked field goals.** The receiving team's first run or pass is the next play, in the same quarter, and its
  spot is within 2 yards of the Rule 11-4-2 spot (the holder seven yards behind the line; the receivers' 20 when the holder is
  inside it). That is `classified_next_snap`. In all 30 such blocks the observed starts sat 0 to 2 yards from the rule spot.
- **Blocks that use up the half or the game.** The quarter ends on the block, with only kneels after it and zero clock on its
  last play. That is `period_expired`. No spot is needed, because no possession carries over.
- **Still refused, by name:** 3 field goals and 2 punts with a penalty, fumble, or replay review. Those need penalty and
  fumble handling, which the engine does not model.

Commits: `5ed3c7e6` (classification, fixture sha `0099fce6`) and `e2cd6019` (sampling fix below).

## A defect found and fixed

The first run of this slice had 9 failed seeds out of 300, all `TypeError` in the drive loop. A `period_expired` record was
being sampled into a state whose clock still had time, so the drive continued with no spot.

Fix (`e2cd6019`): a blocked kick is drawn only from records that fit the state. A period-end record fits when its observed
remaining time covers the state's clock. Other records always fit. A state where no record fits refuses by name. E1 also
refuses a period-end outcome whose state clock does not run out.

The 9 seeds from the failed run now complete as ordinary games. The rerun below is from the fixed code.

## Validity result (300 pinned seeds, unconditional, safety table on)

Run from a clean worktree at `e2cd6019`, so no overtime code is included.

| outcome | count |
|---|---|
| valid | 285 |
| tied at regulation end (overtime not yet modelled) | 12 |
| blocked before regulation end | 3 |
| failed | 0 |

Blockers: `overtime_not_modelled` 12, `blocked_kick_outcome_unresolved:field_goal:guarded_penalty_fumble_or_review` 1,
`thin_kick_cell:field_goal:50+` 1, `safety_free_kick_not_modelled` 1.

Wilson 95%: 285/300 = 0.919 to 0.969. The safety-table arm (`docs/evidence/e2-safety-kick/`) was 261/300 = 0.827 to 0.903.

**This is not a paired comparison.** The blocked-kick fixture is part of the reference fingerprint, so every seed is
re-keyed. Read the difference as independent Monte Carlo, not as a seed-by-seed effect.

## Limits

- The three remaining refusals are listed above. Penalty, fumble, and review handling on blocked kicks is not modelled.
- The 50+ field-goal cell has 4 published attempts in 2022-2025. The engine refuses a thin cell rather than filling it from a
  neighbour, so that seed is refused until a data-window decision is made.
- Overtime ties are counted as not yet modelled in this run. The overtime slice is separate.

## Files

- `validity-300-unconditional.csv` and `.json`: the rerun described above.
