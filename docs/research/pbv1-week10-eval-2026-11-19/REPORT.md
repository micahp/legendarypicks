# Week 10 PBV1 evaluation, partial (3 of 14 games)

Status: **exploratory, partial.** Three of the fourteen Week 10 games are compiled (BUF at NYJ, CAR at NO, HOU at CLE). The
remaining eleven games are still running on the fast host. Twenty seeds per game are not enough for strong conclusions.
Do not promote the model on this result.

## Arms

All three arms run the same branch and commit, `research/pbv1-pbp-fully-enabled-2026-11-18` at `831ff0a0`, with the same
frozen pregame snapshots, streak files and seeds 300001 to 300020.

| Arm | Flags added to the shared settings |
|---|---|
| A-control | `--rng-protocol v2` only. No participation field, no PBV1. |
| B-field | `--rng-protocol v2 --participation-field <field_v4_2022_2025.json> --participation-field-sha256 b53b25...` |
| C-field-pbv1 | B plus `--playcall-pbv1-package pbv1_training_plays.csv` (PBV1 sets the lineup grouping) |

Shared settings: `--slc-profile v1_full_stack`, `SLC-PLAYCALL-ARTIFACT-v1.json`, the game's streak file, and the five blocker
fixes. Export of box scores and plays is on. Overtime is not turned off anywhere.

A-control uses the v2 random protocol because the field requires it. So A is not the original v1 run. The three arms
share one random protocol, which keeps them paired.

## Coverage

| Arm | Seeds per game | Games | Simulations |
|---|---|---|---|
| A-control | 20 | 3 | 60 |
| B-field | 20 | 3 | 60 |
| C-field-pbv1 | 20 | 3 | 60 |

The runner manifests show zero failures for all three games. All 60 paired seeds per arm pair are present.

## 1. Game predictions (Oracle grade, `results/oracle-grade.json`)

| Arm | Brier | Log loss | Mean abs margin error | Mean abs total error |
|---|---|---|---|---|
| A-control | 0.328 | 0.863 | 10.45 | 5.35 |
| B-field | 0.512 | 1.384 | 13.62 | 5.48 |
| C-field-pbv1 | 0.372 | 0.959 | 11.32 | 4.22 |

Lower is better. The grade covers the three games only.

## 2. Per-game win probability and actual winner

Home team probability of a win, from 20 seeds. Actual home winner shown last.

| Game (home) | Final | A | B | C | Actual home win |
|---|---|---|---|---|---|
| 2026_10_BUF_NYJ (NYJ) | NYJ 12, BUF 31 | 0.25 | 0.30 | 0.25 | no |
| 2026_10_CAR_NO (NO) | NO 17, CAR 20 | 0.75 | 0.85 | 0.70 | no |
| 2026_10_HOU_CLE (CLE) | CLE 27, HOU 24 | 0.40 | 0.15 | 0.25 | yes |

Mean margin (simulated home minus away) against the actual margin:

| Game | Actual | A | B | C |
|---|---|---|---|---|
| BUF_NYJ | -19 | -6.7 | -1.9 | -7.6 |
| CAR_NO | -3 | 8.7 | 10.4 | 7.4 |
| HOU_CLE | +3 | -4.4 | -7.4 | -9.2 |

Mean total points (simulated) against the actual total:

| Game | Actual | A | B | C |
|---|---|---|---|---|
| BUF_NYJ | 43 | 46.5 | 43.1 | 42.5 |
| CAR_NO | 37 | 39.2 | 41.3 | 36.6 |
| HOU_CLE | 51 | 40.7 | 38.9 | 39.3 |

## 3. Team attempts (sum of three games)

| Source | Rush attempts | Pass attempts | Targets |
|---|---|---|---|
| Actual (player logs) | 157 | 205 | 199 |
| A-control | 182.5 | 223.5 | 223.5 |
| B-field | 183.4 | 221.7 | 221.7 |
| C-field-pbv1 | 183.3 | 220.3 | 220.3 |

Note: the simulator's pass attempts equal its targets. The actual pass attempts are QB attempts from the logs.

All arms run about 25 more rush attempts than the actual total across the three games. The arms are nearly identical here.

## 4. Individual players (starters and backups)

Starters are players with at least half of their actual offensive snaps. Carry and target errors are mean absolute error per
player-game. Sums are over the three games.

