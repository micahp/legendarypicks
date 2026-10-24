# BDB2025 snap-anchored all-player movement benchmark — preregistration (2026-10-24)

**Status:** frozen before any movement metric is computed on the snap cohort. Owner: LP tracking
(cohort) and Gridiron movement (metrics). The frozen 49-row tackle manifest is **not modified**
(`docs/research/bdb2025-observed-tackle-manifest-v1.csv`, SHA-256
`3c16d3814847170edfc35ba3ca098ff3c82bbc5f8b36b22c05639780d6b41353`).

## What is and is not claimed

This benchmark measures how well **simple kinematic arms and the existing `Player.locomote()` response**
predict the movement of all tracked players for **1.0 s after the snap**, using only information available
at the snap. It does **not** claim tackle prediction, tackle success, yards, scoring, win probability, calibrated
player physics, or any improvement of a game or drive forecast. Those are separate evaluations.

## Data and frozen inputs

- Source: unofficial 2025 Big Data Bowl mirror of **2022-season** tracking, staged at
  `/root/nfl-tracking-data/bdb2025/code-data/` (outside Git). Rights are user-reported.
- **Weeks 1–5 only.** Weeks 6–9 are not read by this benchmark and remain reserved for held-out
  confirmation after the model choice is frozen.
- Frame rate 10 Hz (`frameId` steps of 0.1 s). Coordinates are yards (x 0–120, y 0–53.3), converted to
  metres with 0.9144. `playDirection` is recorded, not used to flip coordinates.
- Football is the row with `nflId = NA` and `displayName = "football"`.

## Origin, ball policy, alignment

- **Origin = the `ball_snap` event frame** of the play (the same definition as the earlier tackle audit).
  It is cross-checked against the `frameType = SNAP` frame. Any disagreement is counted and the play is excluded
  with reason `snap_definition_disagreement`. Nothing is silently reconciled.
- Horizons are measured in frames from the origin: **0.5 s = origin + 5 frames, 1.0 s = origin + 10 frames**.
  Curves use every 0.1 s step from 0.1 s to 1.0 s.
- **Ball policy:** football position is a label only. It is reported as observed displacement and is not an input
  and is not predicted.

## Eligibility

**Input eligibility, as of the snap (applied before any prediction is made):**

- E1: play exists in `plays.csv` with a non-blank `offenseFormation`. Blank formation is excluded with reason
  `blank_formation`. This is a pre-snap field. Per-week counts are printed by the cohort build and recorded in the
  results, not asserted here.
- E2: exactly 22 distinct tracked players at the origin, 11 per club, with the offense club equal to
  `possessionTeam` and the defense club equal to `defensiveTeam`.
- E3: each of the 22 players has a track at every frame from origin−5 to origin (six frames).
- E4: a football row exists at the origin.

**Scoring eligibility (counting only, never an input):** all 22 players present at origin+5 for the 0.5 s
horizon, and at origin+10 for the 1.0 s horizon. Plays that end early are counted separately and are not
scored at the longer horizon. This condition uses future tracking presence to decide what can be scored, not
what is predicted.

Every exclusion is counted by stage and reason per week, and the counts are printed. No play is dropped silently.
Each week's play count is reconciled to `plays.csv`.

## Model inputs (frames ≤ origin only)

For each of the 22 players: origin position `p0`, origin velocity `v0 = (p(0) − p(−1)) / 0.1 s`, five history
velocities from frames origin−5 to origin, and acceleration `a` = least-squares slope of those five velocities
against their midpoint times (−0.45 … −0.05 s). Also mass from `players.csv` weight, `club` at the origin, and
`hasBall = false` for everyone, because no carrier is identifiable at the snap. Team membership comes from the
pre-snap `possessionTeam` / `defensiveTeam`. Position group from `players.csv` is for description only.
`offenseFormation` is a descriptor only and is not a predictor input in this round.

## Arms (identical inputs for all four)

