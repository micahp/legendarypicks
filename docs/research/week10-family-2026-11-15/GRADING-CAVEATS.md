# Week 10 family grading: caveats that must travel with the numbers

Read this before quoting any Week 10 figure. Three things limit what the numbers
can support.

## 1. Two grading tiers, never mixed inside an arm

`failures: []` in `all-games-grading.json` means the grading pipeline hit no
error. It does not mean every simulation completed.

Every row carries its own `tier`:

- **26 rows** are the frozen 1,000-seed blocks (`runs/`): NE_DET, BUF_NYJ, and the
  main four arms of CAR_NO, HOU_CLE and JAX_TEN.
- **40 rows** are 100-seed blocks (`runs100/`) started after the 1,000-seed queue
  was stopped.

A 100-seed probability can only take values in 0.01 steps, so per-game Brier
differences below about 0.02 between arms at that tier are quantisation, not
signal. Tiers are never mixed inside one arm: a 100-seed block reuses seeds
300001-300100, and blending it with the 1,000-seed block would double-count them.

## 2. Seed attrition: two simulation errors, both classified

Coverage is not 100/100 everywhere. Two blocks produced 99 valid seeds:

| Game | Arm | Seed | Status | Failure class |
|---|---|---:|---|---|
| HOU_CLE | v1.7 | 300055 | `simulation_error` | `FootballAssertionError` / `ILLEGAL_STATE` |
| JAX_TEN | v1.7-pr43 | 300088 | `simulation_error` | `FootballAssertionError` / `ILLEGAL_STATE` |

Both share one violated assertion:

```
sack_fumble_lost loss -9 carries the ball past its own goal line
```

Both seeds reach the same state: own 7 (`yl: 93`), 3rd & 10, Q3 with 375 s left,
on a `sack_fumble_lost` that loses 9 yards. The simulator resolves the loss to
`next_snap_spot: 5` instead of recognising the play entered the end zone and
should have resolved as a safety, then trips its own realism guard and refuses
the seed (`state_after: not_applied`).

- **Not a data problem.** The snapshot, roster and prop inputs are shared by arms
  that completed 100/100 on the same game.
- **Not a grading problem.** The seed is never scored; it is excluded upstream.
- **v1.7-only.** Scanning every chunk in both tiers, these are the only two
  simulation errors in 26,250 + 4,600 seeds — both in the v1.7 code paths. The
  same failure would need a `sack_fumble_lost` from inside the 10-yard line
  losing 9+ yards, which is rare but reachable.
- **Effect on the numbers:** 99 vs 100 seeds moves a probability by at most 0.01,
  i.e. inside the 100-seed quantisation floor above.

Open item: the goal-line resolution for `sack_fumble_lost` in the v1.7 paths is
worth a targeted replay of seeds 300055 and 300088 before v1.7 is promoted.

## 3. These results do not validate PR #47

The Week 10 v1.7 arms were built from the earlier v1.7 refs:

| Arm | Ref | Commit |
|---|---|---|
| v1.7 | PR #42, `feature/slc-v1.7-penalty-model-2026-11-12` | `6ac6180c` |
| v1.7-pr43 | PR #43, `fix/slc-v1.7-fractional-state-precision-2026-11-13` | `984751d5` |

Both were invoked with `--slc-profile v1_full_stack` and
`--playcall-pass-label-mode conditional`. Neither uses the newer **PR #47
`v1_7_candidate` profile** or its fitted penalty-model arguments.

So: the v1.7 rows here measure the PR #42/#43 code paths under the v1 stacks
profile. **They must not be presented as a performance validation of the exact
PR #47 candidate.** Validating PR #47 needs its own run at that profile, with the
fitted penalty-model inputs, and its own grading pass.
