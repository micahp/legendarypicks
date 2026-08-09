# Plan — Esports league destination (EWC 2026 tournament center under the Leagues system)

**Plan iteration:** 3 — post-correction rewrite (2026-08-08)
**Implementation status:** IMPLEMENTED — plan rewrite `4735620`, module extraction `0c74089`,
titles route `ccbc866`, hub build-out `668a160`, focused tests `c62b40b`; worktree clean.
**Release status:** candidate only — no DEV, production, database, or managed-service change.

This plan is the event-specific iteration of `ESPORTS-PRODUCT-DIRECTION.md`. It supersedes the
iteration-2 framing ("/esports behaves like an EWC tournament center"), which was **rejected**.
The Esports World Cup remains the editorial centerpiece of the product, but it lives in the Leagues
system, not on the live board.

## The correction — accepted information architecture (2026-08-08)

1. **`/esports` is the existing live broadcast and match board.** It keeps its confirmed-live hero,
   broadcast continuity, upcoming slate, results, and picks entry — with **no EWC tournament-center
   takeover**. EWC matches appear only as ordinary board rows with their existing live/final/up-next
   behavior. The page file contains no EWC tournament-center module.
2. **`/leagues/esports` is the Esports league destination.** It owns the EWC 2026 tournament center:
   event focus, today/results across titles, the Club Championship rail, and the honest unavailable
   state until a permitted publisher exists.
3. **The main `/leagues` list includes Esports**, using the existing league-card design system.
4. **The EWC backend APIs are preserved as shared contracts**: the projection route, the Club
   Championship reader, explicit `ewcEventId` identity, qualifier exclusion (`c64f6df`), the CoD
   structural pending-participant/TBD repair, and the request budgets.

## Requested outcome

1. A complete Esports league destination at `/leagues/esports`: league-style header/navigation,
   game/title discovery and links, the EWC 2026 tournament center, Club Championship standings with
   source/freshness honesty, live and upcoming EWC schedule, completed results, broader non-EWC
   esports context, direct paths to title pages and picks/prediction, responsive desktop/mobile
   hierarchy, and loading/error/empty/stale states — with continuity to existing streams, results,
   and match identity.
2. Focused tests proving: `/esports` no longer renders the EWC module, `/leagues` links Esports, and
   `/leagues/esports` renders the complete product and all data states responsively.
3. Preserve the EWC APIs, qualifier exclusion, CoD pending-participant repair, request budgets, and
   honest unavailable standings until a permitted publisher is found.

## Research snapshot — 2026-08-08 (preserved from iteration 2)

### What EWC is right now

- EWC 2026 runs July 6 through August 23 and contains 25 competitions across 24 games.
- Call of Duty: Black Ops 7 is an EWC Club Championship competition. Its tournament is active
  August 5–9 and has a $1.8 million game-title prize pool.
- Upcoming tent-pole events after the current week include Chess (Aug 11), CS2 (Aug 12), Rocket
  League (Aug 12), CrossFire (Aug 17), Fortnite (Aug 17), and Trackmania (Aug 19).
- The Club Championship is a real cross-title narrative, not a cosmetic leaderboard. A club must
  place top eight in at least two competitions to be eligible, and must win at least one competition
  to finish first overall. Standard points are 1,000 / 750 / 500 / 300 / 200 for first through the
  common shared placement bands, with narrower 5th–8th values when a title ranks them individually.

Current top ten snapshot (research evidence only; **do not hard-code this table into the UI**):

| Rank | Club | Points |
|---:|---|---:|
| 1 | Team Falcons | 2,600 |
| 2 | Natus Vincere | 2,250 |
| 3 | Virtus.pro | 2,200 |
| 4 | Team Vitality | 2,000 |
| 5 | T1 | 1,750 |
| 6 | Team Vision | 1,750 |
| 7 | ZETA DIVISION | 1,500 |
| 8 | All Gamers Esports Club | 1,400 |
| 9 | Twisted Minds | 1,400 |
| 10 | Team Spirit | 1,200 |

### Sources checked

- Official EWC 2026 global rulebook (competition list, eligibility, point table, tiebreakers):
  https://d3h9qea4qy4169.cloudfront.net/EWC_2026_Global_Rulebook_1_1_55b3cc60e1.pdf
- Official EWC Call of Duty rulebook/resource page:
  https://resources.esportsworldcup.com/en/competitive-ops/rulebooks/cod-mw3
- EWC 2026 media guide (calendar and titles):
  https://cdn.esportsworldcup.com/resources/uploads/EWC_26_Media_Guide_short_d6f73c0f8a.pdf
- Current standings and event schedule cross-check, updated through Aug 7:
  https://escharts.com/special/ewc2026
