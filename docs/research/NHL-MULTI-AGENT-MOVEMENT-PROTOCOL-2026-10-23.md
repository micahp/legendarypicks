# NHL multi-agent movement engine v0.1: frozen development protocol

Frozen 2026-10-23 before candidate fitting  
Legendary Picks branch: research/nhl-multi-agent-movement-2026-10-23  
Base: 5528cf43ecb6d9e8af16379b6954f9c3ac3dcf27  
Source: Stathletes Big Data Cup 2026, ten anonymized games  
Use: noncommercial research only

## Why this code and these derived values

The code needs to exist because the current kinematics fit predicts one skater endpoint and has no joint state, closed-loop rollout, or sport-neutral execution interface. The publisher supplies observed coordinates, not multi-agent policies, headings, interaction effects, or movement forecasts. These derived values will be labeled as estimates and remain in ordinal observation units.

## Data and timing decision

The existing ten-game release manifest and quality audit govern file eligibility. They cover 54 assets and 959,754 Image Id groups. Earlier audit, model, and prediction artifacts are preserved.

Metadata inspection found:

- The organizer README documents Image Id, period, Game Clock, entity/team/track identifiers, and rink XY/Z. It publishes no subsecond timestamp or capture cadence.
- The local download manifest records asset names, byte counts, SHA-256 digests, source URLs, and release identifiers, but no capture-time field.
- camera_orientations.csv records which team has its goalie on the right in period 1. This is orientation metadata, not timing. It may label a period-one display transform; later-period attack direction remains unknown.
- The full-population audit reports 32 measurable suffix/game-clock proxies from 44.79 to 76.33. The whole-second clock and inconsistent ratios do not identify cadence.

No timing relationship will be fitted. Horizons and movement rates use numeric Image Id suffix increments. One controller update is one ordinal suffix increment. Feet per Image Id increment is not feet per second. Physically timed simulation remains disabled.

The event-coordinate alignment gate failed. Event coordinates, event types, outcomes, event-derived possession, shot labels, and goalie roles are excluded from features, scenario selection, and targets. Puck proximity is a geometry proxy, never a possession label.

## Input quality gates and frozen dispositions

These data gates are checked before fitting; a failed gate narrows use rather than being repaired with
future labels or inferred identities.

| Gate | Acceptance condition | Measured disposition |
|---|---|---|
| Release integrity | All 54 manifest assets match published byte counts and SHA-256 values. | Existing audit PASS; the extractor independently rehashes all assets. |
| Rink XY validity | At least 99.0% of coordinate rows are finite and inside the declared rink bounds. | 8,355,303 / 8,401,602 = 99.449%; PASS for XY movement research. |
| Ordinal ordering | Image Id suffixes strictly increase within each period file; a suffix gap resets a track history. | Existing order gate PASS; 793 gaps are retained as missing observations, never bridged. |
| Timed simulation | A publisher-documented subsecond timebase and independently validated cadence are available. | FAIL: no timestamp/cadence field; 27 game-clock reversals and 1,102 missing-clock observation groups. Use ordinal suffix increments only. |
| Athlete identity | No conflicting jersey mapping among fitted track-period IDs; quarantine every conflicting ID and its windows. | 292 / 32,312 IDs conflict (0.904%); 7,697 / 462,680 windows excluded; 454,983 remain. Cross-game identity remains unverified. |
| Endpoint training coverage | At least 10,000 eligible windows overall and 1,000 in every game. | Prior quarantine audit: 454,983 total and more than 31,000 in each game; PASS. Exact extractor counts must reconcile again. |
| Autonomous start coverage | Exactly 20 valid starts per game, spread across eligible period files; each has 3 stable skaters per team, six consecutive pre-cutoff observations, and 45 suffix increments remaining. | Enforced as a fail-loud extraction gate; future locations are not used to qualify or select starts. |
| Event integration | Prior event-to-track coordinate-alignment gate must pass before any event-linked movement label is used. | FAIL; events and all event-derived features/labels are excluded. |
| Puck movement | A puck displacement feature is present only when current and immediately prior consecutive XY are valid; otherwise mark unavailable. Timed or physical puck flight requires independently validated continuity and Z. | Current puck XY exists in 918,907 / 959,754 groups (95.744%); continuous flight and Z remain unvalidated. No physical puck simulation. |
| Player-specific skill | Require enough persistent, identity-verified within-player observations for split-half reliability before fitting athlete-specific parameters. | Prior split-half audit qualified 0 track-period entities; only 1 entity reached 3,000 frames. Preserve scoped track IDs, but fit pooled policies and claim no individual skill. |

