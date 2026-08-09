# Provider audit — verification of section-6 "NOT verified" items (2026-08-06)

Follow-up to `docs/PROVIDER-AUDIT-2026-08-06.md` §6 items 2–6 (item 1, ESPN, excluded —
handled by the parent agent). Every claim below was re-checked with live fetches on
**2026-08-06** (URLs recorded per claim). Note: `web_search`/`web_extract` (Firecrawl)
were unconfigured in this environment, so all fetches were made directly over HTTP from
this box via Python stdlib; the evidence is the live response, not a search index.

| # | Claim | Verdict |
|---|-------|---------|
| 2 | Underdog `over_under_lines` contains tennis rows | **VERIFIED** (rows exist — players + match appearances; **0 active tennis O/U lines** in this snapshot — see notes) |
| 3 | Kalshi trade-api v2 exact query params (`series_ticker` / `event_ticker`) | **VERIFIED** (exact working URL shapes recorded) |
| 4 | FotMob men's CONCACAF Champions Cup league id | **VERIFIED** — league id **297** |
| 5 | tennis-data.co.uk live fetch (was 504 ×2) | **VERIFIED** — live over `http://` (https TLS-broken from this box) |
| 6 | concacaf.com internal JSON API | **VERIFIED** — `dapi.concacaf.com/v2/content/en-us/...` works; `api-sdp.concacaf.com/v1/` referenced but path shape unconfirmed |

---

## Item 2 — Underdog Fantasy tennis rows inside `over_under_lines`

**Claim being verified:** `api.underdogfantasy.com/beta/v5/over_under_lines` actually
contains tennis rows; the prior 2 MB truncation (NFL/MLB/WNBA first) hid them.

**Verdict: VERIFIED (with an important caveat — see notes).**

**Evidence (fetched 2026-08-06):**
- `GET https://api.underdogfantasy.com/beta/v5/over_under_lines` → **200**, `application/json`, **12,771,192 bytes** (full book, unfiltered).
- In the full payload: **75 tennis player records** with `sport_id: "TENNIS"`,
  `position_name: "TP"`, `position_display_name: "Tennis Player"` (e.g. Aryna Sabalenka
  id `8fd4c6db-19e8-443f-9ba8-6eea0a8af21c`, Coco Gauff); **75 tennis match
  appearances** (`match_type: "SoloGame"`, `type: "Player"`) spanning **38 distinct
  tennis match_ids**; 113 occurrences of the quoted `"TENNIS"` string in the book.
- Query-param filter attempts (all fetched 2026-08-06): `?sport=tennis`,
  `?sports=tennis`, `?league=tennis` → each returned **200 with the same ~12.77 MB
  payload and identical 451 "tennis" hits** — the endpoint ignores sport filters;
  there is no server-side sport filter.

**Notes / caveat (the part that matters for the plan):**
- **0 of the 5,617 `over_under_lines` entries are tied to a tennis appearance** (joined
  via `options[].appearance_id` → `appearances[].id` → `players[].id`; line entries carry
  no top-level `player_id`). So today's book contains tennis **players and scheduled
  matches but no active tennis O/U props** — Underdog is not currently offering tennis
  pick'em lines in this capture, so the endpoint cannot yet be used to ingest tennis
  props. The audit's "fallback, verify shape at implementation" verdict stands: shape of
  a tennis *line* row remains unobserved. Re-check at implementation (tennis slates
  appear only when Underdog runs them).
- This also explains the original truncation: tennis rows are present but sort low;
  the earlier 2 MB cut was a sampling artifact, not absence.

---

## Item 3 — Kalshi trade-api v2 exact query params

**Claim being verified:** read endpoints are
`https://api.elections.kalshi.com/trade-api/v2/events?series_ticker=KXATPMATCH` and
`/markets?event_ticker=...` (public GET, no key).

**Verdict: VERIFIED.** Both URL shapes are correct and work with no authentication.

**Evidence (all fetched 2026-08-06, status 200 `application/json`):**
- `GET https://api.elections.kalshi.com/trade-api/v2/events?series_ticker=KXATPMATCH`
  → 200, 97,321 bytes, **200 events**, first results:
  `KXATPMATCH-26AUG07VANHUR` "Van de Zandschulp vs Hurkacz",
  `KXATPMATCH-26AUG07TIEPAU` "Tien vs Paul", `KXATPMATCH-26AUG07MERMIC` "Merida vs
  Michelsen".
- `GET https://api.elections.kalshi.com/trade-api/v2/events?series_ticker=KXWTAMATCH`
  → 200 (WTA series resolves the same way).