- Current EWC Call of Duty bracket feed and its unresolved downstream slots:
  https://aws.breakingpoint.gg/matches

The rules and calendar have authoritative official sources. The current standings table found in
research is a third-party live table. Source rights and a stable machine-readable contract must be
resolved before automating ingestion; the browser must not scrape third-party HTML.

## What we already have (as of iteration 3)

This is a reprogramming and contract-hardening job, not a greenfield esports build.

- `pages/esports.tsx` already renders the live board: confirmed live broadcasts, continuous
  multi-match broadcast identity, upcoming matches, results, and links into picks. It no longer
  renders the EWC module (removed at `1dab7f7`), but the module code still lives in that file —
  Phase B moves it out.
- `pages/leagues/esports.tsx` already exists as a thin wrapper (breadcrumb, header, live link,
  `EwcModule` + standings rail with the responsive 5/10 limit). It is not yet the complete
  destination: no title discovery, no non-EWC context, thin loading/error/empty states.
- `pages/leagues.tsx` already lists Esports with a league card (added at `1dab7f7`).
- `backend/routers/esports/ewc.py` owns the EWC projection
  (`GET /api/esports/events/ewc-2026`) and the Club Championship reader
  (`GET /api/esports/events/ewc-2026/club-standings`), including the honest `unavailable` state.
- `backend/routers/esports/streams.py` and `yt_live_resolver.py` handle the EWC official channel,
  simultaneous arenas, game-first narrowing, YouTube preference, Twitch/Kick fallbacks, language
  ranking, and bounded YouTube API use.
- `backend/routers/esports/pandascore.py` fetches the `codmw` feed and retains enough past matches
  to close the earlier EWC result hole.
- `league_tier.py` treats the EWC main event as Tier 0 and keeps qualifiers demoted.
- The title-scoped routes `/esports/[title]` and `/predict/[title]` support all registered titles;
  `components/Esports/LeagueDesk.tsx` is the per-title desk (title pills, streams, results, picks).
- Finished esports rows carry `endTime`, and `/esports` groups results by viewer-local end day.
- `/scores` CoD path uses Breaking Point first, then the CDL site, then attaches a PandaScore detail
  ID; the EWC bracket reconciliation in `backend/routers/esports/cod_ewc.py` resolves structural
  pending participants so no card shows a raw `TBD`/`TBA`.
- Backend tests (fixture-driven, zero external requests): `test_ewc_routes.py`,
  `test_ewc_contract.py`, `test_cod_ewc_reconcile.py`, `test_esports_streams.py`,
  `test_esports_predict_api.py`, `test_wc_context.py`. Frontend: `components/EsportsEwcModule.test.tsx`
  (rail states, module render, GameCard pending labels).

## Skill-driven constraints

This iteration incorporates the local `delightful-design`, `build-league-data-pipelines`,
`espn-request-budget`, and `legendarypicks-esports` skills.

- **Published first:** ingest and validate the complete Club Championship population before one
  atomic publication. The UI top ten is a projection of that population, not the stored universe.
- **One writer:** the standings publisher and every reader are named. No request handler or browser
  may become a competing writer or reconstruct totals from match fragments.
- **Source-native identity:** retain the provider's stable club ID and competition contribution IDs.
  Names are labels and matching candidates, never primary identity.
- **Last good survives:** incomplete pages, duplicate IDs, contradictory totals, or source failures
  do not replace a valid published run.
- **Bounded requests:** one bulk standings request where possible, shared caches/single-flight, and
  a declared per-host request budget. This feature requires **zero new external requests**; the
  title-discovery route reads the already-cached shared slate. ESPN stays out of the esports
  request path entirely.
- **Esports package ownership:** the event routes live in the self-contained
  `backend/routers/esports/` package (`ewc.py`, `predict.py`, `slate.py`), not in
  `sports_service.py` or grafted onto `slate.py`.
- **Matcher scope:** shared `_team_match`/`_same_team` behavior is not loosened for the EWC CoD
  bracket; reconciliation stays local to `cod_ewc.py` with stable IDs first.
- **Quiet interface:** hierarchy comes from type, spacing, alignment, and subtle background shifts.
  The tournament center is one subtle plane, not another wall of bordered cards.

## Verified defect: raw `TBD` on the EWC CoD scoreboard (status: fixed, regression-tested)

Breaking Point identifies the active EWC quarterfinals but intentionally leaves future bracket
participants unresolved. `breakingpoint_client.py` previously converted a missing team lookup
directly to the literal string `"TBD"`. The Phase 1 repair (`184eb21`) introduced structural
pending participants in the backend normalization boundary (`participant: {state: "pending",
feederGameId, outcome, label}`), a narrow EWC/CoD reconciliation layer in `cod_ewc.py`, and
`GameCard` rendering of dependency labels — never a fabricated club, never a bare `TBD`/`TBA`.
The regression suite (`test_cod_ewc_reconcile.py`, incl. `test_no_raw_tbd_anywhere` covering both
`TBD` and `TBA`) pins this. This plan adds one frontend guard so the assertion holds at render too.

