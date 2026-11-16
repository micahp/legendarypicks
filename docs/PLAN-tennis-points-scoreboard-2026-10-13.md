# PLAN: live tennis point score on the LP scoreboard (ATP Shanghai, WTA Wuhan first)

Date: 2026-10-13. Status: plan only. Nothing implemented, no DB written, no process started.
Facts marked (checked) were confirmed read-only on 2026-10-13 around 22:50 UTC.

## A. Recommended architecture

```
prediction-market-trading (PMT owns)              legendarypicks (LP owns)
------------------------------------              ---------------------------------------------
kalshi_live_points.py (cron */5, flock, 4s poll)
  |-- KALSHI_POINTS_YYYYMMDD.jsonl  (unchanged; trade desk + join_points_to_tape.py)
  '-- KALSHI_LIVE_STATE.json  (NEW, atomic        ingest_tennis_live_state.py (dev timer, 10s)
       tmp+rename every poll cycle,       ---->     reads the file, never the lock
       heartbeat + published current state)        |
                                                    v
                                                  dev DB: tennis_live_state (upsert per match)
                                                          tennis_match_source_ids (crosswalk)
                                                    |
                                                    v
                                                  GET /api/{atp|wta}/games  adds `livePoint`
                                                    (as_of, age_s, source, or null + reason)
                                                    |
                                                    v
                                                  components/Scores/GameCard.tsx tennis row
```

The trade desk poller stays the only process that calls Kalshi. It gains one output: a small
state file, rewritten atomically after every poll cycle, that carries the publisher's CURRENT
score for each live match plus a poll heartbeat. LP never calls Kalshi and never touches PMT's
lock. An LP-owned ingest copies that file into the dev DB; the existing `/api/{league}/games`
handler (backend/routers/games/scoreboard.py) attaches the point score to ESPN games that have a
verified crosswalk row; the card renders it with its age. ESPN stays the source for schedule,
names, round, final status and per-set games when the Kalshi panel is absent.

Why a new state file and not the point rows: each point row records the score BEFORE the point
(`row()` writes `prev["g1"]`, `prev["sets1"]`) plus the winner, so the current score would have to
be derived, including game and set rollover. The poll already holds the published current score
(`state(cur)`), so we write that instead (published-first). And point rows are written only when a
point happens, so a 90 second changeover is indistinguishable from a dead poller; a per-poll
heartbeat fixes that.

## B. Transport: a shared file, PMT writes, LP reads

Recommended: shared file. LP already reads PMT output this way (`LP_BROADCAST_DIR` in
backend/wc_context.py, backend/cod_context.py, backend/routers/games/contexts.py) and PMT already
writes into LP (`refresh_plays_board_from_feed.py` to backend/data/plays_board.json). (checked)

Rejected:
- DB table both write: puts a PMT process on LP's 1.8 GB dev DB as a second writer, couples PMT to
  LP's schema and migrations (memory: two migrations must not share a column), and adds SQLite lock
  contention to the trade desk's hot loop.
- HTTP API: PMT has no server for this; a new long-running service is a new process to keep alive
  and a second thing that can be down.

Rules:
1. Path is configurable: `LP_KALSHI_LIVE_STATE` env var, default
   `/root/prediction-market-trading/data/orderflow/KALSHI_LIVE_STATE.json`. A missing file is an
   explicit `source_unavailable`, logged, never an empty slate.
2. Writer writes `KALSHI_LIVE_STATE.json.tmp` then `os.replace`. Readers never see a partial file.
   The reader still validates JSON and a `schema_version` field and fails loudly on mismatch.
3. LP NEVER opens, flocks or stats `_kalshi_live_points.lock`. An `flock` from LP during a cron
   relaunch would make the poller exit for that 5 minute window. The lock mtime is also useless as
   liveness: `open(LOCK, "w")` touches it every 5 minutes even when the run exits immediately
   (checked: all PMT lock files show 17:50 mtime).
4. Liveness comes only from fields inside the file: `poll_at` (last completed poll cycle) and
   per-match `last_ok_at` (last successful live_data call for that match). Process existence is not
   liveness: on 10-13 the poller was running while discovery failed on DNS from 19:25 UTC (checked
   in _kalshi_live_points.log).