- `GET https://api.elections.kalshi.com/trade-api/v2/markets?event_ticker=KXATPMATCH-26AUG07VANHUR`
  → 200, 4,907 bytes, **2 markets**:
  `KXATPMATCH-26AUG07VANHUR-HUR` "Will Hubert Hurkacz win the Van de Zandschulp vs
  Hurkacz: Round Of 32 match?" and `-VAN` for Van de Zandschulp.
- `GET https://docs.kalshi.com/` → 200 (JS SPA shell; no server-rendered
  `series_ticker` text to quote — the live GETs above are the authoritative evidence).

**Exact working URL shapes:**
```
https://api.elections.kalshi.com/trade-api/v2/events?series_ticker=KXATPMATCH
https://api.elections.kalshi.com/trade-api/v2/markets?event_ticker=<EVENT_TICKER>
```
Note: the events response is paginated (200 returned); cursor pagination exists.
No key needed for public reads.

---

## Item 4 — FotMob men's CONCACAF Champions Cup league id

**Claim being verified:** men's CCC league id on FotMob (Leagues Cup = 10043 and
W Champions Cup = 11013 were already verified).

**Verdict: VERIFIED — men's CONCACAF Champions Cup league id = 297.**

**Evidence (fetched 2026-08-06):**
- `GET https://apigw.fotmob.com/searchapi/suggest?term=champions%20cup` (headers
  `Accept: application/json`, `Referer: https://www.fotmob.com/`) → **200** JSON with
  `leagueSuggest` options: **`"CONCACAF Champions Cup|297"`** (payload `id: "297"`,
  `countryCode: "INT"`), `Arab Club Champions Cup|10474`, `CONCACAF W Champions Cup|11013`.
- `GET https://www.fotmob.com/leagues/297` → **200**; `<title>` = **"CONCACAF Champions
  Cup matches, tables and news 2026"**; embedded data shows `leagueId: 297`, seopath
  `concacaf-champions-cup`, and a live-fixture link
  `https://pub.fotmob.com/prod/db/api/fixture/live?leagueId=297`.

**Notes:**
- The old `https://www.fotmob.com/api/leagues?id=...` endpoint now returns 404 from this
  box (FotMob tightened the legacy `/api/` paths); the suggest endpoint
  `https://apigw.fotmob.com/searchapi/suggest?term=...` works but requires the
  `Accept: application/json` + `Referer` headers.
- Bonus finding: `https://pub.fotmob.com/prod/db/api/fixture/live?leagueId=297` is the
  page's declared live-fixture API for the competition (not probed this run).

---

## Item 5 — tennis-data.co.uk live fetch (was 504 ×2)

**Claim being verified:** the per-season files (`2026/2026.xlsx`, index `/alldata.php`)
are live and fetchable.

**Verdict: VERIFIED — the site and files are live, but only over plain `http://`;
`https://` is broken from this box (TLS alert, not 504, this run).**

**Evidence (fetched 2026-08-06):**
- `GET http://www.tennis-data.co.uk/alldata.php` → **200**, `text/html`, 68,710 bytes;
  index contains the expected links verbatim:
  `<A HREF="2026/2026.xlsx">2026</A> (Match results and betting odds)` (ATP) and
  `<A HREF="2026w/2026.xlsx">2026</A> (Match results and betting odds)` (WTA).
- `GET http://www.tennis-data.co.uk/2026/2026.xlsx` → **200**,
  `application/vnd.openxmlformats-officedocument.spreadsheetml.sheet`, **286,859 bytes**,
  zip magic `PK\x03\x04` (valid xlsx). Saved to `/tmp/probe/2026.xlsx` as a working
  artifact.
- `https://www.tennis-data.co.uk/...` and `https://tennis-data.co.uk/...` (both www and
  bare, 4 URL variants) → fail with `[SSL: TLSV1_ALERT_INTERNAL_ERROR]` — a server-side
  TLS negotiation failure from this box (prior run observed 504 ×2; different symptom,
  same conclusion: **use `http://`**, not https).

**Notes:** The audit's "contents verified via search-indexed copy + Kaggle mirror" can be
upgraded to a direct live fetch. Data pipeline should hardcode `http://` (or accept
http→https with a fallback), and treat the https failure as a known WAF/TLS quirk of the
host, not a data outage.

---

## Item 6 — concacaf.com internal (undocumented) JSON API

**Claim being verified:** an undocumented JSON API exists behind the concacaf.com SPA.

**Verdict: VERIFIED — a working undocumented content JSON API exists at
`dapi.concacaf.com`; a second sports-data host (`api-sdp.concacaf.com/v1/`) is
referenced by the site but its endpoint shape is unconfirmed.**

**Evidence (fetched 2026-08-06):**
- `GET https://dapi.concacaf.com/v2/content/en-us/competitions` → **200**,
  `application/json`, 62,569 bytes, 25 competition items (slugs incl. `leagues-cup`,
  `gold-cup`, `nations-league`, `caribbean-cup`, `fifa-world-cup`).
