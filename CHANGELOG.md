# Changelog

All notable changes to Legendary Picks are documented here.

Versioning follows [Semantic Versioning](https://semver.org): `vMAJOR.MINOR.PATCH`.
- **MAJOR** — breaking changes / major product milestones (still `0` pre-launch).
- **MINOR** — new features, backwards-compatible.
- **PATCH** — bug fixes, backwards-compatible.

Each released version corresponds to a git tag and a production deploy. The version
in `package.json` tracks the next (in-development) release.

> Note: a stray `package.json` version of `0.3.1` predated this scheme and was never a
> real release. Disciplined versioning starts here, with the current production state
> tagged `v0.1.0`.

## [Unreleased]

## [0.4.5] — 2026-07-17

Minor: market-first props board, leagues-page refactor, non-WC game times, nicer predict loading.

### Added
- **Market-first props board** (`components/Props/MarketSlateBoard.tsx`) — pick a stat → every
  player's line across the slate, each with the last-N `PropChart` + hit rate, sortable by edge.
  (Charts populate where we have player logs — MLB now; UFC/WC lack game history so their charts are
  empty for now, pending the individual-sport stats DB.)
- **UFC Rankings tab** on the leagues hub.

### Changed
- **Non-WC/UFC game times** — `/api/props/ingest` now accepts + stores `start_time`, so MLB/NBA/NHL/NFL
  slate cards carry kickoff times (previously WC/UFC only, via their direct-DB paths).
- **Leagues hub page split** — `pages/leagues/[league].tsx` (1,300+ lines) decomposed into focused tab
  components + data hooks under `components/Leagues/`. Behavior-preserving: 34/34 render-harness checks
  pass (nfl/wc/ufc).
- **Predict** loading is now a skeleton placeholder instead of a "Loading…" string.

> Next (→ v0.5.0, pending review): rename this board's tab to **Props**, restore a real **Slate** =
> the day's games (game-based, linking to per-game props via `GameProps`), and retire the Lines tab.

## [0.4.4] — 2026-07-17

Minor: UFC props — the first custom individual-sport prop system — plus all-leagues ingest routing.

### Added
- **UFC props on the board.** A custom parser (`_parse_ufc_props`) maps Bovada's Method of Victory
  market to per-fighter yes/no props (`win_by_ko` / `win_by_submission` / `win_by_decision`, o0.5) —
  the WC anytime-goal shape applied to fighters, and the template for tennis majors next. Fighters are
  ingested as players via a direct-DB path (`_ufc_direct_ingest`) with kickoff times. UFC added to the
  props page league filter. (Fight-level markets — total rounds, go-the-distance — are deferred; they
  need a game-level prop representation the schema doesn't have yet.)
- The props page **defaults to the All league** (was MLB), so the whole upcoming slate shows on open.

### Changed
- **Prop ingest now routes per prop-league**, not the CLI arg: `bovada_scraper.py all --ingest` sends
  WC + UFC to their direct-DB paths and every other league to the resolver API, and derives each game's
  date from the Bovada startTime instead of "today".

## [0.4.3] — 2026-07-17

Patch: the props board shows the upcoming slate grouped by date, with game times.

### Added
- **Game kickoff time on each slate card** — `prop_games` gains a `start_time` (derived from the
  Bovada event startTime), stored on WC ingest, surfaced through `/api/props/slate`, and shown on the
  card. (Requires the additive `ALTER TABLE prop_games ADD COLUMN start_time TEXT` on deploy.)

### Changed
- **Props slate is now the UPCOMING board**: `/api/props/slate` without a date returns today-forward
  games (dropping months-old stale games that never pruned), and the Slate tab groups them into
  per-date sections instead of one day at a time. The page also lands on the nearest date that has
  props, so it no longer opens blank on a fixture-less day (props post ~a day before a match).

## [0.4.2] — 2026-07-17

Patch: a non-English broadcast no longer takes the auto-playing hero over an English one.

### Added
- **Backend surfaces the stream `language`** (it was computed for stream ranking but dropped before
  output) and an authoritative **`foreign`** flag per match, from: titles with no English broadcast
  (King of Glory / Honor of Kings), the chosen stream's own language tag, foreign-only streaming hosts
  (bilibili/huya/douyu/…), and locale-suffixed channels.

### Changed
- **A non-English broadcast is demoted in `prominence`** below every English/unknown one, so it can no
  longer grab the auto-playing hero (King of Glory went 210 → −790) while still showing on the board.
  Competitive prestige (`tier`) is unchanged — this is a separate language axis. Replaces a fragile
  client-side language heuristic with the authoritative backend signal.

## [0.4.1] — 2026-07-16

Patch: a stable per-broadcast stream identity, and an `/esports` rewrite that renders every broadcast.

### Added
- **Stable `streamKey` + `eventId` on every match** (backend) — a channel-level stream id
  (e.g. `twitch:callofduty`) and the PandaScore `serie.id`, both of which survive a match finishing.
  A finished match's `watch` degrades to a bare web link and loses its stream key; these fields are
  recovered from the persisted PandaScore streams/serie (with a `(title, team-pair)` fallback for
  archived rows), so a broadcast's games — including the finished ones — group onto one stream.
- **CoD league page + grounded match-detail pages** (`/cod`).

### Changed
- **`/esports` builds an independent view per proven `streamKey::eventId` broadcast** — each renders
  Live / Final + Up Next / Starting soon. Prominence only orders the views and picks the hero rather
  than gating whether a stream shows. Parallel channels in one event stay separate; the `event:<id>`
  fallback is never grouped as a broadcast (no merging YouTube-only arenas); the same iframe survives
  Final → Starting soon → Live.

## [0.4.0] — 2026-07-16

The 0.3 → 0.4 milestone. This minor rolls up everything shipped since v0.3.2 — the incremental
steps were tagged `v0.3.3` (Leagues Hub + Pick Desk) and `v0.3.4` (World Cup intelligence + board
dupe fix); v0.4.0 adds Call of Duty and promotes the whole arc to production.

### Added
- **Call of Duty (CDL) on `/esports`** — registered Call of Duty as an esports title, so Call of Duty
  League matches (the Championship, and future Majors) surface on the board with Bovada odds, live
  state, PandaScore scores/winner/logos, the official broadcast, and picks — reusing the existing
  Bovada-schedule + PandaScore-enrich + YouTube-resolver pipeline (no new pipeline).
  - Tier-aware: the pro CDL is a flagship international circuit (Tier 0); "Call of Duty Challengers"
    (development ladder) stays Tier 2, and qualifiers demote as usual. CoD Champs is ranked as the
    season-finale event so it outranks the mid-season Majors.
  - Stream: official CDL YouTube channel (@CODLeague, Data-API-resolved) for the live embed, with a
    "where it'll air" fallback for scheduled matches.
- **Leagues Hub** — per-league tabbed pages with full completed-season team-stat parity for NBA / NHL
  / NFL / MLB, player stat categories with advanced controls, recent-form evidence, and WC knockout
  standings. _(tagged v0.3.3)_
- **Pick Desk (`/predict`)** — free binary esports picks with a record header, callable matches, a
  settled-picks list, crowd/Bovada reveal after picking, contrarian scoring, and a pick/crowd/
  leaderboard ledger; labeled as Esports. _(tagged v0.3.3)_
- **World Cup intelligence** — WC props (Phase 1) on `/props`; game-detail context (broadcast +
  market + form), a **"From the Booth"** tab of live broadcast reads, **"The Read"** synthesized
  intel tied to Bovada props, and an optional **discount play** (team, player, or none). _(tagged
  v0.3.4)_

### Fixed
- **Class-A display-duplicate suppressor** on the esports board — collapses pure casing/spacing/punct
  team-name twins at the same start time (e.g. `PARIVISION`/`Parivision`), leaving true rematches and
  name-variants logged-not-merged. _(tagged v0.3.4)_
- Esports durability (15-min prod board warmer, 7-day results retention, key self-hydration), Leagues
  Hub UI fixes (flicker, Stats-tab revert, NHL standings), and a league-agnostic footer disclaimer.
  See v0.3.3 / v0.3.4 for the full list.

## [0.3.4] — 2026-07-16

World Cup intelligence: what the market says vs what the booth sees.

### Added
- **World Cup props (Phase 1)** on `/props` — display-only prop lines scoped per ESPN game, with
  automated odds refresh.
- **Game-detail intelligence** — replaced the AI "story" with a grounded game context (broadcast +
  market + form), a **"From the Booth"** tab (live broadcast reads, roster-normalized and deduped),
  and **"The Read"** — a synthesized intel summary tied to Bovada props and data-authoritative
  grounding (per-team stats labeled to stop home/away mixups; goal-scorer vs assist disambiguated).
- **Discount play** — an optional value lean (team, player, or none) surfaced when the booth's read
  makes a market-priced-unlikely outcome more plausible; never a forced prop.
- Player props moved into their own tab on the game-detail page.

### Fixed
- **Class-A display-duplicate suppressor** on the esports board — collapses pure casing/spacing/punct
  team-name twins at the same start time (e.g. `PARIVISION`/`Parivision`) while deliberately leaving
  same-name/different-time rematches and true name-variants logged-not-merged.

## [0.3.3] — 2026-07-15

Leagues Hub and the Pick Desk.

### Added
- **Leagues Hub** — per-league tabbed pages with full completed-season team-stat parity for NBA / NHL
  / NFL / MLB, player stat categories with advanced controls, recent-form evidence, and WC knockout
  standings. MLB recent-changes evidence for batting categories.
- **Pick Desk (`/predict`)** — free binary esports picks with a record header, callable matches, a
  settled-picks list, crowd/Bovada reveal after picking, contrarian scoring, and a pick/crowd/
  leaderboard ledger. Labeled as **Esports** (badge + copy); plainer copy throughout.
- **Esports durability** — in-app prod board warmer (15 min) to keep the lazily-cached slate fresh
  without organic traffic; results retention extended 3→7 days; API keys self-hydrate at startup.

### Fixed
- Leagues Hub: sub-view flicker, Stats tab reverting after async leaders fetch, double-fetch on
  player-stat category switch; NHL Standings Win% `0.0%` and L10 `0 PTS`; date-aware schedules; UFC
  rankings served from package when the prod cache is empty.
- Footer disclaimer made league-agnostic (was hardcoded NBA). FIFA World Cup shown as the league
  title (keys unchanged).

## [0.3.2] — 2026-07-12

Hotfix: scores page alignment.

### Fixed
- **Scores page** — removed the winner arrow (`◄`) from final score cards. It rendered only on the
  winning team's row, pushing that score out of vertical alignment with the loser's. The winner is
  already indicated by the brighter score/name (loser dimmed), so the caret was redundant as well as
  misaligning.

## [0.3.1] — 2026-07-10

Esports polish + the deploy fix that makes the board work in production.

### Added
- **"Building the board" state** — while the slate warms on a cold rebuild (~30–40s the backend
  returns an empty `building` board), show skeleton match rows under a live-signal eyebrow instead
  of a misleading "no matches" message.

### Changed
- **Desktop live cards drop the inline preview** — at `sm` and wider an Also-live card's only action
  is "watch in featured player"; the redundant show/hide-preview toggle is gone. Mobile keeps inline
  "watch here". MSI compact card follows the same rule.

### Fixed
- **Prod backend gets its esports source keys** — the Docker Compose backend now forwards
  `PANDASCORE_API_KEY` / `GRID_API_KEY` / `YOUTUBE_API_KEY` (host-shell pass-through, like the
  DeepSeek key). Without them the containerized board silently degraded — no truth layer, no live
  scores, no stream resolution. Source `/root/.hermes/.env` before `docker compose up`.

## [0.3.0] — 2026-07-10

Esports control-room release — a more reliable slate pipeline and a desktop viewing experience
that treats the featured player as the center of the live page.

### Added
- **Desktop featured-player handoff** — selecting an Also-live match promotes it into the hero and
  returns the displaced hero to its normal prominence-ranked grid position. The rich MSI hero joins
  the same exchange as the source-ranked match cards.
- **Optional inline previews** — every Also-live card offers Show preview / Hide preview beneath its
  featured-player action without mounting every stream at once.
- **MSI game-state layout control** — an icon docks live state below the full-width broadcast
  (the default) or in the right rail, with the explicit choice persisted locally.

### Changed
- **Slate backend decomposed by ownership** — `slate.py` is now a 582-line route/rebuild orchestrator
  (down from 1,222 lines); team identity, source adapters, and lifecycle/clustering live in
  `match_identity.py`, `slate_sources.py`, and `slate_state.py`.
- Simplified redundant live indicators while preserving the prominence-ranked live order.

### Fixed
- Single-flight cold-cache rebuilds prevent concurrent first requests from pinning the backend.
- A confirmed official broadcast can promote a source-stuck scheduled match to Live without adding
  blocking network checks to the rebuild path.
- Restored the previously stale zombie-state assertion suite against the extracted state module.

## [0.2.6] — 2026-07-09

Esports slate correctness — team-identity matching, stream switching, and result repair.

### Added
- **YouTube-default stream switcher** on every live card — English-YouTube-first source order
  (trusts backend ranking), with Twitch/Kick as one-tap fallbacks. MSI unified into the
  live-now section as the featured slot; prominence-based ordering (tier + stage).
- **`docs/ESPORTS-EXPECTED-BEHAVIOR.md`** — state-machine invariants, matcher fail-closed
  allowlist, stream ranking, and Results-gap policy (read before editing esports code).

### Changed
- Slate section renamed **"Schedule & Results"** (from "What's next"), redundant subtitle dropped.

### Fixed
- **Team matcher hardened** — word-boundary affix + vowel-elision matching; same-org sub-rosters
  stay split via an allowlist; `ex-<org>` treated as a **distinct** team (no prefix stripping);
  accent-fold + generic-aware camelCase canon; `LVLUP == Level UP` dedup; relaxed same-match
  merge governed by the "one team, one time" physical invariant.
- **Streams** — verify attested Twitch liveness and drop dark streams; narrow YouTube resolution
  by game before team/arena; drop the dead link when every candidate is dark.
- **Slate** — reconcile reschedules and purge map (`LMap`) markers; group Scheduled/Results by
  stable calendar day; resolve EWC + minor-league result holes; correct flipped team crests.

### Performance
- Precompute PandaScore name-token/canon sets — enrich **7.8s → 0.7s**.
- Moved YouTube resolution off the rebuild path (async background pool).

## [0.2.5] — 2026-07-08

Live "cheap quality" trading surface, a momentum engine, and esports-board hardening.

### Added
- **"Cheap Quality, Live" widget** — the value-discount trading strategy as a live scores-page
  surface. Grew from v0 (MLB) → edge-vs-live-win-probability → **Class C** pre-priced discount
  + World Cup wiring → **Class D** gift-fade. Guarded against value traps and knife-catching
  (form gates, witching-hour contest, rally-evidence requirement); renders nothing when no live
  cards; no "favorite" chip below 55%.
- **Momentum engine (phase 1)** — Wilder dual-MA core with MLB player/team adapters and a
  cross-feed API; live level outputs phase labels (crash-cycle frame).
- **Stakes engine** — every AI summary now leads with what the game *is*.
- **4-level esports league-tier taxonomy** + tier-sort and odds-or-stream visibility filter;
  per-day results archive in the state monitor.

### Fixed
- Stop fabricating winners from ambiguous Kalshi settlements — wait for real results.
- Official team names on merged rows; Bovada live-map phantom filter; Poor Rangers / "Power
  Ranger" alias dedup; zombie-live freshness gate + persistent `ended_unknown` label.
- RES Showdown reclassified as a real BLAST Premier qualifier (not Tier-3 novelty).
- **EWC YouTube streams** resolved via the Data API + a free channel-streams scrape (no quota).

### Changed
- Version corrected from a mistaken `0.3.0` minor bump back to the `0.2.5` patch.

## [0.2.4] — 2026-07-03

Live esports hub — the big one: real-time broadcast, scores, and game-detail depth.

### Added
- **Live esports hub** — hero + tabs, GRID/frag live scores, verified in-app broadcast embeds.
  Live games surfaced above the fold (multi-live grid, not buried in Scheduled); the featured
  match auto-plays, the rest are tap-to-watch.
- **Broadcast embedding** — GRID-official CS2/Dota adapter via tournament→channel map; frag.se
  per-match live source; YouTube / Twitch / Kick embeds; stable featured-match pick (stop the
  flipping); unmuted stream audio. Overwatch added as a covered title.
- **Game-detail tabs** — box score / play-by-play / game info for MLB, NFL, NBA, NHL, and the
  World Cup, each fed by per-tab backend endpoints.
- **Scores page** — winner arrow (`◄`) + "Final/N" on cards (ESPN parity); Live-Now discovery
  banner; feature-one-live-big with "+N more" reveal; **free World Cup audio** (iHeart's direct
  AAC stream, US-accessible).
- Kalshi settled-market result fallback for unsourced matches; acronym team-name bridging.

### Changed
- Slate rewritten as an **explicit state machine** with unified identity; PandaScore truth layer;
  canonical dedup key; zombie-live matches killed; on-air freshness gate.

### Fixed
- Box score gated on game state (scheduled games no longer render a zeros table identical to a
  final); tennis "P3" → "Set 3"; NFL/WC cards clickable to their detail pages; soccer lineup
  React crash + robust minute parse.

### Performance
- Parallelized upstream fetches, memoized match-matching, stale-while-revalidate serving.
- Split the 1162-line esports monolith into a package.

## [0.2.3] — 2026-06-28

Hotfixes shipped to prod.

### Fixed
- **Footer pinned to the viewport bottom** on short pages — the layout wrapper is now a flex
  column with `main` growing (`flex-1`), so the footer stops floating mid-page on the homepage.
- **App icons + favicon: transparent corners** — circular alpha mask applied to every `logo-*.png`,
  `apple-touch-icon.png`, and a rebuilt `favicon.ico`, removing the black square corners while
  keeping the holographic disc and the black "LP" mark intact.

## [0.2.2] — 2026-06-28

### Added
- **Stats (league) tab** — `GET /api/{league}/leaders` leaderboard + a **Players | Teams**
  sub-view toggle on the Stats page; MLB batting/pitching toggle. Player names link to `/player/[id]`.
- **NBA matchups** — the Matchups tab now works for NBA (per-game logs got `opponent`/`home_away`
  via `ingest_nba_logs` fix + `backfill_nba_opponent.py`), no sportsbook data needed.
- **NBA edge slot** on the game page — projected stat lines where NBA has no posted props
  (`/api/game/{lg}/{id}/edge`).
- **AI game previews generated on discovery** — loading a scoreboard warms the preview cache in
  the background (`_core.kick_game_stories` on `/api/{league}/games`), so the preview is instant
  on click instead of making the first viewer wait ~7s. `pregenerate_game_stories.py` backfill helper.
- **Projection-vs-line badge** on player-page prop rows.

### Changed
- **Backend de-monolithed** — `sports_service.py` (2125 lines / 30 routes) split into a thin app
  shell + `routers/{games,players,props,analytics,game_extras}.py` + shared `_core.py`.
- **Frontend game page** split into `components/Game/*`.
- **Analytics tab removed** from the nav (EV all-zero / CLV empty per the M7 audit; deferred).
- Stats tab kept the name **"Stats"** (briefly "Leagues"; reverted pending the richer-stats build).

### Fixed
- Game-state labelling — never show "FINAL" on a live/upcoming game (state-aware ScoreStrip).
- Removed the World Cup dead-click (no detail page exists for WC).

### Docs
- Engineering retro (`docs/RETRO-2026-06-27.md`), next-phase spec
  (`docs/SPEC-2026-06-27-next-phases.md`), AGENTS `§0` current-state pointers.

## [0.2.1] — 2026-06-27

### Added
- **Player page** — `/player/[id]` + `/api/player/{id}`: header, current props (with charts),
  projections, recent games — reached via a new **global player search** in the header
  (search icon on mobile, inline on desktop).
- **Prop visualization** — `<PropChart>` + `/api/props/history`: bar chart of last N games vs
  the line + hit rate + projection, with L5/L10/L20 + home/away + vs-opponent filters. Replaces
  the retrospective ✅/❌ in Props·Lines.
- **MLB pitcher game-logs** — pitcher props (strikeouts/outs/hits_allowed) now chart.
- **Matchups tab** — live player-vs-opponent splits (was a stub).
- `opponent` / `home_away` added to game logs (+ backfill).

### Fixed
- **MLB identity dedup** — merged 317 duplicate player rows; batter prop-chart coverage 53%→90%
  (Freeman/Betts/Kurtz now resolve). `dedupe_mlb.py`.
- Prop market mapping — league-keyed + `total_*` Bovada names + `_base_market` normalization.
- Header nav hidden on mobile; dev frontend silently proxying to prod (`.env.local`).

### Docs
- `IDENTITY-SPINE-STATE.md` + the resolve-or-queue rule in `AGENTS.md §7`.

## [0.2.0] — 2026-06-26 — analytics-backbone (cut; not yet deployed)

### Added
- **Per-game player logs** (`player_game_logs`) across all four leagues — 111k+ logs,
  spine-resolved. The stats foundation projections/fantasy run on, no sportsbook data needed.
  Ingests: NFL weekly 2024 + NFL play-by-play 2025 (EPA/CPOE/air-yards), MLB Statcast,
  NHL nhle.com game-log, NBA ESPN box scores.
- **Player projections** — `/api/projections/player/{id}` + the **Model tab**: recency-weighted
  expected value, floor/median/ceiling, P(over a line), and projected fantasy points.
- **roster_sync** — current ESPN rosters populate `espn_id` and a meaningful `active` flag.
- **World Cup standings** consolidated into the Stats tab as a league option.
- **Tennis scoreboard cards** show per-set game scores (parsed from ESPN `linescores`)
  in a proper scoreboard layout — each player's games-per-set as aligned columns.

### Changed
- **NFL identity dedupe** — removed 380 id-less orphan player rows that shadowed real players
  (distinct same-name players preserved).
- **Standings** page removed; folded into Stats.

### Fixed
- `/api/player/{id}/stats` raised `NameError('now')` on every call — the Performance tab's
  advanced-stats panel was dead for all leagues.
- World Cup / COD live badges (match clock + game number display).
- World Cup winner dimming (winner flag now reaches the frontend; draws no longer dim both sides).

## [0.1.0] — 2026-06-26 — production baseline

First tagged release. Snapshot of what was live on prod:
- backend `dee1133` (COD/breakingpoint scoreboard fix)
- frontend `b4ae8f9` (~2 commits behind backend on the `dev` line — a known deploy drift)

Includes the ESPN-based sports backend, scores/standings/predict/props/stats/analytics pages,
settlement pipeline, odds capture, and EV/CLV/calibration analytics (M1–M7).
