# Playcall baseline, 2022 to 2025 (WP0)

Built by `build_baseline.py` from `/root/gridiron-playbooks-research/data/raw/pbp_{2022,2023,2024,2025}.csv.gz`.
No 2026 file is read. Outputs: `team_season.csv` (128 rows, 32 teams x 4 seasons), `player_season.csv`.

## Definitions (decided by the manager; not open)

- Scope: season in 2022-2025, season_type REG, posteam present.
- Scrimmage play: play_type in {run, pass}, excluding qb_kneel and qb_spike.
- Run: play_type == run. Dropback: play_type == pass, which includes sacks.
- Sack: sack == 1.
- Drives: distinct (game_id, drive) per posteam that contain at least one scrimmage play.
- plays_per_drive = scrimmage plays / drives.
- Per game: divided by distinct REG game_ids for the team.
- Carries: rusher_player_name on run plays. Targets: receiver_player_name on dropbacks (sacks have no receiver).
- Shares: player count / team total for the season.

## Checks against the write-up (pre-2026 data only)

| Write-up claim | Pre-2026 result | Status |
| --- | --- | --- |
| Dallas observed 22.86 team rush attempts per game | DAL 2025: 26.41 runs per game (449 runs, 17 games). 2022-2024: 30.47, 26.29, 24.71 | Not reproduced in 2022-2025. The 22.86 may refer to 2026, or to a different rush definition (for example, including scrambles or kneels). Not resolved here; 2026 is not read. |
| Michael Wilson 23.3% observed target share (Arizona) | ARI 2025: M.Wilson 67 targets, 10.8%; Mi.Wilson (second Wilson) 60 targets, 9.7%. Leader T.McBride 27.4%. | Not reproduced in 2025. The 23.3% may refer to 2026. Two Wilsons appear in the data; the write-up does not say which one. |
| Javonte Williams 15.71 observed carries; 68.7% observed carry share (Dallas) | DAL 2025: J.Williams 252 carries, 56.1% of 449 team runs (M.Davis 11.6%, J.Blue 8.5%). | Not reproduced in 2025. The 15.71 and 68.7% may be 2026 or a different definition. |
| RB carry variance 1.77x; WR target variance 1.40x | Not computed in this step | Pending. Needs the simulation output, which is not part of WP0. |

## Decisions taken without waiting (non-blocking)

- Q1 (playbook prior default): not needed for the baseline. Left as an open item for WP1 only.
- Q2 (personnel and eligibility): treated as a gap to close in WP1, as recommended in the M1 design note.
- Q3 (defensive label source columns): not needed for the baseline. Left for WP4.

## WP3 step 1: personnel groups, 2022-2025 (report only; no model)

Source: `/root/gridiron-playbooks-research/data/raw/pbp_participation_{2022..2025}.csv`, column `offense_personnel`.
Output: `personnel_by_team_season.csv` (team, season, personnel_code, plays, share).

- personnel_code = count of RB followed by count of TE, the same code `formation_layer.personnel_code` uses. "11" is
  1 RB and 1 TE. The raw strings also list the offensive linemen (for example "1 C, 2 G, 1 QB, 1 RB, 2 T, 1 TE, 3 WR"),
  so counting raw strings splits one package across many keys; that is why the code is used.
- Plays with no personnel text: 0 of 175,499.
- Overall share of plays: 11 = 58.1%, 12 = 21.8%, 13 = 4.4%, 01 = 3.9%, 21 = 3.7%, 02 = 2.7%.

## Source of the write-up's observed numbers (pointer from hermes2; file not opened by the manager)

hermes2 was asked which file produced the Dallas 22.86, Wilson 23.3%, and Williams 15.71 / 68.7% figures. Its reply
gives one path: `docs/research/ari-dal-player-tail-audit-v5-2026-10-30/REVIEW.md`. That path is dated 2026-10-30, so the
observed side of those comparisons is likely 2026 data, which is sealed. The manager did not open that file, so the
numbers are not verified. Whether the owner may open it is open decision D1 (2025 and 2026 status). Until D1 is
answered, the four write-up comparisons stay marked as unverified.

## Status of the write-up (owner decision, 2026-11-02)

The source write-up is not canonical. These pre-2026 numbers are canonical. The four write-up comparisons above are
unverified; 2026 may be opened for verification because SLC v1 does not use 2026 data, but any access must be logged in
the holdout record first.