1. **Constant velocity (CV):** `p0 + v0·t`.
2. **Constant acceleration (CA), unbounded:** `p0 + v0·t + ½·a·t²`, `v(t) = v0 + a·t`.
3. **Bounded acceleration (CA-B):** as CA with `|a|` clipped to **6.5 m/s²**, the pinned engine reference
   `alat` (`engine/constants.js`). Fixed, not fitted. Sensitivity at 3.0 and 9.0 m/s² is reported as descriptive
   only and does not enter the decision.
4. **Existing locomotion controller (LOC):** the unchanged pinned `Player.locomote()` at
   `a09329185451faad44ef7453c7c47bea9d7253a4` (`world.js` SHA-256
   `bc82736164fcd06fffd379efea5b71f6a1373b3dadeb27fe5fa3c1be0f9c0dac`), driven as in the earlier harness:
   desired velocity `v + a·0.12 s`, dt = 1/120 s, 120 steps for 1.0 s, no pursuit AI, no collision, no teammate
   avoidance. The only change is that the forecast length comes from the request instead of being hard-coded to
   0.5 s. Its controller logic is byte-identical.

Reference controller constants are unchanged: `vmax = 9.0 m/s`, `F0 = 1100 N`, `alat = 6.5 m/s²`, `μ = 0.95`
(generic, not fitted to any player).

## Metrics (each computed per play, then compared across arms on the same plays)

- **M1 position error:** `|p̂_i(h) − p_i(h)|` for each of the 22 players at h ∈ {0.5, 1.0} s. The per-play score
  is the mean over players. Also reported by offense/defense and by position group, and as a curve over 0.1 s steps.
- **M2 team centroid error:** distance between predicted and observed centroid of each club at h.
- **M3 spacing:** error in the mean pairwise distance at h, for all 22 players, for the offense only, and for the
  defense only.
- **M4 nearest-defender relationships:** for each offensive player, the defender nearest to that player **at the
  origin** (observable at the snap) forms the pursuit pair. Reported: pair distance error at h, and nearest-defender
  identity agreement at h (does the predicted nearest defender match the observed one?).
- **M5 velocity change:** `Δv(h) = v(h) − v0`, with observed `v(h)` by backward difference at h. Reported:
  `|Δv̂ − Δv|` (m/s) and speed error `|‖v̂(h)‖ − ‖v(h)‖|`.
- **M6 corrected minimum separation:** for each nearest-defender pair, minimum separation over **(0, h]**, with the
  origin **excluded**, its timing, and its error against the observed minimum. Reported with the share of plays
  whose predicted or observed minimum sits at the horizon end (a boundary artefact) and not interior.

## Statistics

- Paired by play. For each metric, the difference `A − B` is taken per play, and the median, mean, share of plays
  where A has lower error, and a **bootstrap 95% CI** of the mean difference are reported
  (2,000 resamples over plays, seed `20261024`).
- Reported per week (weeks 1–5 each) and pooled. No model is fitted and no parameter is tuned on this data.

## Decision rule for "a more sophisticated movement policy is justified"

A more elaborate policy is justified only if **all** of the following hold at **1.0 s**:

1. At least one controller-based arm beats the **best kinematic arm** on the M1 per-play median and mean, by a
   paired bootstrap 95% CI that excludes zero.
2. The sign of that difference is the same in each of weeks 1–5.
3. The result holds on M4 and M5 as well, not on M1 alone.

If any condition fails, the answer is **no**: the kinematic evidence stands and no new policy or calibration is
started. This rule is the decision for this round. It does not establish that movement is unpredictable, and it
does not establish anything about tackles.

## Failure handling

Any missing input, hash mismatch, count mismatch with `plays.csv` or with the 2022 weekly profile, or non-finite
value is a hard error. Excluded plays are never silently dropped; each exclusion is recorded with its reason.

## Reproduction

Cohort build: `scripts/bdb2025/snap_anchored_cohort.py`. Movement comparison and metrics live in the M4d checkout
(`research/physics-3d-evaluation/m4b/m4d/football-tracking-feasibility/`). Hashes of every input and output are
written into the results `provenance` block.