## Product shape (corrected IA)

### `/esports` — live broadcast + match board only

The existing board already answers, in order:

1. **What is live now?** One stable featured official broadcast, every other confirmed-live arena
   immediately reachable (broadcast continuity, gap states, up-next).
2. **What is this competition?** Game, stage, teams, series score, and start/live/final state.
3. **What happens today and what finished?** Day-grouped upcoming slate and viewer-local result days.
4. **Where do I make a call?** The existing picks entry.

Contract for this plan: the `/esports` page renders **no** EWC tournament-center elements — no event
focus module, no Club Championship rail. EWC matches are ordinary board rows. `pages/esports.tsx`
contains no EWC module code (Phase B). Non-EWC live content must never disappear.

### `/leagues` — the Esports entry

An Esports card in the `LEAGUES` list (existing league-card design system) linking to
`/leagues/esports`. Already present at `1dab7f7`; kept and verified by test.

### `/leagues/esports` — the complete Esports league destination

Section order (desktop; stacking the same order on mobile):

1. **League-style header/navigation** — breadcrumb to `/leagues`, page title "Esports", one-line
   description, and a persistent "Live esports →" link to the live board.
2. **EWC 2026 tournament center** — the event-focus module: featured live broadcast via the shared
   `LiveCard`/`buildBroadcastViews` machinery (continuity with the board), today's EWC slate across
   titles, and EWC results. One subtle background plane; no nested card walls.
3. **Club Championship rail** — the honest standings surface: rank, club, tabular points, `as of`
   time, source link, visible stale badge, loading skeleton, and the explicit unavailable state
   ("no licensed machine-readable publisher is wired yet — we are not guessing the table"). Real
   `0` points render as `0`; unknown renders as an em dash. Desktop requests ten rows, mobile five
   with an expand action to ten (bounded follow-up request).
4. **Game/title discovery** — pills for every registered title with live/match counts, from the new
   `GET /api/esports/titles` route (one source of truth: the backend registry + the shared slate).
   Each pill links to its title desk `/esports/{slug}`; a secondary link takes the user to
   `/predict?title={slug}`.
5. **Broader non-EWC esports context** — a quiet section linking to the live board (`/esports`, the
   full schedule) and the picks board (`/predict`), so the destination is a league hub, not an
   EWC-only island. No duplicated collectors; the links point at the existing surfaces.
6. **States** — loading skeletons, a fetch-error card with retry, an honest empty state when the
   EWC event is inactive or has no matches, and the rail's current/stale/unavailable states.

Responsive contract: `lg:` two-column (center + rail), single column below; the title pills and any
horizontal nav scroll rather than cram (`overflow-x-auto`); the rail limit follows the viewport
(`matchMedia`), 10 on `>=1024px`, 5 below, expand → 10.

### Club Championship table (preserved contract)

Minimum row contract:

```json
{
  "rank": 1,
  "clubId": "team-falcons",
  "clubName": "Team Falcons",
  "logo": null,
  "points": 2600,
  "eligibleTopEightCount": null,
  "titleWins": null,
  "eligibleToWin": null,
  "movement": null
}
```

Top-level response contract:

```json
{
  "event": "ewc-2026",
  "standings": [],
  "asOf": "absolute ISO timestamp",
  "source": { "label": "...", "url": "..." },
  "status": "current | stale | unavailable"
}
```

`eligibleToWin` stays `null` unless the publisher contains enough per-title placements to compute
the rulebook conditions. If refresh fails, serve the last known good snapshot with
`status: "stale"`; if no valid snapshot exists, show the honest unavailable state rather than an
empty table or zero points. Display semantics are explicit: `0` points means a published real zero;
`null` renders as an em dash and means unknown; movement only between two comparable complete
published runs; eligibility reads only what the source evidence supports; rank ordering follows the
publisher's official tiebreak.

## Data and API design

### Preserved backend contracts (do not regress)

- `GET /api/esports/events/ewc-2026` — the EWC projection over the shared slate, filtered by the
  normalized `ewcEventId` stamped at the backend boundary (never a UI substring search); explicit
  `eventId: "ewc-2026"`; live/upcoming/completed buckets; `active`/`building` so the UI falls back
  honestly when the event expires. Qualifier series stay excluded (`c64f6df`).
