# Backlog: holes in the app

**Measured 2026-08-20** against `backend/data/picks.db` (prod), `backend/data/picks.dev.db`
(dev) and the live prod API. Zero ESPN requests spent.

**Where this file sits.** `docs/ROADMAP.md` is what we intend to build. This file is what is
measurably broken. Both funnel into `CHANGELOG.md`, which is the only history of record, and
`scripts/release.sh` generates the GitHub release notes from it. **A fixed item moves to
"Closed" here and gets a CHANGELOG entry; it does not accumulate in a separate archive.**

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

## P0: wrong or invisible in production today

| # | defect | evidence | fix |
|---|---|---|---|
| 104 | **913 tennis props cannot reach a game page in managed data.** 274 of 325 prod ATP/WTA `prop_games` carry no `espn_event_id`, and the game page joins on it. **The 2026-08-18 figure of 2,475 props was not reproducible on 08-20** and is not explained by the 08-19 dedupe alone; re-measure before quoting a tennis number. | prod tennis `prop_games` **51 of 325 linked (16%)**; current dev (2026-08-21) **53 of 63 linked**, or **907 of 1,017 props**. Candidate `7ca4fbb` clone reached **1,017 of 1,017** after six known duplicate fixtures folded into their existing event rows. | land and remeasure on a clone before any managed-data run. The linker uses resolved ESPN athlete IDs plus an exact two-name fallback only when it identifies one event; it does not fuzzy-match. |
| 105 | **Tennis settles nothing at all in managed data.** Every ATP and WTA prop on both databases still has no outcome. The board shows a line and never says how it landed. | prod atp **0 of 536**, wta **0 of 377**; current dev atp **0 of 556**, wta **0 of 461**. Candidate clone holds **913 numeric results of 1,017** from normal final scores (including two legitimate pushes); 58 are pre-match, and 46 are one retirement plus two walkovers with no authoritative sportsbook settlement rule. | land and clone-rehearse the grader, then run only linked normal final games. Keep retired/walkover source results retryable and visibly counted; do not stamp null rows as settlements or invent a void policy. |
| 106 | **The World Cup's settled props are voids.** 392 prod / 1,128 dev `prop_results` rows with `actual_value` NULL and `hit` NULL, all stamped 2026-07-20. Every count that keys on `settled_at` reports WC at 100%. | prod 392 rows, **0** with an outcome | either grade them or record them as voids somewhere a reader can see. Do not leave a settlement count that grades nothing. |
| 107 | **UFC settles 112 on prod and 0 on dev.** The dev/prod skew running backwards: a green dev suite says nothing about UFC settlement. **Correction to the 08-18 row, which said dev has no UFC `prop_results` rows at all:** dev now holds 466 UFC props and settles none of them. | prod **112 of 142** (79%), dev **0 of 466** | run settlement against dev. Until then treat any dev-only UFC result as unmeasured. |

| 109 | **NFL props settle zero.** 1,080 on prod and 1,082 on dev, all from the 2026-08-19 RotoWire relay, none graded. New since the last measurement and the largest unsettled block outside tennis. **The props exist and look healthy on the board**, which is what makes it a P0 rather than a P1. | prod **0 of 1,080** settled | confirm the grader has a mapping for the relay's NFL markets. A book pricing a market our grader cannot map produces props that land, look fine and never grade. |

**The scoreboard block (old 101, 102, 103, 108) shipped in v0.8.2.** See Closed.

---

## P1: a league is materially incomplete

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

## P2: integrity

