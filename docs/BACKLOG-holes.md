# Backlog — holes in the app

Generated from `backend/league_feature_matrix.py` + the audit run of 2026-08-11/12.
Re-run the matrix before working any item; every line here is a measured count, not
a guess, and counts move.

```
venv/bin/python league_feature_matrix.py --db data/picks.db --compare data/picks.dev.db
```

Severity: **P0** users see it wrong today · **P1** a shipped feature is empty ·
**P2** a league is incomplete · **P3** cleanup.

---

## P0 — wrong or misleading in production

| # | defect | evidence | fix |
|---|---|---|---|
| 1 | **Prod has zero news.** `news_items` empty for every league; the news engine is v0.8.0's headline feature. | prod 0 rows / dev 3,908 | run the collector against prod, or promote `news_items` |
| 2 | **Tennis discards a working feed.** Bovada serves ATP/WTA markets, the parser reads them, and every prop is dropped because `players` has **no atp/wta rows**. Swiatek rejected 244×, Gauff 238×. | 169 in `unresolved_players`; 101 `prop_games`, 0 props | ingest a tennis athlete spine (`espn_client` already has `atp`/`wta`) |
| 3 | **UFC prop links regressed on dev.** Same fights as prod with `espn_event_id` blanked, so props never reach a game page. | prod 24/25 linked, dev **0/36** | copy from prod (careful: no shared `prop_games.id`, join is date+fighters = ambiguous key) or relink when ESPN recovers |
| 4 | **MLS props unreachable.** 714 props across 15 games; only 2 games carry an `espn_event_id`. Matcher fixed (`b8886e9`), rows not yet linked. | 2/15 both DBs | `link_prop_games.py --league mls` once `site.web.api` recovers |
| 5 | **MLB prop links incomplete.** | prod 564/610, dev 656/723 | same relink path |

## P0 — product surfaces (added 2026-08-12, from the surface pass)

Rows in a table do not prove a page works. These are the surfaces a user opens.

| # | defect | evidence | fix |
|---|---|---|---|
| 21 | **MLB: 57,392 settled props unreachable on game detail (dev).** The page joins on `espn_event_id`; a settled prop on an unlinked game exists and is invisible. **Prod is clean** (659,108 / 659,108), so dev regressed. | dev 688,858 settled / 631,466 reachable | relink the unlinked `prop_games`; same root cause as #3 |
| 22 | **UFC props never settle.** 252 props on dev, 102 on prod, **0 settled on either**. The board shows lines and never says how they landed. | `prop_results` empty for ufc | settlement path exists (WC settles 1,128/1,128) — wire ufc into it |
| 23 | **MLS props never settle.** 714 props, **0 settled**. Same shape as #22. | `prop_results` empty for mls | as #22 |
| 24 | **UFC/MLS/NCAAF/WC have no game story.** No recap, no preview. | `game_story` 0 | the story generator is wired for mlb/nba/nfl/nhl/wc only |
| 25 | **MLS player game logs are half-promoted.** 878 players with a log on dev, 358 on prod. | prod 358 / dev 878 | part of #6's promotion |

### Corrected 2026-08-14 — measured, and rows 3/4/21/22/23/24 were partly wrong

Rows kept as written; these supersede them. The prescriptions in 3, 4 and 22 would
each have sent the next person somewhere that does not work.

- **#3, #4 — "when ESPN recovers" / "once `site.web.api` recovers" was never the
  blocker.** `site.web.api.espn.com` answers 200 and is the host the linker uses
  (`espn_client.py:97`); `sports.core.api` is the 403 one and the linker never
  touches it. **MLS is now 15/15 linked** (`025ee05`). The real cause was a
  vocabulary gap: Bovada and ESPN spell 8 of 13 clubs differently ("New York Red
  Bulls"/"Red Bull New York", "DC United"/"D.C. United", "Los Angeles FC"/"LAFC",
  five dropped FC/SC/CF suffixes). A second one in the MLB map — `CWS` in a repo
  that is canonically `CHW`, plus a retired `OAK` — is fixed in `ece6b9d`.