- `GET /api/esports/events/ewc-2026/club-standings` — bounded `limit` (1–100) over the published
  snapshot; desktop 10, mobile 5 expanding to 10; honest `unavailable` when no valid publication
  exists; never a self-certified empty success; never silently converts unknown eligibility to
  `false`.
- CoD scoreboard arbitration (`cod_ewc.py` + Breaking Point + PandaScore detail IDs) unchanged.

### New read-only route — `GET /api/esports/titles`

Lives in `backend/routers/esports/predict.py` next to `_title_options` (one source of truth), reads
the already-built shared slate (`esports_upcoming()`, shared cache), and returns:

```json
{
  "titles": [
    { "slug": "call-of-duty", "label": "Call of Duty",
      "match_count": 3, "live_count": 1, "result_count": 5, "next_start": 1786215600000 }
  ]
}
```

No new collector, no new external request — the slate is already fetched and cached by the existing
board path. The client never reconstructs title identity from match labels.

### Request and cache contract (unchanged — this iteration adds zero external requests)

| Host/source | Operation | Calls per cold refresh | Cache/freshness | Failure behavior |
|---|---|---:|---|---|
| Liquipedia MediaWiki API (standings) | complete current-stage population (action=parse, prop=text\|wikitext\|revid) | **1** per operator run (not request-path) | published snapshot; route status current → stale after publisher cadence | retain last good; failed candidate never readable |
| PandaScore `codmw` | bounded EWC match window | reuse existing bulk fetch | existing shared cache | retain BP row/pending state |
| Breaking Point | current/history bracket feed | reuse existing bulk fetch | existing shared cache | existing CDL fallback |
| ESPN hosts | none | 0 | n/a | never introduced as fallback |
| YouTube Data API | none for standings/scores | 0 | existing resolver only | free resolver/fallback policy unchanged |

The standings publisher is now wired: Liquipedia's MediaWiki API (`action=parse` on
`Esports_World_Cup/2026/Club_Championship_Standings`, gzip + descriptive User-Agent; terms
allow API access, no HTML scraping, no request-path fetching). See
`docs/ewc2026/PHASE0-SOURCE-AND-CONTRACTS.md` §2b. Continue to treat the research top ten as
evidence only — the snapshot is the published population.

## Implementation sequence

### Phase A — plan iteration (this document)

Rewrite the plan as the authoritative post-correction contract and commit it separately.

### Phase B — extract the EWC module out of `/esports`

- Move `EwcProjection`, `Standings`, `EwcMatchRow`, `ClubStandingsRail`, and `EwcModule` from
  `pages/esports.tsx` into `components/Esports/EwcModule.tsx` (self-contained, importing the shared
  `LiveCard`/`buildBroadcastViews` machinery and primitives from the board page — one-direction
  dependency, no cycle).
- `pages/esports.tsx` keeps only board code: no EWC types, no EWC components. `Eyebrow`,
  `SectionHeader`, `TeamCrest`, `localDateKey`, `groupTime` remain available to the module (exported
  or copied as pure helpers).
- Update `components/EsportsEwcModule.test.tsx` imports to the new location.

### Phase C — titles route

- Add `GET /api/esports/titles` to `predict.py`; bounded, reads the shared slate.
- Add fixture-driven backend tests (no network): titles derived from the slate, live/match/result
  counts, unknown titles excluded, zero external requests.

### Phase D — league hub build-out

- Rework `pages/leagues/esports.tsx` into the complete destination per "Product shape": header,
  title discovery, EWC center, Club Championship rail, non-EWC context, picks links, and the full
  loading/error/empty/stale state set. Keep the responsive 5/10 standings limit.
- Keep the existing EWC fetch logic (projection + standings) and add the titles fetch; poll the
  projection at the existing cadence; no new collectors.

### Phase E — focused tests

- `/esports`: render the board with mocked fetch; assert no `EWC 2026` module header and no
  `Club Championship` rail, while non-EWC live content still renders (live/non-EWC content not
  lost).
- `/leagues`: render the list; assert the Esports card links to `/leagues/esports`.
- `/leagues/esports`: render the hub with mocked fetch (projection, standings, titles); assert the
  complete product (header, title pills → `/esports/{slug}`, picks links, EWC center, rail) and all
  data states (loading, current, stale, unavailable, inactive/empty, error) plus the responsive
  limit (matchMedia 10 vs 5).
- GameCard: assert pending labels never render raw `TBD`/`TBA`.
- Backend: qualifiers stay excluded (existing suite), titles route (new), projection/standings
  contracts (existing suite) — all fixture-driven.

### Phase F — release gates

- Backend: run the EWC-adjacent pytest suite from the venv interpreter with cwd in `backend/`
  (fixture-driven, zero external requests). All green.