| # | defect | evidence | fix |
|---|---|---|---|
| 120 | **1,121 players have a game log and a blank `position`.** Position decides which columns a game log renders, so a blank one renders a generic or wrong table. **MLB is now the whole problem**: NCAAF was 5,897 and is 176. | prod: mlb **767**, ncaaf 176, ufc 68, wc 61, nba 47, mls 2 | MLB's 767 is likely the same population as the known Statcast-only rows. Confirm that before treating it as a backfill. |
| 121 | **815 players have a log and a blank `team`.** Unchanged since 08-12. | prod 815 / dev 808 | same shape as 120 |
| 122 | **230 players (prod) have props and no game log.** Their prop chart cannot render: a line with no history behind it. | prod 230 / dev 276 | separate genuinely pre-debut from missing-a-log. Only the second is a defect. |
| 123 | **78 props point at a `players.id` that does not exist.** Identical on both databases, so it is old and static. | prod 78 / dev 78 | part of the 168 pre-existing orphans (props 78, roster_snap 90) |
| 124 | **`player_stats` has a second column family.** `att`/`rec` duplicate `attempts`/`receptions` and the two are perfectly disjoint, so any cross-league query silently NULLs for one of them. | ncaaf `att` 799 / `attempts` **0**; nfl `att` **0** / `attempts` 81 | migrate ncaaf into the existing columns. **`pass_yds` (season) is NOT a duplicate of `pass_yds_g` (per game). Do not consolidate those.** |
| 125 | **`atp`, `wta` and `wnba` have no MANIFEST entry** (`audit_league_stats/cli.py:22`, 8 keys). The audit only fails a missing entry for a league that serves `player_stats`, and these three serve zero, so **the audit stays green by never asking**. WNBA does not exist in either database at all. | 8 of 11 leagues covered | write the entries, or record explicitly that these leagues have no season-stat surface |
| 127 | **38 shadow MLS players on prod**, 33 on dev. No `espn_id`, duplicates of athletes already in the spine. Was 531 on prod. | `players` where league='mls' and espn_id IS NULL | `merge_mls_prop_players.py --apply`. Writing to prod needs authorisation. |
| 128 | **NCAAF `C/vocabulary[position]`**: two levels of one vocabulary in one column (`C` under `OL`, `CB`/`S` under `DB`). | gate FAIL, MLS reported not blocking | position_group split pattern |
| 129 | **The esports board buckets by start time**, so a match that ends late lands on the wrong day. Same class as the props-board defect, different surface. | `pages/esports.tsx`, `localDateKey(m.startTime)`; the slate payload carries no end time | `docs/TASK-esports-local-day-endtime.md`: add an end time, group finished matches by it |
| 130 | **`roster_season()` infers a season from a timestamp** with a hardcoded month rule. Same class as the `_SEASON = {"mls": 2025}` constant that served last year's squads all season. | `roster_membership.py:218` | read the published current season |

---

## P3: cleanup

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
| **MLB pitching stats empty on prod.** `player_stats` had `innings`, `era` and `whip` present as columns with **0 rows populated**, while dev held 735/734/734. Never a numbered row here; it surfaced as a BLOCKING gate FAIL on the v0.8.5 dry run. | 2026-08-20, before v0.8.5 | prod **784 / 783 / 783**. Fixed by re-ingesting from `statsapi.mlb.com` (`ingest_mlb_counting_stats.py --season 2026`), not by copying dev: 784 pitching and 697 batting rows updated, 0 created, 0 rejected. **This gate had been silently skipped since the 08-18 split**, so v0.8.2 and v0.8.3 were both cut without it running. v0.8.5 is the first release it spoke on, and it caught this. |
| **#101 / #102 / #103 / #108 The scoreboard block.** 60-second stall on prod, zero games behind today, dead day arrows, broken previous-day navigation. Written 08-18 as "fixed on dev, undeployed". | 2026-08-18, shipped v0.8.2; re-measured on prod 2026-08-20 | `/api/mlb/games?date=<today>` **60.06s to 0.10s** (9 games); a past day **0 to 15 games**; `schedule-dates` `source=unavailable, available=false` to `source=local, available=true` with `future_event_starts` populated. |
| **#126 576 duplicate prop groups on prod, 70 on dev.** | 2026-08-19 dedupe, verified 08-20 | **0 on both**, keyed `(game_id, player_id, market, line, side, source)`. Prod props 62,835 to 58,480, dev 69,069 to 68,697. **Beware the measurement:** dropping `source` from that key reports 240 groups on prod and 1,085 on dev, but those are `rotowire:prizepicks`, `sleeper` and `underdog` quoting one line. Three books is not a duplicate. |
| **Prod's props ingest was 500ing: `database is locked`.** `props-prod` exited 3 with "2 of 14 mlb games failed to POST" every 30 minutes. Never reached this file as a numbered row; recorded here because the cause generalises. | 2026-08-19, deployed in the 23:13 rebuild | **Prod was `journal_mode=delete` while dev was `wal`.** Under `delete` a writer locks the whole database and every reader waits, so prod serialised its API reads, the per-minute snapshot writer and the props ingest; **dev could never reproduce it**. Prod is now WAL with a 30s busy timeout. **Not fully closed:** every props run since the flip has been a quiet evening slate, so watch a daytime slate before believing it. |
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

