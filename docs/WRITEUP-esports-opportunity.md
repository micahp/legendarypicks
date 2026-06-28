# Writeup — the esports opportunity

Status: strategy note, not a committed roadmap item. Author prompt: "esports has a huge following
of people just as cracked-out paying attention — could be a huge opportunity." This lays out the
case, the fit with what we've already built, what's unknown, and a concrete first step. Honest
about what we don't know yet — claims that need validation are marked **[verify]**.

## The thesis
Esports has the one thing our whole model is built around: an audience that follows competitive
outcomes and player performance obsessively. The viewership for top titles (CS2, League of Legends,
Valorant, Dota 2, CoD) is large and young, the fandom is forum-deep and stats-literate, and there's
an active betting market around it. That's the same shape as the NBA/NFL hardcore we're courting —
just a different sport. We already have a toe in: **CoD is on the scoreboard today** (via
`breakingpoint_client` / `cdl_client`).

The honest uncertainty (the prompt named it): we don't know yet whether the esports audience *bets*
at the same rate per fan as traditional-sports fans, or how mature esports prop markets are. That's
the main thing to validate before investing heavily. **[verify]**

## Why it fits what we've already built
Our engine is league-agnostic: **scoreboard → props → stats/leaderboards → per-player game logs →
modeling**. Esports maps onto every layer:
- **Scoreboard** — matches with states (upcoming/live/final), same as CoD already does.
- **Stats / leaderboards** — every title has per-player performance stats (CS: K/D, ADR, rating;
  LoL: KDA, CS/min, gold; etc.). Same Stats-tab shape we're building for traditional leagues.
- **Per-match player logs** — the esports analog of `player_game_logs`. The prop-outcome engine
  ("did the line hit") generalizes directly: maps, kills, rounds are countable outcomes.
- **Brackets / pick'em** — esports playoffs are bracket-shaped and a huge engagement moment. This is
  the *same* bracket/pick'em feature already on the v0.3.0 roadmap for World Cup + CoD.

So the marginal cost of adding an esports title is mostly **data ingestion + identity**, not new
product surface. That's the strategic point: we don't build a separate thing, we add a league.

## Data — the deciding factor per title
Esports lives or dies on data accessibility, and it varies a lot by title:
- **CS2** — the classic: HLTV and similar carry rich, scrapeable match + player stats and a deep
  betting culture. Strongest candidate for "accessible data + bettor overlap". **[verify access terms]**
- **League of Legends** — Riot has an official data API + sites like Leaguepedia/Oracle's Elixir; very
  stats-heavy audience.
- **Dota 2** — OpenDota / STRATZ expose extensive free APIs (most open data of any title).
- **Valorant** — growing fast; data via VLR.gg and others. **[verify access]**
- **CoD** — we already ingest it (breakingpoint.gg); a proven path to extend, not start from zero.
- Aggregators (Liquipedia, Abios, PandaScore, GRID) cover many titles but some are paid. **[verify]**

Identity resolution is the recurring tax (our spine rule applies): players use handles, switch teams,
and span titles — resolve by a stable per-title source ID, never by name (`AGENTS.md §7`).

## Where the money/risk sits
- Esports betting is real and growing, but **per-title** markets and prop depth are uneven; aggregate
  is meaningful, any single title may be thin. **[verify market size + prop availability]**
- Scenes are more volatile than traditional leagues (titles rise/fall, orgs fold, patches reshape
  meta). Favor titles with durable competitive ecosystems (CS, LoL, Dota have lasted a decade+).
- Our edge is the same as everywhere: **selection + the prop-outcome data layer**, not being a book.

## Recommended first step (cheap, falsifiable)
Don't commit to "esports" broadly. Pick **one** title where the data is most open and the betting
overlap is clearest, and run it through the existing engine end-to-end as a probe:
1. **Validate demand + market** first (a day of research): is there prop-betting interest and data we
   can legally use for this title? Kill the idea here if not. **[verify]**
2. If yes, **extend the CoD pattern**: a scoreboard client for the chosen title (matches + state),
   then per-match player logs (the `player_game_logs` analog), then a Stats leaderboard, then — if
   prop lines exist — props. Reuse `_core` + the routers; it's a new league, not a new app.
3. **Brackets/pick'em** is the natural engagement hook (shared with the WC/CoD bracket work) and is
   title-agnostic — a fast way to draw the esports audience in before full prop depth exists.

Leading candidate to probe first: **CS2** (deepest bettor culture + scrapeable stats) or **Dota 2**
(most open free API, lowest data friction). Decide on data access, not vibes.

## Open questions to answer before building
- Does the esports audience bet at a rate that justifies the build? **[verify]**
- Which single title has the best (data accessibility × bettor overlap × scene durability)?
- Are there legal/ToS constraints on the stats sources we'd scrape? **[verify]**
- Does our prop-outcome engine need any title-specific outcome types (maps/rounds vs counts)?