- Frontend: run Jest via the shared binary only (`/root/legendarypicks/node_modules/.bin/jest`)
  from the worktree. All green.
- `git diff --check` clean; secrets scan clean; worktree clean at the end.
- No DEV/production DB write, no managed-service restart, no deploy, no push, no tag move; the
  disposable preview directory `/root/lp-ewc-preview-BIEs6Q` is untouched (Codex rebuilds it).
- Browser verification is out of scope for this iteration by constraint (no next/browser commands in
  the worktree); the static render guarantees are covered by the Jest suite.

## Acceptance criteria

- `/esports` renders no EWC tournament-center elements — proven by test, and by the page file
  containing no EWC module code.
- Non-EWC live content is not lost on `/esports`.
- `/leagues` shows an Esports card linking to `/leagues/esports`.
- `/leagues/esports` renders the complete destination: header/nav, title discovery (pills linking to
  title desks and picks), EWC tournament center (live, today, results), Club Championship rail with
  source/`as of`/stale/unavailable honesty, non-EWC context links, and responsive desktop/mobile
  hierarchy.
- The standings API never emits a self-certified empty success and never silently converts unknown
  eligibility to `false`; the UI shows the honest unavailable state until a permitted publisher
  exists.
- EWC qualifiers stay excluded from the event focus (`c64f6df` preserved, suite green).
- No `/scores` EWC CoD card displays a raw `TBD`/`TBA` team name — backend suite and the new
  frontend guard both prove it.
- The landing page requests only the five or ten standings rows it renders; expanding mobile
  standings performs the bounded follow-up request.
- Zero new external requests; the declared per-host matrix is unchanged.
- Existing Call of Duty league pages, picks, result grouping, stream continuity, and other sports
  scoreboard cards retain their current behavior.
- The EWC APIs and CoD scoreboard reconciliation remain shared backend contracts, unchanged.

## Explicit non-goals for this iteration

- No new collector, no second esports pipeline, no rewrite of the existing esports state machine or
  stream resolver.
- No Ultimate Team, packs, marketplace, or new monetization system; no model probabilities.
- No browser-side scraping and no hard-coded standings, bracket winners, dates, or club totals.
- No DEV/production restart, deployment, database write, or tag move without separate authorization.
- No npm/npx/yarn/next/browser commands from `/root/lp-ewc-2026`; no alteration of
  `/root/legendarypicks/node_modules` or the managed `:3096`/`:8096`/tunnel services.

## Post-implementation decision record

1. **Information architecture — accepted and implemented (2026-08-08).** `/esports` is the live
   broadcast + match board only: the page file contains no EWC tournament-center code (extracted to
   `components/Esports/EwcModule.tsx`), never fetches the EWC endpoints, and keeps non-EWC live
   content. `/leagues` lists Esports with a league card. `/leagues/esports` owns the complete
   destination: header/nav, EWC tournament center (live/today/results), Club Championship rail with
   source/`as of`/stale/unavailable honesty, title discovery pills (`/esports/{slug}` +
   `/predict?title=`), non-EWC live-board context, and the responsive 10/5 standings limit.
2. **Page hierarchy — accepted.** League header first, EWC tournament center second (one subtle
   plane), title discovery third, live-board context last; desktop two-column (center + rail),
   single column below.
3. **Standings rail content — LIVE as of 2026-08-09.** The Liquipedia MediaWiki API (rev 15997)
   publishes the full current-stage population (90 rows) with total points, so the route now
   serves `status: "current"` rows and the rail renders the top ten with source attribution.
   Contribution chips (`eligibleTopEightCount`/`titleWins`) remain `null` — the source does not
   directly expose per-club eligibility evidence.
4. **Final standings data provider — RESOLVED: Liquipedia MediaWiki API.** Terms explicitly allow
   access through the MediaWiki API (no HTML scraping, no browser request-path fetching). The
   operator-run published-first fetcher (`backend/fetch_ewc_standings.py`) is the single writer;
   the research table was never hard-coded or scraped.
5. **Title discovery — new read-only `GET /api/esports/titles`.** Reads the shared cached slate and
   the backend title registry; zero new external requests; client never reconstructs title identity.

### Release-pass evidence — 2026-08-08 (final)

Worktree `/root/lp-ewc-2026` (branch `feat/esports-ewc-2026`, isolated from committed HEAD).
Implementation commits in order: `4735620` plan rewrite, `0c74089` module extraction,
`ccbc866` titles route, `668a160` hub build-out, `c62b40b` focused tests.

**Backend (fixture-driven, zero external requests): 111 passed.** `test_ewc_routes.py` (now with the
titles-route cases), `test_ewc_contract.py`, `test_cod_ewc_reconcile.py`, `test_esports_streams.py`,
`test_esports_predict_api.py`, `test_wc_context.py`. Run from the worktree `backend/` with the main
repo venv interpreter (`/root/legendarypicks/backend/venv/bin/python -m pytest`); no network.

