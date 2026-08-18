# Backlog — holes in the app

**Measured 2026-08-18** against `backend/data/picks.db` (prod), `backend/data/picks.dev.db`
(dev) and the live prod API. Zero ESPN requests spent.

```
venv/bin/python league_feature_matrix.py --db data/picks.db --compare data/picks.dev.db
```

Severity: **P0** a user sees it wrong today, or a shipped feature is invisible ·
**P1** a league is materially incomplete · **P2** integrity · **P3** cleanup.

## How to read this

1. **Every line is a count, and counts move.** Re-measure before working an item. Nothing
   here is a standing fact.
2. **A corrected item is REWRITTEN, not appended under.** The previous version of this file
   appended four correction passes beneath the original rows while the original rows kept
   their place in the P0 table, so a reader scanning P0 read five items of which four were
   dead. Corrections now replace the row and the old text moves to "Closed" with its date.
   The reasoning is preserved; the wrong claim is not left standing.
3. **Settlement is `actual_value IS NOT NULL`, never `settled_at`.** `settlement.py` stamps
   the timestamp on props it could not map, so a failed settlement is stored in the same
   shape as a landed one. Every "settled" figure in the pre-2026-08-18 version of this file
   counted failures as successes.
4. **Do not quote any six-figure props number from an older version of this file.** It said
   MLB settled 747,498 on dev. The entire `prop_results` table is 48,641 rows on dev today,
   with zero orphans. Those counts were real rows inflated by the duplicate-scrape defect
   (old #40): 30-minute timers inserting unconditionally into a table with no UNIQUE
   constraint. The dedupe has since run. **Every hit-rate denominator computed before it is
   wrong by roughly 15x.**

---

## P0 — wrong or invisible in production today

| # | defect | evidence | fix |
|---|---|---|---|
| 101 | **The scoreboard stalls for 60 seconds on prod.** `paced_http` answers an exhausted per-host count with `time.sleep(60)`, inside the serving process. A cold board cost 22 ESPN requests, so the ceiling arrives about every five page loads. This is what a visitor experiences as the site being broken. | prod `/api/mlb/games?date=<today>` = **60.06s** | **Fixed on dev, undeployed.** A handler refuses a spent budget; only a batch job waits. Needs a release. |
| 102 | **Prod serves no past days on the scoreboard.** `team_game_results` holds NFL only, so every other league has no finished-day rung and the board is blank behind today. | prod `?date=2026-08-15` = **0 games** | **Fixed on dev, undeployed.** `scoreboard_snapshots` plus a capture-once rung. |
| 103 | **The day arrows are dead on prod.** They asked ESPN per click, so a refusal froze the board silently. | prod `schedule-dates` = `source: unavailable` for every league | **Fixed on dev, undeployed.** Arrows answer from the store first. |
| 104 | **2,475 tennis props cannot reach a game page.** 264 of 304 prod ATP/WTA `prop_games` carry no `espn_event_id`, and the game page joins on it. This is the old #2 one layer up: the athlete spine was fixed, the linking never was. | prod atp **13.1%** linked (18/137), wta **13.2%** (22/167) | `link_prop_games.py` for atp/wta. Note `reference_espn_folds_tennis_names`: ESPN folds accents in tennis but not soccer, so a name join behaves differently per sport. |
| 105 | **Tennis settles nothing at all.** Every ATP and WTA prop on both databases has no outcome. The board shows a line and never says how it landed. | atp **0 of 2,402**, wta **0 of 2,119**, prod and dev | no grader path exists for tennis markets. Decide the markets first, then wire them. |
| 106 | **The World Cup's settled props are voids.** 392 prod / 1,128 dev `prop_results` rows with `actual_value` NULL and `hit` NULL, all stamped 2026-07-20. Every count that keys on `settled_at` reports WC at 100%. | prod 392 rows, **0** with an outcome | either grade them or record them as voids somewhere a reader can see. Do not leave a settlement count that grades nothing. |
| 107 | **UFC settles 112 on prod and 0 on dev.** Dev has no UFC `prop_results` rows at all. This is the dev/prod skew running backwards, and it means a green dev suite says nothing about UFC settlement. | prod 112/120 (93%), dev **0/336** | run settlement against dev. Until then treat any dev-only UFC result as unmeasured. |
| 108 | **`/scores` previous-day navigation is broken on prod.** Reported 2026-08-14. | prod, unverified end to end | **Fixed on dev 2026-08-18**, undeployed. Rides on the same release as 101 to 103. |

**101, 102, 103 and 108 are one release.** Nothing else in this file is closer to shipped.

---

## P1 — a league is materially incomplete

| # | defect | evidence | fix |
|---|---|---|---|
| 110 | **Prod MLS game logs are half of dev's.** | prod **10,603** / dev **21,177** | promotion job, no deploy needed |
| 111 | **MLS has no game stories on prod.** | prod **0** / dev 30 | as 110 |
| 112 | **MLS leaders lag standings by a season.** Standings serve live 2026; the leaders endpoint offers only 2025, so two surfaces on one league disagree about what year it is. | `/api/mls/leaders` → `available_seasons: [2025]` | ingest 2026 MLS season stats |
| 113 | **UFC prop links regressed on DEV.** The old row said prod 24/25 and dev 0/36, which named the wrong healthy database for today. | prod **97.1%** (33/34), dev **25.5%** (12/47) | relink dev. Prod's correct links are an **oracle to grade a matcher against**, not rows to copy: `prop_games.id` is not shared and a date-plus-fighters join is an ambiguous key. |
| 114 | **NFL, MLS and NCAAF have zero `scoring_plays`.** Only NBA, MLB and NHL fill it. | prod: nba 2,386, mlb 759, nhl 16, everything else 0 | the boxscore snapshot only ever ran for nba/nhl/mlb. Confirm the publisher has them before recording it as a gap. |
| 115 | **`game_context` is empty everywhere.** 14 rows across three leagues on prod. It reads as a populated surface and is not one. | prod: mlb 8, nba 4, nhl 2 | decide whether this is a product surface or delete it |
| 116 | **`prop_games` has no `status` column**, so the board cannot tell postponed from started. This blocks the decided rule of dropping props at kickoff: applied naively it would silently delete a postponed game whose props are still live. | schema: `id, league, date, home, away, espn_event_id, final_home, final_away, start_time` | add a nullable `status`, populate from the linked `espn_event_id`. Additive, so it does not outrun prod's frozen code. |
| 117 | **The tennis spine decays by design.** It is the top 150 per tour, and a tournament field is not the rankings: it includes qualifiers, wildcards and returning players. The overlap drops as the tour moves to Challengers and qualifying. | ESPN's `atp\|wta/scoreboard` publishes 263 to 328 distinct athletes for one event, against 150 from rankings, for the same 2 requests | swap `ingest_tennis_players.py` from rankings to the tournament scoreboard, on a timer ahead of the props scrape |
| 118 | **Surname-first names never resolve.** Folding diacritics and case does not touch word order. Not tennis-only. | Bovada "Xinyu Wang" vs ESPN "Wang Xinyu"; MLS "Kim Kee-Hee" | one fix in `_resolve_player_for_ingest`, not per league |

---

## P2 — integrity

| # | defect | evidence | fix |
|---|---|---|---|
| 120 | **1,121 players have a game log and a blank `position`.** Position decides which columns a game log renders, so a blank one renders a generic or wrong table. **MLB is now the whole problem**: NCAAF was 5,897 and is 176. | prod: mlb **767**, ncaaf 176, ufc 68, wc 61, nba 47, mls 2 | MLB's 767 is likely the same population as the known Statcast-only rows. Confirm that before treating it as a backfill. |
| 121 | **815 players have a log and a blank `team`.** Unchanged since 08-12. | prod 815 / dev 808 | same shape as 120 |
| 122 | **230 players (prod) have props and no game log.** Their prop chart cannot render: a line with no history behind it. | prod 230 / dev 276 | separate genuinely pre-debut from missing-a-log. Only the second is a defect. |
| 123 | **78 props point at a `players.id` that does not exist.** Identical on both databases, so it is old and static. | prod 78 / dev 78 | part of the 168 pre-existing orphans (props 78, roster_snap 90) |
| 124 | **`player_stats` has a second column family.** `att`/`rec` duplicate `attempts`/`receptions` and the two are perfectly disjoint, so any cross-league query silently NULLs for one of them. | ncaaf `att` 799 / `attempts` **0**; nfl `att` **0** / `attempts` 81 | migrate ncaaf into the existing columns. **`pass_yds` (season) is NOT a duplicate of `pass_yds_g` (per game). Do not consolidate those.** |
| 125 | **`atp`, `wta` and `wnba` have no MANIFEST entry** (`audit_league_stats/cli.py:22`, 8 keys). The audit only fails a missing entry for a league that serves `player_stats`, and these three serve zero, so **the audit stays green by never asking**. WNBA does not exist in either database at all. | 8 of 11 leagues covered | write the entries, or record explicitly that these leagues have no season-stat surface |
| 126 | **576 duplicate prop groups remain on prod**, 70 on dev. The mechanism is fixed (the ingest endpoint upserts) and the bulk dedupe has run; this is the tail. | `(game_id, player_id, market, line, side, source)` groups with >1 row | per-league dedupe keeping `MAX(id)` |
| 127 | **38 shadow MLS players on prod**, 33 on dev. No `espn_id`, duplicates of athletes already in the spine. Was 531 on prod. | `players` where league='mls' and espn_id IS NULL | `merge_mls_prop_players.py --apply`. Writing to prod needs authorisation. |
| 128 | **NCAAF `C/vocabulary[position]`**: two levels of one vocabulary in one column (`C` under `OL`, `CB`/`S` under `DB`). | gate FAIL, MLS reported not blocking | position_group split pattern |
| 129 | **The esports board buckets by start time**, so a match that ends late lands on the wrong day. Same class as the props-board defect, different surface. | `pages/esports.tsx`, `localDateKey(m.startTime)`; the slate payload carries no end time | `docs/TASK-esports-local-day-endtime.md`: add an end time, group finished matches by it |
| 130 | **`roster_season()` infers a season from a timestamp** with a hardcoded month rule. Same class as the `_SEASON = {"mls": 2025}` constant that served last year's squads all season. | `roster_membership.py:218` | read the published current season |

---

## P3 — cleanup

| # | defect | evidence | fix |
|---|---|---|---|
| 140 | **MLB `team_game_stats` is 16 rows** against 3,364 game-detail rows, with no populated stat column. Reads as a league with team stats and is not one. | prod 16 rows | give MLB a `STAT_FIELDS` entry and backfill, or delete the 16 |
| 141 | **`team_game_stats` frozen columns not dropped.** The JSON migration is dual-write and prod is not backfilled. | `b227781` | backfill prod, then drop roughly 45 columns |
| 142 | **0-byte `data/picks.dev.db` at the repo root.** A backend launched from the repo root with a relative `LP_DB_PATH` opens it, starts fine and serves nothing. Still present, dated 2026-08-14. | 0 bytes | delete |
| 143 | **Three transient systemd units** under `/run/systemd/transient/`, including the dev tunnel. None survive a reboot. | `legendarypicks-dev-tunnel`, two mls-ncaaf candidates | write persistent units, or accept and write down that a reboot takes the tunnel |
| 144 | **Prod's frontend proxies `/api/*` to `127.0.0.1:8000` inside its own container**, where nothing listens. Harmless only because nginx routes `/api/` straight to `:8100` and never uses that path. A trap for anyone testing the container directly. | `docker logs legendarypicks-frontend-1` → `ECONNREFUSED` | point the rewrite at the compose service name |
| 145 | **`link_prop_games` fetches 3 neighbour days per slate.** A date-range scoreboard request would make MLS 1 request instead of 12. | `b8886e9` states the spend | confirm ESPN's `dates=` range parameter. Measure it once, when the host is answering. |
| 146 | **Tennis start times are partly bucketed placeholders.** Improved but not gone: a session start is still being stored as a match time for some rows. | 2026-08-19: 3 prod rows share exactly `15:00`, against real per-match times like `00:10` and `00:30` on the same day | the tournament scoreboard (117) publishes per-match times |

---

## Closed, with the evidence that closed them

Kept so they stop being re-raised. Old numbers are shown so the correction is legible.

| was | closed | now |
|---|---|---|
| **#1 Prod has zero news.** `news_items` empty for every league. | 2026-08-17, remeasured 08-18 | **5,526 rows on prod** across 9 leagues, newest minutes old. Dev 8,183. The credential was present the whole time under a different spelling (`BLSKY_PASS`) and a single-spelling lookup reported "no credential" with the value in the file. |
| **#2 / #20 / #41 Tennis discards a working feed.** ATP/WTA `prop_games` were empty shells, 0 props, and `props-prod` exited 3 every 30 minutes. | 2026-08-17 | **2,402 ATP + 2,119 WTA props on prod.** 150 per tour ingested from ESPN rankings in 2 requests. Superseded by 104, 105 and 117: the spine exists, the linking and settlement do not. |
| **#4 MLS props unreachable, 2 of 15 linked.** | 2026-08-14 | prod **96.4%**, dev **100%**. The cause was never "ESPN is down": it was a vocabulary gap, Bovada and ESPN spelling 8 of 13 clubs differently. |
| **#5 MLB prop links incomplete, 564/610.** | 2026-08-18 | prod **99.3%** (610/614). |
| **#6 MLS is HIDDEN on prod.** No coverage row, no team results, no team stats. | 2026-08-18 | fully visible: coverage vouched 30/30 teams and 510/510 games, 1,020 team results, 1,020 team stats, live 2026 standings. |
| **#7 MLS has no season stats on either DB.** Called "the only genuine acquisition gap". | 2026-08-17 | prod **851**, dev **850**. |
| **#21 MLB settled props unreachable on game detail.** | 2026-08-14, again 08-18 | misread its own number then, and its scale is now void. prod **52,301 of 52,492 reachable**. |
| **#22 UFC props never settle.** "0 settled on either." | 2026-08-18 | prod **112 of 120**. Survives inverted as 107: dev settles zero. |
| **#23 MLS props never settle.** 714 props, 0 settled. | 2026-08-16 | prod **718 of 2,207**. The blocker was never the settlement path: MLS logs carried 4 stats, so a card prop had nothing to grade against. |
| **#24 UFC/MLS/NCAAF/WC have no game story.** | 2026-08-14 | the generator was never the problem. `scripts/game-recaps.sh` already passed `mls` and `lcup`; the sweep had been dying on a `NameError` on its first MLB game every three hours since 08-12. MLS-on-prod survives as 111. |
| **#26 6,818 players with a log and a blank position**, NCAAF 5,897. | 2026-08-18 | **1,121 total**, NCAAF **176**. Survives as 120, where MLB's 767 is now the whole problem. |
| **#40 `props` holds 47,827 duplicate groups.** | 2026-08-18 | **576 on prod, 70 on dev.** The mechanism was fixed at the endpoint; the bulk dedupe has since run. See "How to read this" note 4: this is why every older count in this file is wrong by roughly 15x. |
| **#42 531 shadow MLS players on prod.** | 2026-08-18 | **38.** Survives as 127. |
| **#45 The props board served games that had already finished.** Two rulers on one board, a UTC filter against a local-date display. Shipped 2026-07-17 and invisible for a month. | 2026-08-18 | **0 of 49** slate games on prod started more than 3 hours ago. v0.8.1 carried the fix. |
| **#47 Tennis start times are bucketed placeholders**, 13 of 15 sharing `15:00:00Z`. | partly, 2026-08-18 | real per-match times now appear alongside a smaller bucket. Survives as 146. |
| **NBA 269 split identities.** | 2026-08-05 | 0 splits on both databases by the script's own definition. |

---

## Not defects — recorded so they stop being re-raised

- **NFL, NBA and NHL have no props in August.** Out of season. NCAAF's board opens Aug 29.
- **NCAAF is hidden by decision** (Micah, 2026-08-11), not by absence. It is OFFERED on both
  databases now, so `league_feature_matrix.py`'s docstring citing it as the hidden example
  is stale.
- **`scoring_plays` / `game_context` only fill for games captured live**, so a league
  backfilled by season will always read empty there. That is the reason 114 and 115 need a
  decision rather than a backfill.
- **UFC and WC have no `team_stats_coverage` row by design.** Not team-stats leagues.
- **Fullbacks are not a fantasy position.** The `{QB,RB,WR,TE}` filter in
  `ingest_nfl_season_stats.py:29` is correct. Kicker, defense and FLEX **are** fantasy
  positions and the draft board already offers them; FB is the outlier.
- **Draft research is shipped.** The draft board, the four-tab player detail overlay and the
  mock draft simulator are all live on prod.

---

## What this file cannot tell you

Every figure above is a database or prod-API claim. **None of it proves a page renders.**
Rows are necessary and not sufficient, and the gap between "we hold it" and "a reader sees
it" is exactly where 104, 106 and 121 live. See `.claude/skills/honest-data-ui`.

The ESPN-backed surfaces (standings, scoreboard, live game state) are **UNPROBED** here on
purpose. The budget is a count per host, and on 2026-08-18 two concurrent backfills spent it
twice over and took all three ESPN hosts from answering to refusing. Absent evidence is not
a zero.
