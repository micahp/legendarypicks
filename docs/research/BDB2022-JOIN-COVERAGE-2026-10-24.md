# 2022 Big Data Bowl tracking to LP nfl_pbp: join and coverage (2026-10-24)

Source. The BDB files are the 2022-season files at `/root/nfl-tracking-data/bdb2025/code-data/` (weeks 1–9; `PROVENANCE.json`
names the upstream repository and commit). The LP side is `nfl_pbp` in the dev database, season 2022, weeks 1–9. Both sides
were read only. The join script is `scripts/bdb/bdb2022_join.py`. Its outputs are `bdb2022-join-counts-2026-10-24.json` and
`bdb2022-join-pairs-2026-10-24.csv` (one row per unique match).

## Join keys, and what matches

| field | BDB side | LP side | match result |
| --- | --- | --- | --- |
| game | `gameId` via `games.csv` (season, week, visitor, home) | `game_id` via away and home team columns | **136 of 136** games, one-to-one, after mapping `LA`→`LAR` and `WAS`→`WSH` in both the team and the side fields |
| quarter | `quarter` | `qtr` | equal on every plays of the 136 games that are in quarters 1–4 |
| clock | `gameClock` (mm:ss left in the quarter) | `game_seconds_remaining` minus the seconds of later quarters | equal on every matched play |
| down | `down` | `down` | equal on every matched play |
| distance | `yardsToGo` | `ydstogo` | equal on every matched play |
| team | `possessionTeam` | `posteam` | equal on every matched play |
| spot | `yardlineSide` and `yardlineNumber`, converted to offense-relative `yardline_100` | `yardline_100` | equal on every play where the BDB side is a team (15,765 plays) |

The first attempt matched 119 games, not 136, because the game index was built from LP's `game_id` string, which writes the
team codes differently. The second attempt mapped only the possession team, so the yard-line side used `WAS` and the spot was
wrong by 50 or 60 yards on 640 plays. Both were bugs in the join, and both are fixed. The final result has no mismatch left on
any field.

## Counts, for the 16,124 tracked plays

| outcome | plays |
| --- | ---: |
| unique match (one LP play) | **15,765** (97.8%) |
| ambiguous (two or three LP candidates, none unique) | 3 |
| spot unresolvable (BDB yard-line side is `NA`) | 222 |
| overtime (quarter 5, clock convention not checked) | 134 |
| **total** | **16,124** |

Funnel, in the order the fields were applied. The number of plays still matching after each step:
game 15,990 (all non-overtime plays), quarter 15,990, clock 15,990, down 15,990, distance 15,990, team 15,990, spot 15,768.
The only step that eliminates candidates is the spot, and only for the 222 plays with an unresolvable side.

## Coverage of LP play-by-play and drives

| level | covered | of | share |
| --- | ---: | ---: | ---: |
| LP scrimmage and kick plays (run, pass, punt, field goal), 136 games | 15,585 | 18,518 | 84.2% |
| LP drives with at least one scrimmage play | 789 complete, 2,014 partial, 46 with none | 3,091 | 25.5% complete |
| LP games with every drive complete | 0 | 136 | 0% |

Why the 2,933 unmatched scrimmage and kick plays are unmatched, by type and flag:

- **Punts: 1,100 of 1,100 unmatched.** The BDB file has no punt plays.
- **Field goals: 517 of 517 unmatched.** The BDB file has no field-goal plays.
- **Runs and passes: 1,228 unmatched.** Mostly plays whose yard-line side is `NA` (222 across all types), overtime, and two-point
  tries, which are in the BDB file but not in the scrimmage count.

So the tracking set covers runs and passes only, and within those, 15,765 of 16,124 plays join to LP play-by-play. A complete LP
drive therefore cannot be fully covered whenever it contains a punt or a field goal, which is most drives. That is why no game
is complete.

## Fields this join cannot use

- The BDB side has no timeout counts, so a timeout cannot be matched to the LP timeout flag except through the play itself.
- `playNullifiedByPenalty` is `N` on all 16,124 plays. The BDB set contains no penalty-nullified plays.
- Overtime (quarter 5) is not checked: its clock convention differs and is not verified here.