**Frontend Jest (shared binary only — `/root/legendarypicks/node_modules/.bin/jest`): full suite
149/151.** The two failures are the pre-existing `components/Game/WCContext.test.tsx` pair (last
touched by `2f754e2`, untouched by this work). The EWC/league suites: `EsportsEwcModule.test.tsx`
(12, incl. TBD/TBA render guard), `EsportsBroadcast.test.tsx` (2), `EsportsPage.test.tsx` (1 —
no-takeover + non-EWC content), `EsportsLeagueHub.test.tsx` (7 — full product, responsive 5→10
expand, unavailable/stale/error+retry/inactive-empty/titles-error), `LeaguesList.test.tsx` (1).
Zero "not wrapped in act" warnings.

**Request counts (this pass: zero external requests).** All backend tests fixture-driven; the Jest
suites mock `fetch`/`matchMedia`. The per-host matrix is unchanged: PandaScore 1 bracket call per
120 s cold window plus existing bulk title feeds (shared caches); Breaking Point existing 300 s
cache; ESPN 0 (never introduced); YouTube Data API 0 for standings/scores. `GET /api/esports/titles`
adds no collector — it reads the already-cached shared slate.

**Candidate vs DEV/production.** Everything above ran in the isolated worktree only. No DEV or
production DB write, no managed-service restart, no deploy, no push, no tag move. The disposable
preview directory `/root/lp-ewc-preview-BIEs6Q` was not touched (Codex rebuilds it). No
npm/npx/yarn/next/browser command was run from the worktree; `node_modules` is the untouched shared
symlink.

**Remaining blockers.** (1) Club Championship standings: no permitted machine-readable publisher
resolved; the honest unavailable state ships until one exists. (2) Hydrated browser verification of
the hub remains out of scope by constraint (no next/browser commands in the worktree); static render
guarantees are covered by the Jest suite, and the preview environment is Codex's to rebuild.

**Hygiene.** `git diff --check` clean; secrets scan across the five commits and this plan: zero
matches; worktree clean at completion.

## Post-review gap and correction — 2026-08-08 (public preview review)

**Reviewer finding:** `cf55c5f` is visibly too shallow. It leaves the EWC block largely unchanged and
adds a title directory plus outbound links; that is not the complete Esports league page requested.
**Status:** REJECTED as final; corrected in the follow-up commits on this branch.

### Concrete acceptance criteria for the corrected hub

1. **EWC-first, preserved at top.** The EWC 2026 tournament center (event focus, live, today across
   titles, results, Club Championship rail with the honest unavailable state) remains the top
   section and is not degraded.
2. **Inline all-esports board — no link card.** The hub renders the broader esports live, upcoming,
   and recent-results content directly below the EWC center, from the existing
   `GET /api/esports/upcoming` contract, using the existing shared UI (`LiveNow` and the day-grouped
   `UpcomingSlate` row rendering) wherever practical. Non-EWC live matches render inline, not just
   via an outbound link.
3. **Obvious in-page navigation.** Tabs: **EWC · Live & Upcoming · Results · Games · Picks**.
   Client-side tab state; EWC is the default tab; the tab bar scrolls on mobile and is sticky
   enough to be unmistakable.
4. **Interactive title controls that filter content.** The Games tab gives each title useful
   context — live now, next match, most recent result with teams/times/scores — not counts alone.
   Selecting a title **filters the rendered live/upcoming/results content** (a visible filter chip
   with a clear action), and each title keeps deep links to its desk (`/esports/{slug}`) and picks
   (`/predict?title={slug}`).
5. **`/leagues` retains Esports; `/esports` is not taken over.** The live board page file stays
   board-only; the hub's tabs replace the old link-card section.
6. **Club Championship honesty.** Standings stay `status: "unavailable"` until a permitted
   machine-readable publisher exists; never invent rows, never show a zero-point table.
7. **States + responsive.** Loading skeletons, error + retry, and empty states for each data source
   (projection, standings, titles, upcoming); desktop two-column where useful and clean
   single-column stacking on mobile.
8. **Tests.** Focused Jest tests prove: inline live/upcoming/results content renders from the
   upcoming payload (not merely links), title filtering interactively narrows the board and clears,
   and tabs switch sections. The existing no-takeover, `/leagues`-card, standings-state, and EWC
   module suites stay green. The backend suite stays green (no contract change).
9. **Preview + browser gate.** Rebuild only the disposable preview `/root/lp-ewc-preview-BIEs6Q`
   (:3105/:8105) and browser-verify the public `/leagues/esports` route with **zero console/page
   errors**. No managed DEV, no merge/push/deploy, no DB write.

