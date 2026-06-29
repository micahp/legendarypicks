# Esports data recon — what's free, what's paid, and the workarounds

Companion to `esports-opportunity-feedback.md` (the strategy) and
`Free_Sports__Esports_Streams_for_Embedding.md` (the stream research). This doc answers the
*binding-constraint* question those two skip: **which esports give us live structured player
data**, and at what cost — because the "Live Now / about-to-hit" feature is gated by live data,
not by stream availability. Guiding constraint (Micah): **don't pay for data first; validate on
free data before building proprietary ingest.**

## The reorder
ChatGPT's order ranked by *audience size*. Ranked by *free live data* (what actually gates the
feature), the order inverts — the biggest-audience titles (CoD, Valorant) are the most data-locked.

| Title | Free live data? | Source | Catch |
|---|---|---|---|
| **Dota 2** | ✅ free even commercially | **STRATZ** (free GraphQL, wants brand attribution) + **OpenDota** (open-source) | none at scale — the lead |
| **CS2** | ✅ free *official* | **GRID Open Access** (official, real-time, 70+ TOs) | **non-commercial / pre-revenue ONLY** → free to validate, pay GRID's tier at monetization |
| **Valorant / LoL** | ❌ (free) | GRID/Riot exclusive **paid** portal | paid from day one |
| **CoD (CDL)** | ❌ official | CitoAPI ~$25/mo third-party | paid + unofficial |
| **Chess** (non-esport, included) | ✅ free | **Lichess API** + Chess.com API (open, live, eval/win%) | none — zero-cost loop validator |

## Workarounds for the paid tiers (3 & 4)
The paid lock is on the *official* feed. Big-audience titles have community/aggregator routes that
are free-or-cheap and good enough for the **stats / projection / summary** surfaces:

- **Valorant:** `vlrggapi` (unofficial REST over vlr.gg) for match + player data; rib.gg for
  analytics. Near-live, not licensed.
- **LoL:** Leaguepedia/Liquipedia data; community scrapes. (Bayes/GRID hold the official rights.)
- **CoD (CDL):** CitoAPI (~$25/mo, live matches + map-by-map + player stats), Breaking Point
  (breakingpoint.gg) and cod-stats.com for stats, Liquipedia portal, `COD-Stats-API` on GitHub.

**Honest caveats** (don't build on these blind):
1. **ToS** — scraping vlr.gg / breakingpoint / etc. may violate their terms; fine for prototyping,
   diligence needed before commercial use.
2. **Fragility** — scrapers break when the source site changes; needs maintenance.
3. **Latency** — "live" via scrape is delayed (seconds→minutes). Fine for prop-hit-rate *context*
   and summaries; weaker for a true real-time "about to hit THIS second" feel. The cleanest
   real-time feel stays with the official feeds (Dota / CS2 / chess).

**Takeaway:** workarounds *do* unlock a big cross-title push — but treat each league as a **data
adapter** behind one league-agnostic engine, not a bespoke product. Official feed where it's free
(Dota, CS2, chess); scrape/cheap-API adapter for CoD/Valorant/LoL. One spine, many faces.

## Data Skrive (why "free data first" is correct, not a compromise)
ESPN's auto game summaries (incl. the MLB ones in our `generate_game_story`) are produced by a
vendor, **Data Skrive**. So our summary feature is a baby Data Skrive — validating data-grounded
auto-content as a real, sellable market. The lesson: **raw stats are a free/licensed commodity;
the ownable, sellable asset is the DERIVED layer** — projections, hit-rates, prop-outcome history,
generated narratives. We can build all of it on $0 data and never own raw ingest until validated.

## Plan
1. **Lead = Dota 2** — free forever (STRATZ/OpenDota), real betting-adjacent audience.
2. **CS2 = live-Major validation now** — free GRID Open Access while pre-revenue; a Major is live.
3. **CoD / Valorant / LoL** — bring in via scrape/aggregator adapters (workarounds above) for the
   stats/summary/projection surfaces; pay for official feeds only once a title proves out.
4. **Chess** (Lichess) — zero-cost fallback to prove the loop.
5. **Thin slice to build first:** live feed → projection-vs-actual → "about to hit" card/alert,
   on one source (Dota free, or CS2 during the Major).
