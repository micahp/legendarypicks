# NHL V3 Phase 2B: scoring model diagnosis

- Base: `19bb60cf8997abe1368b732983a4ed2ac1904cd3`
- Research branch: `research/nhl-v3-phase2b-scoring-2026-10-21`
- 2021 development simulations per game: 16; fixed seed: `20261021`
- 2022 is historical Phase 2A evidence only. No Phase 2B candidate was selected or tuned on 2022.
- Frozen Phase 2A simulator, fitted model, and evaluation hashes are recorded in `RESULTS.json`.

## Decision

Best 2021 development candidate by goal CRPS is C v2 goal prior: paired goal-CRPS gain +0.0529 [+0.0357, +0.0697] and final-energy gain +0.0799 [+0.0530, +0.1056] versus matched Phase 2A. It also worsens team SOG CRPS on this fold. These intervals are descriptive after candidate selection, so this remains a research result, not adoption evidence.

## Why the Phase 2B code exists

The Phase 2A fit and evaluator provide the frozen shot generator and the 2021/2022 reference scores, but do not expose generated attempt counts, controlled conversion offsets, or a state-conditioned location pool. This research runner adds those measurements and isolated adapters. The fitted outcomes, SOG targets, scores, and model features still come from the hash-pinned NHL replay and official outcome artifacts; the derived values below are reconciled to those sources.

## Component diagnosis on 2021

Accepted games: 1312; official SOG eligible games: 1292. Attempt and event conversion diagnostics use 148665 accepted PBP shot attempts. Event-level probabilities condition on observed in-game states and observed locations for diagnosis only; the simulator never receives target-game events, locations, or shooters.

| Measure | Observed | Phase 2A generated / predicted |
|---|---:|---:|
| Attempts per team-game | 56.656 | 56.470 |
| Official team SOG per team-game | 31.602 | 31.095 |
| Regulation + OT goals per team-game | 3.106 | 3.434 |
| Final score margin (home minus away) | 0.247 | 0.163 |
| Final margin variance | 7.069 | 6.070 within-game predictive |
| Goals per PBP SOG | 0.0982 | 0.1105 generated |

| Count | Observed variance | Mean predictive variance | 50% coverage | 80% coverage | 90% coverage |
|---|---:|---:|---:|---:|---:|
| Team attempts | 119.726 | 62.992 | 0.426 | 0.628 | 0.750 |
| Official team SOG | 47.792 | 29.889 | 0.470 | 0.684 | 0.790 |
| Team reg+OT goals | 3.154 | 3.068 | 0.623 | 0.812 | 0.905 |

### Measured error attribution

The largest direct scoring mismatch is in even-strength goals: 5.565 generated versus 4.388 observed per game (+1.177). The model generates +0.328 regulation/OT goals per team-game overall. This excess is partly offset by zero generated empty-net goals versus 0.363 observed per game, and by advantage goals 1.146 versus 1.312. Generated penalties also undercount events (4.890 vs 7.390 per game).
Attempts are close in mean (56.470 vs 56.656), and SOG are modestly low (31.095 vs 31.602); their predictive variances are substantially low (63.0 vs 119.7 attempts and 29.9 vs 47.8 SOG). On generated SOG, conversion is 0.1105, above observed 0.0982; at the actual event locations, the conditional model predicts 0.0927 versus 0.0982 observed. This points toward the generated location/type and game-state mix compounding over a game, rather than a uniform excess in the per-shot conversion probability. It is a diagnostic attribution, not a causal decomposition.
Candidate D did not fix composition: joint distance-angle-type TV moved from 0.0469 to 0.0487, and its goal and energy scores did not improve over Phase 2A. The population intercept adjustment also failed to improve scoring.


### Regulation, overtime, and special teams

| Measure | Observed | Phase 2A generated / predicted |
|---|---:|---:|
| Games reaching overtime | 288 | 212.1 expected games |
| Games reaching shootout | 102 | 77.8 expected games |
| Accepted penalties per game | 7.390 | 4.890 |

| Goals per game by period / strength | Observed | Phase 2A generated |
|---|---:|---:|
| Goals, OT | 0.142 | 0.102 |
| Goals, REG | 6.070 | 6.766 |
| Goals, ADVANTAGE strength | 1.312 | 1.146 |
| Goals, DISADVANTAGE strength | 0.149 | 0.157 |
| Goals, EMPTY_NET strength | 0.363 | 0.000 |
| Goals, EVEN strength | 4.388 | 5.565 |

The conditional event check isolates conversion from game-level compounding. The generated count check includes the downstream effect of goals changing score-state shot rates.

