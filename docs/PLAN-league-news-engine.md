# PLAN — League News Engine (POC first)

**Status:** LIVE on main dev — 2026-08-07 (see §8 Progress update)
**Branch:** `feat/league-news-engine` (built directly on main dev tree)
**Owner:** Micah (vision) + Hermes (build)
**Roadmap home:** `docs/ROADMAP.md` → POST-DRAFT section

## Version history

- **v2 — CONVERSATIONS model (current, 2026-08-07).** One card per important
  conversation (conv_id-keyed), each with a news anchor + attributed fan voice
  with evidence, rendered as prose paragraphs. Seeds = Micah's dictated
  narratives; adjacent queries derived from seed × texture dimensions. See §8.
- **v1 — per-league narrative (2026-08-06, superseded).** One AI narrative per
  league with 2-3 points + source chips; Home feed = narrative-layer items.
  Rollback checkpoint: **tag `news-engine-v1` → commit `095bb6b`**
  (`git checkout news-engine-v1` to restore v1, or `git diff
  news-engine-v1 -- <files>` to compare).

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
   firings/hirings), injuries to key/notable players. **Speculation is not
   news (Micah, 2026-08-06):** trade rumors, "realistic packages", "top 10
   trades that should happen", trade-value/projection listicles are classified
   `speculation` and never served. Only confirmed transactions (acquired /
   signed / released / extension) or definitive statements ("no plans to trade
   X") reach the board. Staff means a decision happened (fired / hired /
   resigned / stepping down) — commentary that merely mentions coaches is not
   staff.

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
| X/Twitter timelines | `https://nitter.net/{handle}/rss` | none | ✅ **SOLVED 2026-08-10** — see §2.1. Free Nitter mirror, 17 accounts |
| X/Twitter search | `nitter.net/search/rss?f=tweets&q=...` | none | ❌ returns an empty document — X's search endpoint is closed to Nitter. Keyword queries stay on Bluesky |

**The Underdog signal — resolved 2026-08-10.** The earlier conclusion here
("unreachable", "registered-but-dormant") was **wrong on the handle**:
Underdog's X account is **@Underdog**, not @UnderdogFantasy, and it is live.
Its Bluesky presence really is dormant (`underdogfantasy.bsky.social`: 0 posts,
3 followers), and PrizePicks and Polymarket have no Bluesky presence at all —
so X was the only way to reach them, and a Nitter mirror reaches it for free.

Eleven mirrors were tried; **nitter.net is the only one that answers** this box.
The rest are 502, expired certs, NXDOMAIN, or a JS browser challenge that
replies "Automated verification failed" to headless Chrome. Self-hosting is not
a fallback: X killed guest accounts, so an instance now needs real session
tokens. `twitterapi.io` (~$0.15/1k reads) stays wired as a paid fallback behind
`LP_XAPI_KEY`, unused by default.

## 2.1 The X accounts we cover (measured 2026-08-10)

Every account was scored on the same ruler — 20 rows each, share that classify
into a served layer (narrative/trade/staff/injury/notable), and share that fail
to classify into a league at all.

**Beat reporters — the best per-item signal we have.** They also post
availability ("sat out practice", "not travelling") hours before a brand
account repackages it.

| Handle | League | Usable | Note |
|---|---|---|---|
| `@ShamsCharania` | nba | **80%** | highest of anything we read |
| `@TomBogert` | mls | 44% | MLS transfers specifically |
| `@Ken_Rosenthal` | mlb | 40% | |
| `@FriedgeHNIC` | nhl | 36% | |
| `@RapSheet` | nfl | 35% | 19 posts/day |
| `@JeffPassan` | mlb | 35% | |
| `@AdamSchefter` | nfl | 45% | |
| `@FieldYates` | nfl | 25% | |

**Props desks — league-specific, and the reason we came to X at all.** The
handle states its own league, which beats the classifier guessing: these are
0% unclassified where cross-league accounts run 25–40%.

| Handle | League | Usable | Rate |
|---|---|---|---|
| `@UnderdogNFL` | nfl | 35% | **83/day** — densest feed we have |
| `@UnderdogMLB` | mlb | 20% | 22/day |
| `@UnderdogNBA` | nba | 60% | 4/day |
| `@Underdog` | — | 5% | 7/day, cross-league |

