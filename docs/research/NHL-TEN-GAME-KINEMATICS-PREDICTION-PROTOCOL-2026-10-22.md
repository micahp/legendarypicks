# Ten-game kinematics prediction protocol

**Study branch:** `research/nhl-ten-game-kinematics-2026-10-22`  
**Quality audit:** `research/nhl-ten-game-kinematics-2026-10-22/quality/tracking_quality.json`  
**Frozen before model fitting:** 2026-10-22

## Gate disposition and scope

The frozen raw-release gates pass for release integrity, rink-coordinate coverage, aggregate
forecast-window volume, and puck row/coordinate coverage. They fail for the initial 25–32
Image-Id/game-clock-second proxy check, clock monotonicity (27 reversals), track-ID-to-jersey
consistency (292 conflicting track-period IDs), and event-coordinate alignment. These outcomes are
not reclassified as passes.

The official [Big Data Cup 2026 data dictionary](https://github.com/bigdatacup/Big-Data-Cup-2026)
defines `Image Id`, period, whole-second game clock, and rink coordinates, but supplies no capture
rate or subsecond timestamp. Numeric Image Id suffix/game-clock ratios also vary by file. Therefore
the experiment predicts the next **15 consecutive Image Id increments**; it does not call that a
known fraction of a second and it does not convert Image-Id-index derivatives into real-world speed.
Clock values, events, shot outcomes, and goalie labels are excluded from all candidate inputs and
targets. Any window crossing a missing Image Id suffix, coordinate, identity conflict, file, or period is
discarded.

The selected mechanism is a skater's short-horizon 2D path. This is the movement component with
sufficient observed volume to test. It is not a shot, rebound, possession, or goalie-response
experiment. Only track-period identities whose nonblank jersey mapping is consistent for the full
file are eligible. Identity is scoped to game, period, team, track ID, and jersey; there is no
cross-game athlete merge.

After that quarantine, fitting proceeds only if at least 10,000 windows remain overall and each of
the ten development games contributes at least 1,000. This retains the frozen window-volume floor
for every outer held-out fold.

## Frozen target and candidates

Each example uses the same skater's six consecutive observed XY positions through cutoff `t` to
predict its XY position at `t+15`. Coordinates are rink feet. Samples are emitted at most once per
15 Image Id suffix increments for a track. No future observation is used as a feature.

1. **Constant velocity:** fit a least-squares line to the six input positions and extrapolate its
   slope by 15 Image Id suffix increments.
2. **Learned kinematic correction:** predict the two-dimensional residual from the constant-
   velocity endpoint using pooled ridge regression on the six-position linear velocity and
   quadratic acceleration estimates. Standardization uses the fitting games only; the intercept
   is unpenalized and the fixed ridge penalty is `0.1` under a mean-squared-error objective.
3. **Constrained kinematic prediction:** project candidate 2's average per-Image-Id-increment displacement into
   the intersection of a training-only speed disk and acceleration disk. Their radii are the
   99.5th percentiles of six-position speed and acceleration estimates from fitting games. Clip the
   endpoint to the documented rink bounds. Candidate 3 differs from candidate 2 only by these
   constraints, so their paired difference measures the effect of the feasibility projection.

These are deterministic trajectory predictions on common windows. Candidate 3 tests empirical
per-Image-Id-increment kinematic feasibility and rink boundaries; it does not implement validated collision,
reachability, skating biomechanics, or puck physics.

## Separation, calibration, and uncertainty

- All ten anonymized games are development data. Use leave-one-whole-game-out outer predictions;
  all three candidates use identical eligible windows in each held-out game.
- Within each outer fold, select one calibration game by taking the next game in sorted order,
  wrapping around and skipping the held-out game. Candidate models and kinematic limits for the
  calibration residuals are fit on the other eight games. Refit point-prediction candidates on all
  nine outer-training games before scoring the held-out game.
- For each candidate and fold, use the calibration game's 90th percentile radial residual as the
  held-out 90% prediction-radius threshold. Report achieved coverage; this small-sample,
  game-calibrated interval is descriptive and not a formal population guarantee.
- Report per-game and equal-game-weighted mean Euclidean position error, median and 90th percentile
  error, displacement-magnitude error in feet per 15-Image-Id-increment horizon, and heading error when observed
target displacement is at least one foot. Also report calibration coverage, eligible window
  counts, and runtime.
- Report paired candidate differences with a 10,000-replicate game-cluster bootstrap, seed
  `20261022`. The ten-game intervals describe development-set variability only.
- Do not tune hyperparameters, choose thresholds, or select a candidate using the held-out fold
  results. There is no independent adoption set in this release.

## Player-specific movement description

Retain stable track-period IDs for descriptive analysis only. For entities with at least 3,000
valid observed Image Id groups and at least 100 eligible kinematic windows in each chronological half,
report per-half median movement rate (feet/Image-Id increment), 95th percentile acceleration proxy
(feet/Image-Id increment²), and median absolute turn angle per Image-Id increment. Report split-half rank stability and
counts. Split each track-period file at the midpoint of its first and last Image Id suffix. Estimate
turn from linear slopes on input positions 1–3 and 4–6, divide the absolute angle change by three
Image Id increments, and include it only when both slope magnitudes exceed 0.1 feet/Image-Id increment. Do not
convert these quantities to physical speed or present them as athlete skill ratings.
Do not estimate reaction ability: the release has no subsecond stimulus/onset labels. A track ID is
not assumed to identify the same real athlete in another game.

## Adoption boundary

All ten games have already been inspected and are development data. Even a favorable leave-one-game-
out comparison is not an adoption result. Adoption requires independent games with a documented
subsecond timebase, verified stable player identities, and a separately frozen evaluation. Shot,
goalie, rebound, and possession modeling remain out of scope until their event labels can be aligned
to the tracking timeline and their quality gates pass.
