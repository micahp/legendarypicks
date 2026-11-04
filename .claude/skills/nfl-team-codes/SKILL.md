---
name: nfl-team-codes
description: MUST load before any code that reads, joins, filters or compares NFL team codes from more than one source: nflverse files (play-by-play, schedules, depth charts, rosters, injuries, weekly player stats, dated archives, FTN), the LP database, ESPN, odds or props feeds. The LP database says LAR and WSH; nflverse says LA and WAS; game_id strings keep nflverse's spelling even inside the database. A missed translation never raises: it shows up as "team absent", "no injury rows", a 30-of-32 coverage count or two teams that never match. Triggers on any team join, posteam, home_team, club_code, team_abbr, a coverage or readiness check by team, "team absent from", a new ingest, and any hard-coded {'LA': 'LAR'} map.
---

# NFL team codes

Every season this bites again, always the same way: one source says **LA / WAS**, another says
**LAR / WSH**, the other 30 teams match, and the two that do not look like missing data instead of a
key error. In the 2026-10-29 weeks 1-7 readiness audit it refused 13 games as "team absent from depth
chart". The depth rows were there under LA and WAS the whole time.

## The rule

**Translate at the read boundary with `scripts/nfl_team_codes.py`, never with a local dict.**

```python
import nfl_team_codes as teams          # scripts/ is on sys.path in scripts/nfl_sequence

teams.to_db('LA')                       # 'LAR'   any known spelling -> database code; unknown raises
teams.to_nflverse('WSH')                # 'WAS'   any known spelling -> nflverse code; unknown raises
teams.convert(column, to='db')          # whole column; one error names every unknown code with its count
teams.normalize_frame(df, ['team'], to='db')
teams.teams_from_game_id('2026_08_LAC_LA')   # ('LAC', 'LAR'): game_ids are nflverse spelling
```

Convert the outside source to the side you are joining on, once, as it is read. Do not convert
inside the join, and do not compare raw codes from two sources.

## What each source uses (measured 2026-11-03)

| Source | Rams | Washington | Seasons checked |
|---|---|---|---|
| LP database: nfl_pbp, nfl_schedule, players, player_game_logs | LAR | WSH | 2010-2026 |
| nflverse pbp, depth charts, rosters, injuries, stats_player, archives | LA | WAS | 2010-2026 |
| game_id strings, in nflverse AND in the database | LA | WAS | all 4,635 schedule rows |
| ESPN | LAR | WSH | |

The database stores relocated clubs under the current code in every season (LV, LAC, LAR), and so
does nflverse play-by-play. `to_db` also accepts OAK, SD, STL, JAC, ARZ, AZ and a few
Pro-Football-Reference spellings.

## Why the functions refuse instead of passing through

`codes.get(x, x)` is the bug. An unknown or untranslated code passes through unchanged, the join
misses, and the miss reads as a coverage gap. `to_db`, `to_nflverse` and `convert` raise on any code
not in `TO_DB`, nulls included. If a new source uses a new spelling, add it to `TO_DB` with a comment
naming the source. Do not catch the error.

The older wrappers `to_pbp_team_code` and `to_nflverse_team_code` still pass unknown codes through
for existing callers. New code uses `to_db` and `to_nflverse`.

## Checking a coverage claim by team

Before writing "team X has no rows in source Y", convert Y's team column with `convert` and count
again. If the only teams missing are LA/LAR or WAS/WSH, it is this bug, not missing data.

## Known local copies still to migrate

These keep their own dicts and are where it will bite next: `backend/team_codes.py` (the ESPN
vocabulary for all leagues; its NFL aliases agree), `backend/build_player_game_shares.py`,
`backend/routers/nfl_model.py`, `backend/nfl_news.py`, `backend/capture_espn_weekly_projections.py`,
`backend/validate_nfl_seeding_history.py`, `backend/settlement/boxscore_extract.py`,
`backend/ingest_rotowire_props.py`, and the research scripts under `docs/research/playcall-m3-fold-*`.
