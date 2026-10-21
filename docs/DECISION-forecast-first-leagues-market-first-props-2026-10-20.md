# Decision: Forecast-first leagues and market-first Props
Date: 2026-10-20
Status: **Agreed product direction, NOT yet implemented.**
Supersedes the navigation destination proposed in PROPS-TABS-DESIGN.md; that older file is historical context, not current IA guidance.

## User jobs, not model names

The two primary questions are:
- **What will happen in a game?** The league's **Forecasts** experience, default landing for leagues with verified game forecasts.
- **What will this player do and how does it compare with a line?** The existing **Props** market board, with projections and real provider offers shown together.

"Model" describes machinery. Forecasts, Props, Schedule, Performance and Matchups describe the user's task. Do **not** add a new Player Projections tab to NCAAF or another Props-wide standalone model page. Place full player distributions within contextual market cards, player details, and game details.

## Canonical product map

| User intent | Primary location | Relevant content |
| --- | --- | --- |
| Winner / scores / game-level forecasts | League -> **Forecasts** (default when certified) | Upcoming games, winners, win probabilities, validated score lines, lock/grade record, ratings |
| Fixture browsing / results | League -> Schedule; game detail | Published schedule and final scores, linked to projections |
| Team tables / stats | League -> Standings, Stats | Existing factual surfaces |
| Player prop market discovery | **Props -> Props** (future default) | Book lines, provider/price/time, L5/L10/L20, projected stat + distribution, P(over/under) |
| Browse player markets by game | Props -> Slate | Game groups, links to the same card/market |
| Evaluate a player's complete forecast | Player profile or expanded card | All supported modeled stats, quantiles, evidence, history, as-of and model version |
| Performance and opponent splits | Props -> Performance / Matchups | Historical data, never conflated with model probabilities |
| Evaluate one game's player outcomes | Game detail -> Props | Both teams' player markets and probabilities from same forecast snapshots |
| Understand accuracy and methodology | In-context forecast details | Brier, CRPS, calibration, model version, paired benchmarks, caveats |

## League landing and Forecasts design

- Rename **user-facing** "Model" to **Forecasts** where the model is ready. Keep existing URL ?tab=model working as an alias during rollout, including shared/bookmarked links. Any future ?tab=forecasts route must preserve the old URL.
- When entering /leagues/{league} with no tab, choose Forecasts only for a league with an **operationally verified** nonempty game forecast. NHL is the primary reference. NCAAF cannot be automatically promoted while C2/G2h production parity or locking is blocked; NFL requires its own model-pick workflow checks. No unsupported league should default to an empty "coming soon" panel.
- Preserve useful current landings for unsupported/special cases (NFL Home, UFC, Standings or Schedule as appropriate).
- Show game card headline: opponents, kickoff, source/as-of, frozen/preview state, predicted winner and win probabilities. Show mathematically implied fair prices where appropriate, but label them **model prices** rather than real bookmaker offers. Only show spreads/totals/scores when those separate distributions have passed their validation.
- Keep Records/Ratings/methodology secondary within the Forecasts surface. An ordinary user should not have to navigate through model names to discover outcomes.
- Explicitly distinguish preview, locked, final, research/late, missed. Only immutable eligible pregame forecasts enter the official record. "Model pick" means the committed forecast; a priced wagering opportunity requires a separately validated market and policy.
- Provide obvious links league -> game -> player -> Props, and back.

## Props: integrate instead of duplicate

As checked on 2026-10-20, pages/props.tsx has five tabs: Slate, Props, Performance, Matchups, Model. The current Model tab is a simple player-search view of recency-weighted per-game estimates from GET /api/projections/player/{id}; those values are **not** the adopted 2026 FBS direct-props models.

- Make **Props -> Props** the intended implicit /props landing, with league/date/market filters retained. Preserve explicit ?tab= links. For a league with no published offers, show a true coverage explanation and an easy route to Slate or player detail, not invented offers.
- Keep Slate for fixture-first browsing; Performance and Matchups for observed historical evidence.
- **Consolidate first, retire later:** move useful Props -> Model functions (multi-stat projections, percentiles, custom line checks) into the existing expanded prop card and player profile; preserve old ?tab=model links until new destinations cover the same jobs, then redirect with context. Do not delete the tab ahead of replacement.
- A single prop card represents **player x game x market**, with provider/line variants nested beneath. Keep current MarketSlateBoard.tsx grouping, provider treatment, price labels, settled result history and charts. Do not flatten boosted and alternative lines.
- Show the real sportsbook line alongside our validated projection (expected stat, median, relevant quantiles) and P(over)/P(under) **computed at that exact line** from the same frozen predictive distribution.
- Distinguish L5/L10/L20 historical hit rate from model P(over). The current difference between projection and line is a **stat-unit difference**, not verified expected value, profitable edge, or confidence. A true price-adjusted edge requires real comparable line-side odds; pick'em offers may have no leg price.
- Deep view: lazy distribution chart + credible ranges, data coverage, usage/availability caveats, model version, timestamp, and optional benchmark comparison. An individual forecast may exist when no book line exists; let users discover it via player/game views with a truthful "no published line" state.
- Fetch forecasts as batched league/date/game/market snapshots rather than an extra request for every row. NCAAF boards have thousands of lines and previously exhausted the browser with excessive row fetches.

