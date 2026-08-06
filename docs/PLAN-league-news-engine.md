# PLAN — League News Engine (POC first)

**Status:** Draft — 2026-08-06
**Branch:** `feat/league-news-engine`
**Owner:** Micah (vision) + Hermes (build)
**Roadmap home:** `docs/ROADMAP.md` → POST-DRAFT section

## 1. What this is

AI-generated news per league for Legendary Picks. Two layers, per league:

1. **Narrative layer** — the league's dominant story right now. Not a score recap;
   the meta-story the whole league is talking about. Examples Micah gave:
   - **MLB** — the Dodgers' "Avengers" superteam + the salary cap / salary floor
     debate ("everyone says the cap will save baseball — what if it doesn't need
     saving?")
   - **MLS** — relegation/promotion. (Competitive balance was THE story when
     Messi landed — the article "How Messi's Next Gen Jordan Deal Ushers In A New
     Era for Major League Soccer" — but the narrative has moved on.)
   - **NCAAF** — SEC vs Big Ten consolidation ("is the SEC about to lead the
     NCAA?"), playoff legitimacy. Anchored by "From Mayo Showers to Media
     Monopoly: ESPN's Hand in Bowl Mania and the Quest for a True CFB Champion".
2. **Granular layer** — concrete events: trades, staff decisions (coach
   firings/hirings), injuries to key/notable players.

Both layers surface in a **News page in the top-level nav**. The **Home tab is
the catch-all** across all leagues; **eventually there is one tab per league**
(NFL, MLB, MLS, NCAAF…). The classifier tags every item with a league, which is
what makes both views come from one feed.

**Right now: a proof of concept only.** Prove the collector + classifier on real
signals before designing the pipeline, DB, or UI.

## 2. Signal sources — verified 2026-08-06 (all tested, real responses)

| Source | How | Auth | Status |
|---|---|---|---|
| ESPN news API | `https://site.api.espn.com/apis/site/v2/sports/{sport}/{league}/news` | none | ✅ nfl, baseball/mlb, soccer/usa.1, football/college-football all 200, fresh articles |
| Deadspin | `https://deadspin.com/rss` | none | ✅ 200 — feed literally carries injuries/extensions/suspensions (the granular layer) |
| Awful Announcing | `https://www.awfulannouncing.com/feed` | none | ✅ 200 — sports-media/strategy niche |
| FanSided | `https://fansided.com/feed/` | none | ✅ 200 |
| SB Nation network | `https://www.sbnation.com/rss/index.xml` + team blogs (e.g. bleedcubbieblue.com) | none | ✅ 200 |
| Bluesky post search | `https://api.bsky.app/xrpc/app.bsky.feed.searchPosts?q=...` | none | ✅ narrative queries return real strategy chatter (dodgers salary cap, mls relegation, SEC superleague). `public.api.bsky.app` 403'd this box 2026-08-06; `api.bsky.app` verified working |
| Bluesky author feeds | `.../app.bsky.feed.getAuthorFeed?actor=...` | none | ✅ works unauth (SB Nation verified) |
| Google News RSS | `https://news.google.com/rss/search?q=...` | none | ✅ fallback aggregator |
| The Athletic | (paywall + robots bans AI/LLM scraping) | — | ❌ use their Bluesky posts (@theathletic.com, 17k posts) instead |
| Bleacher Report | (no RSS; robots disallows /api) | — | ❌ use Bluesky (@bleacherreport) + Google News |
| Yahoo Sports | (429) | — | ❌ Google News fallback |
| X/Twitter | (search locked) | — | ❌ **the Underdog accounts Micah wanted are unreachable** — see below |

**The Underdog signal, specifically:** Underdog's official Bluesky accounts
(`@underdogsports.bsky.social`, `@underdog-sports.bsky.social`) are
registered-but-dormant — 0 posts each. The live Underdog signal on Bluesky:
`@underdogtracker` (fan-run, 280 posts), Underdog CPO William Lovely (`@wsul`),
and keyword search (bestball, underdog fantasy, league strategy). Worth watching
— the accounts may activate; the tracker is the current proxy.

## 3. POC scope (this session)

A standalone collector+classifier, no DB, no UI, no app wiring:

1. **Collect** from a fixed, small set (respect the ESPN request budget — news
   endpoints are 1 request per league, total ≤ 5 ESPN requests):
   - ESPN news for MLB, MLS, NCAAF, NFL (4 requests)
   - Deadspin + Awful Announcing RSS (2 requests)
   - 1-2 Bluesky narrative searches (e.g. "dodgers salary cap", "mls relegation")
2. **Classify** every item:
   - `league` — nfl/mlb/mls/ncaaf/nba/nhl (keyword + source rules)
   - `layer` — `narrative` | `trade` | `staff` | `injury` | `other`
     (keyword rules: trade/move/acquire, fired/hired/coach, injury/out/surgery…)
   - `key_player` — name extracted if a notable name is mentioned (start simple:
     flag `titlecase` phrases against a small notable-name list per league)
3. **Emit** a compact JSON report: per league → narrative candidates + granular
   items, each with source URL + headline. Console print + JSON file.

**Success = the classifier's output reads like what Micah described**: the MLB
section surfaces the Dodgers/cap story, MLS surfaces relegation talk, NCAAF
surfaces SEC/consolidation, and the granular rows are real trades/injuries/firings
with links. Judge the detector against the signal, not against our own output
(AGENTS.md rule).

## 4. Real-feature architecture (NOT built now — direction only)

```
┌ collector (cron-able, separate from app) ┐
│  ESPN news API (per league, 1 req)       │
│  RSS tier (deadspin/AA/fansided/sbnation)│
│  Bluesky searchPosts (narrative queries) │
│  Google News RSS (fallback per league)   │
└──────────────┬───────────────────────────┘
               ▼
┌ classifier (AI or rule-based v1) ┐
│  layer: narrative|trade|staff|injury │
│  league tag, key-player tag          │
└──────────────┬──────────────────────┘
               ▼
SQLite: news_items(id, league, layer, source, url, headline, body, published, key_player, narrative_score)
               ▼
API: /api/news/{league}  +  /api/news (catch-all Home tab, filtered)
               ▼
UI: News page in the top-level nav — Home tab = catch-all across leagues;
    per-league tabs (NFL, MLB, MLS, NCAAF…) land later. The classifier's league
    tag is what splits one feed into both views.
```

Rules to carry forward:
- **Collection is out-of-band, never per-pageview** (AGENTS.md: ESPN calls belong
  in the collection path, DB-first serving).
- **O(1) player lookups only** (Micah, 2026-08-06): never scan the players table
  (15k+ NCAAF names). Player info is pulled only when a news item makes it
  relevant — an indexed by-name lookup per candidate mention. No pre-loading,
  no O(n) sweep, no gain from it.
- ESPN news endpoint is already proven in the codebase (player news tab,
  `backend/routers/players.py` — gzip handling pattern exists). League-level news
  was rejected for the *player* tab as too general — it is exactly right for the
  *league narrative* surface.
- One ingest at a time, idempotent upserts, resumable (project doctrine).
- No API keys anywhere. Bluesky and Google News need none.

## 5. Acceptance criteria (POC)

- [ ] Runs with plain `python3`, no third-party deps — the only import beyond
      stdlib is the in-repo shared client `backend/paced_http.py`.
- [ ] States the request count per host **before** running (ESPN ≤ 4 to
      `site.api.espn.com`, budgeted at 20; re-runs inside the cache TTL cost
      zero requests).
- [ ] Output JSON lists per league; MLB shows the Dodgers/cap narrative,
      MLS shows relegation, NCAAF shows SEC/consolidation, or explicitly reports
      which of those signals were NOT found (absence is a finding, not a pass).
- [ ] Granular items carry a working URL back to the source article.
- [ ] Deterministic enough to re-run: same day ≈ same output (no randomness).

## 6. Open questions (for Micah)

1. **Narrative freshness**: a narrative persists for weeks (the cap debate). Do we
   refresh it per-day (detect drift) or per-week? POC assumption: per-day collect,
   surface the top narrative with a first-seen date.
2. **Notable-player detection — resolved 2026-08-06 (Micah): no full-table
   scans.** Never pre-load or sweep the players table (15k+ NCAAF names). A name
   is pulled only when a news item makes it relevant — an indexed by-name
   lookup (O(1)) per candidate mention, or the small curated list. O(n) for
   potentially no gain.
3. **Underdog strategy content**: the tracker + keyword search is a proxy for the
   unreachable X accounts. Is that enough for the strategy layer, or should the
   POC also test brid.gy mirrors (RSS→Bluesky bridges)?

## 7. Non-goals (this session)

- No DB schema, no migrations, no API endpoints, no UI.
- No X/Twitter scraping (locked; not legal/robust).
- No paywalled-content scraping (The Athletic robots explicitly forbids AI/LLM use).
- No deployment. This is a sketch in `sketches/`.
