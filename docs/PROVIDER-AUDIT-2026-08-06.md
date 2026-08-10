# Provider audit — MLS / NCAAF / CONCACAF / tennis (2026-08-06)

Method: published-first enumeration. For every candidate provider we name the actual
endpoint/artifact it publishes and what it returns, verified from the provider's own
docs or a live response on 2026-08-06 (URL + date recorded per claim in the
Verification log). ESPN hosts were NOT fetched (box is rate-limited; ESPN's role is
already confirmed). Verdicts: **ADOPT** / **CROSS-CHECK** (viable second source) /
**REJECT** / **UNVERIFIED** (question, not fact).

TL;DR: ESPN remains primary for MLS, NCAAF and the CONCACAF tournaments — but the
"CFBD is season-level only" claim in LEAGUE-SOURCES-FIELDS.md is **wrong**, and for
tennis props there is now a **verified second bookmaker (Kalshi)** and a **verified
history source (tennis-data.co.uk)** that the plan can build on.

---

## RECOMMENDED SOURCES (final set per league)

| League | Primary | Second source (cross-check) | Notes |
|---|---|---|---|
| MLS game logs | ESPN `site.web.api.espn.com` soccer/usa.1 summary (unchanged) | **FotMob** `api.fotmob.com/api/matchDetails?matchId=` (lineup `playerStats`: goals/assists/shots/xG) — unofficial, no key; **Sofascore** `api.sofascore.com/api/v1/event/{id}/lineups` — unofficial, Cloudflare-sensitive | No free bulk per-game-log file exists for MLS; ~510 summary calls is inherent to every provider that has the data |
| NCAAF (FBS) game logs | **CFBD `GET https://api.collegefootballdata.com/games/players?year=&seasonType=regular&classification=fbs`** (free key, 1,000 calls/mo) — replaces the per-game ESPN loop for the log rows; ESPN `college-football` summary retained for reconcile/count envelopes | cfbfastR — REJECT (wraps ESPN, R dep) | CFBD publishes per-game player stats (passing/rushing/receiving/defensive categories per player per game). ~1–6 requests per season vs 888 ESPN summaries |
| Leagues Cup / CCC / Campeones Cup | ESPN slugs `concacaf.leagues.cup`, `concacaf.champions`, `campeones.cup` (unchanged) | **FotMob** tournament pages (`fotmob.com/leagues/10043/overview/leagues-cup`; CONCACAF comps present) — cross-check scores, not stats | CONCACAF official site has NO documented public API; Sportmonks covers CCC but is paid (€29/mo) |
| Tennis props | **Bovada** coupon API (unchanged — verified 188 ATP + 187 WTA) | **Kalshi** `api.elections.kalshi.com/trade-api/v2/...` series `KXATPMATCH` / `KXWTAMATCH` (VERIFIED live: ATP Montreal, WTA Toronto markets) | **Underdog** also publishes tennis (verified via vendor help article + live endpoint) but tennis rows were NOT confirmed in the captured payload — treat as fallback, verify shape at implementation |
| Tennis results (backtest) | ESPN tennis/atp + tennis/wta scoreboards (unchanged) | **tennis-data.co.uk** per-season files `tennis-data.co.uk/2026/2026.xlsx` (ATP, "match results and betting odds") and `2026w/` (WTA) — free CSVs/XLSX since 2000/2007 | Historical closing odds enable prop backtests; NOT live |

---

## 1. MLS player game logs / stats

