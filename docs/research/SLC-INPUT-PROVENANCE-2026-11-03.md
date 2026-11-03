# SLC input provenance and cleaning, 2026-11-03

Status: provenance record, not a model decision. It lists every cleaning, filtering and normalization step that shapes the
inputs of SLC v1 and of the playbook prior, with the file and function that performs it and the counts the code reports.
The ablation pre-registration (`PLAYCALL-ABLATION-SPEC-M3-2026-11-02.md`) is not edited. Its pinned hashes stay valid.

Counts below come from one run: the frozen snapshot `docs/research/slc-week8-2026/snapshots/2026_08_BAL_BUF.json`
(snapshot sha256 `97ac907bae1dbb2b…`), against the dev database copy with sha `1a775208…`. The counts were read from the
current working tree (branch `slc-v1.5` with uncommitted edits) and from the committed tree at `73b3becc`. They are the same
in both trees, because the reference pool is identical between them. Counts that the code does not report are marked "not measured" and are not estimated.

## 1. Raw inputs

| Input | Where | Pinned by |
|---|---|---|
| nflverse play-by-play 2022 to 2025 | `/root/gridiron-playbooks-research/data/raw/pbp_YYYY.csv.gz`, and the `nfl_pbp` table in the dev DB | SHA-256 in ablation spec section 8 |
| nflverse participation 2022 to 2025 | `pbp_participation_YYYY.csv` | SHA-256 in ablation spec section 8 |
| Schedule and final scores | `nfl_schedule` in the dev DB | game_id, season, week |
| Play-call artifact | `docs/research/SLC-PLAYCALL-ARTIFACT-v1.json` | `artifact_sha256` in the run record |
| Current-streak file | `docs/research/slc-week8-2026/wl-streaks-2026-10-29.json` | `current_streak_file` sha256 |
| Team playbook files (season minus 1) | `/root/gridiron-playbooks-research/data/playbooks/research-2026-10-27` | `playbook:<file>` sha256 |
| Safety, overtime and blocked-kick source tables | rebuilt from nflverse play-by-play by the scripts in section 3 | `*_source_sha256` fields |
| Extra play fixture | `docs/fixtures/e2/play_extras_2022_2025.csv` | `play_extras_sha256` |

## 2. Cleaning steps applied to the engine's play pool

Each step runs in code and records what it removed. Order follows `slc_engine.load_reference`.

1. **Season window.** `e2_reference.load(eligible_before=(season, 1))` keeps only seasons before the game's season. For the
   2026 snapshot, `eligible_play_seasons` is 2022 to 2025 and `eligible_before` is `[2026, 1]`. No 2026 outcome enters the
   pool. (`e2_reference.py`, `slc_engine.load_reference`; reported in `pool_scope`.)

2. **Regulation-only pool.** `e1.build_pool(regulation_only=True)` removes overtime rows (quarter 5 or later) from the play
   pool and the kickoff pool. Removed: **1,214 rows**, reported as `overtime_rows_excluded_from_pool`. The published kick
   table is not filtered, because its rates include overtime kicks (`pool_scope.kick_table`). (`e1` `build_pool`; `e2_reference.py` line 564 and 699.)

3. **Unmodeled lateral transfers.** `slc_engine.exclude_unmodeled_lateral_rows` links each E1 row to the participant facts
   by `(game_id, play_id)` and drops rows whose play carries a lateral. Removed: **50 rows** (45 `pass_complete`, 5 `run`).
   E1 rows do not carry lateral columns, so the link to `nfl_pbp` is what makes this step work.

4. **Inconsistent completion yardage.** `slc_engine.exclude_inconsistent_pass_yardage_rows` drops completions whose passing
   yards and receiving yards disagree, because SLC cannot represent a second credited receiver. Removed: **1 row**,
   `2022_16_LAC_IND` play 3371 (passing 13, receiving 12). The row stays in the source data and the workload references.

5. **Team-code normalization.** `scripts/nfl_team_codes.py`. Frozen source artifacts use nflverse codes; the database uses
   PBP codes. `to_pbp_team_code` maps `LA` to `LAR`, `WAS` to `WSH` and `JAC` to `JAX`. The conversion direction is named at
   each call site. `canonical_franchise_team_code` also maps `OAK` to `LV`, and is used only for cross-season identity
   comparisons, never as a join key. `missing_pbp_team_codes` reports any required team absent from a source table.

6. **Scrimmage plays.** Ablation spec section 2 defines the denominators: regular season, `posteam` present, `play_type` in
   run or pass, `qb_kneel` and `qb_spike` excluded. This definition governs the baseline tables. The engine's own play
   classes are set in the play-call layer (not re-described here).

## 3. Rebuilt outcome pools (own scripts, own fixtures)

| Pool | Builder | Status rule | Sampled in the run |
|---|---|---|---|
| Blocked kicks | `build_blocked_kick_outcomes.py` | Each blocked kick is joined to the following play-by-play rows. Ambiguous records are kept and labelled, and the simulator refuses them by name. | 86 field-goal and 39 punt outcome samples; blocked-kick rates by snap bucket |
| Safety free kicks | `build_safety_kick_outcomes.py` (2022 to 2025 regular season) | Unclassifiable rows are kept with a status and refused at sampling. | 46 usable samples |
| Overtime drives | `build_overtime_drives.py` (2022 to 2025 regular season) | Rule 16 logic is checked in `game_state.py`, not supplied by the pool. Unclassified drives are refused by name. | 140 drive samples |
| Overtime kick-or-receive choice | `build_overtime_choice_model.py` | Estimated from `docs/fixtures/e2/overtime_coin_toss_2023_2026.csv`, 2025 regular season (14 games), Beta(1, 1) prior. The coin toss is a seeded fair draw in the engine. | Not measured here |

## 4. Player identity and usage

- Receiver and runner position shares join the play-by-play player GSIS id to `players.nfl_gsis_id`, with position groups from
  the canonical identity.
- Receiver side: **68,664 classified rows**, **81 non-eligible position rows** (kept out of the shares).
- Runner side: **54,897 classified rows**, **2,219 non-eligible position rows**.
- Non-eligible rows are counted and not dropped silently. They appear in the reference as `noneligible_position_rows`.

## 5. Playbook prior

- `playbook_prior.load(season)` needs the team playbook files for season minus 1. The engine raises `ValueError` if a target
  team is missing from them (`slc_engine.py`, `missing_pbp_team_codes`).
- `playbook_crosscheck.py` compares the playbook files with the database decision labels for 2025 regular season, on pass
  depth (D), pass location (E) and run gap (C). It reports every team and category. **Its results are not read in this
  document**, and no pass or fail is claimed here.

## 6. The reference that the run used

From the observed-reference fingerprint of the run (after every step above):

| Component | Count |
|---|---|
| Play cells | 75 |
| Play samples | 141,176 |
| Kickoff samples | 9,963 |
| Participant rows | 188,282 |
| Missed field-goal return samples | 513 |
| Safety kick samples | 46 |
| Overtime drive samples | 140 |

The pool before steps 2 to 4 is **not measured** in this document. Only the removed counts above are known.

## 7. Known gaps

- Pre-filter row counts per season are not recorded in one place. Measuring them needs a re-run of `e1.build_pool` without
  the filters.
- The sha of the team playbook files used by the run is recorded in the run record, but it is not listed here.
- This document covers the inputs of SLC v1 and the playbook prior. It does not cover the 2026 V1.5 season adaptation
  (`team_season_adapt.py`), which has its own cutoff rule (kickoff minus 90 minutes) and is documented in the protocol.