## P4: carried from the old roadmap Ledger, ALL UNVERIFIED

Thirty unchecked items (`B1`-`B16`, `M1`-`M7`, `R1`-`R9`) spent weeks underneath a `# Ledger`
heading whose own rule said "history, do not rewrite", so open work was sitting in the history
section and stopped being read. They belong here, not in the roadmap, because this is the file
for things that may be broken.

**None has been re-measured. Most predate 2026-08-11.** Do not treat this as a list of
confirmed defects, and do not treat it as noise either: `B8` is user-reported. Rule 1 at the
top of this file applies with force.

**Full original text:** `git show 0d2ec7c:docs/ROADMAP-ARCHIVE.md`. That commit is the last
one that carried the archive as a file; it was removed afterwards because `CHANGELOG.md` is
the history of record and a second archive competes with it.

| # | carried item | why it is here |
|---|---|---|
| 150 | **B8. The player page renders the wrong game-log columns for K and D/ST.** | **User-reported.** A kicker's log showing skill-position columns is visibly wrong to the one person who has used this. |
| 151 | **B8 (mock-draft series). Kicker game data does not exist; Brandon Aubrey renders a false figure.** | A fabricated number is worse than a blank (`project_lp_honest_data_ui`). |
| 152 | **B15. `adp: p.adp ?? 999` fabricates an ADP in the UI.** | Same shape as 151: the UI invents a value the data does not have. |
| 153 | **R7. Player search on the draft board.** | Marked user-blocking when written. |
| 154 | **B1.** Mid-season team change doubles the availability denominator. | Availability is a headline number on the draft board. |
| 155 | **B2.** `team_game_results` has two incompatible key schemes. | Same class as the `prop_games.date` two-convention defect that reached prod. |
| 156 | **B3.** Team abbreviations disagree between tables. | `reference_lp_team_code_vocabularies`: a wrong join key misses silently. |
| 157 | **B7.** `players.nfl_gsis_id` mixes two id schemes. | Same class as 156. |
| 158 | **B9.** `players.position` has the same two-vocabulary split as `players.team`. | Overlaps 128 and 120. Check whether they are one defect. |
| 159 | **B10.** Playoff rows in `player_game_logs` are unmarked. | `project_lp_nhl_three_player_types` is the same shape: a playoff row served as a season row. |
| 160 | **B11.** D/ST ADP is published; we derived it instead. | `feedback_check_if_the_value_is_published`. |
| 161 | **B14.** `team_games` absent from the mock-draft pool payload. | Small, per its own note. |
| 162 | **M2.** Availability computed from a table that cannot express it. | Was marked blocking for mock draft v1. |
| 163 | **B4 / B5 / B6 / B16.** Four gate and test items: three red draft-board tests, `test_league_stats_contract` failing, the 16-row NFL cleanup not reproducible, two jest suites with no gate. | Rule 6 of the roadmap: a check that stays green by not being asked. B16 is exactly that. |

**Product decisions, not defects, so they stay in the roadmap:** `R5` (`--all-positions` for
IDP and kickers), `R9`/`R8` (accounts and draft notes), `M3`-`M7` (mock-draft UX). Those need
Micah, not a measurement.

---

## Not defects: recorded so they stop being re-raised

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
