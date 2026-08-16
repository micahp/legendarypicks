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

---

## CORRECTION — 2026-08-04: most of the "no" column above is wrong

Three separate rows in this document record a stat as unpublished or
underivable. All three were measured against the wrong publisher. Keeping the
originals above, because the error is more instructive than the fix.

| this document said | actually |
|---|---|
| **AB** — "Not derivable", and OBP/SLG/OPS blocked behind it | published directly, with HBP and SF alongside |
| **ERA** — "nothing publishes earned runs into our logs"; "there is no ERA anywhere in this database" | published, with earned runs, IP, W, L, SV and WHIP |
| **every goalie stat** — saves, shots against, GAA, SV%, W/L, shutouts | published league-wide by nhle.com, one request |

One request each:

```
statsapi.mlb.com/api/v1/stats?stats=season&group=hitting&playerPool=All
   PA 215, AB 184, H, R, RBI, 2B, 3B, BB, K, SB, TB, HBP, SF, .299/.391/.467/.858
statsapi.mlb.com/api/v1/stats?stats=season&group=pitching&playerPool=All
   ERA 3.57, IP 128.2, W 9, L 5, SV 0, WHIP 1.19, ER 51
api.nhle.com/stats/rest/en/goalie/summary
   saves, shotsAgainst, goalsAgainst, savePct, GAA, shutouts, W, L, OTL, GS
```

`playerPool=All` matters. The default is `Qualified` — 149 hitters of 679 for
2026 — so a snapshot built on the default is silently a leaderboard.

**Innings are thirds.** MLB publishes `inningsPitched` as "128.2", meaning 128
and two thirds. The published qualifier (1.0 IP × team games) is a comparison,
and comparing 128.2 against a threshold is arithmetic on a number that does not
mean what it looks like. `outs` is published; `innings` stores outs/3.

Landed on dev: `A/required-stats[batting]`, `A/required-stats[pitching]`,
`E/qualifier[batting]`, `E/qualifier[pitching]` and NHL
`A/required-stats[season]` all FAIL → PASS. 78 goalies, 63,525 saves.

**Still open:** `B/position-content[D]`. Blocks and hits ARE published per game,
by `gamecenter/{gameId}/boxscore` — which also publishes `saves` directly, so
the derived `saves` in `ingest_nhl_logs.py` (stamped `saves_derived`) should be
replaced from there. A game can have two goalies; a derivation is exactly where
that gets punished.

**The lesson, and it is the same one twice:** every "we cannot get this" here
was a statement about which publisher we asked, not about what is published.
Check the league's own API before recording a gap.

---

## 4. MLS and NCAAF — added 2026-08-06/07

Measured against the dev DB (`picks.dev.db`) 2026-08-07.

### MLS

Have: player game logs with `goals, assists, shots, sot` (16,661 rows, 100%
player_id resolved); team results 1,020 (W/D/L, 256 draws); team stats `shots,
blocked_shots` (1,020 rows); player leaders (goals/assists/shots/sot) via
`/api/mls/leaders`; team aggregates (Record + Scoring & shooting) via
`/api/mls/team-aggregates`.

| missing | in the logs? | note |
|---|---|---|
| **saves / goalsConceded / shotsFaced (GK)** | **yes — published, unmapped** | the summary publishes them per keeper (measured event 727308: Pantemis saves=2); `ingest_soccer_logs` maps only goals/assists/shots/sot. GK-saves gap flagged in MANIFEST. Needs a position-G mapping + `position_group` on log rows |
| **xG / xA / possession-adjacent player stats** | **no** | ESPN's soccer feed does not publish player xG in the summary line |
| shots_on_target / possession / corners **team** stats | **no** | soccer-native team stat columns have no schema column yet; `team_game_stats` holds shots + blocked_shots only |
| **draws on the standings surface** | yes (256 draws in results) | `/api/mls/standings` returns W/L/win_pct with no draws field, and the UI renders the generic W-L table for mls (the soccer P W D L table only renders for `isWorldCup`). **Open gap — MLS is paused with this unfixed** |

Qualifier: **NONE PUBLISHED** that this project could verify (MANIFEST records
this). No playing-time minimum is published for MLS leaderboards.

