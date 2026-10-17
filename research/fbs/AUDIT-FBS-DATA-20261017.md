# FBS data coverage audit - 2026-10-17

Measured read-only. Database `/root/legendarypicks/backend/data/picks.dev.db`. Parquet dir `/root/lp-fbs-audit/research/fbs/parquet`. Nothing here was written.

### 1. What the dev database already holds

Read through `file:/root/legendarypicks/backend/data/picks.dev.db?mode=ro`.

| season | log rows | players | distinct games | distinct teams |
|---|---|---|---|---|
| 2025 | 56577 | 11914 | 888 | 230 |
| 2026 | 24864 | 9725 | 387 | 234 |

By source:
| source | rows | first game | last game |
|---|---|---|---|
| cfbd | 81441 | 2025-08-23 | 2026-10-04 |

Player identity:
| measure | count |
|---|---|
| NCAAF `players` rows | 23360 |
| with an ESPN id | 23360 |
| with a position | 23169 |
| `player_game_logs` rows with no `player_id` | 0 |
| `unresolved_players` rows queued | 1295 |

Other stored surfaces:
| surface | rows |
|---|---|
| `player_stats` season rows | 4267 |
| `team_game_results` | 1776 |
| `team_game_stats` | 1776 |
| `roster_snapshots` | 1 |
| `roster_memberships` (all leagues) | 295261 |
| `roster_memberships` for ncaaf | 15672 |
| `published_roster` | 0 |
| `team_stats_coverage` | 1 |

Season totals vs the publisher's own per-game values:

The rollup rule is `ingest_ncaaf_season_stats.py`: sum the stored `player_game_logs.stats` per player, count games as the number of log rows, REG only. The check below recomputes that sum straight from the logs and compares it to `player_stats` on the columns that both carry. A mismatch means the rollup drifted from its input, which is a real defect rather than a missing feature.

| column | matching rows | total rows | note |
|---|---|---|---|
| att vs att | 799 | 799 | pass attempts; the CFBD label is `att` |
| rec vs rec | 3018 | 3018 | receptions; the CFBD label is `rec` |
| pass_yds vs pass_yds | 799 | 799 | same key on both sides; a mismatch is a drift |
| rush_yds vs rush_yds | 2474 | 2474 | same key on both sides; a mismatch is a drift |
| rec_yds vs rec_yds | 3018 | 3018 | same key on both sides; a mismatch is a drift |

Column-family note: NCAAF's rollup landed in the `att` / `rec` / `pass_yds` / `rush_yds` / `rec_yds` family while NFL owns `attempts` / `receptions` / `pass_yds_g` / `rush_yds_g` / `rec_yds_g`. Measured on this database: NCAAF `attempts` 0 rows, `receptions` 0 rows, `att` 799 rows, `rec` 3,018 rows. A cross-league query reading the NFL family returns NULL for every NCAAF row silently. That is a real ambiguity, not a missing value, and it is recorded here rather than fixed by this audit.

Missing statistics must not become fabricated zeroes. CFBD omits a category when the value is zero (the manifest already declares `def_int` at a low coverage floor because `/games/players` publishes `interceptions` only when an INT was recorded). The per-key presence rates below are the honest-zero evidence; a category at 0% presence means the ingest stopped landing it, not that nobody did it.

| stat key | log rows | present | presence |
|---|---|---|---|
| att | 81441 | 4091 | 5 |
| pass_yds | 81441 | 4091 | 5 |
| pass_td | 81441 | 4091 | 5 |
| intc | 81441 | 4091 | 5 |
| rush_yds | 81441 | 14386 | 17.7 |
| rush_td | 81441 | 14386 | 17.7 |
| rec | 81441 | 18951 | 23.3 |
| rec_yds | 81441 | 18951 | 23.3 |
| rec_td | 81441 | 18951 | 23.3 |
| tackles | 81441 | 54488 | 66.9 |
| sacks | 81441 | 54488 | 66.9 |
| def_int | 81441 | 1794 | 2.2 |

### 2. The prop side: lines, sides, sources, history

Props and fixtures, whole table:
| measure | count |
|---|---|
| `props` rows | 627975 |
| `props` for ncaaf | 81030 |
| `prop_games` rows for ncaaf | 400 |
| of those, with an ESPN event id | 323 |
| of those, with a final score | 272 |
| distinct player-games | 3837 |
| `prop_results` rows | 484581 |

`prop_games` is the board fixture, not the schedule. The NCAAF props board is 2026-only today: the season is still being played, so there is no prior-season prop history in this table. A claim of the form "NCAAF props cover N seasons" is a claim about this table and it currently answers 1.

