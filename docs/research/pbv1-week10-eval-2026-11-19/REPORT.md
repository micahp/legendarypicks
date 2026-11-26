# Week 10 PBV1 evaluation, full slate (14 games)

Status: **exploratory.** Twenty seeds per game are not enough for strong conclusions. Do not promote the model on this
result. The earlier three-game version of this report is in git history at `ed2e1ad6`.

## Arms

All three arms run the same branch and commit, `research/pbv1-pbp-fully-enabled-2026-11-18` at `831ff0a0`. They use the
same frozen pregame snapshots, the same streak file for each game, and seeds 300001 to 300020.

| Arm | Flags added to the shared settings |
|---|---|
| A-control | `--rng-protocol v2` only. No participation field, no PBV1. |
| B-field | `--rng-protocol v2 --participation-field field_v4_2022_2025.json --participation-field-sha256 b53b25...` |
| C-field-pbv1 | B plus `--playcall-pbv1-package pbv1_training_plays.csv`. PBV1 sets each snap's lineup grouping. |

Shared settings: `--slc-profile v1_full_stack`, `SLC-PLAYCALL-ARTIFACT-v1.json`, the game's streak file, and the five
blocker fixes. Box score and play export are on. Overtime is not turned off in any arm.

No arm uses `--paired-randomness`. See the random streams section for why that is not a problem.

## Coverage

All 14 games and 3 arms ran with 20 seeds each, 840 simulations in total. The runner manifests show zero failures for every
game and arm. All 280 paired seeds per arm pair are present.

Actual results come from the frozen database (`picks.frozen.db`). It has the same week 10 counts as the slow-host database:
14 final scores and 981 player game logs. The analysis ran on the fast host.

## 1. Game predictions (Oracle grade, `results/oracle-grade.json`)

| Arm | Brier | Log loss | Mean abs margin error | Mean abs total error |
|---|---|---|---|---|
| A-control | 0.235 | 0.654 | 11.94 | 8.06 |
| B-field | 0.316 | 0.870 | 13.21 | 9.16 |
| C-field-pbv1 | 0.261 | 0.728 | 12.09 | 9.66 |

Lower is better. On Brier, log loss and margin error, the order is A, then C, then B. C is closer to A than B is. On total
error, C is the worst of the three. The total-error gap is about one point.

## 2. Per-game predictions and actual winners

Home win probability (p) from 20 seeds. Brier score is for the home win. Margin is the mean simulated home minus away.

| Game | Final (away at home) | Home won | A p / Brier / margin | B p / Brier / margin | C p / Brier / margin |
|---|---|---|---|---|---|
| BUF_NYJ | BUF 31 at NYJ 12 | no | 0.25 / 0.063 / -6.7 | 0.30 / 0.090 / -1.9 | 0.25 / 0.063 / -7.6 |
| CAR_NO | CAR 20 at NO 17 | no | 0.75 / 0.563 / 8.7 | 0.85 / 0.723 / 10.4 | 0.70 / 0.490 / 7.4 |
| HOU_CLE | HOU 24 at CLE 27 | yes | 0.40 / 0.360 / -4.4 | 0.15 / 0.723 / -7.4 | 0.25 / 0.563 / -9.2 |
| JAX_TEN | JAX 40 at TEN 23 | no | 0.20 / 0.040 / -8.3 | 0.35 / 0.123 / -2.9 | 0.25 / 0.063 / -9.4 |
| KC_ATL | KC 35 at ATL 13 | no | 0.15 / 0.023 / -8.2 | 0.30 / 0.090 / -6.9 | 0.15 / 0.023 / -6.1 |
| LAC_BAL | LAC 23 at BAL 20 | no | 0.25 / 0.063 / -4.9 | 0.35 / 0.123 / -5.1 | 0.40 / 0.160 / -1.1 |
| LA_ARI | LA 34 at ARI 6 | no | 0.30 / 0.090 / -4.8 | 0.25 / 0.063 / -6.4 | 0.35 / 0.123 / -4.0 |
| MIA_IND | MIA 22 at IND 24 | yes | 0.25 / 0.563 / -6.3 | 0.40 / 0.360 / -0.8 | 0.15 / 0.723 / -8.2 |
| MIN_GB | MIN 30 at GB 10 | no | 0.60 / 0.360 / 3.0 | 0.80 / 0.640 / 6.8 | 0.65 / 0.423 / 1.8 |
| NE_DET | NE 10 at DET 35 | yes | 0.35 / 0.423 / -3.8 | 0.30 / 0.490 / -0.1 | 0.55 / 0.203 / 2.8 |
| PIT_CIN | PIT 18 at CIN 38 | yes | 0.70 / 0.090 / 4.0 | 0.45 / 0.303 / -2.8 | 0.60 / 0.160 / 2.8 |
| SEA_LV | SEA 21 at LV 13 | no | 0.20 / 0.040 / -8.3 | 0.35 / 0.123 / -4.2 | 0.20 / 0.040 / -11.9 |
| SF_DAL | SF 46 at DAL 40 | no | 0.60 / 0.360 / 1.7 | 0.65 / 0.423 / 1.9 | 0.65 / 0.423 / 2.3 |
| WAS_NYG | WAS 24 at NYG 21 | no | 0.50 / 0.250 / 1.1 | 0.40 / 0.160 / -1.1 | 0.45 / 0.203 / -0.9 |

