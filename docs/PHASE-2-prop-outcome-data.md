# Legendary Picks — Phase 2: Prop-Outcome Data

## What this is (and why it's the wedge)
Phase 2 is **not** the player-stock-market dream — it's the **data engine that the dream needs
underneath it anyway**, productized as the lowest-risk, fastest, *sellable-standalone* slice:

> "Here is every player prop, the line, and whether it hit — searchable, with hit-rate history,
> available as a public page and a paid API."

Why first:
- **Lowest legal risk** — it's historical data/analytics, not a betting market or a security.
- **You already generate it** — the prediction-market trading op tracks props + outcomes; the ESPN
  backend (`backend/sports_service.py`, `espn_client.py`) already pulls box scores. This is mostly
  *assembly*, not new science.
- **Sells by itself** (Micah's words) — B2B API/CSV, no user liquidity or cold-start needed.
- **It's the pricing engine** for the eventual player-shares flagship (a share price needs a model;
  this is the model's ground truth).

Identity, resolved: **Legendary Picks is a sports prediction & prop-outcome data company**, with a
player-market consumer app as the eventual flagship — not four products, one engine in risk order.

## Data foundation — build on nflverse/nflfastR (the nfelo lesson)
Benchmarks: **nfelo** is built *entirely on the free open-source `nflfastR` dataset* + custom Elo/EPA
models (no paid data partners; backtested since 2009; power ratings, QB rankings, game projections,
+EV betting). **EstablishTheRun** goes deeper (projections, best-ball/dynasty/rookie rankings, The
Solver DFS optimizer + sims, mock-draft assistant, props analysis) but pays Sports Data IO + Sports
Info Solutions for it. **Lesson: the value is the MODELS on top of open data — start free.**

`nflverse` is the goldmine and there's a Python port (`nfl_data_py`) that drops into our FastAPI
backend. ONE source powers all four needs:

| Need | nflverse data |
|---|---|
| Depth worth paying for | Full play-by-play since 1999: EPA, win prob (WP), CPOE, xYAC, usage |
| Sims (game/season/playoff) | PBP + EPA + WP → Monte-Carlo |
| Mock drafts / draft assistant | ADP, depth charts, rosters, rookie + combine data |
| Prop settlement + CONTEXT | box-score stats per player + the usage/matchup context that makes a hit-rate mean something |

**This reframes "worth paying for":** not "did the prop hit," but "here's the hit-rate AND the
EPA/usage/matchup context that explains it, plus a sim projecting the next line" = nfelo-grade.
- **Start with NFL** (nflverse is the deepest, free, nightly). Other sports later via analogs
  (`hoopR` NBA, `baseballr`/Statcast MLB) and your existing ESPN backend for cross-league coverage.
- Ingest nflverse releases (parquet) via `nfl_data_py` → our DB. Keep the ESPN backend for live
  scores + the cross-sport `strength` prior; nflverse is the deep historical/analytical layer.

## Data model (start SQLite, move to Postgres for prod)
```
players(id, name, team, league, espn_id)
games(id, league, date, home, away, espn_event_id, final)
props(id, game_id, player_id, market, line, side, source, captured_at)
       market ∈ {points, rebounds, assists, threes, pra, ... per sport}
       side   ∈ {over, under}
results(prop_id, actual_value, hit BOOL, settled_at)
```
`hit = (actual_value > line)` for OVER, `< line` for UNDER; push if equal. One prop+result row per
(game, player, market, line, side).

## Ingestion flow (daily cron)
1. **Lines in** — capture the day's props. SOURCING DECISION (pick one to start, see below):
   - (a) reuse the trading op's already-collected Kalshi/Polymarket sports markets, or
   - (b) a licensed odds API with player props (cleanest legal path), or
   - (c) start with a single hand-curated feed for the MVP sport.
2. **Results + context in** — after games go final, pull from **nflverse via `nfl_data_py`** (NFL):
   box-score stats per player (settle the prop) AND the EPA/usage/snap-share/matchup context. ESPN
   backend stays for live scores + cross-sport. nflverse backfills cleanly to 1999 = instant history.
3. **Settle + enrich** — compute `hit`, write `results`, attach the context fields. Backfill historical
   seasons from nflverse to seed deep hit-rate + usage history (this is the "worth paying for" depth).

## Backend API (extend the existing FastAPI service)
```
GET /api/props?player=&market=&date=&league=     -> list w/ line, side, actual, hit
GET /api/props/player/{id}/history?market=        -> chronological hits + rolling hit-rate
GET /api/props/stats?market=&league=&window=      -> aggregate hit rates (over vs under, by line band)
GET /api/players/search?q=                         -> typeahead
```
- **Free tier**: public page + limited unauthenticated calls.
- **Paid tier**: `X-Api-Key` header, tiered rate limits (nginx `limit_req`), CSV export endpoint.
  Billing via Stripe — **Micah's account owns it** (per agent-autonomy policy: humans own inbound $).

## Consumer page (Next.js, reuse the dapp shell)
- Search a player → table of recent props (market, line, side, actual, ✅/❌) + a hit-rate sparkline.
- Filters: market, league, date range, over/under.
- "Pro" CTA → API keys + CSV. Loading skeletons + empty/error states (see POLISH-CHECKLIST.md).
- No wallet required for this surface — keep Flow/wallet out of the data product (it's not web3).

## Build order (ship the smallest loop first)
1. **MVP loop, one sport, ~3 markets** (e.g. NBA points/rebounds/assists): ingest lines → settle from
   ESPN → SQLite → one search page showing hit/miss + hit-rate. *This is "something on Legendary
   Picks," then build from there.*
2. Backfill history (richer hit-rate); add more markets/leagues.
3. API keys + rate limiting + CSV export (the sellable B2B layer).
4. Stripe paywall on the API tier.
5. Only then revisit the fantasy/player-shares flagship on Flow (needs this engine + users + a lawyer
   for the "shares whose value floats" structure).

## Decisions to make before building
- **Line source** (a/b/c above) — biggest fork; determines legal posture, cost, and coverage.
- **First sport/markets** — pick where your trading-op data is already deepest.
- **Free vs paid boundary** — how much hit-rate history is public before the API paywall.

## Reuse / don't rebuild
- ESPN ingestion + the `strength` prior already exist — the predictor (Phase 3, idea #3) plugs into
  the same backend later.
- Keep this product **web3-free**; the Flow/dapp machinery is for the future player-market app.
- Secrets per DEPLOY doc: never ship `emulator-account.pkey`/`emulator.key`; API/Stripe keys via env.
