# Role usage reference: snap, target and carry shares by role, league and team, 2016 to 2026

Built by `build_role_usage.py` from published nflverse files only (snap counts and weekly player stats); hashes in
`manifest.json`. Pinned so comparisons read it instead of recomputing it. 2026 covers weeks 1 to 7 (the snap counts in
the local backfill end there). 42,454 role rows; every team-week has stats; at most 177 skill snaps a season have a pfr
id with no gsis id.

Roles are ranks by offensive snaps within a team-week: RB1, RB2 (RB or HB), TE1, TE2, WR1, WR2, WR3, FB1. Target share is
the player's targets over the team's targets that week; carry share the same for carries (QBs in the team total).

Cross-check: the snap-share means match the earlier `role_snap_share_2024_2026.csv` (database `off_pct`) to within 0.002
for every role in 2024 to 2026, with the same team-week counts.

## Files

| File | What |
|---|---|
| `role_usage_team_week.csv.gz` | One row per season, week, team and role: player, snaps, snap, target and carry share |
| `role_usage_league.csv` | League, per season, season type and role: mean, p10, p50, p90 of each share |
| `role_usage_team_season.csv` | Per regular season, team and role: the team's mean shares, the league's, and the difference |
| `snap_trajectory_team.csv` | Per regular season, team and role: mean snap share in weeks 1-4, 5-8, 9-18 |
| `snap_trajectory_players.csv` | Per regular season and position: how far players' snap shares move from weeks 1-4 to 5-8 |

## League, regular season, mean share (snap / target / carry)

| Role | 2022 | 2025 | 2026, weeks 1-7 |
|---|---|---|---|
| WR1 | 0.880 / 0.228 / 0.007 | 0.854 / 0.229 / 0.006 | 0.839 / 0.223 / 0.007 |
| WR2 | 0.785 / 0.195 | 0.738 / 0.179 | 0.723 / 0.182 |
| WR3 | 0.561 / 0.112 | 0.525 / 0.110 | 0.528 / 0.115 |
| TE1 | 0.738 / 0.142 | 0.748 / 0.156 | 0.738 / 0.155 |
| TE2 | 0.399 / 0.050 | 0.435 / 0.060 | 0.460 / 0.058 |
| RB1 | 0.636 / 0.109 / 0.528 | 0.650 / 0.111 / 0.549 | 0.648 / 0.111 / 0.565 |
| RB2 | 0.309 / 0.059 / 0.224 | 0.296 / 0.051 / 0.216 | 0.292 / 0.051 / 0.216 |

WR snap shares are falling and TE2's rising, 2022 to 2026: more two-TE football league-wide.

## Snap share through the season

- Role level: the mean absolute change in a role's snap share from weeks 1-4 to weeks 5-8 is 0.059 to 0.071 every season
  2022 to 2026 (0.067 in 2026). 2026 is not unusual.
- Player level: 28% to 50% of RBs, TEs and WRs with two or more games in each window move 10 points or more between
  weeks 1-4 and 5-8, every season. WRs move most (mean 0.10 to 0.13).
- 2026, most changed teams (mean role change): HOU 0.126, LV 0.112, BAL 0.098, IND 0.093; least: KC 0.028, BUF 0.032.
  Largest moves: HOU RB1 0.56 to 0.84 (and RB2 0.44 to 0.16), DET WR3 0.68 to 0.44, IND TE1 0.90 to 0.70.

## Team against league, 2026 (examples)

- Target share: SEA WR1 0.369 against 0.223 league, DAL WR1 0.332, ARI TE1 0.297 and NYG TE1 0.271 against 0.155.
- Carry share: DET RB1 0.834 and KC RB1 0.763 against 0.565 league; GB RB1 0.317 and NO RB1 0.372 (committees).
