# Snap anchored all player movement benchmark

**Registered:** 2026-10-24, before model scoring on the snap cohort
**Status:** development benchmark; weeks 6–9 reserved for future evaluation
**Source season:** 2022 tracking distributed for Big Data Bowl 2025

## Question and scope

Does any unchanged kinematic baseline or the existing Gridiron locomotion controller reduce short horizon all player movement error relative to constant velocity when all approaches receive the same snap available player history?

This benchmark measures player movement only. It does not estimate tackle success, yards gained, scoring, play outcomes, drive results, or game forecasts. The football is retained as an observable label and is not forecast by the player movement arms.

## Cohorts

The event centered diagnostic retains the frozen 49 row manifest and scores only its 40 included development plays. Weeks 6–9 are not part of that diagnostic.

The separate snap anchored cohort uses weeks 1–5. A play is eligible when it has one `ball_snap` frame; pre snap `possessionTeam` and `defensiveTeam` metadata; 11 tracked players on each team; one football row; and complete tracking row presence for those same 22 players and the football from five frames before the snap through ten frames after it. Eligibility can use future **row presence** to establish label coverage, but never future coordinates or outcome labels. All tracked players are included; no player is selected by eventual tackle credit, carrier outcome, or future geometry.

The snap manifest records game/play keys, snap and input frame boundaries, teams, roles, roster position and snap available metadata. It does not store play outcomes or tackle labels. The companion local observation file separates each player's six input positions (snap−0.5 s through snap) from the eleven scoring positions (snap through snap+1.0 s); football coordinates are stored only as labels. Bulk observations remain outside Git.

## Input and alignment

- Source cadence: 10 Hz; each frame is treated as 0.1 s.
- Coordinates: source field x/y in yards, converted to metres without changing field orientation.
- Forecast origin: the unique `ball_snap` frame.
- Input: each player's x/y positions at snap−0.5, −0.4, −0.3, −0.2, −0.1, and 0.0 s. Velocity is the last finite difference. Acceleration is the linear slope across the five 10 Hz finite difference velocities.
- Controller mass: season roster weight converted from pounds to kilograms. Team, role, listed position and the football are not used to choose a trajectory target.
- Excluded from model input: every post snap location, football tracking, eventual tackle frame, credited tacklers, `player_play` outcome fields, play endpoints, and drive outcomes.
- Evaluation horizons: 0.5 s and 1.0 s after the snap. The 0.0 s anchor is excluded from forecast errors.

## Frozen movement approaches

All four receive the same player history and derived origin velocity/acceleration.

1. **Constant velocity:** continue the final history velocity.
2. **Constant acceleration:** extend the history slope without clipping.
3. **Bounded acceleration:** extend that same slope after clipping its vector magnitude to `min(6.5 m/s², 1100 N / listed player mass)`.
4. **Existing locomotion controller:** pass the same acceleration proposal through the pinned `Player.locomote()` implementation at 120 Hz, with its existing 0.12 s response. Reference settings remain `vmax=9 m/s`, `F0=1100 N`, `alat=6.5 m/s²`, and `μ=0.95`.

No parameter fitting, threshold tuning, pursuit policy, collision handling, teammate avoidance, ball handling, or contact simulation is included.

For the event centered diagnostic, the same four approaches use the existing conditional origin at tackle frame−5. Focal defender identity retains the prior manifest rule and therefore remains hindsight defined. All event centered error and minimum separation calculations score only 0.1–0.5 s; minimum separation excludes the exactly matched starting position.

## Metrics

Primary metric: per play mean Euclidean position error over all 22 players at each horizon. Report mean and median error and paired per play difference from constant velocity, including the share of plays improved.

Secondary metrics: within team pairwise spacing error; snap nearest defender pair distance error and nearest defender identity agreement; velocity vector and speed change errors; heading change error; offense and defense centroid displacement and velocity errors; inter team centroid separation error; predicted speed above 9 m/s; and predicted lateral acceleration above 6.5 m/s². Report metrics separately at 0.5 s and 1.0 s.

For the 40 event centered plays, report paired per play carrier/defender position MAE, carrier–defender separation MAE, absolute and signed event separation error, and origin excluded minimum separation and timing error. Count cases where including the starting separation would select the origin as the full window minimum.

## Interpretation and decision rule

Development results can nominate a model for the reserved weeks but cannot establish adoption. A candidate must lower paired all player position error against constant velocity at both horizons, show gains on more than half of paired plays, and avoid a consistent adverse shift in spacing, nearest defender relationships, or team movement. Any future adoption decision requires a frozen model and a separate evaluation on weeks 6–9.

Play outcome and drive result evaluations remain separate. They require their own target definitions, eligible populations, snap available inputs, prediction origins, and scoring rules. No movement result will be described as evidence of outcome or forecast improvement.