| Provider | What it actually publishes (endpoint) | Cost | Verdict |
|---|---|---|---|
| ESPN (current) | `site.web.api.espn.com/sports/soccer/usa.1/summary?event=` — per-game rosters[].stats (goals/assists/shots/sot + more); `sports.core.api.espn.com` count envelopes | free, ~100 req/host budget | ADOPT (unchanged) |
| FotMob | Unofficial API, no key: `https://api.fotmob.com/api/matches?date=YYYYMMDD`, `/api/leagues?id=130` (MLS), `/api/matchDetails?matchId=` → `content.lineup.playerStats` per player (goals, assists, shots, xG, xA, rating); league players via `/api/leagues?id=130&tab=overview` | free, undocumented, unstable (schema changes; some endpoints need headers) | CROSS-CHECK only — same ~1 call/game shape as ESPN, no count envelopes, no SLA |
| FBref / StatsBomb | Scrape-only HTML tables (no API); StatsBomb free data is limited to selected competitions (MLS not in free set) | free scrape, ToS-restricted | REJECT (prior doc correct) |
| Understat | `understat.com/league/...` JSON endpoints (xG, xGA, shots) — **does NOT cover MLS** (covers EPL, La Liga, Bundesliga, Serie A, Ligue 1, RFPL only) | free | REJECT (no MLS; verified via Understat scraper docs) |
| mlssoccer.com | No public developer API. Site renders stats via undocumented internal calls; third-party `rogersmark/mls-api` scrapes the site | — | REJECT (no documented API) |
| API-Football (api-sports.io) | `https://v3.football.api-sports.io/players?season=&league=253` (MLS league id 253) season aggregates; per-fixture player box scores via `/fixtures/players?fixture=` | free tier 100 req/day forever; paid from ~$31/mo | CROSS-CHECK candidate, but same per-game request shape with a 100/day cap → worse than ESPN for a 510-game ingest; REJECT as primary |
| Football-Data.org | v4 API; MLS listed in coverage but **not in the free 12-competition tier**; no per-game player logs even paid (player endpoints are match-level appearances) | free tier = 12 comps, 10 req/min | REJECT (no per-game player stats for MLS) |
| Sofascore | Semi-public `https://api.sofascore.com/api/v1/...`: `/sport/football/scheduled-events/{date}`, `/event/{id}` (hasEventPlayerStatistics), `/event/{id}/lineups`, player season stats `/player/{id}/unique-tournament/{tid}/season/{sid}/statistics/overall`; covers MLS + tennis | free, no key, unofficial (Cloudflare; may need headers/geo) | CROSS-CHECK candidate; fragile |
| Sportmonks | Soccer API, `league_id 779` = MLS; fixtures/lineups/stats/xG | from €29/mo | REJECT (paid; ESPN free covers the needed fields) |
| WhoScored | Scrape-only, heavy bot protection | — | REJECT (not independently verified this run; prior doc) |

## 2. NCAAF (FBS) player stats

| Provider | What it actually publishes (endpoint) | Cost | Verdict |
|---|---|---|---|
| **CollegeFootballData.com** | **`GET https://api.collegefootballdata.com/games/players?year=2025&seasonType=regular&classification=fbs`** → per-GAME player box-score rows (player, team, opponent, week, position, category, stat/value: passing C/ATT/YDS/TD/INT, rushing, receiving, defensive…). Also `GET /stats/player/game` (category-filterable rows) and `GET /stats/player/success/game`. Free tier (1,000 calls/month, no card) includes Player Statistics + Team Statistics; "CFB Data Exporter" offers season CSVs. | free key (1k calls/mo; Academic 3k; $1/mo = 5k) | **ADOPT as per-game log source.** The LEAGUE-SOURCES-FIELDS.md claim "player-stats endpoints are season-level, not per-game-log shaped" is REFUTED. Request cost: ~1 call per season (or ~4–6 if per-category) vs 888 ESPN summaries |
| ESPN (current) | `college-football/summary` per game (boxscore.players[].statistics[]), group 80 envelopes | free, ~100 req/host budget | ADOPT for reconcile/count envelopes (unchanged); per-game log loop can move to CFBD |
| cfbfastR / sportsdataverse | R wrapper; `espn_cfb_game_player_statistics()` calls ESPN's own endpoints | free | REJECT (indirection + R dep; prior doc correct) |
| Sports Reference (CFB) | Scrape-only HTML; no API, ToS blocks bots | — | REJECT |
| nflverse / collegefootballdata R pkg | The R pkg is a CFBD client (same API as above); nflverse is NFL-only | — | REJECT (redundant with CFBD REST) |

## 3. Leagues Cup / CCC / Campeones Cup

