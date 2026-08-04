# What every league is missing, and what a leaderboard is allowed to claim

Measured against prod `backend/data/picks.db` on 2026-08-04. Two questions:

1. Which **essential** stats do we not have, per league?
2. Are there **games-played requirements** we are not honouring — and where a
   player is missing, is that a qualifier problem or a game-log problem?

They have different answers per league, and conflating them is how a 38-game
player ends up leading a 112-game season's batting average.

---

## 1. The stat gaps

`player_stats` has 66 columns and **zero of them are entirely NULL** — the gaps
below are columns that do not exist, not columns nobody filled.

The distinction that matters for planning: a stat already present in
`player_game_logs` is an **aggregation** away. A stat absent from the logs too is
an **ingest** away, which is a different size of job.

### MLB — batting

Have: `games avg hr k_pct bb_pct exit_velo hard_hit_pct barrel_pct launch_angle woba xwoba`

| missing | in the logs? | note |
|---|---|---|
| **PA** | **yes** (38,680 rows) | the qualifier itself — see §2 |
| H, R, RBI, 2B, 3B, BB, K, TB | **yes** | aggregation only |
| **AB** | **no** | `AB = PA − BB − HBP − SF − SH`; we have BB, not HBP/SF/SH. **Not derivable** |
| OBP, SLG, OPS | **no** | need AB/HBP/SF first |
| SB, CS | **no** | no ingest at all |

We have a Statcast quality panel and not a baseball card. `exit_velo` and
`xwoba` are on the page; hits and RBI are not.

### MLB — pitching

Have: `games k_pct whiff_pct exit_velo_against barrel_pct_against xwoba_against`

Logs carry `outs, hits_allowed, batters_faced, BB, K` across 10,511 rows, so:

| missing | derivable? |
|---|---|
| IP | **yes** — `outs / 3`, and outs is the better key to store |
| WHIP | **yes** — `(hits_allowed + BB) / IP` |
| **ERA** | **no** — nothing publishes earned runs into our logs |
| W, L, SV, QS, HR allowed | **no** |

**There is no ERA anywhere in this database.** A pitching leaderboard without
ERA or innings is not a pitching leaderboard.

### NHL

Have skater stats: `goals assists points_nhl shots shooting_pct plus_minus pim ppg ppp shg toi faceoff_pct`

| missing | in the logs? |
|---|---|
| **every goalie stat** — saves, shots against, GAA, SV%, W/L, shutouts | **no** |
| hits, blocked shots | **no** |

This is the worst one and it is invisible. There are **90 goalies in
`player_stats`**, each carrying skater columns, and **78 of 90 have game logs** —
but a goalie's log holds exactly `goals, assists, pim, toi`. Karel Vejmelka has
**64 logged games and not one save recorded**. The rows look like coverage.

### NFL

Have: `pass_yds_g pass_td interceptions cmp_g pass_epa carries_g rush_yds_g receptions rec_yds_g targets fantasy_pts_g fantasy_ppr_g`

| missing | in the logs? |
|---|---|
| **rush_td, rec_td** | **yes** | 
| defensive stats (sacks, tackles, INT for defenders) | no |
| kicking (FG, XP) | **yes**, per game — see `ingest_nfl_published_fantasy.py` |

**You cannot sort the NFL leaderboard by rushing or receiving touchdowns.** The
single most-used fantasy stat, and the logs have had it the whole time.

### NBA

Have: `games pts reb ast stl blk tov fgm fga fg3m fg3a ftm fta minutes ts_pct`

