# Bovada player-props odds: the public path, measured 2026-09-05

Scope: pulling Bovada's **fantasy-style player prop** odds (the alt-line ladders,
e.g. `36+ Receiving Yards` → `-197`, `46+` → `-115`, `56+` → `+119` …) for today's
games **without login**. Every claim below is a probe run on 2026-09-05, not a
recollection.

## TL;DR

- The endpoint already wired into `config.py` is the correct one, and **a UA-only
  request is all it takes** — no cookies, no login, no API key.
- It returns the **entire market tree (~72 MB)** with every market and its odds inline.
  Filter client-side for sport + date + player-prop markets.
- **Confirmed working from a residential IP** (`68.203.204.219`, Charter/Spectrum,
  `hosting:false`).
- **Our production box egress is a datacenter IP (proven).** Bovada runs PerimeterX
  (`x-px` response header, `TS…` bot cookie), which is built to challenge and block
  datacenter IPs and non-browser clients. So this scrape **cannot come from the
  datacenter box** — it has to originate from a residential egress (proxy pool or a
  separate residential host) and push results into prod.

## The request (verified)

The same endpoint as `config.py`:

```text
https://www.bovada.lv/services/sports/event/coupon/events/A/description
```

Minimal working request — just a browser UA + `Accept: application/json`:

```bash
curl -sS \
  -A "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36" \
  -H "Accept: application/json" \
  "https://www.bovada.lv/services/sports/event/coupon/events/A/description"
```

Response: `HTTP 200`, `Content-Type: application/json`, ~72 MB of a full market tree.
(The repo's `config.py` `HDR` uses a Linux Chrome UA; both UAs return the full payload —
the server keys on the UA being a browser, not on which one.)

`client.py` shards it per sport/league with `{BOVADA}/{sport}/{league}`
(e.g. `/soccer/north-america/leagues-cup`, `/ufc-mma/ufc`, `/tennis/atp`). A sharded
`{sport}/{league}` path returns the same shape but only that slice — much smaller than
the 72 MB whole-site tree, and the right call for scheduled runs. The 72 MB whole-tree
fetch is a research/debugging convenience, not a production request shape.

## Payload structure

```text
top-level node
  .path[]            # [category, league, ...] e.g. ["College Football","Football"]
  .events[]
     .id, .description, .competitors[], .startTime (ms UTC), .live
     .displayGroups[]
        .description                             # e.g. "Receiving Yards"
        .markets[]
           .description, .key (e.g. GAME-PROP-12), .marketTypeId
           .outcomes[]
              .description                       # e.g. "36+ Receiving Yards"
              .price.american / .price.decimal
              .competitorId
```

Every market's odds are inline in `outcomes[].price`. There is no separate odds call.

## Per-sport prop groups (measured)

- **NCAAF (FBS)** — `path = ["College Football","Football"]`. Props live under groups
  like `Receiving Yards`, `Passing Yards`, `Rushing Yards`, `TD Scorer Props`. The
  alt-line ladders are the `Alternate * Yards` markets (`key=GAME-PROP-12`), which is
  exactly the "36+ / 46+ / 56+ …" shape behind a fantasy prop.
- **MLS** — `path = ["MLS","United States",...,"Soccer"]`. Props under `Goalscorer`,
  `Assists`, `Cards`, `Game Props`, `Goal Props`. (NB: as `config.py` notes, Bovada
  prices only 2 of the 11 stat markets this league is built for — the RotoWire/PrizePicks
  relay remains the MLS source; Bovada's value here is as a second book/holiday.)
- **US Open singles** — `path = ["Men's Singles","US Open","Tennis"]` and `...Women's…`.
  Props under `Set Props`, `Match Props`, `Service Game Props`, `Break Props`,
  `Player Props`, `Ace/Double Fault Props`.
- **UFC** — each fight is its own event under `path = ["UFC <card>","UFC","UFC/MMA"]`,
  with a single `Fight Odds` display group carrying the moneyline + `Method of Victory`
  and other fight props.

## Verified numbers (residential, 2026-09-05)

```text
  ufc              12 events
  ncaaf_fbs        67 events
  mls              14 events
  usopen_singles   15 events
  TOTAL           108 events / 2,968 markets / 1,302 player props
```

## Datacenter IP (prod) — the constraint

The probe that confirmed the UA-only path ran from **residential** egress
(`68.203.204.219`, Charter/Spectrum, `hosting:false`, `proxy:false`). **Our prod box is
a proven datacenter IP**, and Bovada is behind **PerimeterX**: the page load sets a
`TS…` bot cookie and responses carry an `x-px: …` header. PerimeterX/Cloudflare
bot-management is built to challenge and block datacenter IPs and non-browser clients.

So: the residential-confirmed path does **not** apply to the prod box directly. On a
datacenter egress the expected result is a JS-challenge / captcha page (`403`,
`captcha_type`) instead of the JSON, or the JSON once and then throttled/flagged (one
probe during this run returned a ~5 KB truncated body on a back-to-back request).

### Production approach (given a datacenter box)

1. **Residential proxy rotation** (Bright Data / Oxylabs / Smartproxy) on the server.
   Fetch the (small, sharded) per-league slices 1–2× a day, cache to the DB, serve from
   cache. Player-prop odds do not need to be real-time.
2. **Headless Chrome / Playwright** to pass the PerimeterX JS challenge, then reuse the
   `cf_clearance`-style / `TS…` cookie on the same egress.
3. **Fetch from a residential egress** and push the parsed results to the datacenter
   server (keeps the whole scrapable surface on a residential IP).

## Do not

- Don't hit the 72 MB whole-tree endpoint repeatedly. It is the whole site; a scheduled
  run should use the `{sport}/{league}` shards, plus backoff (already in `backoff.py`).
  The payload is large, and hammering it burns the egress.
- Don't wire this scrape into a job that runs on the datacenter box directly — it will
  hit the PerimeterX challenge. Put the fetch on residential egress, cache to the DB.
- These are proprietary Bovada markets made public without auth; check their terms before
  redistributing odds on the public site, and keep request volume low.

## Reference implementation

Production logic already lives in `backend/bovada_scraper/` (`config.py` endpoint +
`client.py` fetch/parse, `parsers.py` per-league, `backoff.py`). The standalone
residential-egress explorer used to measure the numbers above is at
`C:\Users\micah\OneDrive\Desktop\Workspace\bovada-props\bovada_props.py`
(not in-repo; reference only) and prints the same per-sport/per-market breakdown.

## Trace

- 2026-09-05 — confirmed the UA-only `/description` path returns full odds from
  residential egress, measured the four sport boards, and confirmed the prod box (a
  datacenter IP) must scrape via a residential egress.