- **#3 — UFC is not a copy-from-prod job.** Its scoreboard enumeration is the wrong
  shape: `espn_client.games('ufc', '2026-08-16')` returns **zero** events for a date
  carrying a full card, because a card is one event containing many fights rather
  than many events on a date. Prod's 33 correct links are useful as an **oracle** to
  grade a new matcher against, not as rows to copy.
- **#21 misreads its own number.** MLB settles 747,498 on dev and 690,106 of those
  ARE reachable — 57,392 is the 7.7% remainder, not the whole. MLB is the healthiest
  league here, not a regression.
- **#22's fix instruction is the dangerous one: "WC settles 1,128/1,128" is false.**
  `settlement.py` stamps `settled_at` on a prop it could not map and leaves `hit`
  and `actual_value` NULL, so a failed settlement is stored in the same shape as a
  landed one. Every count of "settled props" in this document counted failures as
  successes. Requiring a real outcome:

  | league | rows with `settled_at` | rows with a real outcome |
  |---|---|---|
  | wc | 1,128 | **0** |
  | mlb (dev) | 747,498 | 642,348 |
  | mlb (prod) | 700,549 | **421,145** |

  **MLB is the only league that settles anything.** There is no working WC path to
  wire UFC or MLS into. `league_feature_matrix.py` now requires `hit IS NOT NULL`
  (`f1604e6`); the write side is open.
- **New, and it gates 22 and 23:** an unmappable prop is currently **unsettleable
  forever**. `settle_props.py` selects games `HAVING settled_props < total_props`
  against `prop_results`, so a prop stamped with a NULL outcome is permanently
  excluded from retry — adding the market mapping it lacked will not bring it back.
- **#24 — the generator was not the problem, a crash was.** `scripts/game-recaps.sh`
  already passed `mls` and `lcup`. The sweep had been dying with a `NameError` on
  its first MLB game every three hours since `25391c7` (08-12) left three modules
  reaching for names they never imported, so nothing after MLB ever ran. Fixed in
  `8c63459` and `39063a0`; recaps resumed immediately (mlb 531→541, nfl 26→33,
  lcup +1). Previews remain genuinely unwired — nothing generates them on a timer.
- **ATP and WTA are empty shells**, not partial coverage: 206 `prop_games` between
  them and **zero** `props`. Both HIDDEN, so not release-blocking.

## P1 — shipped or shipping, but empty

| # | defect | evidence | fix |
|---|---|---|---|
| 6 | **MLS is HIDDEN on prod** — no coverage row, no `team_game_results`, no `team_game_stats`. Dev has all three. Release calls out MLS. | prod ✗/dev ✓ on 3 rows | promote coverage + team tables + 10.5k logs + 352 players |
| 7 | **MLS has no season stats on either DB.** The only genuine *acquisition* gap in the set — nothing publishes into `player_stats` for MLS. | 0 / 0 | pick a publisher; ESPN summary has keeper saves/goalsConceded unmapped |
| 8 | **NCAAF `league_stats.py` contract never landed in main.** Dev holds 4,267 rows its own code calls unsupported; `COV-identity` FAILs on dev. | worktree has 4 ncaaf hunks, main has 0 | land the hunk from `/root/lp-league-mls-ncaaf` |
| 9 | **NCAAF standings function is worktree-only**, and derives `rank` from array position while discarding the publisher's stat values (reads `displayValue`). | `ncaaf_conference_standings()` | land + re-read `stats[]` names when ESPN is up |

## P2 — league incompleteness

| # | defect | evidence | fix |
|---|---|---|---|
| 10 | **`player_stats` second column family.** `att`/`rec` duplicate `attempts`/`receptions`; cross-league queries silently NULL for ncaaf. `pass_yds` (season) is NOT a dup of `pass_yds_g` (per-game) — do not "consolidate" those. | disjoint: nfl 81/527, ncaaf 799/3,018 | migrate ncaaf into the existing columns; document the per-game/season split |
| 11 | **NCAAF `C/vocabulary[position]`** — two levels of one vocabulary in one column (`C` under `OL`, `CB`/`S` under `DB`). | gate FAIL | position_group split pattern |
| 12 | **NCAAF `G/published-identity` UNVERIFIED** — no publisher id→name map fetched. | gate UNVERIFIED | `fetch_identity_names.py` when ESPN is up |
| 13 | **NFL has no `scoring_plays` / `game_context`** — game detail leans entirely on the DB-first final (`405ebe8`). Same for MLS and NCAAF. | ✗ on both DBs | boxscore snapshot only ever ran for nba/nhl/mlb |
| 14 | **WC has no coverage row** and no game detail; offered via the ALWAYS_OFFERED shape exception. | ✗/✗ | decide whether WC is still a product surface |