Note: the home team is the second team in each game ID. The table keeps that order.

## 3. Team attempts (sum over 14 games)

| Source | Rush attempts | Pass attempts | Targets |
|---|---|---|---|
| Actual (player logs) | 742 | 913 | 881 |
| A-control | 846.7 | 1029.7 | 1029.7 |
| B-field | 850.6 | 1020.5 | 1020.5 |
| C-field-pbv1 | 847.8 | 1018.5 | 1018.5 |

The simulator's pass attempts equal its targets, so the two simulated columns match. The actual pass attempts are QB
attempts from the logs. All three arms simulate about 105 more rush attempts than the actual total, and about 137 to 149
more targets. The arms are close to each other.

## 4. Individual players: starters and backups

Starters are players with at least half of their actual offensive snaps. Errors are mean absolute error per player-game.
Totals are sums over the 14 games.

| Arm | Group | Carry MAE | Target MAE | Sim carries / actual | Sim targets / actual |
|---|---|---|---|---|---|
| A-control | Starters | 1.464 | 2.031 | 449.5 / 489 | 582.9 / 649 |
| A-control | Backups | 1.752 | 1.404 | 210.3 / 253 | 179.3 / 232 |
| B-field | Starters | 1.330 | 1.941 | 337.5 / 489 | 531.4 / 649 |
| B-field | Backups | 1.671 | 1.402 | 281.2 / 253 | 196.3 / 232 |
| C-field-pbv1 | Starters | 1.249 | 1.916 | 357.9 / 489 | 530.6 / 649 |
| C-field-pbv1 | Backups | 1.731 | 1.374 | 269.9 / 253 | 190.8 / 232 |

Two things are true at once, and I am reporting both as measured:
- **Totals:** both field arms give starters much less carry volume than control. B gives 337 carries against 489 actual.
  C gives 358. Control gives 450. PBV1 coupling adds about 20 starter carries back.
- **Per-player error:** the field arms have lower mean absolute carry error for starters. That is not consistent with the
  totals. A mean absolute error and a sum can point in different directions when errors cancel across players. I have not
  broken that down further.

Starter target volume is also lower in both field arms, by about 51 targets against control (531 and 531 against 583).
Starter target error is slightly lower in C than in B.

Coverage: 228 player rows in the simulation have no actual line. 679 player rows in the actual logs are absent from the
simulation roster. Most of those are non-touch players. These are roster coverage gaps in the Week 10 snapshots, not model
choices.

## 5. Paired seeds (`results/paired.json`)

280 seeds per pair (14 games times 20 seeds).

| Pair | Final score differs | Player lines differ | Play sequence differs |
|---|---|---|---|
| A vs B (field) | 240 of 280 | 280 of 280 | 258 of 280 |
| B vs C (PBV1 on field) | 257 of 280 | 280 of 280 | 269 of 280 |
| A vs C (combined) | 247 of 280 | 280 of 280 | 265 of 280 |

Seeds with identical final scores exist in every pair. They are a minority. Player lines differ in every seed. I did not
compute the size of the score differences, only how many seeds differ.

## 6. First divergent play (`results/first_divergence.json`)