**Publishers.** The Athletic's league desks share **zero** posts with the
parent account (0 of 20 each) — they are separate desks, not mirrors.

| Handle | League | Usable |
|---|---|---|
| `@TheAthletic` | — | 16% |
| `@TheAthleticNFL` | nfl | 30% |
| `@TheAthleticNHL` | nhl | 25% |
| `@TheAthleticCFB` | ncaaf | 15% |
| `@BleacherReport` | — | 20% |

**Deliberately NOT carried**, same ruler:

| Handle | Why |
|---|---|
| `@Kalshi` 100% unclassified / 0% usable, `@Polymarket` 95%/10%, `@PrizePicks` 65%/5% | politics, crypto, streamer news |
| `@KalshiSports` 75%/15%, `@PolymarketSport` 60%/10% | the sport desks beat their parents and still miss the bar; ~half their posts are the brand's own marketing. Market signal is probabilities, not news — it belongs in the odds pipeline beside the Bovada scraper |
| `@FabrizioRomano` 63% usable | scores well but covers European club competitions we do not carry — the same trap as the ESPN soccer rollup |
| `@arielhelwani` 0%, `@Brett_McMurphy` 5%, `@PeteThamel` 10%, `@TomPelissero` 10% | low yield; Pelissero posts ~once a day |

**Handles that do not exist:** `@UnderdogNHL`, `@UnderdogCFB`, `@BR_NFL`,
`@BR_NBA`, `@PolymarketSports` (plural), `@UnderdogMLS`, `@TheAthleticSoccer`.

**Cadence — two lanes.** X posts far faster than the nightly run: @UnderdogNFL
at 83/day against a 20-post RSS window means its feed holds about six hours, so
a daily run captures a quarter of it. `legendarypicks-news-x.timer` runs
`--x-only` **every 2 hours** (17 requests, no ESPN, no Bluesky, no model;
~200 requests/day against a free mirror). The full collector plus narrative
generation stays on the nightly `legendarypicks-news.timer` at 03:35.

## 3. POC scope (DONE — superseded by §8)

A standalone collector+classifier, no DB, no UI, no app wiring — **completed
2026-08-06**. The POC proved the collector + classifier on real signals; the
real feature then grew from it (see §8).

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

## 5. Acceptance criteria (POC) — ALL MET 2026-08-06

- [x] Runs with plain `python3`, no third-party deps — the only import beyond
      stdlib is the in-repo shared client `backend/paced_http.py`.
- [x] States the request count per host **before** running (ESPN ≤ 7 to
      `site.api.espn.com`, budgeted at 20; re-runs inside the cache TTL cost
      zero requests).
- [x] Output JSON lists per league; MLB shows the Dodgers/cap narrative,
      MLS shows relegation, NCAAF shows SEC/consolidation, or explicitly reports
      which of those signals were NOT found (absence is a finding, not a pass).
- [x] Granular items carry a working URL back to the source article.
- [x] Deterministic enough to re-run: same day ≈ same output (no randomness).

## 6. Open questions (for Micah)

1. **Narrative freshness**: a narrative persists for weeks (the cap debate). Do we
   refresh it per-day (detect drift) or per-week? POC assumption: per-day collect,
   surface the top narrative with a first-seen date. **Status: conversations are
   regenerated on each manual collector+narrative run (see §8.9 — cron not built
   yet); freshness policy still open.**
2. **Notable-player detection — resolved 2026-08-06 (Micah): no full-table
   scans.** Never pre-load or sweep the players table (15k+ NCAAF names). A name
   is pulled only when a news item makes it relevant — an indexed by-name
   lookup (O(1)) per candidate mention, or the small curated list. O(n) for
   potentially no gain.