## P2 — integrity sweep (added 2026-08-12)

| # | defect | evidence | fix |
|---|---|---|---|
| 26 | **6,818 players have a game log and a blank `position`.** Position drives which columns a game log renders — a QB's passing line vs a WR's receiving line — so a blank one renders a generic or wrong table. Worst by far is NCAAF at **5,897 (49% of its players)**. | prod: ncaaf 5,897, mlb 767, wc 61, nba 47, ufc 45, mls 1 | backfill from the publisher that already prints it; MLB's 767 may be the same population as the known Statcast-only rows |
| 27 | **550 players (prod) / 262 (dev) have props but no game log.** Their prop chart cannot render — the page offers a line with no history behind it. | measured both DBs | confirm how many are genuinely pre-debut vs missing a log; only the second group is a defect |
| 28 | **78 props point at a `players.id` that does not exist.** Same count on both databases, so it is old. | prod 78 / dev 78 | already on the roadmap as "168 pre-existing orphans (props 78, roster_snap 90)" — still 78 |
| 29 | **815 players have a log and a blank `team`.** | prod | same shape as #26 |

## P3 — cleanup

| # | defect | evidence | fix |
|---|---|---|---|
| 15 | **MLB `team_game_stats` is 16 rows** against 3,364 game-detail rows, and carries no populated stat column. Reads as a league with team stats; isn't one. | 16 rows, skipped by the JSON migration as UNVERIFIED | either give MLB a `STAT_FIELDS` entry and backfill, or delete the 16 |
| 16 | **`team_game_stats` frozen columns not yet dropped.** JSON migration is dual-write; prod is not backfilled. | `b227781` | backfill prod, then drop ~45 columns |
| 17 | **0-byte `data/picks.dev.db` at repo root.** A backend launched from the repo root with a relative `LP_DB_PATH` opens it, starts fine, serves nothing. | 0 bytes, created 2026-08-11 16:37 | delete |
| 18 | **`:8105` unit is transient** (`/run/systemd/transient/`) — will not survive a reboot. | `systemctl cat` | write a persistent unit, or accept it |
| 19 | **`link_prop_games` fetches 3 neighbour days per slate.** A date-range scoreboard request would make MLS 1 request instead of 12. | `b8886e9` states the spend | confirm ESPN's `dates=` range param when the host is up |
| 20 | **ATP/WTA `prop_games` are empty shells** — 101 rows, 0 props, no players. They exist only to make the linker spend requests. | see #2 | resolved by #2, or stop creating the rows |

---

## Not defects — recorded so they stop being re-raised

- **NFL/NBA/NHL have no props in August.** Out of season. NCAAF's board opens Aug 29.
- **NCAAF is hidden by decision** (Micah, 2026-08-11), not by absence. See
  `/root/lp-league-mls-ncaaf/.ralph/request.md`.
- **`scoring_plays`/`game_context` only fill for games captured live**, so a league we
  backfilled by season will always read ✗ there.
- **UFC/WC have no `team_stats_coverage` row by design** — not team-stats leagues.

---

## Added / closed 2026-08-16 — the MLS props pass

Rows above are kept as written. These supersede where they overlap.

### Closed

| # | was | now |
|---|---|---|
| 23 | **MLS props never settle.** 714 props, 0 settled. | Settlement grades `goals` (0.5/1.5/2.5), `assists`, `card_shown`, `goal_or_assist` and `first_goal_scorer`. The blocker was never the settlement path — it was that MLS logs carried 4 stats, so a card prop had nothing to grade against. |
| — | **MLS props were a one-off.** 714 props captured 08-07..08-09, nothing refreshed them. | `mls` was absent from `bovada_scraper.LEAGUES`; the `all` timer covers it now with no new unit. 1,542 props, refreshed every 30 min. |

### New

