# PLAN — Add MLS + NCAAF, tennis props, radio map (2026-08-06)

Branch: `feat/league-mls-ncaaf` (worktree `/root/lp-league-mls-ncaaf`, off dev 34401d7)
DB: copy at `/root/lp-league-mls-ncaaf/backend/data/picks.dev.db` (VACUUM INTO of dev, quick_check ok).
Main tree / main DB are NOT touched. Prod off-limits.

## Doctrine (load before every task)

- published-first: copy published values, never derive. Expected totals come from ESPN `limit=1`
  envelopes, checked by `reconcile_totals.py`.
- DATA-COVERAGE-CONTRACT §4/§6/§7: coverage registry is the switch; only `complete` is offered;
  read `types[]`/`displayName` from the season doc; season key from startDate/endDate.
- honest-data-ui: sample size on the surface, dash ≠ zero, absence ≠ zero, table with columns.
- Python 3.8 typing (Optional/List/Dict from typing, no `X | None`).
- Never npm/npx/yarn in the worktree. Subagents: NO terminal. Report file paths, stop.

## Measured shape (2026-08-06, from sports.core.api.espn.com)

### MLS — soccer/leagues/usa.1
- 2025: displayName "2025 MLS". 18 published types (ids 0..17). Type 1 "Regular Season" = **510 events**.
  Type 2 "All-Star Game" = 1 event. Teams = **30**. Calendar-year season; season key 2025.
- 2026: displayName "2026 MLS". Type 1 = 511 events. Teams = **32** (expansion). All-Star type 2 = 0 events (published fact).
- Types are NOT contiguous-ish in the old sense: iterate the published list, never range(1,6).
  Postseason = ids 3..17 (per-conference wild card/rounds/semis/final + MLS Cup).

### NCAAF — football/leagues/college-football
- 2025: displayName "2025". Types: 1 Preseason (0 events), 2 Regular Season = **911 events**,
  3 Postseason, 4 Off Season. Groups = 2: **group 80 = FBS = 146 teams / 888 events**;
  group 81 = FCS = 131. Season key 2025 (starts/ends inside one academic year — confirm from startDate/endDate).
- League-wide `teams` = 807 — EVERY expected count is group-scoped to 80.

### Tennis (bonus)
- espn_client.LEAGUES already has `atp: ("tennis/atp", 3)` and `wta: ("tennis/wta", 3)`.
- props table has NO league column; league resolves via players.league / prop_games.
- Bovada scraper (`backend/bovada_scraper.py`) has `_parse_standard_props` — tennis needs its own
  parser for match-winner / total-games / set markets.

### Radio (bonus)
- `components/ListenLive.tsx` hardcodes WC_STREAM. `components/Game/BoothFeed.tsx` renders ListenLive.
- Goal: a team→station map (JSON) for every team in every league we cover (nfl, mlb, nba, nhl, mls,
  ncaaf, wc, ufc, atp, wta as feasible), plus a component that picks the station for a given game.
- Known anchors: WUUB-FM = Inter Miami English radio (amperwave HLS); iHeart zc11554 = WC/FOX.

## Waves (3 concurrent max, file-disjoint)

Wave 1 — backend foundation (parallel):
- A: `backend/espn_leagues.py` registry + `backend/espn_client.py` LEAGUES += mls/ncaaf + team vocab
- B: `backend/ingest_soccer_logs.py` (new, MLS; base ingest_wc_logs.py)
- C: `backend/ingest_ncaaf_logs.py` (new, FBS; base ingest_nfl_logs.py)

Wave 2 — backend integration (parallel):
- D: `backend/reconcile_totals.py` += mls/ncaaf checks (ESPN_PATH, group scope)
- E: draw handling: `backend/team_stats_schema.py` + `backend/backfill_team_parity.py` (result TEXT)
- F: `backend/audit_league_stats.py` MANIFEST += mls/ncaaf BEFORE ingest; `backend/audit_field_utilization.py` ENDPOINTS

Wave 3 — frontend (parallel):
- G: `components/Leagues/presentation.ts` + `components/Leagues/hooks/useLeagueRouteState.ts` + `types.ts`
- H: `components/Leagues/StandingsTab.tsx` (soccer P W D L for mls; conference for ncaaf)
- I: `components/Leagues/PlayerGameLog.tsx` (soccer columns + N of M) + `PredictTab.tsx` (draws)

Wave 4 — bonus (parallel):
- J: tennis props (backend parser + ingest + router + frontend surface)
- K: radio station map (JSON + component + BoothFeed/ListenLive integration)