### Conditional probability checks

| Candidate | P(SOG) observed | P(SOG) predicted at observed states | Goal/SOG observed | Goal/SOG predicted at observed locations | Goal Brier |
|---|---:|---:|---:|---:|---:|
| A population conversion | 0.5583 | 0.5508 | 0.0982 | 0.0949 | 0.0860 |
| B rolling team goals | 0.5583 | 0.5508 | 0.0982 | 0.0936 | 0.0862 |
| B v2 team strength | 0.5583 | 0.5508 | 0.0982 | 0.0898 | 0.0860 |
| C v2 goal prior | 0.5583 | 0.5508 | 0.0982 | 0.0824 | 0.0862 |
| D state-conditioned quality | 0.5583 | 0.5508 | 0.0982 | 0.0927 | 0.0860 |
| Phase 2A | 0.5583 | 0.5508 | 0.0982 | 0.0927 | 0.0860 |

Attempt volume is measured independently from event-level SOG and goal conversion. Shot-quality composition is evaluated with joint and marginal total-variation distances against accepted 2021 spatial events. Strength, OT, and shootout counts are reported separately in `RESULTS.json`.

## Controlled candidate comparison

Positive paired deltas favor the candidate. Bootstrap intervals resample games. Every Phase 2B candidate and the matched Phase 2A/simple-rate simulations use identical game IDs, seeds, simulation counts, and full event validation. The same-window v2 score refit uses the identical 2018–2020 training games.

| Candidate | Goal CRPS | Final energy | Winner Brier | Team SOG CRPS | Runtime (s) |
|---|---:|---:|---:|---:|---:|
| Same-window v2 refit | 1.0428 | 1.6447 | 0.2445 | n/a | 0.6 |
| Simple historical-rate | 1.0479 | 1.6668 | 0.2674 | 4.0804 | 124.4 |
| A population conversion | 1.0606 | 1.6845 | 0.2548 | 3.9188 | 588.1 |
| B rolling team goals | 1.0796 | 1.7109 | 0.2581 | 3.9321 | 631.6 |
| B v2 team strength | 1.0276 | 1.6325 | 0.2398 | 3.9430 | 615.1 |
| C v2 goal prior | 1.0016 | 1.5944 | 0.2375 | 3.9513 | 616.4 |
| D state-conditioned quality | 1.0591 | 1.6832 | 0.2556 | 3.9428 | 646.6 |
| Phase 2A | 1.0544 | 1.6743 | 0.2541 | 3.9126 | 594.6 |

### Previously exposed 2022 diagnostic

These frozen Phase 2A values are historical context only; no Phase 2B candidate used them for selection.

| Model | Goal CRPS | Final energy | Winner Brier | Team SOG CRPS |
|---|---:|---:|---:|---:|
| Frozen Phase 2A | 0.9930 | 1.5859 | 0.2424 | 3.8702 |
| Simple historical-rate | 0.9448 | 1.5036 | 0.2502 | 4.0976 |
| Same-window v2 refit | 0.9466 | 1.4998 | 0.2439 | n/a |

### Paired 95% game bootstrap deltas

Each cell is baseline loss minus candidate loss, followed by the 95% game-bootstrap interval. Positive values favor the candidate. The intervals resample games and do not include finite Monte Carlo uncertainty; the comparison uses 16 common-seed simulations per game. The candidate was selected on this same development population, so intervals that exclude zero are descriptive and do not establish confirmatory significance.