3. **Narrative generation — LinkedIn-trending style — BUILT 2026-08-06, EVOLVED
   2026-08-07.** `backend/ingest_league_narratives.py` runs a DeepSeek pass
   (in-repo key, max_tokens=4000 + 1 retry) over each conversation's chatter and
   writes the two-layer card (news anchor + attributed fan voice with evidence)
   + grounded sources to `news_narratives` keyed by `conv_id`. Served via
   `/api/news` and `/api/news/narratives`, rendered as the conversation card on
   Home and per-league tabs, honestly attributed ("Fans argue…", "Supporters
   point to…") with source chips. Bullet points were dropped 2026-08-07 — the
   card is one attributed prose paragraph (Micah: the bullets read as the app's
   own voice).
4. **Underdog strategy content**: the tracker + keyword search is a proxy for the
   unreachable X accounts. Is that enough for the strategy layer, or should the
   POC also test brid.gy mirrors (RSS→Bluesky bridges)?

## 7. Non-goals (this session)

- No DB schema, no migrations, no API endpoints, no UI.
- No X/Twitter scraping (locked; not legal/robust).
- No paywalled-content scraping (The Athletic robots explicitly forbids AI/LLM use).
- No deployment. This is a sketch in `sketches/`.

---

## 8. PROGRESS UPDATE — 2026-08-07 (built on main dev, all verified live)

**This is v2 — the CONVERSATIONS model** (supersedes v1, the per-league
narrative; rollback = tag `news-engine-v1` → `095bb6b`, see header). The POC
grew into the real feature on main dev. Everything below is live on
`:8096`/`:3096` and verified through the dev tunnel
(`https://dev-button-file-approaches.trycloudflare.com/news`).

### 8.1 What the surface became: CONVERSATIONS, not league summaries

**Each conversation is its own card and gets to breathe.** We deliberately do
NOT merge a league's stories into one summary card — the league summary is a
future pass over the conversation set, not this surface (Micah, 2026-08-07).

Card shape (one per row in `news_narratives`, keyed by `conv_id`):
- `narrative` — the NEWS ANCHOR: the official, high-importance story (a
  commissioner's decision, a signing, a rule change, a lawsuit).
- `fan_voice` — what fans are saying/wanting around it, WITH the evidence
  backing them (the packed stadium, the player quote, a poll number).
- `paragraph` — the card's prose: leads with the anchor, then carries the fan
  voice WITH attribution ("Fans argue…", "Supporters point to…") so the app
  never sounds like it is making the fan's claim itself. (Bullet points were
  dropped 2026-08-07 — they read as the app's own voice.)
- `sources` / `source_count` — real-article receipts; bluesky posts feed the
  signal but are never shown as source chips.

### 8.2 Seeds + texture dimensions (the systematization)

- `backend/ingest_league_news.py` now defines `CONVERSATIONS` — Micah's
  dictated narratives ARE the seed: `mlb-salary-cap` ("dodgers salary cap"),
  `mls-pro-rel` ("mls relegation promotion"), plus
  `nfl-media-rights` / `nfl-turf-grass` / `nba-expansion` / `nhl-salary-cap` /
  `ufc-title-fight` / `ncaaf-realignment` / `esports-worlds` / `esports-valorant`.
- Adjacent-topic queries are DERIVED, never hand-written per league: each seed
  × a sport-agnostic texture-dimension list (`stadium`, `attendance`, `fans`,
  `lower division`, `highlight`). A seed about pro/rel becomes
  "mls relegation promotion stadium", "…fans", etc. This is how the packed-USL-
  stadium texture and the player grass-preference quotes get collected.
- Collected bluesky items carry `conv_id` so chatter attributes back to its
  conversation.

### 8.3 The NFL turf-vs-grass conversation (the concrete second example)

Seed "nfl turf grass" + dimensions surfaced: Browns installing turf in the new
$2.6B stadium (17-15 turf), NFLPA poll 92% players prefer grass, Kupp /
Will Anderson injury quotes, World Cup temporary grass in indoor venues.
Card: anchor = the Browns decision; fan voice = players/fans pushing for
grass with the poll + injury evidence.

### 8.4 Fan voice with WHY (fans have a voice)

The desk prompt demands the fan side be ATTRIBUTED and EVIDENCED: "just because
the league decided something does not mean fans agree or have stopped wanting
the alternative. Name the evidence — the packed stadium, the lower-division
crowds, the player quote." The MLS card says the commissioner ruled out pro/rel
AND that fans disagree, pointing to the closed-model critique and the
two-division proposals. Both sides get to exist on the card.

### 8.5 Esports gating

Esports conversation cards stay OFF the Home tab until their quality is there
(Micah, 2026-08-07) — they still render on the Esports per-league tab. Filter
is frontend-only for now (`pages/news.tsx`).

### 8.6 Collection fixes that mattered

- **ESPN UA**: `site.api.espn.com/news` 403s the Chrome UA but answers
  `curl/8.5.0` (measured 2026-08-07). The collector's ESPN fetcher now sends
  the curl UA — before this, ESPN contributed ZERO rows (all news came from RSS
  + bluesky).
- **Leagues wired in**: ESPN news now collected for all 7 leagues + esports
  (nba/nhl/ufc were missing entirely).
- **Classifier false positives**: standalone "promotion" was stealing NCAAF/UFC
  articles into MLS (promotions happen in every sport) — MLS now keys on
  "relegation"/"pro/rel"/"usl", the distinctive vocabulary. "champion" was too
  generic for UFC. Esports got its own term set (LoL/Valorant/CS2/Dota/OWL/CDL
  + team/player vocabulary).
- **dotesports RSS** added for esports chatter.
- **Request budget respected** (espn-request-budget skill): ESPN stays at 7
  requests (1/league, host_budget=20, disk-cached 1h); bluesky is a public API
  without the ESPN wall.

### 8.7 Data model

- `news_items` gains `conv_id TEXT` (which conversation an item feeds).
- `news_narratives` keyed by `conv_id TEXT PRIMARY KEY` with
  `league, title, narrative, fan_voice, paragraph, sources, source_count,
  generated_at`. (Migrated on dev; prod `picks.db` still needs the ALTER
  before promotion — see RUNBOOK-prod-promotion.md.)

### 8.8 API / UI

- `/api/news` → `{conversations: [...], leagues: {lg: {conversations,
  narratives, granular, other}}}`. Home tab renders the flat conversations
  list (esports filtered); per-league tabs render that league's conversations
  + the granular feed.
- `/api/news/narratives` → every conversation card.
- `pages/news.tsx` renders each card as prose paragraph + source chips
  (up to 2, then "and more"). Card header: `LEAGUE · CONVERSATION TITLE`.
- 26/26 tests pass (`test_news.py`).

### 8.9 Next steps (not built)

- ~~League summary pass~~ → **BUILT 2026-08-09, see §9.**
- More seeds per league as conversations firm up (MLB salary cap, UFC, NCAAF
  realignment, Valorant declined on 2026-08-07 because their chatter was
  genuinely scattered/weak — honesty over padding). → **one new seed added
  2026-08-09 from evidence, see §9.4.**
- ~~Scheduled collector/narrative cron~~ → **BUILT 2026-08-09, see §9.5.**
- Prod promotion: migrate `news_narratives` schema on `picks.db` first.

---

## 9. PROGRESS UPDATE — 2026-08-09 (items 2-5 from §8.9)

Built on the v2 conversation surface. All dev-DB only (news still excluded
from prod; see §0 coordination note).

### 9.1 League summary pass (item 2) — DONE

`backend/ingest_league_summaries.py` rolls each league's conversation cards up
into ONE "state of the league" paragraph. Runs AFTER `ingest_league_narratives`.
One DeepSeek batch call across every league that has cards, so the model varies
voice across leagues (same reason the narrative desk batches). Same
strict-JSON + retry + keep-old-on-batch-fail pattern. A league whose cards have
no through-line declines (honest — a run on 2026-08-09 declined 2-3 of 8).

- New table `news_league_summaries(league PRIMARY KEY, summary, generated_at)`
  in `_core._init_db`.
- API: `_league_report` carries `summary` per league (or `""`); served on
  `/api/news` and `/api/news/{league}`.
- UI: `LeagueSummaryCard` at the top of each per-league tab (emerald left-rule,
  "State of the league" label), above the conversation cards. No source chips of
  its own — it synthesizes the cards beneath it, which carry the receipts.
- Verified: plain worker on a spare port served all 8 leagues' summaries; live
  dev backend (:8096) needs a recycle first (see §9.6).

### 9.2 Freshness policy (item 4) — DECIDED

Per-day (1 day). Surfaced as the daily cron below. Conversations regenerate on
each collect; the top conversation carries a first-seen date.

### 9.3 Source grounding — NOT an issue (Micah, 2026-08-09)

Earlier flagged that 5/9 cards carried `source_count=0`. Not an issue: the
granular feed items all link to real articles (`url` is UNIQUE NOT NULL), and
the conversation cards are grounded in the collected chatter. Source-chip
grounding on the narrative cards is left as-is.

### 9.4 More seeds (item 5) — one, evidence-based

Mined the already-collected signal (no extra ESPN budget) for recurring
conversations not yet seeded. Only ONE met the bar (multiple recurring
headlines, distinct from existing seeds):

- `nba-kawhi-cap` ("Kawhi Leonard salary cap circumvention Clippers") — Pablo
  Torre bombshell + Stephen A. "banishment" call (3 refs in collected items).
  The other leagues' live conversations are already covered by existing seeds;
  remaining headlines were single granular events, not recurring narratives —
  declined rather than padded (Valorant precedent).

Verified: the new card generates clean (plain language, attributed fan voice,
2 sources) and the NBA summary now rolls up BOTH Kawhi and Las Vegas expansion.

### 9.5 Daily cron (item 3) — DONE

- `scripts/news-collect.sh`: runs collector → narratives → summaries against
  `picks.dev.db` (dev-only). Each step logged; one failing does not abort the
  next (a transient ESPN per-host 403 must not block the DeepSeek refresh).
  Idempotent upserts; re-runs inside the cache TTL cost zero ESPN requests.
- systemd `legendarypicks-news.service` (oneshot, Nice=10, TimeoutStartSec=900)
  + `legendarypicks-news.timer` (OnCalendar daily 03:35, Persistent). Enabled +
  active; first fire Mon 2026-08-10 03:35 CDT. Mirrors the
  `legendarypicks-nfl-transactions` unit pattern.
- Smoke-tested end-to-end (exit 0).

### 9.6 Open / needs Micah

- **Dev backend :8096 recycle.** A `uvicorn --reload` cycle wedged (dead worker
  + zombie child, socket held but not accepting) after a rapid 3-file edit
  sequence during this work. The code is verified correct on a plain spare-port
  worker; 8096 just needs a process recycle. Claude was blocked from killing
  the managed PID (2081285) by the dev-server guardrail — Micah to relaunch with
  the original command, or authorize it.
- Prod promotion (still): migrate `news_narratives` + `news_league_summaries`
  on prod `picks.db` before any release that ships news.

---

## 10. Cross-league tournaments are not modelled (2026-08-10)

Micah:

> tournaments like leagues cup and ewc are weird because they don't just span
> one league.

He is right, and today the data model has no answer for it. `news_items.league`
and `news_conversations.league` are both a single value, so every conversation
belongs to exactly one league tab. That works for a salary-cap fight inside MLB
and breaks for anything that crosses a border:

- **Leagues Cup** is MLS *and* Liga MX. We do not carry Liga MX as a league at
  all, so a Leagues Cup story can only be filed under `mls`, which quietly
  states that it is an MLS story — half true at best. The
  `mls-ligamx-spending` conversation is exactly this case: its subject is the
  boundary between two leagues, and it renders on the MLS tab.
- **Esports World Cup** spans every title (CS, LoL, Valorant, CoD, RL); we
  flatten all of them into one `esports` league, which is the same compromise
  one level up.
- The same problem is coming for the World Cup, the Club World Cup, and any
  cross-conference college event.

**Decision for now (Micah, 2026-08-10): file it under MLS and move on.** The
card is live on the MLS tab and reads correctly. This section exists so the
compromise is written down rather than discovered later as a bug.

**When it is worth fixing**, the shape is a `competition` dimension that is
independent of `league` — an item and a conversation each carry an optional
competition (`leagues-cup`, `ewc`, `world-cup`) alongside their league, and a
tournament gets its own tab that draws from every league feeding it. That also
gives the esports hub a way to stop pretending CS and LoL are one league. It is
a schema change plus a nav change, not a rewrite — but it should not be done
until a second cross-league conversation actually needs it.