The coordinate condition is sufficient to model observed 2D rink positions, not to align event records.
The identity condition is sufficient for within-file track histories, not cross-game athlete models.
The puck condition supports a missing-aware relative-position feature, not possession, shot trajectory,
goalie response, rebound, or puck physics. The source does not adequately identify those targets.

## Eligibility and normalized state

Read the source release from /root/lp-research-data/stathletes-big-data-cup-2026. Recheck manifest sizes and SHA-256 values before extraction. Keep the source release and full normalized observation stream outside both repositories.

Normalize every source observation group with:

- game, period, source Image Id, numeric suffix, and within-file observation index;
- observed player and puck XY in rink feet;
- team and game-period-file-scoped track ID and jersey where supplied;
- past-only heading and displacement proxy estimated from the preceding six consecutive valid observations;
- visibility, coordinate-validity, identity-consistency, and missingness flags;
- visible tracked-player lists by team, without claiming a complete official lineup;
- source filename, release-manifest hash, and coordinate-transform provenance.

Do not interpolate missing positions. Conflicting track-ID-to-jersey mappings are displayed as conflicted and excluded from learned movement. Never join track IDs across games. If the source supplies no confidence field, confidence is explicitly unknown; no numeric value is invented.

The full normalized observation sequence is a reproducible external artifact. Only compact selected observed/simulated scenarios and hashes may be checked into the noncommercial research branches.

## Frozen targets, policies, and split

### Shared data and split

- Use the prior study’s six consecutive positions through cutoff t and same-player target at t+15 suffix increments for one-step endpoint training and evaluation.
- Use only rows eligible under the prior identity and coordinate quarantine. All candidates use identical player windows, outer folds, and rollout starts.
- All ten games remain development data. Use leave-one-whole-game-out outer predictions. This is not independent adoption evidence.
- Fit feature means/scales, regression coefficients, movement bounds, turn limits, spacing threshold, and uncertainty calibration on outer-training games only.
- For each fold, use the next game in sorted order as calibration, skipping the held-out game; fit calibration on the remaining eight games. Refit point models on all nine outer-training games.
- Fixed seed 20261023 and 10,000 game-cluster bootstrap replicates. Do not add Monte Carlo noise to movement proposals.
- Rollout candidate selection uses a per-file deterministic reservoir seeded by SHA-256 of the source filename plus the fixed seed. Retain up to ten candidates per period file, allocate exactly twenty starts per game as evenly as possible across that game's eligible period files, then take evenly spaced positions from the sorted retained candidates. If a period cannot fill its quota, redistribute the remainder over other retained candidates in sorted period/time order; fail if twenty starts still cannot be formed.

### M0: independent learned kinematics

Use the existing six-position linear-velocity and quadratic-acceleration features, the existing constant-velocity 15-increment endpoint, and a pooled ridge residual correction with alpha 0.1. Standardize on training games only. Predict each player independently; do not use puck or neighbor state.

Compare its direct 15-increment endpoint against the committed development reference: 3.222 ft for learned kinematic prediction and 3.202 ft for its prior constrained endpoint. These are reproduction benchmarks, not expected free-running results.

### M1: interaction-aware learned movement

Use the same M0 features and endpoint baseline, plus only state observed at or before cutoff t:

- puck-relative position and past puck displacement, with a missing-puck indicator;
- distance-weighted relative position and past displacement aggregates for eligible teammates and opponents;
- teammate and opponent counts within 10, 20, and 40 feet.

Fix distance-weighting scale at 20 feet. Standardize on training games only and use ridge alpha 0.1. Do not include player IDs, jerseys, game IDs, future coordinates, events, outcomes, or an inferred possession label as predictors. Neighbor aggregation is permutation-invariant; no graph neural network is evaluated.

### M2: M1 proposals with 2D constraints

Use the exact M1 fitted proposal. Apply fold-specific, training-only constraints at each ordinal observation step:

- maximum displacement: 99.5th percentile of valid one-suffix observed displacement magnitudes;
- maximum displacement change: 99.5th percentile of valid adjacent displacement-vector differences;
- maximum turn: 99.5th percentile of observed one-suffix heading changes, only where both displacements exceed 0.1 feet;
- rink bounds: X [-100, 100] feet and Y [-42.5, 42.5] feet;
- soft pair-separation floor: fifth percentile of per-observation nearest-player center distances.