Closest to complete. Missing `fg_pct / fg3_pct / ft_pct` (derivable from
made/attempted, and **required** by the NBA's published qualifiers — §2),
plus OREB/DREB, PF and +/-.

---

## 2. Games-played requirements

### What the leagues publish

| league | category | published qualifier |
|---|---|---|
| MLB | AVG, OBP, SLG | **3.1 PA × team games** — 502 in a 162-game season |
| MLB | ERA and rate pitching | **1.0 IP × team games** — 162 in a 162-game season |
| NBA | per-game titles | **58 games** |
| NBA | FG% | **300 FGM** |
| NBA | 3P% | **82 3PM** |
| NBA | FT% | **125 FTM** |
| NFL | passer rating | **14 attempts × team games** |
| NFL | per-game stats | generally **50% of scheduled games** |
| NFL | yards per carry | ~**100 attempts** |
| NHL | — | **no official published minimum found in this pass.** 40+ GP is a convention, not a rule. Treat as unverified |

Sources: [MLB rate-stat qualifiers](https://www.mlb.com/glossary/standard-stats/rate-stats-qualifiers) ·
[MLB rule 9.22](https://baseballrulesacademy.com/official-rule/mlb/9-22-minimum-standards-individual-championships/) ·
[BR Bullpen: Qualifier](https://www.baseball-reference.com/bullpen/Qualifier) ·
[NBA statistical minimums](https://www.nba.com/stats/help/statminimums) ·
[PFR minimums](https://www.pro-football-reference.com/about/minimums.htm)

### What we actually do

`routers/players.py` — `min_games` defaults to **0** for every league, with one
exception hardcoded in `league_leaders`: MLB batting **30 games**, MLB pitching
**10 games**.

Every published qualifier above is denominated in **plate appearances, innings,
attempts or made shots**. Ours is denominated in **games**. Those are not the
same question, and the substitution is what puts a 38-game player at the top of
a 112-game season's batting average, and lets a reliever with a handful of
at-bats into the batting top 25.

**Games is not a proxy for PA.** It cannot be made into one — a pinch hitter and
a leadoff man play the same number of games.

### Is the missing-player problem the qualifier, or the logs?

Both, and they separate cleanly. Game-log coverage by position, active players:

| league | reading |
|---|---|
| **NHL** | 87–98% across every position. Coverage is fine; **goalie CONTENT is not** (§1) |
| **NFL** | 44–70% by position. Expected — offensive linemen and most defenders accumulate nothing the log records. Not a bug |
| **MLB** | 79%, single `(none)` position bucket — `players.position` is **100% NULL for all 2,750 MLB players** |
| **NBA** | **two disjoint vocabularies**, see below |

**NBA is a real defect, and this is its shape:**

| position vocabulary | players | with 2026 logs | in 2023 `player_stats` |
|---|---|---|---|
| coarse `G/F/C` | 688 | **488** | 206 |
| granular `PG/SG/SF/PF` | 326 | **39** | **319** |

Two ingests wrote two position vocabularies for two nearly disjoint populations.
The granular one is the hoopR 2023 rollup that the leaderboard still serves; the
coarse one is the ESPN population that has 2026 game logs. **The position column
tells you which ingest created the row.** That is why only 53 of the 525 players
on the NBA leaderboard have a 2026 game log — click through and the page is
empty. See [[reference_lp_team_code_vocabularies]] for the same failure in the
team-code column.

---

## 3. What this implies for the per-league tasks

Ordered by user-visible harm per unit of work.

1. **NFL `rush_td` / `rec_td`** — two columns, data already in the logs.
   Smallest job here and it unblocks the most-asked-for sort.
2. **MLB `PA` + the counting stats** (H, R, RBI, 2B, 3B, BB, TB) — aggregation
   from logs. Lands the counting stats AND makes a real 3.1-PA qualifier
   possible in the same pass. **AB still needs a source** (HBP/SF/SH).
3. **Replace `min_games` with per-league published qualifiers.** Blocked on (2)
   for MLB batting and on ERA/IP for pitching; NBA's needs `fg_pct`/`fg3_pct`/
   `ft_pct`, which are derivable today.
4. **NBA position vocabulary + the 2026 rollup.** One migration to a single
   vocabulary, then publish 2026 season stats from the 23,749 log rows we hold.
   Fixes the stale leaderboard and the dead click-through together.
5. **NHL goalie stats.** New ingest, no existing source. Largest job, and the
   only one where the page currently implies coverage it does not have.
6. **MLB ERA / W / L / SV** — new ingest.
7. **MLB `players.position` and `players.team`** — 100% and 89% blank. Team is
   published in our own `player_game_logs`, 0 blank of 49,144 rows.

Rank cards for non-NFL leagues (`nfl_rankings.py` generalisation) sit **after**
(1)–(3): a rank card over a stat set this thin would rank players on `exit_velo`
and not on RBI.