| season | props | fixtures | players |
|---|---|---|---|
| 2026 | 81030 | 355 | 1265 |

Markets, whole board:

| market | props | fixtures | players | over | under |
|---|---|---|---|---|---|
| receiving_yards | 28790 | 265 | 637 | 14395 | 14395 |
| rushing_yards | 17174 | 263 | 333 | 8587 | 8587 |
| passing_yards | 10714 | 273 | 148 | 5357 | 5357 |
| total_touchdowns | 5634 | 313 | 1028 | 2817 | 2817 |
| receptions | 5450 | 191 | 402 | 2725 | 2725 |
| rushing_receiving_yards | 2902 | 172 | 130 | 1451 | 1451 |
| passing_touchdowns | 2756 | 222 | 132 | 1378 | 1378 |
| passing_rushing_yards | 1676 | 184 | 99 | 838 | 838 |
| rush_attempts | 1508 | 173 | 201 | 754 | 754 |
| kicking_points | 1188 | 156 | 88 | 594 | 594 |
| pass_attempts | 1076 | 166 | 103 | 538 | 538 |
| pass_completions | 924 | 167 | 97 | 462 | 462 |
| total_passing_touchdowns | 708 | 187 | 111 | 354 | 354 |
| extra_points_made | 184 | 60 | 46 | 92 | 92 |
| interceptions_thrown | 176 | 63 | 52 | 88 | 88 |
| rushing_receiving_touchdowns | 134 | 51 | 55 | 67 | 67 |
| field_goals_made | 30 | 7 | 7 | 15 | 15 |
| rushing_touchdowns | 6 | 3 | 3 | 3 | 3 |

Sources are the book that published the line, not the authority for the final statistic. Every source below is a RotoWire relay or Bovada.

| source | props | fixtures | first capture | last capture |
|---|---|---|---|---|
| rotowire:prizepicks | 18244 | 241 | 2026-08-29T07:32:56.464210+00:00 | 2026-10-16T21:36:27.216289+00:00 |
| rotowire:sleeper | 18038 | 318 | 2026-08-29T07:32:56.464210+00:00 | 2026-10-16T21:36:27.216289+00:00 |
| rotowire:betr | 10360 | 219 | 2026-09-02T06:34:38.711736+00:00 | 2026-10-16T21:36:27.216289+00:00 |
| rotowire:underdog | 10040 | 225 | 2026-08-29T07:32:56.464210+00:00 | 2026-10-16T21:36:27.216289+00:00 |
| rotowire:caesars-sb | 8928 | 211 | 2026-08-29T07:32:56.464210+00:00 | 2026-10-16T21:36:27.216289+00:00 |
| rotowire:fanduel-sb | 7672 | 221 | 2026-08-29T07:32:56.464210+00:00 | 2026-10-16T21:36:27.216289+00:00 |
| bovada | 6492 | 197 | 2026-09-05T19:34:46.921910+00:00 | 2026-10-17T02:34:38.940781+00:00 |
| rotowire:pick6 | 1010 | 110 | 2026-09-03T05:04:11.674880+00:00 | 2026-10-16T21:36:27.216289+00:00 |
| rotowire:betmgm-sb | 246 | 11 | 2026-10-09T21:06:22.641296+00:00 | 2026-10-16T21:36:27.216289+00:00 |

Line snapshots (`prop_odds_snapshots`) are the timestamped market expectations a backtest would need. They are the difference between "we projected 0.55" and "the market was 0.52 and we beat it".

| measure | count |
|---|---|
| rows | 3526 |
| distinct props | 1106 |
| distinct ncaaf props | 0 |
| rows with `is_close=1` | 0 |

Market lines and totals for the game model (`nfl_line_snapshots` is the NFL table; the same idea does not exist for NCAAF).

| measure | count |
|---|---|
| `nfl_line_snapshots` rows | 10 |
| of those for ncaaf | 0 |
| `live_price_snapshots` rows | 30 |

### 3. Reconciliation: do two publishers agree on the same game?

The stored NCAAF logs are CFBD (`/games/players`). The ESPN-derived SportsDataverse release is a different publisher with a different key. If the two agree on final scores for the same games, the ESPN play-by-play release can be joined to our prop fixtures by ESPN game id. If they disagree, the join is wrong and the counts below are the evidence.

Stored CFBD fixtures that are final:
| measure | count |
|---|---|
| distinct games in `player_game_logs` | 1275 |
| distinct games with a team code | 1275 |

