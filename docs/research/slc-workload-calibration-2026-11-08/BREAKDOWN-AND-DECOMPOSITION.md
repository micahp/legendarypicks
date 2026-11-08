# By-position breakdown and the Wilson / Charbonnet decomposition, 2026-11-08

Exploratory. No pregame injury or roster-eligibility data is used. Every row is marked `unknown eligibility`.

Scripts: `scripts/nfl_sequence/breakdown_workload_calibration.py`, `scripts/nfl_sequence/decompose_workload_share.py`. Raw output: `breakdown-*.json`, `decompose-*.json`.

## 1. By-position breakdown (models C and D)

Each row scores one position group of one team-game. The group score is a beta-binomial on the group's real count, given the team total N, with the group's summed concentration. It is not the team-level Dirichlet score in `RESULTS.md`, so the values are not comparable with that table. Interval coverage is for the group count.

Rolling check: each prediction used only earlier games. The check found 0 uses of a same-week or later game in all four runs.

Status: `new` = no prior-season usage for this team. `role_changed` = the player's own share of team usage moved by more than 0.10 between the prior season and the current season before the game. `returning` = all others.

### 2025 targets (544 team-games)

| Group | Model | Group NLL | Abs share error | 80% coverage | Rows | New: abs err | Returning: abs err | Role changed: abs err |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| WR | C | 2.72 | 0.0394 | 0.673 | 8,838 | 0.0256 | 0.0463 | 0.1212 |
| WR | D | 2.65 | 0.0310 | 0.728 | 8,838 | 0.0217 | 0.0389 | 0.0646 |
| TE | C | 2.55 | 0.0301 | 0.719 | 4,266 | 0.0200 | 0.0379 | 0.1026 |
| TE | D | 2.49 | 0.0255 | 0.743 | 4,266 | 0.0172 | 0.0336 | 0.0555 |
| RB | C | 2.33 | 0.0235 | 0.752 | 5,053 | 0.0154 | 0.0328 | 0.1151 |
| RB | D | 2.30 | 0.0199 | 0.770 | 5,053 | 0.0143 | 0.0270 | 0.0548 |

### 2026 weeks 1 to 8 targets (244 team-games)

| Group | Model | Group NLL | Abs share error | 80% coverage | Rows | New: abs err | Returning: abs err | Role changed: abs err |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| WR | C | 2.66 | 0.0332 | 0.705 | 4,620 | 0.0190 | 0.0459 | 0.1259 |
| WR | D | 2.63 | 0.0279 | 0.734 | 4,620 | 0.0170 | 0.0398 | 0.0845 |
| TE | C | 2.45 | 0.0248 | 0.807 | 2,232 | 0.0140 | 0.0366 | 0.0869 |
| TE | D | 2.43 | 0.0224 | 0.799 | 2,232 | 0.0131 | 0.0329 | 0.0671 |
| RB | C | 2.33 | 0.0204 | 0.783 | 2,575 | 0.0118 | 0.0345 | 0.0855 |
| RB | D | 2.32 | 0.0185 | 0.770 | 2,575 | 0.0116 | 0.0305 | 0.0513 |

### 2025 carries (544 team-games)

| Group | Model | Group NLL | Abs share error | 80% coverage | Rows | New: abs err | Returning: abs err | Role changed: abs err |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| RB | C | 2.47 | 0.0806 | 0.824 | 5,536 | 0.0487 | 0.0729 | 0.2201 |
| RB | D | 2.43 | 0.0577 | 0.836 | 5,536 | 0.0378 | 0.0642 | 0.1245 |
| QB | C | 2.25 | 0.0310 | 0.796 | 2,952 | 0.0191 | 0.0414 | 0.1032 |
| QB | D | 2.19 | 0.0257 | 0.835 | 2,952 | 0.0186 | 0.0335 | 0.0543 |

### 2026 weeks 1 to 8 carries (244 team-games)

