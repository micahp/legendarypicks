# Does PR #47 fix the goal-line sack-fumble failure?

**Short answer: no.** The guard is byte-identical at PR #47's tip, and the two
Week 10 seeds complete there only because the different code produces a
different trajectory that never reaches the failing state.

The repair is a separate change: **PR #49**
(`fix/slc-v17-goal-line-endzone-2026-11-15`, commit `77a3b563`).

## What the failure was

Two Week 10 seeds hit `FootballAssertionError` / `ILLEGAL_STATE`:

| Game | Arm | Seed | State before | Play |
|---|---|---:|---|---|
| HOU_CLE | v1.7 | 300055 | own 7 (`yl: 93`), 3rd & 10, Q3 | `sack_fumble_lost`, -9 yards |
| JAX_TEN | v1.7-pr43 | 300088 | own 7 (`yl: 93`), 3rd & 10, Q3 | `sack_fumble_lost`, -9 yards |

Both die in the reducer:

```python
# scripts/nfl_sequence/reducer.py, unchanged at 2ebd051e
if st['yl'] - yards > 100:
    raise ValueError(f'{event} loss {yards} carries the ball past its own goal line')
```

A loss into the offense's own end zone is a scoring event, not an illegal state.

## Replay against PR #47 (`2ebd051e`)

Both seeds were replayed on the PR #47 tree with the same snapshot, streaks,
play-call artifact, blocker fixes and profile the Week 10 v1.7 arms used
(`--slc-profile v1_full_stack`, `--playcall-pass-label-mode conditional`).

| Seed | Result on PR #47 | Interpretation |
|---|---|---|
| 300055 (HOU_CLE) | `complete_regulation`, valid, no error | completes |
| 300088 (JAX_TEN) | `complete_regulation`, valid, no error | completes |

**Those completions are not a fix.** `git grep` at `2ebd051e` still finds the
guard at `reducer.py:80`, so the branch would still refuse the state if it
reached it. PR #47 changes RNG consumption upstream, so the replay draws a
different game that never enters the failing state. A seed that completes by
taking a different path is not evidence the path was repaired.

The same replay was run on the repair branch and also completes, for the same
reason. Neither replay exercises the guard - only the reducer tests do.

Profile note: `v1_7_candidate` needs the fitted penalty model plus its two
pinned manifests, which are not present on this host, so these replays use
`v1_full_stack`. The goal-line rule is profile-independent, so this does not
affect the conclusion.

## The repair (PR #49)

`apply_play` now resolves an own-end-zone loss instead of rejecting it:

| Case | Result |
|---|---|
| tackle in the end zone (`run`, `pass_complete`, `sack`) | **safety**, defense scores 2 |
| fumble dead there, `recovery='offense'` | **safety** |
| fumble dead there, `recovery='defense'` | **touchdown**, defense scores 6 |
| fumble dead there, recovery unknown | `UnmodelledOutcome('own_end_zone_fumble_recovery_unresolved')` |

The unknown case is fail-closed deliberately. The published row says the ball
was lost (`fumble_lost`) but not where the loose ball was recovered, so an
end-zone turnover would be invented, not derived. It becomes a named block the
drive loop already classifies rather than an unexplained `simulation_error`.

`apply_play` gains an optional `recovery` argument so a caller that knows the
recovery can score it correctly. Regression tests: seven cases in
`OwnEndZoneResolution` (safety from a sack, safety from a run, defensive
touchdown, offensive recovery, unknown-recovery block, invalid role, and a loss
stopping exactly on the goal line). `test_e1_transitions`: 51 passed.

## Merge state

- **PR #47 is already MERGED** (`gh pr view 47`: `state: MERGED`), head
  `fix/slc-v17-validity-and-seed-failures-2026-11-13` into
  `fix/slc-v17-fractional-state-precision-2026-11-13`.
- The goal-line repair is **PR #49**, opened against that same
  `fix/slc-v17-fractional-state-precision-2026-11-13` branch.
- Forecast-release approval remains separate and untouched: nothing in the
  repair sets `forecast_release_validated`, and the v1.7 penalty rulings stay
  research-only.

No Week 10 rerun is required to land the repair: the change is a reducer rule
plus its tests, and neither Week 10 arm is re-scored by it.