ESPN-derived release, 2025:
| measure | count |
|---|---|
| play rows | 166371 |
| distinct games | 956 |
| rows with a home final score | 166371 |
| games with a home final score | 956 |
| rows with an `espn_game_id`-style id | 166371 |

Join attempt: stored CFBD `game_no` against the ESPN release `game_id`.

| measure | count |
|---|---|
| stored 2025 game ids | 888 |
| ESPN release 2025 game ids | 956 |
| exact intersection | 887 |
| stored ids present in the release | 887 |

The stored logs carry a CFBD game id, and the ESPN release carries an ESPN game id. The intersection above is the direct join; the overlap is small because the CFBD id is not the ESPN id, which is why the released play-by-play file's own `espn_game_id` column (present in the stats.ncaa.org-sourced release, absent here) is the join key that actually works.

Second path, different publisher: `ncaa_mfb_pbp_cfbfastr` (stats.ncaa.org) carries its own `espn_game_id` column.

| measure | count |
|---|---|
| distinct `espn_game_id` in that release | 1649 |
| intersection with stored CFBD `game_no` | 872 |
| stored 2025 games covered by it | 98.2% |

Two publishers, two keys. Where they disagree is the finding; this section reports both rather than choosing one.

### 4. What the publisher releases carry

#### 4s. Season-by-season coverage across the releases

A backtest needs seasons, not one season. This table measures every season for which a release file is on disk, and it is the input to any claim of the form "we can backtest N seasons".

| season | release | rows | distinct games |
|---|---|---|---|
| 2022 | stats.ncaa.org pbp | 296782 | 1590 |
| 2023 | stats.ncaa.org pbp | 285304 | 1569 |
| 2024 | stats.ncaa.org pbp | 305266 | 1664 |
| 2025 | stats.ncaa.org pbp | 309797 | 1685 |
| 2026 | stats.ncaa.org pbp | 149246 | 812 |
| 2022 | ESPN pbp | 149745 | 861 |
| 2023 | ESPN pbp | 153945 | 903 |
| 2024 | ESPN pbp | 163567 | 946 |
| 2025 | ESPN pbp | 166371 | 956 |
| 2026 | ESPN pbp | 78642 | 455 |
| 2022 | ESPN player box | 40598 | 900 |
| 2023 | ESPN player box | 57239 | 911 |
| 2024 | ESPN player box | 78993 | 965 |
| 2025 | ESPN player box | 80498 | 958 |
| 2026 | ESPN player box | 39913 | 455 |

The `stats.ncaa.org pbp` release is the only one of the three with a published floor below 2013, and its own release notes state the floor is fall 2013 and that its ESPN game id reaches roughly 88% of games. The ESPN releases' coverage above is measured here, not quoted from their notes.

#### 4a. ESPN college football play-by-play (2025)

| column | non-null rows | share of plays | value is a flag |
|---|---|---|---|
| rusher_player_name | 65023 | 39.1% | False |
| rusher_player_id | 64934 | 39.0% | False |
| passer_player_name | 63232 | 38.0% | False |
| passer_player_id | 63188 | 38.0% | False |
| receiver_player_name | 56388 | 33.9% | False |
| receiver_player_id | 56329 | 33.9% | False |
| yds_rushed | 63853 | 38.4% | False |
| yds_receiving | 42641 | 25.6% | False |
| yds_sacked | 3684 | 2.2% | False |
| sack | 166371 | 100.0% | True |
| EPA | 166371 | 100.0% | False |

`yds_sacked` and `sack` are the NCAA-specific trap the plan names: under NCAA convention sacks reduce team and QB rushing, unlike the NFL's net-rushing treatment. The simulated box score has to reconcile to NCAA statistics, and this release publishes both columns, so the reconciliation is measurable.

#### 4b. NCAA play-by-play, `cfbfastR` contract (2025)

| column | non-null rows | share of plays |
|---|---|---|
| espn_game_id | 303370 | 97.9% |
| rusher_player_name | 113947 | 36.8% |
| passer_player_name | 113172 | 36.5% |
| receiver_player_name | 101509 | 32.8% |
| yds_rushed | 113872 | 36.8% |
| yds_receiving | 61968 | 20.0% |
| yds_sacked | 6596 | 2.1% |
| sack | 309606 | 99.9% |
| target | 309606 | 99.9% |

Coverage floor for this release is fall 2013 (stats.ncaa.org publishes no football box scores or play-by-play before that) and the ESPN game id reaches roughly 88% of games.

