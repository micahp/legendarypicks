# Week 10 family grading: caveats that must travel with the numbers

Read this before quoting any Week 10 figure. Four things limit what the numbers
can support.

## 1. Two grading tiers, never mixed inside an arm

`failures: []` in `all-games-grading.json` means the grading pipeline hit no
error. It does not mean every simulation completed.

Every row carries its own `tier`:

- **26 rows** are the frozen 1,000-seed blocks (`runs/`): NE_DET, BUF_NYJ, and the
  main four arms of CAR_NO, HOU_CLE and JAX_TEN.
- **46 rows** are 100-seed blocks (`runs100/`) started after the 1,000-seed queue
  was stopped.

Tiers are never mixed inside one arm: a 100-seed block reuses seeds
300001-300100, and blending it with the 1,000-seed block would double-count them.

## 2. The precision limit is Monte Carlo error, not the 0.01 step

A 100-seed probability can only land on 0.01 steps. That quantisation floor is
real, but it is **not** the binding constraint, and a difference under 0.02 is not
automatically meaningless because of it. The sampling error is larger, and it is
what should govern the reading:

- **One game is one Bernoulli draw.** The Brier standard error of a single graded
  win-probability is about `sqrt(p(1-p)) * |2p-1|`, e.g. ~0.35 at p = 0.68. A
  single game's arm Brier is not distinguishable from anything within ~±0.3.
- **Arm-level game Brier over 12 games.** With a per-game Brier SD of roughly 0.2,
  the standard error of a 12-game mean is `0.2/sqrt(12)` ~ 0.06. The entire spread
  between best arm (0.2183) and worst (0.2619) is ~0.04 — **inside one standard
  error**. That ordering is not evidence of a better model.
- **Prop Brier over ~200 items per game.** The standard error of a mean Brier at
  that size is `0.25/sqrt(200)` ~ 0.018 per game. The pooled arm-below-market gap
  (~0.05 over 12 games) is larger than this, which is why that finding carries
  weight while individual per-game gaps do not.

Practical rule: treat a difference as signal only when it survives the sampling
error for the sample size being quoted, and always quote the sample size with it.
Do not reach for "quantisation" as the reason a gap is small — the 0.01 step is
usually the smaller of the two effects.

## 3. Seed attrition: two simulation errors, both classified

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
  failure needs a `sack_fumble_lost` from inside its own 10-yard line losing 9+
  yards: rare, but reachable.
- **Effect on the numbers:** 99 vs 100 seeds moves a probability by at most 0.01,
  far below the sampling error in section 2.

## 4. These results do not validate PR #47

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

The goal-line handling itself is being checked separately against the PR #47
branch — see [V17-GOAL-LINE-REPLAY.md](./V17-GOAL-LINE-REPLAY.md).