### Post-review implementation evidence — 2026-08-08 (final)

Commits on this branch after the gap record: `46409bb` (this gap + acceptance criteria), `78eb91b`
(hub completion), `559a698` (focused tests).

**Implementation.** `/leagues/esports` is now a materially complete league destination: EWC 2026
tournament center stays the default (first) tab; Live & Upcoming and Results tabs render the
broader all-esports board inline from the existing `/api/esports/upcoming` contract using the
shared `LiveNow` player and `UpcomingSlate` `schedule`/`results` variants (no link card); Games tab
shows per-title live/next/recent context with desk + picks deep links and the title controls
filter the rendered live/upcoming/results content (visible chip + clear); Picks tab links the picks
board and every title flow; loading skeletons, error + retry, and empty states per data source; the
tab bar scrolls on mobile. `/esports` page file was touched only to make `UpcomingSlate` reusable
(`variant` prop) and fix a stale footnote — no tournament-center takeover. Club Championship
standings stay honest `unavailable` (no permitted machine-readable publisher; no invented rows).

**Backend: 111/111** (fixture-driven, zero external requests) — unchanged contracts.

**Frontend Jest: 154/156** — the two failures are the pre-existing `components/Game/WCContext.test.tsx`
pair (untouched). The hub suite (12 tests) now proves: inline live/upcoming/results content renders
from the upcoming payload (not merely links), interactive title filtering narrows the board and
clears, tabs switch sections, board loading/error states, plus the earlier EWC-first, standings
honesty, and responsive 10/5 guarantees. Zero "not wrapped in act" warnings.

**Browser gate (public route) — PASS, zero console/page errors.** `scripts/verify-hub-browser.js`
(playwright + installed chromium, run from the preview dir) against
`http://5.252.52.108:3105/leagues/esports`: desktop walk renders the EWC module, Club Championship
rail with the honest unavailable state, all five tabs, 8 Games desk links + 13 context lines, the
filter chip and its persistence on the Live tab, and the Picks board link — `errors: []`; mobile
(390px) renders the EWC center with a scrollable tab bar — `errors: []`; `/esports` shows no EWC
module (no takeover) — `errors: []`; `/leagues` lists the Esports card. The only excluded events are
third-party (YouTube embed telemetry) and `net::ERR_ABORTED` image teardown aborts, both verified
non-failures (sample logo URLs return 200).

**Preview environment fix (root cause, documented).** The preview frontend's `/api` rewrite target
is baked into `.next/standalone/.next/routes-manifest.json` at `next build` time — `next start` does
not re-evaluate `next.config.js` `rewrites()`. The first rebuild baked the default
`http://localhost:8000` (nothing listens there) → all esports APIs 500'd through the proxy. Rebuilt
with `API_PROXY_TARGET=http://127.0.0.1:8105`; all four esports endpoints now proxy 200.

**Candidate vs DEV/production.** All of the above ran in the isolated preview and worktree only. No
managed DEV change, no merge/push/deploy, no DB write, no tag move; `/root/legendarypicks` and the
managed `:3096`/`:8096`/tunnels untouched. Worktree clean; `git diff --check` clean.

## Club Championship standings — source resolution and live snapshot (2026-08-09)

The earlier blocker ("no permitted machine-readable publisher") is **closed**. The accepted
source is **Liquipedia's MediaWiki API** (terms explicitly allow API access; no HTML scraping,
no request-path fetching). See `docs/ewc2026/PHASE0-SOURCE-AND-CONTRACTS.md` §2b for the full
contract.

### Fetcher contract (published-first, one writer)

- `backend/fetch_ewc_standings.py` — operator-run; **one** `action=parse` call
  (`prop=text|wikitext|revid&format=json`, gzip `Accept-Encoding`, descriptive
  `User-Agent: LegendaryPicks/1.0 …`).
- Stage selection from wikitext: `current-stage=N` → `stageNcutoff=C` → the current-stage table
  (`data-toggle-area-content="C"`). Malformed/missing stage or cutoff → the run fails, nothing
  is published.
- Population: **every** row of the current-stage table must parse (rank, stable Liquipedia
  team-page slug as `clubId`, `clubName`, bold total points, optional movement/logo). A single
  unparseable row fails the run — no silent partial ingest. `sourceReportedClubs` =
  `fetchedClubs` = the parsed count (90 at rev 15997); for this source the table IS the
  population.
- Validation (before atomic `os.replace`): revision present, unique clubIds, exact count,
  numeric nonnegative points, publisher ordering (ranks non-decreasing, points non-increasing,
  equal points → equal rank, fewer points → strictly greater rank), event/publishedAt, and the
  point-regression gate (override with `--correction`). A failed candidate never becomes
  readable; the last good snapshot survives. `--dry-run` fetches + validates without writing.