Three diagnostic seeds per game, 42 seed pairs per arm pair.

- A vs B: 41 of 42 diverge. Median first divergent play is 33.
- B vs C: 42 of 42 diverge. Median first divergent play is 25.5.

One A vs B seed produced identical play sequences. Full play traces for seeds 300001 to 300003 are in `traces/`.

## 7. Lineup validity (`results/lineup_checks.json`)

| Check | B-field | C-field-pbv1 |
|---|---|---|
| Lineup snaps with status ok | 37,939 | 37,892 |
| Short snaps | 97 | 44 |
| Cell fallbacks | 23 | 17 |
| Non-QB players with a touch and zero on-field snaps in that game | **0** | **0** |
| QB carries outside the lineup (not counted as violations) | 2,272 | 2,241 |

Package counts across all snaps (lineup groupings):

| Grouping | B-field | C-field-pbv1 |
|---|---|---|
| 10 | 162 | 468 |
| 11 | 22,611 | 24,505 |
| 12 | 8,262 | 9,025 |
| 13 | 1,674 | 1,690 |
| 21 | 2,527 | 1,281 |
| 22 | 778 | 368 |

PBV1 draws fewer 21 and 22 groupings and more 10, 11 and 12 groupings. The packages it draws are not the same mix as the
field transitions.

The eligibility check is per game, not per play. It shows no non-QB player with a touch had zero on-field snaps in his game.
A per-play check needs the play-level lineup, which this export does not record.

## 8. Random streams: what the runs actually share

Two different things are being called "paired." They are not the same.

- **`--paired-randomness`** is an explicit research flag. It keys each draw on game, drive, play and event coordinates.
  None of these runs set it. The output field `paired_randomness: false` records that flag only.
- **V2 named streams** are on for every V2 run, with or without the flag. The code sets `RngPlan.paired = True` for V2, and
  the engine turns on the paired streams from that. So the flag adds nothing to these runs.

Checked in the output, `simulation.rng_protocol.stream_root_sha256` and `model_input_sha256`:
- All 14 games have **one stream root across the three arms**. The root differs from game to game, as it should.
- All 14 games have **one model-input hash across the three arms**.

The root hashes only the pregame state and the SLC layer tables. The participation field and PBV1 are not in those
hashes. So the three arms already share one root by construction, and no common-root mode is needed.

What the shared root does not prove: that each draw gives the same value in every arm. A draw is a fixed function of its
key. So a draw with the same key gives the same number in each arm. But the same number can pick a different player when
the candidate list changes, and a different game state changes the keys that follow. A three-seed diagnostic of BUF at NYJ
checks this. It is still running, and its results are not in this report yet.

## 9. What this does and does not show

- Across 14 games, the field alone raises Brier score, log loss and margin error against control. Coupling PBV1 to the
  field recovers most of that gap on Brier and log loss.
- Starter carry volume falls in both field arms. PBV1 adds back about 20 starter carries on the 14-game total. That is a
  small share of the gap to control.
- Lineup checks pass on this measure. No non-QB touch comes from a player with no snap in his game.
- 20 seeds per game is not enough to separate these effects from noise. The effects in the predictions are small and the
  paired counts are large but the sizes are not computed.

## 10. Limitations

- Week 10 snapshots have no full-depth roster for every team. Some players are missing from the simulation.
- The A arm uses the v2 random protocol, not the original v1 protocol. A is therefore a control for the field and PBV1, not
  the original SLC run.
- The PBV1 table is the 2026-11-02 training table, fitted on seasons before the game season.
- The field table is the v4 table fitted on 2022 to 2025.
- The coupling is the existing `831ff0a0` code. I did not rebuild or change it.
- The per-player accuracy comparison uses actual logs from the frozen database. Those logs use nflverse team codes; game
  IDs and simulation teams are normalised once at the boundary.

## Reproduce

Code is in `code/`. Config generator: `code/make_configs.py`, run on the fast host. Driver: `code/driver.sh`. Grading:
`code/grade.sh DATA OUT DB ORACLE_PY`. Analysis: `code/analyze.py DATA OUT DB`, where DATA holds
`<game>/runs/<arm>/*.boxscores.jsonl`. The Oracle is `backend/oracle.py` on `feat/oracle-next-slate-2026-11-17`.