| Group | Model | Group NLL | Abs share error | 80% coverage | Rows | New: abs err | Returning: abs err | Role changed: abs err |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| RB | C | 2.47 | 0.0671 | 0.746 | 2,861 | 0.0322 | 0.0782 | 0.2264 |
| RB | D | 2.43 | 0.0552 | 0.783 | 2,861 | 0.0284 | 0.0716 | 0.1602 |
| QB | C | 2.17 | 0.0226 | 0.832 | 1,508 | 0.0130 | 0.0371 | 0.0939 |
| QB | D | 2.13 | 0.0199 | 0.852 | 1,508 | 0.0119 | 0.0325 | 0.0594 |

### What the breakdown shows

- D beats C in every group, in every run, on both measures.
- The largest errors are in role-changed players, and RB carries are the worst group. For RB carries in 2026, D cuts the role-changed error from 0.226 to 0.160, but it is still high.
- Coverage for WR and TE is 0.67 to 0.81, below the 0.80 target. RB carries are close to target.
- Players new to the team are not the largest error source, although they have many rows.

Open: eligibility is unknown for every row. Results by status can change when verified availability is added.

## 2. Wilson and Charbonnet decomposition

Simulated share is about P(group) times the player's share inside the group. Real group frequency is the current-season value up to week 8. The simulator's own group frequency is not exported. The lineup filter is also not exported, so its effect is not measured here.

| Quantity | Wilson (ARI, targets) | Charbonnet (SEA, carries) |
|---|---:|---:|
| Base share from prior season (model input) | 0.205 | 0.377 |
| Floor weight used | no | no |
| Candidates in his position group | 7 (WR) | 5 (RB) |
| Share inside his group, mean of 2,000 draws (p10 to p90) | 0.776 (0.581 to 0.937) | 0.836 |
| Real group frequency, 2026 weeks 1 to 8 | 0.508 | 0.865 |
| Implied team share = group frequency times inside-group share | **0.394** | **0.723** |
| Simulated share, layers on (50-seed mean) | 0.432 | 0.757 |
| Simulated share, layers off (50-seed mean) | 0.206 | 0.359 |
| Real share, 2025 | 0.205 | 0.377 |
| Real share, 2026 weeks 1 to 8 | **0.259** | **0.027** |
| Real share inside his group, 2026 | 0.510 (0.259 / 0.508) | 0.031 (0.027 / 0.865) |

### Reading the decomposition

1. **The group step is close to real.** The real group frequencies are 0.508 for WR targets and 0.865 for RB carries. The implied team shares (0.394 and 0.723) are close to the simulated means (0.432 and 0.757).
2. **The inflation is inside the group.** Wilson's real share inside the WR group is 0.51. The model gives him 0.78. Charbonnet's real share inside the RB group is 0.03. The model gives him 0.84.
3. **The inside-group inputs cause it.** Both values come from the prior-season base share and the group concentration. Charbonnet's 2025 base is out of date. His group-mates Emanuel Wilson and Jadarian Price have no 2025 history, so they get only the floor weight, and that is why he dominates the group. Wilson's group-mates also have little or no 2025 history, so his base weight dominates. Neither player is a floor player himself. The floor for the others is part of the cause.
4. **Unexplained gap for Wilson.** The implied share is 0.394 and the simulated share is 0.432. The 0.04 gap is not explained here. The lineup filter and the simulator's group frequency are the likely sources. Both are untraced.

The "layers off" value matches each player's 2025 usage. It is not a correct answer for 2026.

## 3. Conditional versus all team games

The plan asked whether workload should be measured per game the player played, or against all team games. This comparison needs the per-game participation data, which is not in these outputs. It is not done here. The real-share numbers above use all team games.

## Limits

- Exploratory: no verified availability.
- The group NLL is not comparable with the team-level Dirichlet NLL.
- The simulator's group frequencies and lineup filter are not exported. The Wilson gap of 0.04 is unexplained.
- The conditional-versus-all-games comparison is not done.