5. The writer writes the file even when it polls zero matches (`matches: []`, fresh `poll_at`), so
   "no live matches" and "poller down" are different states.
6. Staleness thresholds (LP side, computed against `poll_at` and `last_ok_at`): see D.

## C. Data contract (card fields)

State file, one object per match (all from the live_data poll and the milestone, as published):

| Card needs | State file field | Source in kalshi_live_points.py | Today in point rows? |
|---|---|---|---|
| Current point score per side | `g1`, `g2` | `state()` competitor{1,2}_current_round_score | No, rows hold the score before the point |
| Advantage | `adv` | `advantage` | Before-point only |
| Server | `server_side` "1"/"2"/"0" | `server` vs competitor ids | `ServeIndicator`, before-point |
| Games per set | `sets1[]`, `sets2[]` | competitor round_scores | Only current set (`P1GamesWon`) |
| Sets won | `sw1`, `sw2` | competitor overall_score | `P1SetsWon`, before-point |
| Match status | `status` | widget_status or status | No |
| As-of time | `poll_at`, `last_ok_at` | poll clock | `EpochTimeEnd` (only when a point happens) |
| Match key | `milestone_id` | milestone id | `_match_id` |
| Identity inputs | `competitor1_id`, `competitor2_id`, `event_ticker`, `source_ids` | `c1`,`c2`, primary_event_tickers, source_ids | ids NOT written; tickers, source_ids yes |
| Tournament | `tournament`, `tour` | details.tournament_name, tour | `_tournament`, `_tour` |
| Display names | `p1`, `p2` | milestone title split | `_p1`, `_p2` (display only, never a key) |

Missing, and how the card shows it:
- Per-point timestamp: Kalshi publishes none. The card shows the poll's age, never "live", and the
  tooltip says "updated every ~4s from Kalshi, up to 4s late".
- Side orientation: Kalshi P1/P2 order is the milestone title; ESPN home/away is its own order. The
  crosswalk stores the side mapping; no mapping, no panel.
- Tiebreak point counts, retirement and walkover status values: not verified (see I). Until a
  live tiebreak is observed, an unrecognised score value renders as "?" with the raw value logged,
  never coerced to 0.
- Pre-match: Kalshi discovers a milestone only from 1 hour before start (`discover()` horizon).
  Pre-match cards get nothing from Kalshi.

## D. Scoreboard UI (tennis card states)

Existing card: ESPN per-set columns from `g.sets` (GameCard.tsx lines 195-215), status badge from
ESPN. No point-score field exists today (checked).

- Pre-match: unchanged ESPN card. No point row.
- Live, fresh (`now - last_ok_at <= 15s` and `now - poll_at <= 15s`): per-set games, sets, and the
  current point score all come from the Kalshi state, one source and one timestamp. A small server
  dot on the serving side. A muted "Kalshi, 6s ago" age label. Do not mix ESPN set games with Kalshi
  points in one row: ESPN tennis is cached for 90s (`TENNIS_LIVE_TTL = 90`, checked) and can sit a
  game behind the point score.
- Between points: same as live. The heartbeat keeps the age small, so a changeover does not read
  as stale.
- Aging (15s to 60s): same values, age label turns to "38s ago" in the warning tone.
- Poller down or match missing from the file (> 60s, file missing, schema mismatch): point score
  hidden; the card falls back to the ESPN set columns with the ESPN snapshot age, plus a muted
  "Point score unavailable since 17:42". Never show a frozen point score.
- ESPN says Final: ESPN wins; the Kalshi panel is dropped.

Thresholds (15s, 60s) are a starting proposal from POLL_S = 4 (about 3 polls). Measure poll
cadence on a live match before freezing them.

## E. Identity: Kalshi match to LP scoreboard game

Keys on each side (checked on 10-13 data):
- Kalshi: `milestone_id` (UUID), event ticker `KXWTAMATCH-26OCT13POHWAN` (the suffix is
  name-derived, so it is NOT a key), `source_ids` {`source_1_id` "5437919", `source_2_id`
  "20261013B786F4B2", `source_3_id` "sr:sport_event:75373642"}, `competitor{1,2}_id` (in the poll,
  not yet persisted).