- `GET https://dapi.concacaf.com/v2/content/en-us/tags/central-american-cup` → **200**
  JSON; metadata shows `"createdBy":"concacaf-umbraco-webhook-client"` — i.e. a
  headless-Umbraco content API (`selfUrl` pattern
  `https://dapi.concacaf.com/v2/content/en-us/{type}/{slug}`; homepage SSR HTML embeds
  332 distinct `dapi.concacaf.com/v2/content/en-us/...` URLs incl.
  `competitions/calendar-champions-cup-2027`…`2030`).
- `GET https://www.concacaf.com/` → 200 (3.2 MB SSR HTML) embeds env config
  `"SDP_API_URL_WITH_VERSION":"https://api-sdp.concacaf.com/v1/"`,
  `"SDP_PROJECT":"concacaf"`, host `api-sdp.concacaf.com` (sports-data platform).
- Negative probes (same date): `dapi /v2/content/en-us/matches` → 404
  (`application/problem+json`); `api-sdp.concacaf.com/v1/{competitions,tournaments,
  matches,leagues,standings,scores,teams}` (with/without `?project=concacaf`) → 404.

**Notes:** The verified API is a **CMS content** API (competitions, tags, calendar
pages) — usable for competition/calendar content, but **no match-score JSON endpoint was
confirmed** (`/v2/content/en-us/matches` 404s; the match data likely lives on
`api-sdp.concacaf.com/v1/...` under an unconfirmed path, or behind an app-level route).
For scores the audit's ESPN/FotMob coverage remains the right call; `dapi` is a
documented-in-practice content source, not a scores source.

---

## Verification log

| # | URL fetched | Result | Date |
|---|-------------|--------|------|
| 2 | https://api.underdogfantasy.com/beta/v5/over_under_lines | 200, 12,771,192 B; 75 tennis players, 75 tennis appearances, 38 match ids; 0 tennis O/U lines | 2026-08-06 |
| 2 | https://api.underdogfantasy.com/beta/v5/over_under_lines?sport=tennis (also ?sports=, ?league=) | 200, same ~12.77 MB book, 451 "tennis" hits — filter ignored | 2026-08-06 |
| 3 | https://api.elections.kalshi.com/trade-api/v2/events?series_ticker=KXATPMATCH | 200, 200 events (KXATPMATCH-26AUG07VANHUR etc.) | 2026-08-06 |
| 3 | https://api.elections.kalshi.com/trade-api/v2/events?series_ticker=KXWTAMATCH | 200 | 2026-08-06 |
| 3 | https://api.elections.kalshi.com/trade-api/v2/markets?event_ticker=KXATPMATCH-26AUG07VANHUR | 200, 2 markets (-HUR / -VAN) | 2026-08-06 |
| 4 | https://apigw.fotmob.com/searchapi/suggest?term=champions%20cup | 200, "CONCACAF Champions Cup\|297" | 2026-08-06 |
| 4 | https://www.fotmob.com/leagues/297 | 200, title "CONCACAF Champions Cup matches, tables and news 2026", leagueId 297 | 2026-08-06 |
| 5 | http://www.tennis-data.co.uk/alldata.php | 200, 68,710 B; links to 2026/2026.xlsx and 2026w/2026.xlsx | 2026-08-06 |
| 5 | http://www.tennis-data.co.uk/2026/2026.xlsx | 200, xlsx MIME, 286,859 B, PK magic | 2026-08-06 |
| 5 | https://www.tennis-data.co.uk/alldata.php (+3 https variants) | TLSV1_ALERT_INTERNAL_ERROR (no 504 this run) | 2026-08-06 |
| 6 | https://dapi.concacaf.com/v2/content/en-us/competitions | 200, 62,569 B, 25 competitions | 2026-08-06 |
| 6 | https://dapi.concacaf.com/v2/content/en-us/tags/central-american-cup | 200 JSON (umbraco webhook client) | 2026-08-06 |
| 6 | https://dapi.concacaf.com/v2/content/en-us/matches | 404 application/problem+json | 2026-08-06 |
| 6 | https://api-sdp.concacaf.com/v1/{competitions,matches,leagues,...} | 404 (path shape unconfirmed) | 2026-08-06 |
| 6 | https://www.concacaf.com/ | 200, 3.2 MB SSR; embeds SDP_API_URL_WITH_VERSION + 332 dapi paths | 2026-08-06 |

Method note: Firecrawl web tools were unconfigured in this environment, so no
web_search/web_extract was used; all evidence is from direct HTTP fetches made
2026-08-06 with a browser User-Agent via Python stdlib (`urllib`). No ESPN host was
touched (per constraint). Items 1 (ESPN) handled by parent.
