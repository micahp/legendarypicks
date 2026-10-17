# NCAAF log backfill - 2026-10-17

source release: `ncaa_mfb_player_stats_2026` (ncaa_mfb_player_stats)
database: `/root/legendarypicks/backend/data/picks.dev.db`
mode: WRITE

## 1. Resolution

| measure | value |
|---|---|
| release rows | 103705 |
| resolved to an athlete id | 66895 |
|   via (game, full_name) from game_rosters | 66895 |
| distinct player-games | 42452 |
| distinct athletes | 12884 |
| distinct games | 793 |

## 2. What will be written

| measure | value |
|---|---|
| player-games in the release | 42452 |
| already present (left alone) | 22500 |
| to insert | 19952 |
|   of those, resolvable to a player_id | 12063 |
|   games covered | 778 |

## 3. Games covered

top games by player count:

| game_no | player-games | date | type |
|---|---|---|---|
| 401856718 | 79 | 2026-10-10 | REG |
| 401866411 | 78 | 2026-09-06 | REG |
| 401864499 | 77 | 2026-09-05 | REG |
| 401858482 | 76 | 2026-10-10 | REG |
| 401860902 | 75 | 2026-10-10 | REG |
| 401858257 | 71 | 2026-10-10 | REG |
| 401870766 | 71 | 2026-10-08 | REG |
| 401871066 | 69 | 2026-10-07 | REG |
| 401864507 | 69 | 2026-09-20 | REG |
| 401866436 | 69 | 2026-10-10 | REG |
| 401862797 | 69 | 2026-10-10 | REG |
| 401856714 | 69 | 2026-10-10 | REG |
| 401858487 | 68 | 2026-10-10 | REG |
| 401869949 | 68 | 2026-10-10 | REG |
| 401858258 | 68 | 2026-10-10 | REG |

date coverage of the inserted games: 2026-08-27, 2026-08-28, 2026-08-29, 2026-08-30, 2026-09-03, 2026-09-04, 2026-09-05, 2026-09-06, 2026-09-07, 2026-09-11, 2026-09-12, 2026-09-13, 2026-09-17, 2026-09-18, 2026-09-19, 2026-09-20, 2026-09-24, 2026-09-25, 2026-09-26, 2026-09-27, 2026-10-02, 2026-10-03, 2026-10-04, 2026-10-07, 2026-10-08, 2026-10-09, 2026-10-10, 2026-10-11

## 4. Written

| measure | value |
|---|---|
| rows inserted | 12063 |
| skipped: athlete not in our spine | 7889 |
|   of those, queued for identity review | 7889 |
| total NCAAF log rows now | 93504 |
|   from this source | 12063 |
| distinct games now | 1688 |
