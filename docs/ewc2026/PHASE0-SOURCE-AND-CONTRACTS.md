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
| `fixtures/liquipedia-ewc-standings-20260809.json` | Liquipedia MediaWiki `api.php` `action=parse` `prop=text`, rev **15997** (rendered HTML) | 2026-08-09 ~00:2x UTC |
| `fixtures/liquipedia-ewc-wikitext-20260809.json` | same call `prop=wikitext`, rev **15997** (`current-stage=5`, `stage5cutoff=19`) | 2026-08-09 ~00:2x UTC |

### 1a. Verified defect (reproduced on the live dev feed, 13:20 UTC)

`/api/cod/games` returns **17 of 21 rows with literal `"TBD"` participants**, including
**finished finals with real scores** (e.g. `BP-356979` `3–4` "Final" with both names `TBD`).
Root cause: `breakingpoint_client.get_cod_matches()` falls back to the literal string
`"TBD"` when the BP team id is missing from its `teams` dict (line 168–169). BP's `teams`
dict only covers the 12 CDL franchise ids; EWC matches reference EWC-specific team ids
(51, 58, 99, 712–715, 1103–1105, …) that never resolve.

## 2. Standings source spike — RESOLVED: Liquipedia MediaWiki API (2026-08-09)

### 2a. Original probe (2026-08-08 13:23–13:26 UTC) — superseded conclusion

The original spike found **no permitted machine-readable publisher** and recorded a blocker:

| Host | Result | Meaning |
|---|---|---|
| `esportsworldcup.com` (official standings surface host) | 403 | Cloudflare bot wall from this box; page JS (and its data API) not inspectable |
| `api.esportsworldcup.com` | 401 on every probed path with `WWW-Authenticate: Bearer` | Official API exists but is **Bearer-auth-gated**; no public credentials |
| `api.resources.esportsworldcup.com` / `cms.esportsworldcup.com` | 302 → `/admin` | CMS admin; no public data |
| PandaScore `api.pandascore.co` (our licensed feed) | per-tournament placement rows only (2 teams), **no cross-title Club Championship points** | PandaScore does not publish the Club Championship |
| web.archive.org / escharts.com | no usable capture / third-party HTML (scraping forbidden) | dead ends |

That conclusion is **superseded** by the Liquipedia resolution below. The probe history is kept
for audit; the blocker is closed. **Zero ESPN requests issued (no ESPN host contacted) — unchanged.**

### 2b. Resolution — Liquipedia (MediaWiki API), permitted and machine-readable

| Field | Value |
|---|---|
| Host / API | `liquipedia.net/esports` — MediaWiki `api.php` (`action=parse`) |
| Page | `Esports_World_Cup/2026/Club_Championship_Standings` |
| API call (one, operator-run) | `api.php?action=parse&page=Esports_World_Cup/2026/Club_Championship_Standings&prop=text%7Cwikitext%7Crevid&format=json` |
| Transport | gzip `Accept-Encoding`, descriptive `User-Agent: LegendaryPicks/1.0 …` |
| Terms | Liquipedia's terms explicitly allow access through the MediaWiki API; **no HTML page scraping, no browser request-path fetching** |
| Live revision (research + ingest) | **15997** — `current-stage=5`, `stage5cutoff=19`; rendered current-stage table has **exactly 90 rows** (`data-toggle-area-content="19"`) |
| Population semantics | the current-stage table **is** the source's full population for the active stage; `sourceReportedClubs` = `fetchedClubs` = parsed row count (90 at rev 15997). No independent count literal exists on the page |
| clubId | stable Liquipedia team page slug from the row's team link (`/esports/<slug>`), e.g. `AG.AL_International`, `Team_Falcons`, `Virtus.pro` |
| Points | the row's bold total-points cell (`<td style="font-weight:bold">N</td>` after the club cell); numeric, nonnegative |
| Ties | real published rankings contain tied ranks (e.g. tied 4th Team Vitality 2200 / Virtus.pro 2200; tied 6th T1 1750 / Team Vision 1750); the validator accepts equal ranks with equal points |
| Snapshot file | `backend/data/esports_ewc_standings.json` — atomic last-good publication (tmp + `os.replace`), one writer (`backend/fetch_ewc_standings.py`) |
| Freshness | `publishedAt` = ingest time; route serves `current` until the publisher cadence (default 6 h), then `stale` — **rows are retained either way**; a failed/corrupt candidate never becomes readable |

Top rows at rev 15997 (also what the committed snapshot publishes): 1 AG.AL International 3350;
2 Team Falcons 2900; 3 Natus Vincere 2250; tied 4 Team Vitality 2200 and Virtus.pro 2200;
tied 6 T1 1750 and Team Vision 1750; 8 Twisted Minds 1700; 9 ZETA DIVISION 1500;
10 100 Thieves 1300.

Eligibility fields (`eligibleTopEightCount`, `titleWins`, `eligibleToWin`) stay `null` — the
page does not directly expose per-club eligibility evidence.

Fixtures committed: `fixtures/liquipedia-ewc-standings-20260809.json` (rendered HTML, rev 15997)
and `fixtures/liquipedia-ewc-wikitext-20260809.json` (wikitext, rev 15997).

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
movement/history is useful"; (b) the atomic-file pattern matches `results_store.py` (tmp file +
`os.replace`); (c) zero database writes anywhere — no DEV/prod DB risk, and the "if SQLite is
selected, rehearse on a VACUUM INTO clone" gate is vacuous (never selected).

The published-snapshot reader: `GET /api/esports/events/ewc-2026/club-standings` reads exactly
one published snapshot file; with no valid snapshot it returns the honest
`status: "unavailable"` contract. Since 2026-08-09 a **real publisher is wired** — the
operator-run `backend/fetch_ewc_standings.py` (Liquipedia MediaWiki API, §2b) validates and
atomically publishes to `backend/data/esports_ewc_standings.json`. A failed candidate run is
recorded for diagnosis and never becomes readable; the last good snapshot survives.

## 6. Phase 0 contract tests (written first)

`backend/test_ewc_contract.py` — pins the participant model before any implementation:
named, stale (last-good preservation), pending-winner, pending-loser, fully unavailable.