Wave 5 — me (orchestrator): run ingests on the COPY DB, reconcile, coverage rows, verify-gates,
browser verification at 375/1440, LEAGUE-STAT-GAPS, identity-crosswalk statement. Commits per slice.

## Tournament tracking for soccer (Micah, 2026-08-06 — DO NOW; schedule watcher is LATER)

Two separate mechanisms, deliberately split:

### 1. Tournament-aware game logs (DO NOW)
Soccer players appear in MULTIPLE competitions within one season, and ESPN files
each under its OWN league slug — not under usa.1:
- `usa.1` — MLS regular season + MLS Cup playoffs (18 types: Combined, Regular
  Season, All-Star, Wild Card x2, Round One x8, Semis x2, Conf Finals x2, Cup)
- `concacaf.leagues.cup` — Leagues Cup (2025: League Phase 54 games, QF, SF,
  3rd-Place; verified 2026-08-06)
- `concacaf.champions` — CCC; `campeones.cup` — Campeones Cup; plus Open Cup,
  USOC variants as published
**DECIDED 2026-08-06 (Micah): tournament games live under their OWN league key.**
The log row's `league` IS the competition (`mls`, `lcup`, `ccc`, ...) — no new
`competition` column needed. Consequences:
- the REG denominator counts only `league='mls' AND game_type='REG'` rows; a
  Leagues Cup goal sits in `league='lcup'` rows and never inflates MLS
  regular-season games-played (same pattern as game_types.py's PLAYIN/ALLSTAR).
- the identity spine is still per-person (durable), so one player's logs span
  multiple league keys and join on `player_id` — that is what makes the player
  detail page able to show "MLS 2025" and "Leagues Cup 2025" for the same person.
- On MLS player detail: show ONE season at a time (pre/regular/post for that
  league) with select dropdowns to switch YEAR or LEAGUE (MLS, Leagues Cup, CCC).
  Keys off `position_group` so a GK surface shows saves, not shots.
- ALSO: international duty (player misses club games for national-team friendlies/
  tournaments) and LOANS (player appears for another club mid-season) are absence/
  identity questions, not log rows — the absence comes from the club schedule vs
  the appearance log (honest-data-ui: absence must be visible, not inferred).

### 2. Schedule watcher for postponements/reschedules (LATER — explicitly NOT now)
Games get postponed or moved (observed 2026-08-06: Inter Miami was scheduled
for Leagues Cup vs Monterrey on Saturday, then updated to a regular-season MLS
match). Detecting that is a WATCHER on the schedule: compare the stored schedule
against a fresh fetch, diff date/opponent/competition, and record the mutation.
Different mechanism, different ownership (a cron watcher vs the ingest). Deferred.

## Position vocabulary + groups (DB side) — DONE 2026-08-06

`backend/data/position-vocabulary.json` now covers all six leagues. Extended
`backend/fetch_position_vocabulary.py` with `_SPORT`/`_CORE_LEAGUE` for mls
(soccer/usa.1) and ncaaf (football/college-football), then fetched live:

- mls: 28 positions (G root; D→CD/LB/RB/SW; M→AM/CM/DM/LM/RM; F→CF/LF/RF/FCF)
- ncaaf: 68 positions (OFF root: OL/C/QB/RB/WR/TE...; DEF root: DL/DE/DT/LB/DB/
  CB/S...; ST root: P/PK/KR/PR/LS/H)
- `players.position_group` column already exists — the FE keys off it to render
  position-correct columns (a GK surface shows saves, not shots).

## CORRECTED ORDER OF OPERATIONS (Micah, 2026-08-06 — supersedes "rosters first" in HANDOFF)

1. **Measure season types** (published-first §6): `seasons/{year}/types` per league —
   tells you WHICH phases exist to schedule against. MLS 2025 publishes 18 types
   (0 Combined, 1 Regular Season, 2 All-Star, 3-4 Wild Card, 5-12 Round One,
   13-14 Semifinals, 15-16 Conference Finals, 17 MLS Cup). NCAAF publishes 4
   (1 Preseason, 2 Regular Season, 3 Postseason, 4 Off Season). Measured 2026-08-06.
2. **Schedule**: per-type event collections → which games, which teams, which phases,
   which dates. This is the definitional rung (a schedule is always published).
3. **Season-dates file**: update `backend/season_keys.py` with measured startDate/endDate
   per league (DONE for mls/ncaaf + tournament slugs lcup/ccc/campeones 2026-08-06 —
   MLS/NCAAF/tournaments are all START-year leagues; NCAAF postseason is its own type 3,
   not a second calendar year).
4. **Current standings** (if league is in a current season): the independent record
   authority — verifies the schedule population and gives the team directory + phase
   labels. Do not let the schedule certify itself.
5. **If the league is UPCOMING**: pull previous-season standings + team stats instead
   — an upcoming league has no current-season data yet; the product needs last year's
   evidence. Branch here on season state.
6. **Rosters / identity spine**: pull rosters per team → `players` rows. Roster
   membership = current snapshot; identity = durable person rows. Resolve by
   source-native ID, then evidence (team, position family, DOB).
7. **Position vocabulary + groups (DB side)**: by the time we do player logs, record
   per league: the team the player is on AND the league's position vocabulary AND a
   position GROUP (GK/DEF/MID/FWD for soccer; QB/RB/WR/TE/OL/DL/LB/DB/ST for NCAAF).
   The FE side keys off position group to display the right columns for the player's
   position (a GK surface must show saves, not shots). This is a schema decision, not
   a UI afterthought — verify `players`/`player_stats` can carry it.
8. **Player ingest for props + game logs (PRE, REGULAR, POST)**: last, resolved against
   the identity spine, with phase labels already established from step 1-2. Props from
   Bovada primary, Underdog/Kalshi fallback where Bovada lacks player props.

Ordering rationale: steps 1-5 need no identity and produce the calendar + team
evidence. Step 6-7 give the resolver its join key (the source-native ID must be the
same vocabulary the game-log resolver matches — the LAR/LA lesson). Step 8 is the
only step whose rows depend on the spine, so it runs after everything else.

## ESPN request budget (per .claude/skills/espn-request-budget)

The limit is a COUNT per host (~100), not a rate — pacing never buys budget.
The shared paced_http fetcher enforces host_budget=100 + 60s cooldown/reset and
a disk cache that does not charge on hits. Measured 2026-08-06:

- MLS 2025 ingest: ~510 summaries to site.web.api.espn.com + ~6 event pages to
  sports.core.api.espn.com. At 1.2s pacing + budget cooldowns it completed in
  32 min: 15,361 logs / 499 games, 0 NULL game_type.
- NCAAF 2025 ingest: ~888 summaries to site.web.api + ~10 pages to sports.core.
  Run AFTER the MLS reconcile so the two do not compete for one host budget.
- reconcile_totals --league mls: classifies all 510 published events because
  team_game_results is empty for mls (only player_game_logs populated) — honest
  ours=0 until backfill_team_parity covers mls; disk cache makes re-runs free.
- The MLB retry ladder (ingest_soccer_logs._summary_retry, 4 attempts) exists
  to wait out transient refusals but the real protection is the shared
  fetcher's budget. A 403 that survives the ladder means the host is spent:
  fail loudly per the skill, do not loop.

## GK saves finding (measured 2026-08-06, real MLS summary event 727308)

The ingest maps only goals/assists/shots/sot and drops everything else. But a
real MLS summary publishes per player: appearances, foulsCommitted, foulsSuffered,
ownGoals, redCards, subIns, yellowCards, goalsConceded, saves, shotsFaced,
goalAssists, shotsOnTarget, totalGoals, totalShots (14 keys). A goalkeeper's row
in our copy DB is `{"goals":0,"assists":0,"shots":0,"sot":0}` — while the payload
had saves=2, goalsConceded=4, shotsFaced=0 for that same GK (James Pantemis,
athlete 257619). So "GK saves gap flagged red" is really "GK saves never captured
even though the payload publishes them" — a fix, not a publisher gap. The fix
(follow-up slice): map saves/goalsConceded/shotsFaced for position G (position
abbreviation is published in the payload — the "can't tell GK from outfield"
claim in the MANIFEST is a code choice, not a data limitation), and set
position_group on the log row so the FE can render position-correct columns.

## Definition of done (from task docs)
1. Coverage row `mls 2025` and `ncaaf 2025` = complete via reconcile_totals --write-coverage.
2. reconcile_totals --league mls / --league ncaaf exit 0.
3. Zero rows with NULL game_type for both leagues.
4. A drawn MLS match renders as a draw (standings/game log/momentum).
5. MANIFEST written BEFORE ingest; verify-gates.sh COV-statset pasted.
6. Two players screenshotted (one genuine miss, one un-ingested season) — must look different.
7. Tennis props + radio map delivered.
