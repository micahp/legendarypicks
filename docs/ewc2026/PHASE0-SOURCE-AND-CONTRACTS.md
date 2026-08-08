# Phase 0 — EWC 2026 source contracts and fixtures

**Plan:** `docs/PLAN-esports-ewc-2026.md` · **Branch:** `feat/esports-ewc-2026` (worktree `/root/lp-ewc-2026`)
**Captured:** 2026-08-08 ~13:20–13:30 UTC

## 1. Fixtures captured (committed, with source timestamps)

| Fixture | Source | Captured (UTC) |
|---|---|---|
| `fixtures/cod-games-2026-08-08T1320Z.json` | `GET /api/cod/games` (dev :8096, Breaking Point feed) | 13:20 |
| `fixtures/esports-upcoming-2026-08-08T1320Z.json` | `GET /api/esports/upcoming` (dev :8096) | 13:20 |
| `fixtures/breakingpoint-raw-2026-08-08T1325Z.json` | breakingpoint.gg `/_next/data/<build>/matches.json` | 13:25 |
| `fixtures/pandascore-ewc-cod-brackets-2026-08-08T1325Z.json` | `GET api.pandascore.co/tournaments/21576/brackets` | 13:25 |
| `fixtures/pandascore-codmw-upcoming-2026-08-08T1325Z.json` | `GET api.pandascore.co/codmw/matches/upcoming` | 13:25 |
| `fixtures/pandascore-codmw-serie10834-matches-2026-08-08T1330Z.json` | codmw upcoming+past feeds, serie 10834 filter | 13:30 |
| `fixtures/pandascore-ewc-league-series-2026-08-08T1326Z.json` | `GET api.pandascore.co/leagues/5283/series` | 13:26 |
| `probes/rulebooks-page-2026-08-08T1325Z.html`, `probes/bundle-index.js`, `probes/wayback-club-championship.html`, `probes/api-root-probe.txt` | official EWC hosts + web archive | 13:23–13:25 |

### 1a. Verified defect (reproduced on the live dev feed, 13:20 UTC)

`/api/cod/games` returns **17 of 21 rows with literal `"TBD"` participants**, including
**finished finals with real scores** (e.g. `BP-356979` `3–4` "Final" with both names `TBD`).
Root cause: `breakingpoint_client.get_cod_matches()` falls back to the literal string
`"TBD"` when the BP team id is missing from its `teams` dict (line 168–169). BP's `teams`
dict only covers the 12 CDL franchise ids; EWC matches reference EWC-specific team ids
(51, 58, 99, 712–715, 1103–1105, …) that never resolve.

## 2. Standings source spike — decision: NO permitted machine-readable source (blocker)

Probed 2026-08-08 13:23–13:26 UTC. **Zero ESPN requests issued** (no ESPN host contacted).

| Host | Result | Meaning |
|---|---|---|
| `esportsworldcup.com` (official standings surface host) | 403 | Cloudflare bot wall from this box; page JS (and its data API) not inspectable |
| `api.esportsworldcup.com` | 401 on every probed path (`/`, `/api/v1/standings`, `/api/standings`, `/v1/clubs/standings`, `/api/v1/club-standings`, `/api/v1/club-championship`, `/openapi.json`) with `WWW-Authenticate: Bearer` | Official API exists but is **Bearer-auth-gated**; no public credentials available |
| `api.resources.esportsworldcup.com` | 302 → `/admin` (CMS admin); no public data endpoints | Rulebook/media-guide CMS only; no standings |
| `cms.esportsworldcup.com` | 302 → `/admin` | CMS admin |
| `cdn.esportsworldcup.com` / `resources.esportsworldcup.com` | 200 | static assets/PDFs (rulebooks, media guide) |
| PandaScore `api.pandascore.co` (our licensed feed) | `series/10834/standings`, `tournaments/21576/standings`, `leagues/5283/standings` — per-tournament placement rows only (2 teams), **no cross-title Club Championship points** | PandaScore does not publish the Club Championship |
| web.archive.org | no capture of `/en/club-championship` or `/en` | dead end |
| escharts.com (third-party table from plan research) | not contacted | plan forbids scraping third-party HTML |

**Decision (plan-sanctioned):** no permitted machine-readable Club Championship publisher
exists on this box today. Per `PLAN-esports-ewc-2026.md` §"Data and API design" item 2:
*"If no usable official machine-readable endpoint exists, choose an allowed provider … if no
permitted source exists, preserve an honest unavailable state and report the blocker instead
of scraping in the browser or hard-coding standings."* → the standings **route, validation,
atomic publication store, and last-good/stale/unavailable reader are implemented and tested**,
but **no external publisher is wired**. The route serves `status: "unavailable"` with a
machine-readable `reason` until a permitted source is resolved. The research top-ten table is
**not** hard-coded anywhere.

**Re-open conditions:** (a) a public/official EWC API key or public endpoint; (b) a licensed
feed that publishes the Club Championship (PandaScore or another licensed provider); (c) an
explicit redistribution contract for a third-party table. Until then the blocker stands.

## 3. Source-native ID map (EWC 2026 Call of Duty + event identity)