| # | severity | defect | evidence | fix |
|---|---|---|---|---|
| 40 | **P0** | **`props` holds 47,827 duplicate groups.** `/api/props/ingest` INSERTed unconditionally into a table with no UNIQUE constraint while the scrapers run on 30-minute timers. Every hit-rate denominator counts the same prop once per scrape. | dev: 47,827 `(game_id, player_id, market, line, side, source)` groups with >1 row | **Mechanism fixed** (the endpoint upserts). The existing duplicates are NOT cleaned — MLS was deduped, no other league was. Needs a per-league dedupe keeping MAX(id). |
| 41 | **P1** | **Tennis now fails the timer loudly.** `atp` resolves 0 of 171, `wta` 0 of 139, every 30 minutes. This is row 2, unchanged — but the scraper exits 3 now, so `legendarypicks-props.service` is RED until a tennis spine exists. | `systemctl status legendarypicks-props.service` → exit-code 3 | ingest an atp/wta athlete spine (row 2), or the unit stays red. **Do not silence it by reverting the exit code** — that is the state the feed has always been in. |
| 42 | **P2** | **531 shadow MLS players on PROD.** No `espn_id`, no game logs, props attached; duplicates of athletes already in the spine. Dev repaired (183 → 0). | prod `players` where league='mls' and espn_id IS NULL: 531 | run `merge_mls_prop_players.py --db data/picks.db --apply` (blocked: needs authorisation to write prod) |
| 43 | **P2** | **Prod MLS/NCAAF repairs never applied.** Prod still has 0 MLS `player_stats`, the 159 team-entity rows mislabeled as active players, and the NCAAF position blanks. | dev clean, prod unchanged | `migrate_mls_season_columns.py`, `ingest_mls_season_stats.py`, `migrate_player_entity_type.py`, `backfill_ncaaf_positions_cfbd.py`, each `--db data/picks.db --apply` |
| 44 | **P3** | **`roster_season()` infers a season from a timestamp** with a hardcoded month rule — the same class as the `_SEASON = {"mls": 2025}` constant that served last year's squads all season. | `roster_membership.py:218` | read the published current season, as `ingest_mls_ncaaf_rosters._season()` now does |

---

## Added / closed 2026-08-17 — the props-board pass

Rows above are kept as written. These supersede where they overlap.

### Closed

| # | was | now |
|---|---|---|
| 1 | **Prod has zero news.** `news_items` empty for every league; the headline v0.8.0 feature. | **4,784 rows on prod, 467 in the last 24h.** Bluesky search restored the same day — 91/91 queries, 406 posts, 0 errors. The credential was present the whole time under a different spelling (`BLSKY_PASS`), and a single-spelling lookup reported "no credential" with the value in the file. `_bsky_credential()` now accepts an ordered alias list and prints which one matched. |
| 2 / 41 | **Tennis discards a working feed.** Bovada serves ATP/WTA, every prop dropped because `players` had no atp/wta rows; `props-prod` exited 3 every 30 minutes. | **1,022 tennis props on prod.** 150 ATP + 150 WTA ingested from ESPN's rankings, all carrying publisher ids, 2 requests. `props-prod` 0/384 → atp 182/188, wta 165/188. `props-freshness` went green as a side effect — it had only ever failed because it kept self-healing a service that could not succeed. **DB-only, no deploy.** |

### New