| Candidate | Reference | Goal CRPS | Final energy | Winner Brier | SOG CRPS |
|---|---|---:|---:|---:|---:|
| A population conversion | Phase 2A | -0.0061 [-0.0096, -0.0027] | -0.0102 [-0.0157, -0.0049] | -0.0007 [-0.0032, +0.0017] | -0.0062 [-0.0142, +0.0017] |
| A population conversion | Same-window v2 refit | -0.0177 [-0.0382, +0.0025] | -0.0398 [-0.0705, -0.0096] | -0.0103 [-0.0212, +0.0003] | n/a |
| A population conversion | Simple historical-rate | -0.0126 [-0.0313, +0.0049] | -0.0177 [-0.0448, +0.0100] | +0.0126 [+0.0034, +0.0213] | +0.1616 [+0.1016, +0.2201] |
| B rolling team goals | Phase 2A | -0.0252 [-0.0365, -0.0135] | -0.0366 [-0.0543, -0.0197] | -0.0039 [-0.0101, +0.0021] | -0.0196 [-0.0362, -0.0037] |
| B rolling team goals | Same-window v2 refit | -0.0368 [-0.0603, -0.0144] | -0.0662 [-0.1020, -0.0321] | -0.0136 [-0.0244, -0.0027] | n/a |
| B rolling team goals | Simple historical-rate | -0.0317 [-0.0517, -0.0119] | -0.0441 [-0.0751, -0.0149] | +0.0093 [-0.0007, +0.0186] | +0.1482 [+0.0904, +0.2049] |
| B v2 team strength | Phase 2A | +0.0268 [+0.0167, +0.0368] | +0.0418 [+0.0278, +0.0572] | +0.0143 [+0.0077, +0.0207] | -0.0304 [-0.0473, -0.0141] |
| B v2 team strength | Same-window v2 refit | +0.0152 [-0.0033, +0.0335] | +0.0122 [-0.0143, +0.0397] | +0.0047 [-0.0049, +0.0136] | n/a |
| B v2 team strength | Simple historical-rate | +0.0203 [+0.0021, +0.0383] | +0.0343 [+0.0066, +0.0614] | +0.0276 [+0.0179, +0.0375] | +0.1374 [+0.0812, +0.1913] |
| C v2 goal prior | Phase 2A | +0.0529 [+0.0357, +0.0697] | +0.0799 [+0.0530, +0.1056] | +0.0167 [+0.0076, +0.0259] | -0.0387 [-0.0618, -0.0163] |
| C v2 goal prior | Same-window v2 refit | +0.0412 [+0.0278, +0.0547] | +0.0503 [+0.0304, +0.0707] | +0.0070 [-0.0011, +0.0150] | n/a |
| C v2 goal prior | Simple historical-rate | +0.0464 [+0.0307, +0.0618] | +0.0724 [+0.0498, +0.0938] | +0.0299 [+0.0201, +0.0389] | +0.1291 [+0.0685, +0.1900] |
| D state-conditioned quality | Phase 2A | -0.0047 [-0.0195, +0.0099] | -0.0090 [-0.0293, +0.0134] | -0.0015 [-0.0105, +0.0072] | -0.0303 [-0.0746, +0.0111] |
| D state-conditioned quality | Same-window v2 refit | -0.0163 [-0.0381, +0.0050] | -0.0385 [-0.0711, -0.0076] | -0.0111 [-0.0218, -0.0010] | n/a |
| D state-conditioned quality | Simple historical-rate | -0.0112 [-0.0289, +0.0078] | -0.0164 [-0.0430, +0.0114] | +0.0118 [+0.0031, +0.0208] | +0.1375 [+0.0749, +0.2049] |
| Phase 2A | Phase 2A | +0.0000 [+0.0000, +0.0000] | +0.0000 [+0.0000, +0.0000] | +0.0000 [+0.0000, +0.0000] | +0.0000 [+0.0000, +0.0000] |
| Phase 2A | Same-window v2 refit | -0.0116 [-0.0325, +0.0088] | -0.0296 [-0.0602, +0.0006] | -0.0096 [-0.0197, +0.0009] | n/a |
| Phase 2A | Simple historical-rate | -0.0065 [-0.0236, +0.0111] | -0.0075 [-0.0340, +0.0185] | +0.0132 [+0.0040, +0.0223] | +0.1678 [+0.1092, +0.2291] |

## Limits and next evaluation

No accepted NHL source bundle on this host contains a later complete season: the pinned Phase 1 frame covers 2018–2022, with 2022 partial through November 27. The prospective 2026–27 directory contains forecasts but no settled outcomes. `UNSEEN-EVALUATION-PROTOCOL.md` freezes a later-season evaluation path; Phase 2B is not adopted without it.

NOT_ADOPTED: no independent later-season evaluation exists; 2021 is the candidate-selection fold and 2022 was exposed in Phase 2A.

The generator still omits player identity and shooter skill, verified goalie response, possession and rebound chains, empty-net strategy, full penalty/manpower rules, team discipline, and line changes. It samples exponential event times and its minor-only special-teams process remains a known source of score-distribution error.

## Reproduction and validation

Run `/root/legendarypicks/backend/venv/bin/python -m unittest discover -s research/nhl/nhl-v3-phase2b-scoring-2026-10-21 -p 'test_*.py' -v` and the exact command recorded in `RESULTS.json`. Simulation seeds, input hashes, candidate feature provenance, all paired scores, and full simulation validation counts are retained.

Test counts: Phase 2A `test_invariants.py` — 9 tests; Phase 2B `test_*.py` unittest discovery — 6 tests OK; Phase 1 `test_replay_engine.py` — 12 tests OK.
