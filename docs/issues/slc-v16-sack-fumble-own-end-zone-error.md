# Issue: v1.6 stops with an engine error when a sack fumble lands behind its own goal line

- **Status:** open. Opened 2026-11-23 from the week 11 rerun (`docs/research/week11-rerun-preflight-2026-11-23/`).
- **Failure class:** engine error (`status: simulation_error`). This is a defect, not an unsupported cell.
- **Model:** v1.6 pack `v1.6--season-2026.slcpkg`, sha256 `6cf1e836...`, code commit `1bb3bd50`.
- **Remote issue:** not created.

## What happens

Two of 1,300 v1.6 seeds in week 11 stopped:

| game | seed | state before the play | sampled play | ball would end at |
|---|---|---|---|---|
| MIA at BUF | 300081 | Q3, 3rd and 8, 97 yards from the opponent goal | `sack_fumble_lost`, -9 yards | 106 (6 yards deep in its own end zone) |
| MIN at SF | 300097 | Q3, 3rd and 7, 92 yards from the opponent goal | `sack_fumble_lost`, -10 yards | 102 |

The engine draws a historical sack fumble row with its original yardage. At this field position, that yardage puts the ball
behind the offense's own goal line. `reducer.apply_play` (`1bb3bd50:scripts/nfl_sequence/reducer.py:76`) then raises
`ValueError: sack_fumble_lost loss N carries the ball past its own goal line`, and the seed is lost as a
`simulation_error`. Only v1.6 can reach this state: it keeps sack fumbles as their own event with the sampled
yardage. In v1 (`58ef3861`), v1.5 (`2eab8a89`), v2 and pbv1 (`8a1d9842`) a sack fumble is a plain `fumble_lost` that
takes the published spot, and in every model run, pass and sack losses already stop at the goal line
(`e1_drive._credit_field_boundary_yards`).

## Fix (2026-11-23)

`cf8fd47b` on `fix/slc-v1.6-rules-2026-11-23`, on top of `1bb3bd50`: ports the V1.7 geometry filter (`3b8e8890`)
behind `--slc-geometry-filter`, off by default. With it on, a fumble source row whose net gain crosses a goal line at
the live state is left out of the draw. `test_geometry_filter.py` covers both week 11 states. The v1.6 pack is rebuilt
with the flag on, and its new commit and pack hash go in the registry.

## Existing work: PR #49 and its branch

PR #49 ("Resolve own-end-zone losses instead of refusing them", merged 2026-11-17, merge `a716c649`) is about this
exact state. Checked 2026-11-23:

- `a716c649` is **not** an ancestor of `1bb3bd50` (the v1.6 pack) or of `origin/dev`. It **is** an ancestor of
  `1ca59e0d`, the v1.7 pack. `1bb3bd50` and `1ca59e0d` are the same change ("Require overtime in every full game") on
  two lines: the v1.6 line is kept free of the v1.7 research code on purpose (see the comment in
  `_turnover_geometry_eligible`: "never a silent V1.6 change").
- At `a716c649` the guard has three switches, all off by default:
  - `own_end_zone='resolve'`: a tackle behind the goal line is a safety. A **fumble** that ends there
    (`sack_fumble_lost` is a turnover event) raises `UnmodelledOutcome('own_end_zone_fumble_recovery_unresolved')`.
    So this switch alone turns these two seeds from an engine error into a named block. They still do not complete.
  - `geometry_filter=True` (also on when the penalty layer is on): at this state, turnover source rows whose
    yardage crosses a goal line are left out of the draw. The engine then draws a legal row and the game goes on.
  - `recovery_model`: a fumble at or past the own goal line draws its recovery result (safety, defensive touchdown,
    recovery in the field) from audited 1999 to 2025 frequencies. The game goes on.
- So yes, the #49 line addresses these two failures, but only with the geometry filter or the recovery model on. It
  is not in v1.6. These two seeds were not rerun on any #49 build.

## What to do

- Do not change the v1.6 pack or its results. A repair is a new, separately versioned build (for example
  `v1.6.1`, the v1.6 line plus the #49 resolver and the geometry filter or the recovery model). Evaluate it on the
  same snapshots and seeds, side by side with v1.6, before it replaces anything.
- Do not write a new fix. Port the #49 code.
- Test: replay MIA at BUF seed 300081 and MIN at SF seed 300097 on the new build. Both must complete. Their seed
  streams change after the play, so the other seeds can move too. Report the full-batch change.