Pair separation is a learned 2D spacing constraint, not body geometry, collision, contact, or a validated hockey mechanic. Report corrections and residual violations. Do not invoke Rapier, Jolt, the NFL solver, or 3D contact.

## Closed-loop rollout

The controller updates once per Image Id suffix increment, with no conversion to seconds. At each update, a policy reads the current simulated state and its six-position history, predicts its learned 15-increment endpoint, and proposes one fifteenth of the endpoint displacement. M0 and M1 execute the proposal directly. M2 applies the frozen movement, turning, rink, and pair-separation constraints before advancing all players together.

After the first update, histories contain only initial observed state and previously simulated positions. No recorded future player or puck location is given to a policy. For rollout context only, a visible puck follows a constant ordinal-displacement extrapolation from its past six observations. This helper is not puck physics. If puck XY is missing or extrapolation leaves the rink, puck context becomes unavailable; it is not clamped, reflected, or replaced.

Create 20 deterministic start cutoffs per game (200 total), distributed evenly across eligible period files. Eligibility and selection use only pre-cutoff fields: six consecutive observations for at least three consistent tracks per team and sufficient suffix range for the declared 45-increment horizon. Targets after cutoff are evaluator-only labels. All models use the same starts.

Score one-step controller positions at +1 and free-running positions at +1, +5, +15, +30, and +45 suffix increments. Missing future labels are counted by reason and scored on the common observed subset. Missing labels do not alter generated states.

## Metrics and decision rule

Report equal-game-weighted mean, median, and P90 position error by horizon; heading and displacement error; pair-distance error; team spacing; 2D occupancy divergence using 10-foot cells over X [-100,100] and Y [-42.5,42.5] with total-variation distance; opponent closing-distance distributions; boundary violations; proximity below the empirical spacing floor; path smoothness and turn exceedances; missing labels; identity exclusions; endpoint calibration coverage; runtime; and 95% game-cluster bootstrap intervals.

Call the development interaction signal supported only if M1 reduces equal-game mean position error by at least 2% versus M0 at both +1 and +45, with both paired 95% bootstrap intervals entirely below zero. Otherwise report no supported development interaction improvement. Report M2 minus M1 separately under the same metrics; favorable results do not validate real-world physical mechanics.

Adoption requires independent games, validated timing, identity continuity, tracking-error evidence, and a separately frozen evaluation.

## Representative scenario selection

Choose the first deterministic qualifying cutoff for each category using state at or before cutoff only, and preserve those category examples in addition to the shared 200 rollout starts. Also retain all 200 starts (20 per game) in the visual archive. Labels are geometry descriptions, not event interpretations:

1. puck near a team’s attacking end, only in period one with supplied orientation; label puck-proximity, not possession;
2. puck near a team’s defending end under the same period-one orientation;
3. puck in the central strip (absolute X <= 25 feet), a neutral-zone geometry proxy;
4. at least three eligible skaters with decreasing past-only puck distance;
5. one skater with increasing past-only distance from the nearest eligible opponent;
6. at least three teammates with aligned past displacement directions;
7. a sequence showing missing coordinates or a conflicted track, displayed with an uncertainty flag.

Use the first deterministic qualifying cutoff for each category, avoid duplicate cutoffs, and record a category as unavailable if none qualifies. Never select by future prediction error.

Each recording stores observed trajectories, M0/M1/M2 outputs, evaluator-only future observations, input cutoff, horizon, model/code version, source-file hashes, identity/timebase flags, policy/constraint configuration, and fixed seed. Observed and generated paths use different visual styles and labels.

## Frozen deliverables and validation

- Metadata/timing audit, normalized-state extractor, model fit, and free-running evaluator.
- By-game and equal-game metrics with game-bootstrap intervals and exact sample reconciliation.
- Gridiron Physics movement interface and hockey adapter outside the NFL engine.
- Three.js top-down/side/orbit viewer, model comparison, scrubber, trails, vectors, distances, uncertainty, and per-player errors.
- Versioned scenario archive with compact transform timelines and representative video.
- Report covering unmeasured puck possession, physical contact, and independent-validation requirements.

Validation includes Python syntax compilation, extractor smoke on a small real unit, full hash/count reconciliation, model output gates, standalone Gridiron movement tests, unchanged NFL headless validation, and rendered-page verification. Neither production solver, database, forecast, ratings, ongoing Rapier/Jolt work, nor earlier NHL artifacts may be modified.

