# Playcall baseline, 2022 to 2025 (WP0)

Built by `build_baseline.py` from `/root/gridiron-playbooks-research/data/raw/pbp_{2022,2023,2024,2025}.csv.gz`.
No 2026 file is read by this folder. Outputs: `team_season.csv` (128 rows, 32 teams x 4 seasons), `player_season.csv`,
`personnel_by_team_season.csv`. These tables are pinned by sha256 in `docs/research/PLAYCALL-M3-FREEZE-2026-11-02.md`.

## Definitions (as built; these are the baseline's own definitions)

- Scope: season in 2022-2025, season_type REG, posteam present.
- Scrimmage play: play_type in {run, pass}, excluding qb_kneel = 1 and qb_spike = 1.
- Run: play_type = run. Dropback: play_type = pass, including sacks. Sack: sack = 1.
- Drive: distinct (game_id, drive) per posteam containing at least one scrimmage play.
- Plays per drive: scrimmage plays / drives.
- Per-game quantities: divided by the number of distinct REG game_ids for the team in that season.
- Carries: rusher_player_name on run plays. Targets: receiver_player_name on dropbacks with a receiver recorded.
- `carry_share`: carries / sum of team carries in that season.
- `target_share`: targets / sum of team targets in that season, where the team total counts only targets with a
  recorded receiver. This is the recorded-target convention. It is different from the audit's definition (below).
- Personnel code: count of RB followed by count of TE in offense_personnel. Raw personnel strings list the linemen too,
  so they are not counted directly.

## Pre-2026 results (canonical for this repository)

- DAL 2025: 449 run plays in 17 games = 26.41 per game. 2022-2024: 30.47, 26.29, 24.71 per game.
- DAL 2025: J.Williams 252 carries, 56.1% of the 449 team run plays (M.Davis 11.6%, J.Blue 8.5%).
- ARI 2025, target_share (recorded-target convention): T.McBride 27.4%, M.Wilson 10.8% (67 targets),
  Mi.Wilson 9.7% (60 targets). The 2026 reconciliation identifies "Michael Wilson" as Mi.Wilson, ID 00-0038559.
- Personnel, 2022-2025, by plays: 11 personnel 58.1%, 12 personnel 21.8%, 13 personnel 4.4%, 01 personnel 3.9%,
  21 personnel 3.7%, 02 personnel 2.7%. 0 of 175,499 plays have no personnel text.

## 2026 Weeks 1-7 comparisons (reconciled)

Reconciled in `docs/research/playcall-reconciliation-2026-11-02/`. Under the owner's D1 ruling, that reconciliation
read 2026 observed data after freeze commit 9bbb2af6 and access entry 13 in the holdout record. Every figure cited in
the source audit reproduces exactly, using the audit's own flag definitions from
`scripts/nfl_sequence/build_player_workload_reference.py`:

- DAL rush attempts per game: 160 / 7 = 22.86 (reproduced).
- J.Williams carries per game: 110 / 7 = 15.71 (reproduced). Carry share 110 / 160 = 68.7% (reproduced).
- Mi.Wilson targets per game: 66 / 7 = 9.43 (reproduced).
- Mi.Wilson target share, audit definition (pass attempts with sacks and two-point tries excluded): 66 / 283 = 23.3%
  (reproduced). The 283 includes two QB spikes.

The 2026 numbers are not used to fit, tune, or select anything in this folder. The pre-2026 numbers above are not
comparable to the 2026 numbers as the same population.

## Decisions taken without waiting (non-blocking)

- Q1 (playbook prior default): not needed for the baseline. The owner ruling enables it in v1_full_stack.
- Q2 (personnel and eligibility): a gap to close in WP1, as recommended in the M1 design note.
- Q3 (defensive label source columns): not needed for the baseline. Left for WP4.

## WP3 step 1: personnel groups, 2022-2025 (report only; no model)

Source: `/root/gridiron-playbooks-research/data/raw/pbp_participation_{2022..2025}.csv`, column `offense_personnel`.
Output: `personnel_by_team_season.csv` (team, season, personnel_code, plays, share).

- personnel_code = count of RB, then count of TE. "11" is 1 RB and 1 TE.
- Overall share of plays: 11 = 58.1%, 12 = 21.8%, 13 = 4.4%, 01 = 3.9%, 21 = 3.7%, 02 = 2.7%.