## Shared prediction contract

All public surfaces should read **the same** keyed, persisted forecast: league, game_id, player_id (for props), canonical market, model_version, valid as_of_utc, kickoff_utc, forecast/lock status, source and uncertainty. Historical results must grade the original immutable pregame snapshot. No live fitting in request handlers, no name-only player identity joins, and no invented statistics to fill nulls. Published odds, observed frequencies, candidate predictions, certified previews and frozen forecasts must be labeled differently.

### Readiness

- NCAAF game winners: original G2h research benchmark accepted, but production parity remains **blocked** until the separate parity decision's gates are met.
- NCAAF player distributions: **NOT_ADOPTED for user-facing Props forecasts**. The 2025 active-player cohort audit at research/fbs-direct-props-2026-10-20 @ ad535b9b overturns the four former all-rows ADOPT_CANDIDATE verdicts: the direct model loses to trailing-5 on every positive-usage cohort. Do not display it as a validated projection. Run a new pregame-participation x conditional-volume hurdle-model experiment, grade full-line outcomes under provider settlement rules and only then reconsider integration. See [DECISION-fbs-props-active-cohort-hurdle-2026-10-20.md](DECISION-fbs-props-active-cohort-hurdle-2026-10-20.md).
- NHL/NFL/other leagues require independent readiness gates. Don't copy game-winner Brier scales into player-prop CRPS.

## Delivery plan (future implementation; this branch is docs only)

1. Resolve model/source parity, timestamp discipline, graded records and feature coverage per league. No shortcuts to model certification.
2. Change league tab presentation + default-selection logic in components/Leagues/hooks/useLeagueRouteState.ts and pages/leagues/[league].tsx; preserve tab=model deep links. Do not force defaults based simply on whether a route component exists.
3. Make Props market board the implied default in pages/props.tsx, honoring explicit ?tab and date; verify empty/offseason states.
4. Add a versioned **batch projection read API** for fixture-scoped player distributions. Validate that live board player IDs/market taxonomies map to the modeled athlete and actual market line. No extra per-card request storms.
5. Add compact forecast numbers to MarketSlateBoard cards; show detailed distributions on expansion and on player/game views. Keep the existing older estimator separately labeled as a baseline; never silently substitute it for an unavailable adopted model.
6. Only after equivalent functionality exists, migrate/remove the Props -> Model navigation destination and retain link compatibility. Add game-to-player and player-to-game navigation.
7. Desktop/mobile/e2e QA on NHL, NFL/NCAAF weekly pages, populated NCAAF multi-provider prop slate, and no-data/offseason states; measure data payloads, row-window request counts and meaningful real content, not HTTP 200 alone.

## Acceptance

- Forecast-ready league opens to verified game forecasts; explicit old tabs work; unsupported leagues have a useful landing.
- /props opens the provider-market board when rollout is approved. Slate and all old deep links work through migration.
- One real published line matches the same player/game/market as its frozen forecast; probability, quantiles and as-of can be independently reconciled. Historical hit rate is never called model P(over).
- No uncertified model is presented as locked or production-equivalent. No arbitrary model "fair spread" or unsupported profitability/edge claims.
- Card performance stays bounded on a large NCAAF slate; source/time/coverage are visible; detail is lazy.
- Model page/Props/player/game navigation is coherent without redundant "Model" and "Player Projections" destinations.

## Source implementation checked

pages/leagues/[league].tsx, components/Leagues/hooks/useLeagueRouteState.ts, pages/props.tsx, components/Props/MarketSlateBoard.tsx, components/Props/PropChart.tsx, components/Game/GameProps.tsx, backend/routers/players/projections.py, backend/routers/props.py, docs/PROJECTIONS-METHODOLOGY.md.

**Decision:** League is forecast-first when trusted. Props is market-first. Player distributions enrich existing surfaces, not a new navigation island.