| # | severity | defect | evidence | fix |
|---|---|---|---|---|
| 45 | **P0** | **The props board served games that had already finished.** The upcoming filter was `pg.date >= date('now')` — a UTC calendar date — while the client groups and labels every game by the LOCAL date it derives from `start_time`. Two rulers on one board. Shipped in v0.4.3 on **2026-07-17** and invisible for a month, because until `38f80bb` (08-15) the client grouped by the same UTC date the filter used: a finished Sunday match read as "today, 7:30 PM". Fixing the display half exposed it as a `SUN, AUG 16` header at the top of the board. | 36 of 197 July MLB games and 14 of 28 August MLS fixtures kick off 00:00–03:59Z, the window where UTC and local dates disagree | **Fixed on dev** (`7292522`): filter on the instant with a 3-hour grace, `COALESCE` to end-of-date for the 17 upcoming MLS rows carrying no `start_time`. Both slate paths share one predicate, asserted by a test. **Still live on prod** — `routers/props.py` is baked into the image. |
| 46 | **P0** | **`prop_games` has no status column, so the board cannot tell postponed from started.** This blocks the decided rule (drop props at kickoff, 2026-08-17): applied naively it would silently delete a postponed game whose props are still live. | `prop_games` cols: `id, league, date, home, away, espn_event_id, final_home, final_away, start_time` | add a nullable `status`, populate from the linked `espn_event_id` — ESPN publishes `state`/`completed`/`status` and `reconcile_gap.py:94` already handles `STATUS_POSTPONED`/`CANCELED`/`SUSPENDED`. Additive, so it does not outrun prod's frozen code. |
| 47 | **P1** | **Tennis start times are bucketed placeholders.** 13 of 15 ATP/WTA games on 08-17 share exactly `15:00:00Z`; 15 of 18 on 08-18 share it. A session start time is being stored as a match time, which is why the board reads as a wall of "10:00 AM". | `prop_games` where league in (atp,wta) | trace where `start_time` is set for tennis; the scoreboard source (row 49) publishes per-match times |
| 48 | **P1** | **Tennis pills were missing from the props board.** `LEAGUES` is both the filter row AND the within-day ordering, so atp/wta were unfilterable and sorted last while tennis was 32 of the 71 games. The pills advertised UFC/NBA/NFL/NHL — four leagues with zero games. | `pages/props.tsx:31` | **Fixed on dev** (`750416f`), appended rather than reordered. Prod's frontend image predates it. |
| 49 | **P1** | **The tennis spine decays by design.** It is the top 150 per tour; a tournament field is not the rankings — it includes qualifiers, wildcards and returning players. Cincinnati overlapped heavily so only 2 names missed, and that overlap drops as the tour moves to Winston-Salem, US Open qualifying and Challengers. | ESPN's `atp|wta/scoreboard` publishes **263–328 distinct athletes for one event** vs 150 from rankings, for the same 2 requests | swap the source in `ingest_tennis_players.py` from rankings to the tournament scoreboard, on a timer ahead of the props scrape |
| 50 | **P1** | **Surname-first names never resolve.** Folding diacritics and case does not touch word order. Not tennis-only — the same shape is in MLS. | Bovada "Xinyu Wang" ↔ ESPN "Wang Xinyu"; "Shuai Zhang" ↔ "Zhang Shuai"; MLS "Kim Kee-Hee" | one fix in `_resolve_player_for_ingest`, not per-league |
| 51 | **P2** | **The esports board buckets by start time**, so a match that ends late lands in the wrong day. Same class as 45, different surface. | `pages/esports.tsx`, `localDateKey(m.startTime)`; the slate payload carries no end time | `docs/TASK-esports-local-day-endtime.md` — add an end time, group finished matches by it |
| 52 | **P2** | **`/scores` previous-day button shows today again.** Reported 2026-08-14. The HTTP 500 behind it is **gone** — prod returns 200 for 2026-08-15, 2026-08-10 and 2026-07-04 — but the navigation itself is unverified, so defect A stands and defect B is closed. | `PLAN-scores-prev-day-2026-08-14.md` | drive the page and watch the request the `‹` button actually issues |
| 53 | **P3** | **Prod's frontend proxies `/api/*` to `127.0.0.1:8000` inside its own container**, where nothing listens, so a direct call to `:3100` 500s. Harmless in production only because nginx routes `/api/` straight to `:8100` and never uses that path. | `docker logs legendarypicks-frontend-1` → `ECONNREFUSED 127.0.0.1:8000` | point the rewrite at the compose service name; it is a trap for anyone testing the container directly |

### Gate added the same day

`BOARD-stale` (`verify-gates.sh`) asks the reader's question rather than the code's: **of the
games the API serves as upcoming, has any already been played?** No fixture, so it cannot be
satisfied by relabelling — which the existing unit test could be, and was. That test pins a
00:30Z game to the previous day's group and never asks whether the row belongs on the board, so
it stayed green through the entire month this defect was live.

Graded on dev and prod **separately**, because they are different code:

```
PASS BOARD-stale-dev  (71 games, none finished; 17 carry no start_time)
FAIL BOARD-stale-prod (2 of 56 games already finished — both Sunday-night MLS fixtures)
```