### NCAAF

Have (2026-08-07, after the FBS push): players spine 15,029 (all espn_id);
player game logs with the offense keys `att, pass_yds, pass_td, intc, rush_yds,
rush_td, rec, rec_yds, rec_td` (from the 888-game FBS regular season, REG only,
game_type NOT NULL); team results + team stats (`first_downs, total_yards,
net_passing_yards, rushing_yards, turnovers`) after backfill; conference
standings and schedule surfaces.

| missing | in the logs? | note |
|---|---|---|
| **tackles / sacks / defensive keys (DL/LB/DB)** | **yes (mapped 2026-08-07)** | `ingest_cfbd_logs` maps the defensive + interceptions categories into the stats JSON (`tackles, tackles_solo, sacks, tfl, pd, qbhur, def_td, def_int, def_int_yds, def_int_td`) — closed the gap the ESPN-summary ingest left. UI mapping of the defensive keys is a later slice |
| ~~**Army-Navy 2025-12-13 (401762521) player logs**~~ | **CLOSED 2026-08-07** | the empty passing/rushing/receiving groups were an ESPN-summary artifact — the CFBD re-source publishes the game (42 rows). PLAYER_LOG_GAP_GAMES entry removed; COV-ncaaf expects 888 logs again |
| **receiving C/ATT splits, rushing LONG, per-play EPA** | **yes (published, unmapped)** | summary publishes C/ATT, LONG, AVG; `_STAT_MAP` keeps only the nine offense keys |
| **kick returns / punt returns / FGs** | **no** | special-teams player stats not mapped |
| **playing-time qualifier** | **no** | college football publishes no per-player minimum; MANIFEST records NONE PUBLISHED |
| **CFBD as second publisher** | **yes — the NCAAF log source (2026-08-07)** | key exists; the DO-NOT-use was news-engine-only (Micah, confirmed 08-07). `ingest_cfbd_logs.py` re-sourced the 2025 FBS logs (~139 calls vs 888 ESPN summaries): ESPN game ids + athlete ids (direct spine joins, 100% resolved), defensive stats mapped, FCS buy-game players included (230 teams) |

Qualifier: **NONE PUBLISHED** that this project could verify.

### NCAAF — gate findings 2026-08-10

The COV-statset audit (`audit_league_stats.py`) grades the surfaces the task
doc calls "done". Current ncaaf row, run against `picks.dev.db`:

| check | verdict | note |
|---|---|---|
| A/required-stats[season] | **FAIL** | no `att/pass_yds/intc/rush_yds/rec/rec_yds` columns on `player_stats`; `pass_td/rush_td/rec_td` exist but 0 rows — **zero ncaaf `player_stats` rows at all** (the props/leaders acquisition gap) |
| B/position-content | PASS (all positions) | **def_int floor fixed 2026-08-10**: CFBD publishes the interceptions category only when an INT was recorded (measured: 198 of 366 game blocks), so a DB log without `def_int` is an honest zero. DB/CB/S declare `key_coverage: {def_int: 0.05}` — tackles/pd still hold the 80% floor; a total collapse to 0% interceptions still trips. Measured presence: CB 6.6%, DB 6.5%, S 7.6% |
| C/vocabulary[position] | **FAIL** | two levels of one vocabulary in `players.position`: C under OL, CB under DB, FB under RB, NT under DT, S under DB — each pair is a position and its own parent (same class of defect NBA had; needs the position_group split, see `migrate_league_position_groups.py`) |
| D/leaders-reach-logs | **FAIL** | no `player_stats` rows at all — same root cause as A |
| E/qualifier[season] | UNVERIFIED | NONE PUBLISHED — college football publishes no playing-time qualifier |
| G/published-identity | UNVERIFIED | no publisher id→name map fetched — run `fetch_identity_names.py` |

The pipeline data itself is green: COV-ncaaf passes 888/888 logs, 888 results,
137 FBS teams, 0 NULL game_type. What is missing is the **season-aggregate
surface** (`player_stats` → props tab, leaders, player season stats) — that is
an acquisition job, not an ingest-corruption job. Until it lands, those
surfaces render honest empty states by design.
