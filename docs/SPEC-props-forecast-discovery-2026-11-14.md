# SPEC: Discoverable player forecasts on Props, players, games and homepage

Date: 2026-11-14  
Status: **Design / engineering specification only. Not implemented or approved for rollout.**  
Proposed initial rollout: **NFL only, gated by source and forecast readiness.**  
Canonical IA: [DECISION-forecast-first-leagues-market-first-props-2026-10-20.md](DECISION-forecast-first-leagues-market-first-props-2026-10-20.md).

## 0. Decision

Make the model's next-game player forecast **discoverable before a player search**, but **do not add a sixth Props tab or a separate Player Projections island**.

- Keep **Props** a market-first research and comparison page. Make the **Props board** the default landing rather than Slate, while retaining Slate, Performance and Matchups and their explicit deep links.
- Above the market board, add a compact **Upcoming player forecasts** section that can show a player-game-market forecast **without a sportsbook offer**. It is a *discovery* surface, not a ranked bet-pick carousel.
- On existing player/game/prop cards, show the same **persisted, versioned** player distribution. Make the **projected stat** prominent alongside the **book's actual line and odds**. Show hit rates as historical context, not as forecast probabilities.
- Keep the older Model tab and all its deep links until its custom-line probe and multi-stat views have equivalent replacements. Do not relabel the old recency estimator as NFL Spec B v2.
- Never call a difference of 4.7 projected yards a monetary `edge`, expected value, implied probability or a recommendation. Never label an unvalidated number a winning bet.

The two complementary user questions are:

1. **What do the models expect this player to do?** A next-game forecast, even when no book has posted a line.
2. **How does that expectation compare with the available line and the player's history?** One contextual player/game/market card, not a duplicate per sportsbook offer.

This extends the October 20 decision, rather than replacing its forecast-first leagues / market-first Props information architecture.

## 1. Current implementation, checked on dev (2026-11-14)

| Surface | Current implementation | Design consequence |
|---|---|---|
| `pages/props.tsx` | Five tabs: Slate, Props, Performance, Matchups, Model; default state is `slate`. Explicit query `?tab=` and `?date=` supported. | Switch implicit default to `props` only; explicit links must remain stable. |
| `components/Props/MarketSlateBoard.tsx` | One card per player × game × canonical market; multiple provider/line offers within card. Filters one selected market, initially loads a 150-row window. History fetched for those visible rows. Sort options include hit-rate, Wilson-confidence floor, odds, `edge` and line. | Extend this card. Do not flatten provider variants, relaunch unbounded requests, or imply global ranking of unloaded rows. |
| `/api/props`, `/api/props/slate`, `/api/props/history` | Book quotes, offers and game-log evidence. `/api/props` does not return the canonical NFL `game_id`; the board currently groups by player/date/team strings. | Add canonical fixture identity to an additive API read contract so forecast joins use IDs. |
| `/api/projections/player/{id}` and Props -> Model | Old recency-weighted game-log estimate, plus percentiles and a historical `prob_over` probe. Not Spec B v2 or calibrated NFL next-game probability. | Retain as explicitly labeled **historical estimate** while migrating. Never silently replace/model-tag it. |
| `/api/nfl/projections?week=&season=` | Persisted NFL v2 slate, per-player base mean/median/p10/p90, Marcel/ESPN where present and `p_plays`; latest stored run per key. | Reuse as a source for batch forecast reads, but add timestamps, operational status, fixture cutoff and stable market taxonomy. |
| `/api/nfl/projections/player/{id}?model=v2\|v2-platt&market=&line=` | Persisted v2 player/scenario details with a line-dependent simulated P(over), optionally Platt calibrated. | May power **one expanded card**, not hundreds of individual board fetches. Model/calibration status must be explicit. |
| `backend/nfl_player_projections_job.py` | Writes immutable run IDs and weekly rows to `player_projections`; v2 conditional on participation; receiving targets/receptions/yards/TDs and expected-passer QB attempts/completions/yards/TDs. Rushing forecast not published by this job. | Display only actual supported, published stats and keep `p_plays` separate from conditional stat forecasts. |
| `pages/player/[id].tsx` | Current Props and Projections already exist but are the older profile estimator. | Promote a distinct **Next game forecast** before the old history-oriented breakdown when a valid v2 snapshot exists. |
| `components/Game/GameProps.tsx` | Shows props with history chart and settled outcomes, not a unified player distribution. | Add projected stat line in context without changing settlement/line deduplication. |

