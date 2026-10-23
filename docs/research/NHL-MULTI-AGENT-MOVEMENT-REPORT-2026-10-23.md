# NHL multi-agent movement research v0.1

**Status:** ten-game development study; no adoption or production decision.
**Legendary Picks branch:** `research/nhl-multi-agent-movement-2026-10-23`
**Gridiron Physics branch:** `research/hockey-movement-engine-v0.1-2026-10-23`
**Use:** research-only; source terms govern reuse.

## Decision

The interaction model improves the one-step endpoint benchmark and the 30- and 45-observation
free-running endpoints. It misses the frozen rollout criterion because its +1 error is worse than
M0. Its joint geometry also degrades: pair-distance, team-spacing, and nearest-opponent distribution
errors rise at +45, even as the global occupancy histogram improves. M2 removes nearly all
empirical-spacing-floor violations and rink-boundary projections, but does not improve +45 position
error over M1. These are mixed results on ten inspected development games, so none supports adoption
as an NHL simulator or use in Legendary Picks probabilities.

The implemented system is useful as a reproducible research harness: it loads a multi-player hockey
state, executes all three policies for 45 ordinal observation steps without recorded future positions,
and compares the generated paths with held-back observations. Its spatial constraints are measured
2D regularizers, not validated hockey physics.

## Data quality, provenance, and timing