- ESPN scoreboard: `game_id` (competition id, e.g. 185320), `tournament_id` (315 Shanghai, 381
  Wuhan), `athlete_id` per side, `start_time`, `round`.
- LP: `player_source_ids` has tennis rows only from underdog (341 atp, 168 wta) (checked). No espn,
  kalshi, sportradar, tennisexplorer or WTA API rows for tennis.

No shared match id between Kalshi and ESPN is known. Plan:
1. Tournament key: a two-row config, ("ATP Shanghai" -> atp/315), ("WTA Wuhan" -> wta/381).
2. Match key: `tennis_match_source_ids(source='kalshi', league, source_match_key=milestone_id,
   espn_game_id, side_map, bound_by, bound_at, evidence)`. Bound only when BOTH players are bound by
   id: Kalshi competitor id -> LP player_id and ESPN athlete id -> LP player_id, inside the same
   (tournament, UTC date). Unbound is shown as no panel, never guessed.
3. Measure first, before any binding code:
   - What `source_1_id` and `source_2_id` identify, and whether any ESPN payload or LP table carries
     them. If one is an ESPN or a spine id, the match join is a direct key and step 2 shrinks.
   - The format of `competitor{1,2}_id` (Sportradar `sr:competitor:` or Kalshi's own).
   - Whether ESPN athlete ids are bound to LP player_ids anywhere (rankings spine:
     `save_tennis_ranking_spine` in scoreboard_store.py matches on `_tennis_name_key`, so that path is
     name-keyed today).
   - Count agreement per (tournament, date): 10-13 had 4 Shanghai and 14 Wuhan matches in both ESPN
     snapshots and Kalshi rows. One day's count match is not a join.
4. If no published id link exists, the only name-free route is a human-confirmed binding of player
   ids (about 120 players across both draws): names may propose a candidate into a review queue, a
   person confirms, the confirmed row is an id-to-id binding. That needs Micah (G3).

Conflict to report: docs/CONTEXT-2026-10-13.md line 26 says the tennis spine is "TennisExplorer and
the official WTA API (no ESPN)". The scoreboard tennis games, athlete ids and the ranking spine are
ESPN (`source='espn'` in scoreboard_snapshots; `espn.tennis_ranking_identities` in
ingest_scoreboards.py lines 389-392). So the scoreboard's player identity is ESPN-keyed while the
spine is TE/WTA-keyed, and neither has crosswalk rows in `player_source_ids`. Kalshi would be a third
id system. This plan binds Kalshi to the ESPN game because the card is an ESPN game; it does not
resolve the spine conflict (G4).

## F. Tasks

Every LP task works in its own worktree (`git worktree add /root/lp-tennis-points -b
feat/tennis-points dev`), dev DB only, no prod, no server restarts.

1. PMT: state snapshot file. (Sonnet)
   In: kalshi_live_points.py. Out: `KALSHI_LIVE_STATE.json` per B and C, written each cycle
   including zero-match cycles; point-row shape unchanged. Writes: kalshi_live_points.py,
   test_kalshi_live_points.py. Verify: `cd /root/prediction-market-trading && python3 -m pytest -q
   test_kalshi_live_points.py` and a test that a point row from fixtures is byte-identical before and
   after. Takes effect at the next hourly cron launch; nobody restarts the poller.
2. Identity measurement, read-only. (Sonnet)
   In: state files and point rows from task 1, dev DB, ESPN snapshots. Out: a section appended to this
   plan answering E.3 with counts. Writes: this doc only. Verify: every claim cites the query that
   produced it.
3. LP schema: `tennis_live_state`, `tennis_match_source_ids`. (Haiku)
   Out: CREATE IF NOT EXISTS in scoreboard_store.py, dev DB only. Verify:
   `sqlite3 -readonly backend/data/picks.dev.db ".schema tennis_live_state"` after a dev run, and
   the existing scoreboard_store tests.
4. Binding step for Shanghai and Wuhan. (Sonnet)
   In: task 2 result, crosswalk table. Out: bound rows only on id evidence; others into a review
   queue. Writes: tennis_match_source_ids, review queue (dev). Verify: bound count vs Kalshi matches
   per tournament-date, and zero rows bound with `evidence` naming only names.
5. LP ingest `backend/ingest_tennis_live_state.py`. (Sonnet)
   In: state file. Out: upsert to tennis_live_state only on change; fail loudly on missing file,
   bad JSON, schema_version mismatch. Never touches the PMT lock. Writes: tennis_live_state (dev).
   Verify: unit tests with a stale file, a zero-match file, a torn file; then one manual dev run.
6. API: `livePoint` on `/api/{atp|wta}/games`. (Sonnet)
   Out: `{as_of, age_s, source:"kalshi", g1, g2, adv, server_side, sets, sw}` oriented to ESPN
   home/away, or `null` plus `livePointReason`. Writes: backend/routers/games/scoreboard.py, tests.
   Verify: `curl -s 127.0.0.1:8096/api/wta/games?date=<live day> | jq '.[] | .livePoint'`.
7. Card: tennis live row per D. (Sonnet)
   Writes: components/Scores/GameCard.tsx, a GameCard.livePoint.test.tsx. Verify: tests with
   `/root/legendarypicks/node_modules/.bin/jest components/Scores` and a headless screenshot with zero
   page errors.
8. Live verification on a Shanghai or Wuhan match per H. (Sonnet)

## G. Decisions for Micah

1. Approve the PMT change (task 1): the trade desk's poller gains a second output file.
2. Freshness path: recommended a dev-only systemd timer every 10s (OnCalendar) running task 5. The
   alternative is the API handler reading the state file directly (fresher, but breaks "serving
   reads the DB only"). The existing 60s live timer is too slow for a point score.
3. If E.3 finds no published id link: allow human-confirmed player bindings for the Shanghai and
   Wuhan draws, or ship nothing until a key exists.
4. The tennis spine conflict in E: which id system the scoreboard's tennis players should bind to.

## H. Verification of the end result

On a live Shanghai or Wuhan match (both 1000-level events are in their second week now; dates of the
finals not verified):
1. State file: `poll_at` advances every ~4-6s; the match appears; `last_ok_at` advances.
2. Independent check: the point score on the card equals Kalshi's score for that match at the same
   minute, read from PMT's next KALSHI_POINTS row (that row's before-point score must equal the card's
   last shown score), and matches the ESPN set games once ESPN catches up.
3. Orientation: for 10 consecutive points the side that wins in KALSHI_POINTS is the side whose score
   moves on the card.
4. Age label never exceeds 15s while the match is in play and the poller is healthy.
5. Failure drill without touching the poller: point LP_KALSHI_LIVE_STATE at a copied file frozen 2
   minutes old in a dev test run; the card must hide the point score and show "unavailable since".
6. A changeover: the age stays fresh during the 90s break.
7. Coverage: every Kalshi Shanghai/Wuhan milestone for the day is either bound or in the review
   queue; count both.
8. Page: headless load of /scores?league=WTA with zero page errors; the other leagues' cards
   unchanged.

## I. Not verified

- Kalshi live_data field semantics in a tiebreak, on retirement or walkover; the meaning of
  `source_1_id` and `source_2_id`; the format of competitor ids.
- Whether Kalshi lists every Shanghai/Wuhan main-draw match (only 10-13 counts compared).
- Real poll cycle time with many concurrent matches (POLL_S is 4 plus one call per match).
- Remaining schedule of Shanghai and Wuhan.
- usopen_points.py: confirmed not running and the unbounded dedupe comment present; the rebuilt
  dedup file was not inspected. It is out of scope (Slam only).
- tennis_atp_* end date: max tourney_date in tennis_atp_matches is 20260601 (checked); not used here.
- A generic version (all 500+ events per tennis_scope.py, other publishers) would need: tournament to
  ESPN tournament_id mapping for every scoped event, the full player crosswalk, and a decision on the
  spine. Not designed here.