Do not infer production deployments or model certification from repository code alone; verify real API output on the target environment before enabling the new UI.

### Existing safety/readiness constraints

- The 2026 Weeks 2–9 NFL retrospective study found raw v2 prop probabilities worse than the market; forward-only Platt performed closer to or slightly better than the market in selected weeks. The selected sportsbook quote cutoff still needs independent verification. **These research results do not certify public betting edges.**
- A confirmed weekly NFL ingest defect drops receiving yards/TDs on **zero-target lateral plays**; the research branch has an in-memory corrected-history study, not proof that all stored production histories have been repaired. Validate source correction/version before enabling forecast labels based on those inputs.
- The point-calibration work's **+0.625 receptions** is research-only. It is *not* part of the frozen v2 projection, nor a blanket per-player UI uplift. Never add it client-side.
- NFL forecasts are conditional on playing. A `p_plays` value does not mean a particular prop's chance of hitting, and not all competitors or stat markets have a published v2 forecast.
- NCAAF direct player-prop research is **NOT_ADOPTED** as a public model. Unsupported leagues and markets must show accurate coverage states, not fallback model values with v2 labels.

## 2. User jobs and success criteria

**Job A: Discovery.** On entering `/props`, a new visitor can see meaningful **next-game forecasts** without typing a name or opening the Model tab.

**Job B: Comparison.** On a published line, a visitor can distinguish **our projected mean**, **the book's threshold and price**, and **last-5/10/20 hit rates** in less than a glance.

**Job C: Investigation.** Selecting a player-market shows median, central distribution range, historical outcomes, participation assumptions, provenance and alternate provider offers. A selected line can be changed without recalculating a different, inconsistent model.

**Job D: Context.** Someone arriving at a player, a game or a league page can find the same forecast there, and navigate back to the relevant Props market without losing identity/date/market.

Success is not click-through alone: no forged probabilities, no forecast/history label confusion, no provider identity loss, no late-as-pregame forecasts and no increased page-level request storms.

## 3. Information architecture / routes

**Canonical default:** `/props` with no `?tab` opens the **Props market board**, the current league navigation and a date selected from valid slates; if today has nothing, choose the next upcoming slate as the current date-navigation behavior intends. A date chosen explicitly in `?date=YYYY-MM-DD` always wins.

**Top hierarchy:**

1. Page title **Props** + existing sport/competition navigation.
2. Date navigation (only when relevant to a dated slate).
3. **Upcoming player forecasts**: 3–6 compact diverse items from the selected league/date, *not* “best bets,” high-confidence guesses or unsourced “top plays.” Display more forecasts through existing league/player/game pathways.
4. **Browse player markets**: existing market selector, provider offers, filters, market cards and charts.
5. Historical workflows: **Slate**, **Performance**, **Matchups** as existing navigation destinations; legacy **Model** retained temporarily.

**Deep links:** continue `?tab=slate`, `?tab=props`, `?tab=performance`, `?tab=matchups`, `?tab=model`. Future `?tab=forecasts` is **not** needed; do not add it. Preserve `date`, `league` (or selected competition), `market`, player and game context in links where supported; unsupported query keys must not break the page. When Model is eventually retired, `?tab=model` must redirect/map into the player's forecast details **with the selected player and any custom market/line preserved**; do not delete the original URL first.

**Other entry points:**

- **Player `/player/[id]` → Next game forecast:** all supported modeled stats even if no book offers. Next to each stat, optionally show a real published line. A clear link opens the matching Props card/offer.
- **Game detail → Player forecasts / Props:** both teams' forecasted player outcomes, with player identity and kickoff. Existing game-props chart/settlement affordances remain; no duplicated fake odds.
- **League desk → Upcoming player forecasts** module when that league has operationally verified player forecasts; do not confuse with **game-winner Forecasts**.
- **Homepage → player forecasts** teaser near scores/previews once operational; a lightweight module, not a new top-level nav destination.
- Off-board forecast (no book quote) remains visible on player/game/league discovery, but the offer-driven Props board itself stays truthful about which markets have live lines.