- Source attribution in the snapshot: label, page URL, API revision, stage/cutoff,
  fetched/published timestamps, `sourceReportedClubs`, checksum (sha256 of the sorted rows).

### Validator change (ties)

Real published rankings contain **tied ranks** (rev 15997: tied 4th Team Vitality 2200 /
Virtus.pro 2200; tied 6th T1 1750 / Team Vision 1750). The old validator rejected duplicate
ranks outright; it now accepts equal ranks with equal points and rejects tie mismatches
(equal points / different rank), rank regression, and point regression.

### Committed snapshot + behavior

`backend/data/esports_ewc_standings.json` (rev 15997, stage 5, 90 clubs) is committed, so
`GET /api/esports/events/ewc-2026/club-standings` immediately serves `status: "current"` with
rows and source attribution; the hub rail renders the top ten (10 desktop / 5 mobile + expand)
with the Liquipedia source link. When the snapshot ages past the publisher cadence the route
serves `status: "stale"` and **retains the rows**. Eligibility fields stay `null` (the page
does not expose per-club eligibility evidence).

### Release-pass evidence — 2026-08-09

- Backend suite: **130/130** (fixture-driven, zero external requests at test time) including the
  new `test_ewc_standings_fetcher.py` (13 tests: stage selection + malformed stage, exact
  90-row population, top rows vs the research snapshot, stable slugs, ties accepted, tie
  mismatch / rank regression / point regression / duplicate clubId / incomplete population
  rejected, last-good survival, stale retains rows) and the tie-aware contract tests.
- Jest: **154/156** (only the pre-existing `WCContext` pair fails; the rail suites are
  fixture-mocked and unaffected).
- Live run: `venv/bin/python fetch_ewc_standings.py` fetched rev 15997, parsed stage 5
  (cutoff 19, 90 clubs), validated, and published the committed snapshot
  (`sourceReportedClubs=90`, checksum `c4ad5932bb7c…`). Route read-back:
  `status: "current"`, 10-row limit, top 5 incl. ties, source label/url, `asOf` timestamp.
- Browser gate on the rebuilt preview: standings rows render (top 10), the Liquipedia source
  link is present and opens the source page, mobile requests 5 rows and expands to 10, zero
  page/console errors (verified on the public route `http://5.252.52.108:3105/leagues/esports`).
- Constraints: no request-path network calls (the route reads only the snapshot file), no HTML
  scraping, no DB write, no managed DEV change, no merge/push/deploy.

### Club logos on every standings row — 2026-08-09 (follow-up)

- **Fetcher:** `normalize_logo_url` upgrades protocol-relative (`//liquipedia.net/…`), relative
  (`/commons/…`), and `http://` publisher image URLs to absolute HTTPS; junk/missing → `None`.
  `parse_rows` takes the row's first team image. `build_snapshot` reconciles against the
  maintained `backend/data/esports_team_logos.json` index by **exact canonical-key match**
  (`_canon_team`, the identity the index is built with) — a verified non-empty local mapping
  wins, empty cached negatives never replace a publisher logo, and ambiguous clubs are never
  matched by loose display-name guesses. Re-published rev 15997: 90/90 logos, row payload
  checksum unchanged (`c4ad5932bb7c…`) — today no EWC club has a local mapping, so publisher
  logos carry every row.
- **Rail:** `ClubLogo` renders a fixed 20px slot (layout-shift prevention), `object-contain`,
  alt text (`<Club> logo`), lazy loading, and a neutral initials fallback when no verified logo
  exists or the image fails (`onError`). Unavailable-state copy updated (snapshot readability is
  the gate; the publisher is wired).
- **Tests:** 13 new fixture-driven fetcher tests (relative/protocol-relative/absolute/http
  normalization, junk → None, missing logo, local-wins / absent-keeps / empty-not-used /
  no-fuzzy-match / local-fills-missing / real-fixture reconcile) and 3 new Jest rail tests (logo
  + alt + fixed width; initials fallback with zero `<img>`; `onError` → initials). Backend
  **143/143**; Jest **157/159** (pre-existing `WCContext` pair only).
- **Preview (disposable):** browser gate on `127.0.0.1:3105/leagues/esports` — desktop rail
  renders **10 club logos** (top ten), mobile renders **5** collapsed and **10** after expand,
  standings rows/points/source link intact, `errors: []` everywhere. (The preview frontend was
  externally restarted loopback-only at 19:34, so the gate ran against the preview itself on
  `127.0.0.1`; the public `:3105` exposure is no longer bound.)