| Arm | Group | Carry MAE | Target MAE | Sim carries / actual | Sim targets / actual |
|---|---|---|---|---|---|
| A-control | Starters | 1.025 | 2.201 | 73.8 / 92 | 146.7 / 158 |
| A-control | Backups | 2.182 | 1.240 | 91.7 / 65 | 42.0 / 41 |
| B-field | Starters | 1.101 | 2.178 | 61.7 / 92 | 127.5 / 158 |
| B-field | Backups | 2.072 | 1.363 | 96.4 / 65 | 50.7 / 41 |
| C-field-pbv1 | Starters | 1.058 | 2.137 | 65.3 / 92 | 130.1 / 158 |
| C-field-pbv1 | Backups | 2.104 | 1.232 | 95.5 / 65 | 47.7 / 41 |

Every arm gives starters too few carries and targets. Every arm gives backups too many carries. Target counts for backups
are close to actual in all arms.

On starter carries, the field arm is further from actual than control (MAE 1.101 against 1.025). Coupling PBV1 sits
between them (1.058). On starter targets, the field arm is slightly closer than control (2.178 against 2.201), and the
coupled arm is closer still (2.137). Backup error is about the same in B and C.

Coverage: 43 simulated players have no actual line, and 147 player-game rows with an actual log line are absent from the simulation roster. Those
are roster-coverage gaps in the Week 10 snapshots, not model choices.

## 5. Paired seeds (`results/paired.json`)

Sixty paired seeds per pair (three games times twenty seeds).

| Pair | Score differs | Player lines differ | Play sequence differs |
|---|---|---|---|
| A vs B (field) | 50 of 60 | 60 of 60 | 55 of 60 |
| B vs C (PBV1 on field) | 55 of 60 | 60 of 60 | 59 of 60 |
| A vs C (combined) | 56 of 60 | 60 of 60 | 60 of 60 |

The first divergent play is at play index 26 (median) for A vs B, and 24 (median) for B vs C. A vs C was not computed. Full traces for seeds 300001 to
300003 are in `traces/`. The first divergent play is in `results/first_divergence.json`.

## 6. Lineup validity (`results/lineup_checks.json`)

| Check | B-field | C-field-pbv1 |
|---|---|---|
| Lineup snaps with status ok | 8253 | 8223 |
| Short snaps | 7 | 1 |
| Cell fallbacks | 9 | 9 |
| Non-QB players with a touch and zero on-field snaps in that game | **0** | **0** |
| QB carries outside the lineup (not counted as violations) | 469 | 463 |

Package counts across all snaps:

| Grouping | B-field | C-field-pbv1 |
|---|---|---|
| 11 | 4962 | 5316 |
| 12 | 1743 | 1967 |
| 13 | 336 | 333 |
| 21 | 525 | 280 |
| 22 | 174 | 90 |
| 10 | 33 | 115 |

Under PBV1 the 21 and 22 groupings fall and the 10 and 11 groupings rise. The packages PBV1 draws are not the same
distribution as the field transitions. No non-QB player with a carry, target or reception has zero on-field snaps in his game.
This is a per-game check, not a per-play one. The per-play check needs the play-level lineup, which this export does not record.

## 7. What this does and does not show

- In these three games, the field alone raises Brier score and margin error against control. Coupling PBV1 recovers part of that gap.
- The coupled arm is closer to control than the field-only arm on Brier score, log loss and margin error. It is closer on starter targets too.
- The field and PBV1 arms share a lineup rule. The per-game check found no non-QB touch without an on-field snap.
- Three games and twenty seeds cannot separate these effects from noise. I did not compute the size of the paired score
  differences, only how many seeds differ.

## 8. Limitations

- Three of fourteen games. The full slate is still running.
- Week 10 snapshots have no full-depth roster for every team, so some players are missing.
- The A arm uses the v2 random protocol, not the original v1 random protocol.
- The PBV1 table is the 2026-11-02 training table, fitted on seasons before the game season.
- The field table is the v4 table fitted on 2022 to 2025.
- The coupling is the existing `831ff0a0` code. I did not rebuild or change it.

## Reproduce

Code is in `code/`. Config generator: `code/make_configs.py` (runs on the fast host). Driver: `code/driver.sh`. Grading:
`code/grade.sh DATA OUT DB ORACLE_PY`. Analysis: `code/analyze.py DATA OUT DB`, where DATA holds
`<game>/runs/<arm>/*.boxscores.jsonl`. The Oracle is `backend/oracle.py` on `feat/oracle-next-slate-2026-11-17`.