### Navigation wireframe (illustrative layout, no factual predictions)

    Props                                    [NFL] [NBA] ...
    < previous slate       Sat Nov 14           next slate >

    UPCOMING PLAYER FORECASTS
    [Player 1 · matchup · Receiving yards: projected 64.2 · 10th–90th 30–98]
    [Player 2 · matchup · Receptions: projected 4.6 · 10th–90th 1–9]
    [Player 3 · matchup · Passing yards: projected 242 · 10th–90th 154–326]
    (illustrative figures only; never hard-code these as live data)

    BROWSE PLAYER MARKETS
    [Receiving yards 124] [Receptions 98] [Passing yards 34] ...
    Sort: [Upcoming] [Historical hit rate] [Historical reliability] [Odds]
    Search player (optional)

    Player · Team @ Opponent                  Receiving yards
    OUR PROJECTION            BOOK LINE                RECENT HISTORY
    64.2 yd                   59.5 (-110)              L5 3/5 · L10 6/10
    Median 61 · 10th–90th 30–98            Difference: +4.7 yd (not EV)
    [Choose line & provider]  [View chart / forecast breakdown]

No made-up player forecasts, markets, odds or line timestamps may appear in actual page output.

## 4. Props board: card contract and interaction

**Card identity:** one `(league, game_id, player_id, canonical_market)`. Provider/line variants are **nested offers**. No name-based joins, inferred fixture from date/opponent text, or duplicated cards per over/under. Keep existing real-odds vs pick'em-source handling and alternate-line selection.

**Card visual hierarchy:**

1. Player name, team, opponent, kickoff, market label.
2. **Our projection** (mean and stat unit) and **Book line** (numeric threshold, over/under odds and provider). Show both at the same prominence.
3. **Median**, **10th–90th percentile** interval with a clearly labeled source/model/version. Do not call this a guaranteed 80% confidence interval or “floor/ceiling.”
4. **Historical L5/L10/L20** rates *at the selected line*, with sample denominators. The old Wilson lower bound, currently called `Confidence`, is labeled **Historical reliability** or **Hit-rate evidence**, not model confidence.
5. **Difference from line** in *stat units*, e.g. `Projected +4.7 yards vs line`. Rename the board's current `Edge` display/sort to **Proj.–line** or **Projection gap** until a validated price-aware opportunity model exists.
6. If an eligible probability exists, show `Model P(over) at 59.5` with raw/calibrated provenance. This is **not** the historical hit rate or probability of winning money; it may be absent even when a mean is present.
7. Disclosure for the detailed view. Keep the existing historical `PropChart` data visible and distinct from the new forecast distribution, rather than visually implying the historic sample *is* the simulated forecast.

**Offer switching:** changing an alternate line updates the shown provider/price and historical hit rates for that line; if model P(over) is supported, recalculate/select the probability for **that exact line, same game/player/model snapshot**. The player's mean/median/quantiles do **not** change merely because a different book line was selected. Never use the probability for the previous line under a newly selected one.

**Expanded detail** (lazy):

- Forecast distribution: mean, median, p10 and p90; density/histogram only if actual frozen draws or a documented reproducible distribution are available, not a fake curve interpolated through four summary numbers.
- P(over)/P(under) for eligible half-point lines; if pushing is possible, include `P(push)` and disclose conditional settlement rules. Do not assume `P(under) = 1 − P(over)` in a market where pushes/voids are possible.
- Price comparison only with a **verified paired real-odds offer** observed before kickoff; pick'em fixed placeholder odds are **not** sportsbook pricing. A probability difference is not automatically positive EV.
- Conditional-on-playing and injury/participation information, available scenario switch (base / teammate if-plays / teammate if-out), model version, run/as-of, kickoff, prediction status, and data limitations.
- Actual game-log bars, exact line, L5/L10/L20 rates, observed sample counts and opponent splits where available.
- Real provider alternatives in a compact dropdown; no duplicated card stacks.

**Sort/filter behavior:**