#### 4c. ESPN player box scores (2025)

| measure | count |
|---|---|
| rows | 80498 |
| distinct games | 958 |
| distinct athletes | 12755 |
| categories | defensive, fumbles, interceptions, kickReturns, kicking, passing, puntReturns, punting, receiving, rushing |

#### 4d. Game rosters (2025)

| measure | count |
|---|---|
| rows | 214432 |
| distinct games | 945 |
| distinct athletes | 26316 |
| `starter` non-null | 214432 |
| `did_not_play` non-null | 214432 |
| with a date of birth | 8019 |

This is the per-game availability population the plan needs for the blowout-substitution problem: a starter who plays the first half and sits the fourth is visible here as `starter` plus a partial box score, which a season-average projection cannot represent.

#### 4e. Season rosters (2025)

| measure | count |
|---|---|
| rows | 26327 |
| athletes | 26316 |
| teams | 234 |
| FBS athletes | 15618 |
| FCS athletes | 10709 |
| with a date of birth | 629 |

Class year, FBS only:
| class | athletes |
|---|---|
| Freshman | 7714 |
| Senior | 7472 |
| Sophomore | 5607 |
| Junior | 5505 |
| None | 29 |

#### 4f. Roster crosswalk

| measure | count |
|---|---|
| rows | 37740 |
| distinct ESPN athlete ids | 26056 |
| distinct CFBD person keys | 35652 |
| matched sources | espn, espn+fox, fox |

#### 4g. Team box scores (2025)

| measure | count |
|---|---|
| rows | 1916 |
| games | 958 |
| teams | 236 |
| columns | firstDowns, thirdDownEff, fourthDownEff, totalYards, netPassingYards, completionAttempts, yardsPerPass, rushingYards, rushingAttempts, yardsPerRushAttempt, totalPenaltiesYards, turnovers, fumblesLost, interceptions |

#### 4h. Betting (2025)

| measure | count |
|---|---|
| rows | 958 |
| games with a spread | 958 |
| games with a total | 958 |
| odds sources | core_odds_api, default |

This is a game-level lines file. It is not a player-prop archive.

#### 4i. Injuries (2026)

| measure | count |
|---|---|
| rows | 129 |
| distinct athletes | 3 |
| teams | 3 |
| statuses | Active, Out |

### 5. Which markets have enough history to model

The gate is not "does the market exist" but "is there a published result to train against and a line to grade against". A market with 30 props cannot support a distribution fit no matter how clean the field is.

Gradeability: does a stored log exist for the prop's game?

| market | props | game matched | player exact | settled |
|---|---|---|---|---|
| receiving_yards | 28382 | 17644 | 15850 | 21864 |
| rushing_yards | 16890 | 10126 | 9918 | 13866 |
| passing_yards | 10552 | 6114 | 6098 | 8898 |
| total_touchdowns | 5634 | 3516 | 3134 | 4210 |
| receptions | 5450 | 3490 | 3220 | 4290 |
| rushing_receiving_yards | 2902 | 1864 | 1832 | 2478 |
| passing_touchdowns | 2756 | 1684 | 1684 | 2272 |
| passing_rushing_yards | 1676 | 1092 | 1092 | 1452 |
| rush_attempts | 1508 | 1162 | 1156 | 1394 |
| kicking_points | 1188 | 792 | 0 | 974 |
| pass_attempts | 1076 | 808 | 808 | 990 |
| pass_completions | 924 | 616 | 616 | 820 |
| total_passing_touchdowns | 590 | 320 | 320 | 480 |
| extra_points_made | 184 | 106 | 0 | 134 |
| interceptions_thrown | 176 | 110 | 110 | 154 |
| rushing_receiving_touchdowns | 134 | 44 | 44 | 104 |
| field_goals_made | 30 | 26 | 0 | 30 |
| rushing_touchdowns | 6 | 6 | 6 | 6 |

`game matched` and `player exact` are two questions, not one metric with two names. `game matched` asks whether the ESPN event id of the prop's fixture has any stored CFBD log at all; `player exact` asks whether the specific ESPN athlete id has one in that game. The gap between them is the props whose player row is missing while the game row exists. The market where the gap is largest and `settled` is still non-zero is the one where our own stored history can grade a settlement that the logs cannot explain, which is the identity defect the settlement diagnosis named separately.

Props on an unlinked fixture (no ESPN event id):

| measure | count |
|---|---|
| linked fixtures | 323 |
| unlinked fixtures | 77 |
| props on unlinked fixtures | 972 |