| Plane | ID | Value (2026) |
|---|---|---|
| PandaScore league | `league.id` | 5283 ("Esports World Cup", codmw-specific) |
| PandaScore serie (EWC 2026 codmw) | `serie.id` / `serie.slug` | 10834 / `cod-mw-esports-world-cup-2026` |
| PandaScore playoffs tournament | `tournament.id` / `tournament.slug` | 21576 / `cod-mw-esports-world-cup-2026-playoffs` (`has_bracket: true`, tier `s`) |
| PandaScore team ids | `opponent.id` | e.g. 135374 Falcons, 135375 G2, 135377 Team Heretics, 135378 100T, 135379 Gentle Mates, 137163 KOI, 137164 FaZe, 137201 OpTic |
| Breaking Point event | `event_id` | 211 ("Esports World Cup 2026") |
| Breaking Point match | `id` | 356966–356986 (EWC bracket: 356979–356986) |
| BP↔PS shared id | none | BP team ids (51, 58, 99, 712–715, 1103…) and PS team ids are disjoint spaces; no match-level shared id |
| Normalized event id (new) | `eventId` | `"ewc-2026"` — stamped on slate rows whose PS serie is an EWC-2026 serie (slug ends `-esports-world-cup-2026`, year 2026) or whose normalized league label is EWC main event (excluding `qualifier`) |

### 3a. Bracket mapping (fixture, 13:25 UTC) — BP row ↔ PS node

| BP row | BP round / time / score | PS node | PS sched / begin | Notes |
|---|---|---|---|---|
| 356979 | Quarterfinals 13:00, 3–4 | 1609942 QF1 G2 vs HTCS | 13:00 / 13:07 | time exact; HTCS won 4–3 |
| 356980 | Quarterfinals 14:40, 4–0 | 1609944 QF3 100T vs KOI | 16:20 / 16:22 | BP time 1h40m early; KOI 4–0 (sides reversed) |
| 356981 | Quarterfinals 16:20, live 1–0 | 1609943 QF2 FAL vs M8 | 18:00 / 18:01 | BP time 1h40m early; GM up 1–0 |
| 356982 | Quarterfinals 18:00 | 1609945 QF4 FAZE vs OG | 19:30 / 19:30 | BP time 1h30m early; not started |
| 356983 | Semifinals 13:00 | 1609946 SF1 | 13:00 | prev: winner(1609943), winner(1609942) |
| 356984 | Semifinals 14:40 | 1609947 SF2 | 14:40 | prev: winner(1609945), winner(1609944) |
| 356985 | 3rd Place Decider 16:20 | 1609949 | 16:20 | prev: loser(1609946), loser(1609947) |
| 356986 | Grand Finals 18:00 | 1609948 | 18:00 | prev: winner(1609946), winner(1609947) |

Key facts: PS bracket nodes carry `previous_matches[{type: winner|loser, match_id}]` — the
round/slot/predecessor IDs the plan requires. PS node `name`/`opponents` are **not trusted**
for pending sides (SF2's opponents list still says "100 Thieves" although QF3's winner is
Movistar KOI). Sides resolve from feeder `winner_id`/`loser` + feeder participants.

## 4. Request matrix (declared per host)

| Host/source | Operation | Calls per cold refresh | Cache/freshness | Failure behavior |
|---|---|---|---|---|
| `api.pandascore.co` | EWC CoD bracket graph (new) | **1** (brackets call) | new adapter cache, 120 s TTL, single-flight, monotonic | retain last good; rows fall back to pending state |
| `api.pandascore.co` | codmw upcoming/past/running feeds | reuse existing `_per_title`/`_fetch_ps` bulk fetch (8 title feeds, shared cache) | existing 600/120/45 s caches | existing behavior |
| `breakingpoint.gg` | scoreboard feed | reuse existing `breakingpoint_client` (homepage + matches.json, 5 min cache) | existing 300 s cache | existing `cdl_client` fallback |
| ESPN hosts | none | **0** | n/a | never introduced as fallback |
| YouTube Data API | none for standings/scores | **0** | existing resolver only | unchanged |

No new per-row network calls: the EWC adapter indexes the bracket graph **once per refresh**
and reconciles all rows in memory. The only marginal request is +1 PandaScore brackets call per
120 s cold window.

## 5. Standings persistence decision

**Chosen: existing esports atomic-file snapshot pattern — NO SQLite, NO new schema.**

Rationale: (a) the plan's SQLite option exists only "if the source spike confirms durable
movement/history is useful"; with **no permitted publisher resolved**, there is no history to
store; (b) the atomic-file pattern matches `results_store.py` (tmp file + `os.replace`); (c)
zero database writes anywhere — no DEV/prod DB risk, and the "if SQLite is selected, rehearse
on a VACUUM INTO clone" gate is vacuous (never selected).

The published-snapshot reader: `GET /api/esports/events/ewc-2026/club-standings` reads exactly
one published snapshot file; with no valid snapshot it returns the honest
`status: "unavailable"` contract. A validation-gated publisher function exists for when a
permitted source is resolved; a failed candidate run is recorded for diagnosis and never
becomes readable.

## 6. Phase 0 contract tests (written first)

`backend/test_ewc_contract.py` — pins the participant model before any implementation:
named, stale (last-good preservation), pending-winner, pending-loser, fully unavailable.