- Forecast discovery rail defaults to chronological upcoming kickoff; tie-break by game ID/player ID/market. Diversify by game/market so six cards are not six adjacent alternates of one player. Do **not** rank by speculative edge or unvalidated P(over).
- Props board keeps market-first; default visible-row order must be deterministic and non-promotional (upcoming game/market's player alphabetic or grounded provider ordering). Make historical hit rate and historical reliability explicit opt-in sorts.
- If adding `Projection gap` sorting, it is **only within a single stat market**, never across yards/receptions/TD units; it must say that a bigger gap does not imply a better bet.
- **Global sort integrity:** today only the first 150 market rows get history and sorting. Do not describe an ordered subset as “all players ranked.” Either sort server-side on fully available keys before windowing, or explicitly say **“Sorted within the 150 displayed rows”**. Never fetch thousands of row-history endpoints to fake a full rank.
- Search remains optional and works across already-loaded player-name data; no search gate should block initial forecast discovery.

## 5. Responsive behavior and states

**Desktop:** discovery rail above market selector, max three forecast cards per row; market cards keep full player/line/history detail without horizontal overflow.

**Phone (360–430px):** forecast rail can scroll horizontally with visible next-card hint or stack two high-value forecast cards; touch target at least 44×44 px. On each prop card show player + market, model projection and current book line first, historical L5/L10/L20 in a second row, and expandable history/distribution below. Provider/alternate-line menu is keyboard- and touch-operable. Never require hover for definitions. Avoid 3-wide micro-stat columns that truncate prices/units or hide the selected offer.

**Loading:** reserve card dimensions; do not block current quotes/history while projection snapshots load. Loading a new date aborts prior snapshot requests. Avoid showing prior-date projections with new-date lines during race conditions.

**No forecast:** explicit `No published model forecast for this game/market`; still show real offers and historical rates. A missing forecast is **not zero**. Unsupported league is not “Model predicts 50%.”

**Forecast, no book:** show projected stats on forecast rail, player/game surfaces with `No sportsbook line available` (or `No verified line` when quote provenance fails). Do not synthesize a line or buy link.

**No games/offseason:** show next available fixture if applicable; otherwise preserve honest empty slate with quick path to past performance/last games.

**Injury uncertainty:** `Mean given player participates` with participation estimate separately labeled when present; only show validated scenarios for the saved run. No “certain to play” label inferred from a missing injury report.

**Late/research snapshots:** label as `After kickoff / research` in historical analysis only; never display as a live, locked pregame forecast. Settled games show original pre-kickoff snapshot and realized stat separately, not a later recomputed prediction.

## 6. Data contract (proposed additive read API, not yet implemented)

**Proposed** `GET /api/props/forecast-slate?league=nfl&date=YYYY-MM-DD&market=receiving_yards` (optional `game_id`, `player_id`). This is one **batched** read for the active league/date/market (or bounded discovery sample), not N independent `/api/nfl/projections/player/{id}` calls. For the initial NFL phase, it can adapt the existing `player_projections` rows and `/api/nfl/projections` semantics; later leagues must register their own verified adapters.

**Proposed** `GET /api/props/forecast-detail?league=nfl&game_id=...&player_id=...&market=...&line=...` for one selected expanded card. This may fetch a documented persisted distribution or a deterministic/cached line-specific probability, but must not run full-season simulation during every request. Responses must identify original forecast inputs and probability source.

**Required normalized fields** (exact naming can be finalized with API tests; semantics are not optional):

    forecast_key: (league, game_id, player_id, canonical_market, model_version, snapshot_id)
    game: (kickoff_utc, home_team, away_team, status)
    player: (canonical_player_id, team_id/code, display_name, position)
    forecast: (mean, median, p10, p90, units, scenario, conditional_on_playing, p_plays)
    provenance: (model_family, model_version, run_id, as_of_utc, locked_at_utc?, run_status,
                 snapshot_status, input_source_version, coverage_status)
    quotes: (provider, source_type, over/under side, line, real_odds?, captured_at_utc,
             paired_price_status, event_id, offer_id)
    line_probability: (line, p_over, p_under?, p_push?, model_variant,
                       calibration_status, derived_from_snapshot_id, computed_at_utc)
    historical: (l5/l10/l20 over_count, sample_count, observed_games, line, side)

**Statuses:** `preview`, `locked`, `final`, `research_late`, `missing`, `unsupported`, `invalid_provenance`. Distinguish **persisted eligible preview** from **eligible immutable pre-kickoff lock** and from **research backfill**. Only the lock enters official grading/record. An API response with `as_of_utc >= kickoff_utc` must never be labeled pregame or promoted to the board's featured forecasts. A non-`ok` model run is ineligible.

**Line and key mapping:**

- Existing stored v2 stat keys include `rec_yds`, `rec`, `rec_td`, `tgt`, `pass_yds`, `att`, `cmp`, `pass_td`. Map them explicitly to sportsbook canonical markets `receiving_yards`, `receptions`, `receiving_tds`, `targets`, `passing_yards`, `pass_attempts`, `pass_completions`, `passing_touchdowns`.
- Audit unsupported aliases and compound markets. Do **not** map `rushing_receiving_yards` to receiving yards or `total_touchdowns` to receiving TDs just because the text is similar.
- Add `game_id` and competition/fixture identity to the current offer response as additive fields; for NFL crosswalk to `nfl_schedule.game_id`, with exact provider fixture ID. Do not join `player_projections` by player name, day and opponents; reject ambiguous mappings.
- `p_plays` and stat-line `mean` are different measurements. Do not multiply them client-side and still label the result `mean given plays`.
- `v2-platt` is a **probability transform**; it is not a second point-estimate forecast. The research-only +0.625 receptions offset is not a serving `model_version`.
- `p10/p90` alone cannot be transformed into honest probabilities at arbitrary alternate thresholds. For an exact price-specific P(over), use a saved eligible predictive distribution or reproducible precomputed line-probability snapshots; do not apply a sigmoid to the projected mean.

**Provider data integrity:** use source-category taxonomy (true sportsbook odds vs pick'em placeholders) in `components/Props/odds` and current odds taxonomy. Verify paired sides, line and timestamp; until the kickoff-price audit is closed, use actual provider offers only as labeled quotes, not verified closing lines or a validated model “advantage.”

## 7. Publication / readiness gate

A snapshot is **eligible for a prominent forecast** only when ALL hold:

- Source model/market has been designated publicly available for this league, and the target game has an **actual upcoming fixture**.
- Provenance is complete: stable player/game/stat ID, successful model run, as-of recorded, kickoff checked, named model version and scenario. Any official `locked` designation is backed by a pre-kickoff frozen record, not merely the latest row.
- The displayed distribution belongs to that **same** game/player/market/snapshot as the selected prop line. Missing values remain null, never zero-filled.
- Known correctness blocks in the model inputs (including the zero-target receiving-lateral weekly ingest issue) are either repaired and verified or surfaced as a disqualifying readiness reason. Do not quietly promote a research-only counterfactual.
- If showing Platt P(over), it is fitted only from **earlier** settled periods; the map's existence/version, timing and status are supplied. A `raw_no_map` response shows raw with explicit label or omits public probability. Do not present “calibrated” when none exists.

Publishing a raw point mean may be allowed earlier than publishing a betting probability, but only as a clearly labeled model **preview**, not certified edge or lock. Hide unavailable probability rather than silently use historical win percentage.

## 8. Delivery sequence (small, reviewable PRs)

**PR A — APIs, identity and gates (no visual default flip):**
- Audit available real NFL v2 records and kickoff/as-of integrity in the target DB; enumerate supported markets and unresolved player/fixture mappings.
- Add canonical `game_id`/fixture identity to `/api/props` and relevant slate payloads; preserve old fields and consumers.
- Add batched forecast-slate API, status/readiness metadata and unit-tested mapping. One SQL read or bounded pages; no per-card simulation. Add deterministic fixture tests (good preview, locked, research-late, missing player, aliases, no book line).
- If a distribution/line probability is not available from persisted data, return `null`; do not invent it to satisfy the card design.

**PR B — market board and Props default (NFL behind a flag):**
- Add upcoming forecast rail and compact `Projection vs Line vs History` presentation to existing cards, preserving all provider selections and settled history.
- Preserve explicit `?tab=slate` / Model links; switch **only** unqualified `/props` to the Props tab.
- Rename or accurately relabel the old confidence/edge values. Add forecast/historical sorting, market filters, truthful missing state and small mobile layout.
- Gate rollout so unsupported leagues display the present board and historical estimator without falsely adopting v2.
- Verify real API data against at least three NFL games, one no-offer forecast, one multi-book alternate-line card, and one no-model market.

**PR C — player/game/league/home reuse:**
- Build one shared `PlayerForecastSummary` / `ForecastDetail` rendering contract rather than copying computations into four pages.
- Player overview: next-game stat forecasts above old per-game history estimates; all forecastable stats even with no props.
- Game detail: both teams' eligible player projections alongside existing historical prop chips and settled outcomes.
- League desk and homepage: capped upcoming forecast teasers with direct player/market/game links; publish only after availability/quality gates.
- Keep keyboard navigation, stable return URLs, and no redundant model tabs.

**PR D — deep forecast + retired legacy destination (only after parity):**
- Expanded details: scenarios, p10/p90, audited model P(over) at exact selected line, optional distribution chart when real draws exist, provenance/methodology, compare to available book prices only when safe.
- Move Model-tab multi-stat table and custom line input into expanded player/card experience, preserving user functionality; add a `?tab=model` compatibility route to that same context.
- Do not delete Model tab or historical endpoint until parity tests and deep-link regressions pass. No implicit public bet recommendation.

**Rollout order:** backend/readiness → one NFL flag-enabled slate → player/game integration → league/home surfacing → legacy Model migration → other certified leagues. No data migrations or schedule restarts in this docs-only spec.

## 9. Acceptance tests / design QA

| ID | Acceptance criterion | Evidence required |
|---|---|---|
| UX-01 | `/props` shows existing board plus upcoming real forecast content without search; explicit `?tab=slate` remains Slate. | Desktop and 390px screenshot, direct URL load. |
| UX-02 | A card shows our mean, chosen real book line/odds and distinct L5/L10/L20 history with actual sample counts. | Compare rendered values to API responses; no historical percentage labeled forecast probability. |
| UX-03 | Alternate line/provider switches do not change forecast mean/quantiles; any P(over) is recomputed for exactly that line. | Multi-book same-player fixture and exact joined ID assertion. |
| UX-04 | An NFL player with persisted forecast but zero eligible offers is discoverable on the player/game/league forecast entry point. | No-offer DB fixture and screenshot; no fabricated provider price. |
| UX-05 | Missing/unsupported/late/research-only projection cannot appear as a locked pregame forecast. | API contract and UI negative tests across status codes. |
| UX-06 | All other leagues preserve existing useful book/history UI; NCAAF NOT_ADOPTED cannot appear as approved forecast. | Cross-league smoke tests. |
| UX-07 | Full large NCAAF market does not trigger 2,000 history or forecast calls. | Network request-count assertion, initial payload size, scroll and filter responsiveness, stable 150-row window. |
| UX-08 | Market sort doesn't imply universal ranking when only a visible subset was scored; no cross-unit projection-gap sort. | Controlled 500+ row fixture with out-of-window candidate. |
| UX-09 | Line prices distinguish real sports-book odds from pick'em placeholder quotes and respect captured timestamps. | Exact provider/offer tests; no `-137` interpreted as a real quote. |
| UX-10 | Model/historical estimator versions cannot be mixed under one label, and conditional-on-playing is explained. | API source assertions and visible copy in player, board, game. |
| UX-11 | Calendar/player/game/market deep links survive navigation, refresh and the eventual Model-tab retirement. | Browser/e2e route tests, including `?tab=model` and `?date=`. |
| UX-12 | Touch, keyboard, screen-reader descriptions, narrow widths and loading/race states are usable. | 360px/390px/desktop checks, focus order, accessible name and tab tests. |
| UX-13 | Locked forecast equals the original recorded eligible snapshot when revisiting a settled game, never a later projection. | Fixture with later model run and completed score. |
| UX-14 | Provenance block (late capture, bad stat key, unresolved join, missing kickoff) refuses to show a confident model-probability claim. | Test failure paths and response status metadata. |

**Real-world demo script:** open Props → NFL upcoming date without a search → see a true next-game mean → select a receiving-yards market → compare one provider/line against the mean and L10 → change alternate line → open full distribution and player profile → follow game link and verify same version/as-of → revisit a finished game and verify original frozen preview and actual outcome.

## 10. Explicit non-goals

- No new top-level Projections app, sixth Props tab, redesign of every league, or forced NBA/NCAAF model enablement.
- No hard-coded figures, betting picks, “best bets,” win-rate badge, invented confidence score or hypothetical profit/ROI.
- No new ML model fitting, v2 parameter edits, research-only recalibration applied in the frontend, or rewrite of existing historical props.
- No automatic “edge” ranking across mixed markets or fake sportsbook closing-line comparison.
- No one-request-per-card architecture, unbounded prop fetches, or client-side mass simulation.
- No removal of old Model functionality until parity exists.
- No backend code change, runtime rollout, database write, or deployment under this documentation PR.

## 11. Implementation references

- `pages/props.tsx`; `components/Props/MarketSlateBoard.tsx`; `components/Props/PropChart.tsx`; `components/Props/odds.ts`
- `backend/routers/props.py`; `backend/routers/players/projections.py`; `backend/routers/players/nfl_projections.py`; `backend/nfl_player_projections_job.py`
- `pages/player/[id].tsx`; `components/Game/GameProps.tsx`; league and homepage components (locate at implementation time)
- `docs/DECISION-forecast-first-leagues-market-first-props-2026-10-20.md`
- `docs/PROPS-ODDS-TAXONOMY.md`; `docs/SPEC-player-projections-availability-2026-10-09.md`
- `docs/RESEARCH-nfl-model-inputs-2026-10-11.md`
- `docs/research/nfl-injury-history-2026-weeks2-9/PROP-PROJECTION-BACKTEST-2026-WEEKS2-9.md` and `POINT-CALIBRATION-2026-WEEKS2-9.md` (**research branch; may not yet be on dev**).