| Provider | What it actually publishes | Cost | Verdict |
|---|---|---|---|
| ESPN (current) | `concacaf.leagues.cup`, `concacaf.champions`, `campeones.cup` slugs — events, summaries, rosters | free | ADOPT (unchanged; verified in PLAN doc) |
| FotMob | Tournament pages present: **Leagues Cup = `fotmob.com/leagues/10043/overview/leagues-cup`** (2026 season page live), CONCACAF comps incl. W Champions Cup (11013) → men's CCC almost certainly present (not individually verified) | free | CROSS-CHECK (scores/results) |
| CONCACAF official (concacaf.com) | Match/result pages (e.g. `concacaf.com/competitions/champions-cup/matches`) rendered by an SPA; **no documented public developer API**; media CDN only | — | REJECT as source; UNVERIFIED whether an internal JSON API exists (not probed) |
| Sportmonks | "CONCACAF Champions Cup API" product page, plans from €29/mo | paid | REJECT (paid; ESPN free covers it) |

## 4. Tennis (props + results)

| Provider | What it actually publishes | Cost | Verdict |
|---|---|---|---|
| Bovada (current) | Open coupon API, `{BOVADA}/tennis/atp` + `/tennis/wta` — 188 ATP + 187 WTA player-attributed props (verified 2026-08-06) | free, no key | ADOPT (unchanged) |
| **Kalshi** | **VERIFIED live 2026-08-06:** ATP + WTA + ITF match markets on `kalshi.com/category/sports/tennis/atp-montreal/games` etc. Series tickers `KXATPMATCH` / `KXWTAMATCH` (per-market examples `kxatpmatch-26aug05tsifon`, `kxwtamatch-26aug05boutow`); market = match winner per player (+ set-score / above-below variants per CFTC filing). Read API: `https://api.elections.kalshi.com/trade-api/v2/events?series_ticker=KXATPMATCH` (and `/markets?event_ticker=...`); GET endpoints public, no key | free to read | **ADOPT as second prop book** — the "Underdog/Kalshi fallback" is now real for Kalshi; verify exact ticker/param naming at implementation |
| Underdog Fantasy | `https://api.underdogfantasy.com/beta/v5/over_under_lines` — LIVE, returned a ~13 MB book (2026-08-06). Tennis VERIFIED to exist as a product (official help article "Pick'em Scoring — Tennis", help.underdogsports.com) — but the first 2 MB (rank-ordered: NFL/MLB/WNBA/esports/CFL/NPB/basketball) contained **zero tennis rows**, so the tennis payload shape is UNVERIFIED from this capture | free, no key | CROSS-CHECK/fallback — verify tennis rows (sport filter) before relying on it |
| tennis-data.co.uk | Free historical files: ATP per-season Excel/CSV (`https://www.tennis-data.co.uk/2026/2026.xlsx` "Match results and betting odds"; CSV per competition; back to 2000) and WTA (`/2026w/2026.xlsx`, back to 2007); `notes.txt` key. Contains match results + multiple bookmakers' closing odds. (Live pages 504'd on fetch; contents verified via the site's own index + Kaggle mirror of the same data) | free | ADOPT for backtests/validation (not live, not props) |
| ATP/WTA official | No free public API. ATP data via Tennis Data Innovations (TDI, partner/paid); resellers: Sportradar Tennis API, Matchstat `tennis/v2` (RapidAPI), tennis-api.com (RapidAPI) — all paid | paid | REJECT for this project |

## 5. Bulk / league-wide ESPN question (MLS)