The input is the ten-game anonymized Stathletes Big Data Cup 2026 release, under the [release
terms](https://github.com/bigdatacup/Big-Data-Cup-2026/releases/tag/Data) and [public-data
agreement](https://github.com/bigdatacup/Big-Data-Cup-2026/blob/main/legal.md). All 54 release
assets were hash-verified during preparation and independently rechecked before the compact scenario
archive was registered. Raw tracking and the full normalized stream remain outside both repositories.

| Gate or population check | Measurement | Result |
|---|---:|---|
| Image Id observation groups | 959,754 | Reconciled |
| Coordinate rows | 8,401,602 | Reconciled |
| Finite in-rink XY rows | 8,355,303 (99.449%) | Passes the frozen 99% gate |
| Rows with missing/invalid XY | 46,299 total; 5,452 player rows | Kept missing; not imputed |
| Puck XY | 918,907 / 959,754 groups (95.744%) | Missing puck state is explicit |
| Player rows | 7,441,848 | Reconciled |
| Conflicted game-period track IDs | 292 / 32,312 (0.904%) | All quarantined |
| One-skater windows | 462,680 raw; 454,983 eligible | 7,697 conflicted windows excluded |
| Rollout starts | 20 per game; 200 total | Passes the frozen sampling gate |
| Image Id suffix gaps / game-clock reversals | 793 / 27 | History resets at suffix gaps |

The source release and tracking headers contain no documented subsecond timestamp, frame rate, or
cadence. The 32 Image Id/Game Clock ratios previously audited range from 44.79 to 76.33 and are not
valid timing estimates. The Image Id suffix is used only as an ordinal observation index. Position
differences are measured in the release's rink-coordinate feet; they are not feet per second,
acceleration in ft/s², or reaction delays. Timed movement remains gated.

The prior event-to-tracking coordinate-alignment gate failed. Event outcomes and locations are not
used as features or labels here. Cross-game athlete identity is unverified, and the prior reliability
screen did not qualify any track-period entity for a player-specific model. Track IDs remain scoped
to game and period. Period-one goalie-right orientation is the only verified attack-direction map;
later-period attack direction is unknown. Puck Z is not a continuous flight measurement. Puck
proximity labels in this report describe geometry and do not imply possession.

## Frozen experiment

The model specification, feature cutoff, metrics, rollout sampling, and success rule were frozen in
[`NHL-MULTI-AGENT-MOVEMENT-PROTOCOL-2026-10-23.md`](NHL-MULTI-AGENT-MOVEMENT-PROTOCOL-2026-10-23.md)
before fitting. Ten leave-one-game-out folds train on nine games and predict the tenth. Candidate
inputs contain only the six pre-cutoff observed positions for each eligible skater and the current
cutoff state of the puck and other eligible skaters. Future labels are opened only after each
free-running rollout finishes. A future position never enters the policy state. All candidates use
the same held-out windows and 200 rollout starts.

- **M0, independent kinematics:** the prior ridge correction using six-position velocity and
  acceleration features, applied independently to each skater.
- **M1, interactions:** the M0 features plus puck-relative location and displacement, missing-puck
  indication, distance-weighted relative position and movement of teammates and opponents, and
  nearby-player counts. Neighbor summaries are permutation-invariant; identities and event labels do
  not enter the fitted policy.
- **M2, interactions with constraints:** the same M1 proposals passed through training-fold-only
  per-observation displacement, displacement-change, turning, rink-boundary, and soft pair-spacing
  projection in the observed 2D plane. Pair projection uses two passes and may leave residual
  below-floor pairs.

The M2 fold thresholds averaged 1.303 ft per ordinal increment for displacement, 0.870 ft per
increment for displacement change, 2.864 radians per increment for turning, and 2.682 ft for the
empirical pair-spacing floor. They are sample-derived bounds, not physical player capabilities or
validated collision distances. Rapier, Jolt, the NFL play engine, and football contact mechanics are
not used.

The one-step endpoint is 15 ordinal suffix increments from the cutoff. Autonomous rollouts start
from the 200 observed states and advance every eligible skater together for up to 45 increments.
From the first generated update, each policy receives only its own simulated player positions and
history. The puck context uses an explicitly labeled constant ordinal-displacement helper; it does
not simulate puck physics. Missing future player labels are excluded from scoring, never synthesized.

The 95% intervals below use 10,000 paired bootstrap draws over whole games, with equal weight per
game. Ten game clusters limit how precisely the intervals describe behavior outside this inspected
sample. They are development uncertainty intervals, not independent validation.

## One-step endpoint results at +15 ordinal increments

| Model | Mean position error, ft (95% game interval) | Median, ft | P90, ft | Path-direction error, degrees | Calibrated 90% radius, ft | Empirical coverage (95% game interval) |
|---|---:|---:|---:|---:|---:|---:|
| M0 | 3.222 [3.127, 3.327] | 2.835 | 6.033 | 30.10 | 6.033 | 89.76% [87.93%, 91.55%] |
| M1 | 3.119 [3.021, 3.222] | 2.745 | 5.779 | 28.67 | 5.781 | 89.72% [87.64%, 91.60%] |
| M2 | 3.104 [3.008, 3.207] | 2.735 | 5.750 | 28.58 | 5.750 | 89.73% [87.70%, 91.69%] |

M0 reproduces the prior learned-kinematics mean benchmark of 3.222 ft. M1 reduces endpoint error by
0.104 ft versus M0 (paired difference −0.104 ft; 95% interval [−0.109, −0.099]). M2 reduces it by a
further 0.014 ft versus M1 (95% interval [−0.016, −0.012]), a small under-0.5% gain. The direction
metric is the angle between predicted and observed endpoint displacement vectors from the cutoff,
computed for targets with at least one foot of observed displacement. M0's direction result also
reproduces the prior report. The source does not supply measured skater heading.

## Free-running multi-player rollouts

Each cell gives mean endpoint position error in feet with its 95% equal-game interval. The last two
columns give paired game-level mean differences for M1−M0 and M2−M1; negative is lower position
error.

| Horizon, ordinal steps | M0 | M1 | M2 | M1−M0 (95% interval) | M2−M1 (95% interval) |
|---:|---:|---:|---:|---:|---:|
| +1 | 0.200 [0.188, 0.215] | 0.205 [0.193, 0.220] | 0.216 [0.200, 0.234] | +0.0049 [+0.0010, +0.0097] | +0.0104 [+0.0049, +0.0162] |
| +5 | 1.033 [0.958, 1.128] | 1.057 [0.985, 1.145] | 1.066 [0.993, 1.152] | +0.0238 [−0.0010, +0.0499] | +0.0091 [+0.0029, +0.0177] |
| +15 | 3.645 [3.432, 3.945] | 3.637 [3.414, 3.931] | 3.645 [3.419, 3.937] | −0.0073 [−0.1367, +0.1245] | +0.0075 [−0.0014, +0.0176] |
| +30 | 8.397 [7.919, 8.954] | 7.931 [7.434, 8.534] | 7.927 [7.429, 8.514] | −0.4657 [−0.7532, −0.1610] | −0.0038 [−0.0120, +0.0031] |
| +45 | 13.575 [12.844, 14.369] | 12.178 [11.425, 13.011] | 12.170 [11.393, 12.986] | −1.3968 [−1.8731, −0.9010] | −0.0078 [−0.0178, +0.0011] |

The following equal-game means show how direction, displacement magnitude, and joint geometry errors
evolve. Each cell lists M0 / M1 / M2. Direction is endpoint path-bearing error; occupancy is total
variation over the frozen 20×9 rink grid. Boundary and spacing-floor entries are counts per scored
state.

| Horizon | Direction error, degrees | Displacement-magnitude error, ft | Pair-distance error, ft | Team-spacing error, ft | Occupancy TV | Nearest-opponent quantile gap, ft | Boundary count | Below-floor pair count |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| +1 | 17.611 / 15.213 / 16.227 | 0.138 / 0.138 / 0.142 | 0.140 / 0.148 / 0.163 | 0.096 / 0.101 / 0.110 | 0.018 / 0.018 / 0.020 | 0.114 / 0.122 / 0.151 | 0.010 / 0.005 / 0 | 0.255 / 0.260 / 0.105 |
| +5 | 21.379 / 21.589 / 21.834 | 0.719 / 0.711 / 0.720 | 0.764 / 0.816 / 0.827 | 0.533 / 0.559 / 0.569 | 0.113 / 0.112 / 0.113 | 0.588 / 0.633 / 0.657 | 0.020 / 0.015 / 0 | 0.261 / 0.261 / 0.025 |
| +15 | 32.361 / 33.080 / 33.114 | 2.769 / 2.524 / 2.534 | 2.484 / 2.764 / 2.769 | 1.605 / 1.893 / 1.898 | 0.359 / 0.361 / 0.360 | 1.735 / 1.899 / 1.896 | 0.072 / 0.041 / 0 | 0.289 / 0.289 / 0.050 |
| +30 | 41.713 / 39.864 / 39.790 | 6.800 / 5.658 / 5.663 | 5.404 / 5.893 / 5.885 | 3.670 / 4.277 / 4.286 | 0.651 / 0.626 / 0.624 | 3.021 / 3.301 / 3.256 | 0.136 / 0.058 / 0 | 0.293 / 0.340 / 0.104 |
| +45 | 48.862 / 43.836 / 43.729 | 11.278 / 8.807 / 8.816 | 7.929 / 8.554 / 8.541 | 5.615 / 6.674 / 6.681 | 0.745 / 0.719 / 0.718 | 3.913 / 4.187 / 4.120 | 0.148 / 0.069 / 0 | 0.292 / 0.395 / 0.109 |

At +45, M1 lowers individual position error by 10.3% versus M0; its paired interval excludes zero.
But M1 is 0.0049 ft worse at +1, with an interval above zero. The frozen development signal
required at least a 2% improvement at both +1 and +45, with both paired intervals entirely below
zero. It therefore **fails the preregistered rule**. The result suggests interaction features help
longer-horizon endpoint extrapolation in this sample, while making the first generated movement
slightly less accurate.

Common-label coverage declines from 99.48% at +1 to 98.55%, 95.08%, 89.79%, and 84.95% at +5,
+15, +30, and +45. At +45 this corresponds to an average 1.24 missing player labels per start.
Nothing is filled in for absent future observations. A +15-calibrated radial error threshold covers
about 89.8% of one-step held-out endpoints, but only 19.9% to 20.9% of +45 rollout endpoints; the
one-step radius is not a valid long-horizon uncertainty model.

## Joint geometry and the constraint ablation

At +45, lower global occupancy total variation is better; lower distance errors are better. Boundary
and empirical-floor values are mean counts per scored state, not percentages.

| +45 diagnostic | M0 | M1 | M2 | Interpretation |
|---|---:|---:|---:|---|
| Pairwise-distance error, ft | 7.929 | 8.554 | 8.541 | M1−M0 +0.626 [0.366, 0.871], worse |
| Team-spacing error, ft | 5.615 | 6.674 | 6.681 | M1−M0 +1.059 [0.597, 1.500], worse |
| Occupancy total variation | 0.745 | 0.719 | 0.718 | M1−M0 −0.025 [−0.047, −0.002], better |
| Nearest-opponent distance-quantile gap, ft | 3.913 | 4.187 | 4.120 | M1−M0 +0.274 [0.054, 0.501], worse |
| Mean path-direction error, degrees | 48.86 | 43.84 | 43.73 | M1−M0 −5.03 [−8.31, −1.88] |
| Displacement-magnitude error, ft | 11.278 | 8.807 | 8.816 | M1−M0 −2.472 [−2.790, −2.119] |
| Players outside rink, count per state | 0.148 | 0.069 | 0 | M2 applies rink clipping |
| Player pairs below empirical spacing floor, count per state | 0.292 | 0.395 | 0.109 | M2 reduces this proxy; it does not validate contact |

M1 improves global occupancy and endpoint displacement measures while worsening local pair and team
spacing. That is not evidence of coherent joint movement. M2 reduces the mean below-floor count from
0.395 to 0.109 pairs per state and clips all predicted positions into the rink, but its +45 position
error is essentially unchanged from M1 (−0.008 ft; interval [−0.018, +0.001]). At +1, M2 is
0.0104 ft worse than M1. Across 9,000 M2 rollout frames, the controller applied 253 rink-boundary
projections and 2,321 pair-separation adjustments; speed projections were zero, displacement-change
projections one, and turning projections three. These are observable effects of the chosen 2D
constraints, not evidence that a physical solver predicts hockey motion better.

## Engine interface and visual archive

The Gridiron Physics branch adds a sport-neutral research controller under `engine/movement/` with
`initializeMovementScene`, `proposeMovement`, `stepMovement`, `recordMovementFrame`, and
`replayMovement`. The hockey adapter supplies the rink plane, ordinal state, learned policy, empirical
constraints, and a clearly labeled nonphysical puck helper. It does not import the NFL play solver or
Rapier/Jolt.

The Three.js viewer has four independently selectable panes for observed, M0, M1, and M2 paths. It
supports play/pause, observation-index scrubbing, top-down and rink-side projections, a period-one
attack-direction transform only when orientation is documented, track labels, trails, vectors,
pair-distance overlays, missingness flags, and per-player errors. All four overlay toggles were
browser-tested, and the selected step-15 scenario rendered 30 per-player error rows. The side camera
is a view of the observed 2D XY plane, not measured 3D movement. The browser ran all three learned
policies through the Gridiron controller: maximum path difference from the Python archive was
0.00000 ft. Chromium reported four canvases, 206 scenarios, no page errors, and no console errors.
Seven geometry/quality category videos and top-down/rink-side screenshots at steps zero and fifteen
are stored with a versioned validation manifest.

The authoritative registered archive is `scenario_archive-bc91d1610de5.json.gz` on the Gridiron
branch, SHA-256 `a036d9edd981905646f5efce0b0c340b3fcd7bacaef8037b18e9350395fcacce`. Its registry entry
records the Legendary Picks evaluation commit `bc91d161…` and movement-controller commit
`252ed6d95fbb6a9ac8db5a65aed920139777432a`. The final browser record is
`archive/visual-validation-43d2935a609d.json`, SHA-256
`08c61c77e355a22d7944a0f34a338fc6a96175e5f561025076201973c734878a`. It was generated from the
Gridiron validation-harness commit `43d2935a609de38eb74f82aac50655cc9a14b574`. Clips and screenshots
are under `archive/clips/bc91d1610de5/`.

The earlier `43a81ff70918` archive remains in the registry as a preserved preview. Its entry predates
the JS kinematics-basis correction and carries the earlier controller commit; use the later `bc91`
archive for reproducible controller parity.

Observed playback is explicitly labeled observed. Predictions begin at the selected cutoff. The
browser policy parity run consumes only the serialized fold model and cutoff state; it does not
condition on future observed positions.

## What remains unvalidated

The ten games do not establish an NHL movement simulator. There is no independently validated
subsecond timebase, tracking-error ground truth, cross-game athlete identity, verified lineup
completeness, event-to-tracking join, reliable possession label, measured stick or body-contact
geometry, continuous puck flight, shot trajectory coverage, goalie response, or rebound/recovery
ground truth. The current states support a 2D, game-period-scoped movement experiment only.

Before any adoption claim, freeze the specification and success criteria against genuinely independent
games with verified timestamp cadence, track identity continuity and error, event/possession labels,
complete on-ice personnel, and observed contact/reachability where those mechanics are to be tested.
Evaluate the same one-step and autonomous joint-movement targets on those games. Keep the player
policy statistical and the current movement constraints explicitly unvalidated until such an
independent test passes.

## Reproducibility

The raw release cache is `/root/lp-research-data/stathletes-big-data-cup-2026`; full normalized data
and model matrices are in `/root/lp-research-data/nhl-multi-agent-movement-2026-10-23`. The source
manifest records the raw release hashes and the three external artifacts. Preparation took 1,312.614
seconds. The grouped fit, 200 rollouts, bootstrap intervals, and 206-scenario archive took 137.714
seconds.

The final evaluation code commit is `bc91d1610de5c99a0bdf396738e9d2f493c3d215`; the hockey movement
controller commit is `252ed6d95fbb6a9ac8db5a65aed920139777432a`. The versioned result files are
[`movement_comparison-bc91d1610de5.json`](../../research/nhl-multi-agent-movement-2026-10-23/results/movement_comparison-bc91d1610de5.json),
[`fold_models-bc91d1610de5.json`](../../research/nhl-multi-agent-movement-2026-10-23/results/fold_models-bc91d1610de5.json),
and [`scenario_archive-bc91d1610de5.json.gz`](../../research/nhl-multi-agent-movement-2026-10-23/results/scenario_archive-bc91d1610de5.json.gz).
Their SHA-256 digests are respectively `1f38c1c83b454558d8a48e285a3478f899b3dcc94a4dbc7e9028805de171cbf8`,
`194bae36e356186d50ae2a12afca557f616584bdf96baa2bbc2ffc0b555fd81a`, and
`a036d9edd981905646f5efce0b0c340b3fcd7bacaef8037b18e9350395fcacce`. The source release-manifest
SHA-256 is `6ca13bfa3503d9a86b7dde9589aba4988fd5e9599318e0b97f2f84e94cfcb437`.

The external normalized observation stream, rollout starts, and training matrix have SHA-256 values
`c92789cf3a35b9ba81e2d414e491c385f76cac97f27c720e4cf42af7f75f3227`,
`07d8523d9e8d89748981f326cce92d3bcedb899feea51b5bc12caa8e04a2a5de`, and
`694eb82615d6cd7ab442da23da9d7016aa9e47b6692e5469856a06de2991abd6` respectively. They remain
outside Git.

Commands run:

```sh
/usr/bin/python3 research/nhl-multi-agent-movement-2026-10-23/prepare_movement_data.py
/usr/bin/python3 research/nhl-multi-agent-movement-2026-10-23/evaluate_movement.py --gridiron-commit 252ed6d95fbb6a9ac8db5a65aed920139777432a
/usr/bin/python3 research/hockey-movement-v0.1/register_archive.py --archive /root/lp-nhl-multi-agent-movement-2026-10-23/research/nhl-multi-agent-movement-2026-10-23/results/scenario_archive-bc91d1610de5.json.gz --source-manifest /root/lp-research-data/nhl-multi-agent-movement-2026-10-23/extraction_manifest.json
node test/movement.mjs
node test/validate.mjs --strict
node --check research/hockey-movement-v0.1/viewer/app.js
node research/hockey-movement-v0.1/render_and_validate.mjs
```

Both Gridiron test commands passed; the strict NFL regression simulated 176 plays and 35,478 frames,
with 122/124 end-spot checks within tolerance and no player-speed violations. The browser path
parity and rendering checks passed. The final report and versioned artifacts record exact commits,
source hashes, model settings, folds, cutoff, horizon, and random seed. The ten-game study remains
development-only.