Checked per espn-request-budget §3 ("look for byathlete / season-wide reports before per-entity loops"):
- The bulk `byathlete` / common-v3 `athletes?limit=20000` reports on `site.web.api.espn.com` return **season aggregates, not per-game logs** (that's how the NBA ingest cut 643 calls to 6 for season stats — but those are season totals, not game logs).
- **No provider publishes a free league-wide per-game-log FILE for MLS.** FotMob, Sofascore and API-Football all serve per-match player stats as per-match calls (~510 per season) — same request shape as ESPN, less stable, no count envelopes.
- Therefore ~510 per-game summary calls (site.web.api) is inherent to the MLS game-log ingest; the budget lever is the shared paced_http cache (re-runs free), not a different provider. **UNVERIFIED on this box** (ESPN hosts blocked per constraint): the exact soccer-shaped bulk endpoint — verify with one probe from the box when the budget is quiet.

## 6. Explicitly NOT verified (questions, not facts)

1. ESPN soccer bulk endpoint shape (byathlete/athletes list for usa.1) — hosts blocked this run; the skill documents the pattern for NBA only.
2. Underdog tennis rows inside `over_under_lines` — live endpoint verified, tennis product verified via docs, but the captured 13 MB book was truncated to 2 MB and showed no tennis (rank-ordered; tennis would sort low).
3. Kalshi trade-api v2 exact query params (series_ticker vs event_ticker) — series tickers verified from live market URLs; params per API docs knowledge, confirm with one read call at implementation.
4. FotMob men's CONCACAF Champions Cup league id — Leagues Cup (10043) and W Champions Cup (11013) verified; men's CCC not individually looked up.
5. tennis-data.co.uk live fetch (504 ×2) — contents verified via search-indexed copy of the site's own index page + Kaggle mirror, not a live scrape.
6. concacaf.com internal JSON API — the site is an SPA with no public docs; an undocumented API may exist behind it (not probed; ESPN + FotMob cover the need).

## Verification log (what was checked, when)

| Claim | Source checked | Date |
|---|---|---|
| CFBD has per-game player stats endpoint | api.collegefootballdata.com/ (getting started, free key), collegefootballdata.com/api-tiers (Free 1k calls/mo incl. Player Statistics), mindcloud CFBD docs "List Game Player Stats", github.com/CFBD/cfbd-python (GET /games/players → get_game_player_stats; /stats/player/success/game; /stats/categories) | 2026-08-06 |
| FotMob unofficial API shape | github.com/bjrsti/fotmob (endpoints + responses), parse.bot FotMob API spec (matchDetails → lineup playerStats w/ goals/assists/shots/xG/xA) | 2026-08-06 |
| Understat leagues (no MLS) | apify understat-xg scraper ("Covers Premier League, La Liga, Bundesliga, Serie A, Ligue 1, RFPL") | 2026-08-06 |
| API-Football free tier + endpoints | api-sports.io ("Free plan … 100 requests per day"), api-sports.io/documentation/football/v3 (GET /players?league&season, /fixtures/players) | 2026-08-06 |
| Football-Data.org free tier + MLS | football-data.org/pricing (12 comps free), /coverage (MLS row), thestatsapi.com comparison (free comps list) | 2026-08-06 |
| Sofascore API | github.com/apdmatos/sofascore-api (base `api.sofascore.com/api/v1`, event lineups, player season stats), stackoverflow endpoint Q | 2026-08-06 |
| FotMob covers Leagues Cup / CONCACAF | fotmob.com/leagues/10043/overview/leagues-cup (live page), fotmob.com/leagues/11013 (CONCACAF W Champions Cup) | 2026-08-06 |
| Kalshi tennis markets | kalshi.com/calendar (KXATPMATCH ATP Montreal, KXWTAMATCH WTA Toronto live, $ volumes), CFTC filing ptc01162637322.pdf (tennis match/set-score contract spec), stinson.com (Kalshi sports incl. tennis) | 2026-08-06 |
| Underdog tennis product + endpoint | help.underdogsports.com "Pick'em Scoring - Tennis"; live GET api.underdogfantasy.com/beta/v5/over_under_lines (200, ~13 MB book, sports in first 2 MB: NFL/MLB/WNBA/CS/LoL/Valorant/CFL/NPB/Basketball — no tennis) | 2026-08-06 |
| tennis-data.co.uk contents | Search-indexed copy of tennis-data.co.uk/alldata.php (ATP per-season xlsx "Match results and betting odds" 2000–2026, WTA 2007–2026, CSV per competition), Kaggle mirror (df_atp/df_wta) | 2026-08-06 |
| No free ATP/WTA official API | Sportradar developer docs (paid), matchstat tennis/v2 RapidAPI (paid), tennis-api.com (paid) | 2026-08-06 |
| CONCACAF official: no public API | concacaf.com site structure (SPA, match pages, media CDN), sportmonks CONCACAF Champions Cup API page (paid €29/mo) | 2026-08-06 |
| mlssoccer.com: no public API | reddit r/webdev "mlssoccer.com API?" (undocumented site calls), github rogersmark/mls-api (scraper) | 2026-08-06 |
| Sportmonks MLS paid | sportmonks.com/football-api/mls-api (league_id 779, from €29/mo) | 2026-08-06 |
