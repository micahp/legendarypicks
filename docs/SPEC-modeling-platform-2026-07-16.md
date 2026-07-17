# SPEC — Prediction Modeling Platform: capture → model → predict → brackets/lineups

**Author intent (Micah, 2026-07-16):** "I want to be modeling everything. Kalshi even models how many
maps will be played based on game context. I want historical AND live data powering data modeling so we
can predict everything from who wins a map to who wins the tournament across all these leagues. Then I
want to let people do brackets (playoffs/tournaments) and lineups."

This spec is phased. **Phase 1 (market-tape capture) is the clock-sensitive foundation and should start
immediately** — Kalshi's public API does NOT backfill historical order books, so price history only
accrues from the moment we capture it. Everything downstream (modeling, brackets, lineups) sits on that
tape.

---

## NORTH STAR — the user persona (read this FIRST; it governs every scope call below)

We are **not** building a trading tool. We are building a consumer product for a fan who wants what
**Nate Silver** gives: trustworthy **predictions** (who wins the map / series / tournament), **signals
that connect the dots** ("this team is underpriced because their roster just changed"), and help
**seeing the thing they'd have missed**. The user experience for that persona is the point.

So the value of any data we capture is measured by **what it lets us SHOW the user**, not by whether it
proves a trading edge:
- **A prediction they'll trust** — we can only model markets we have data for; capturing that data is
  what powers the forecast the user reads.
- **A signal worth surfacing** — "market says X, our read says Y, here's why" only means something when
  there's a real, liquid market to disagree with. Against a dead market there's no signal, just noise.

CLV / Brier / edge are **internal quality gates** — "is this model good enough to put in front of a
user" — never the deliverable. This flips the capture scope (below): we capture what powers a
user-facing prediction or a user-facing signal, and we skip everything that powers neither.

**Fresh evidence this is the right lens (Codex WC mining, 2026-07-16, 494 episodes):** generic booth/
tape signals moved correctly only **33.5% @+5min** — capturing "everything" is capturing noise. The
value was in the *specific, connectable* reads: a player the desk flagged, priced against his own prop
(Gordon +9.00R, Ndoye +13.29R, Bellingham 2+ +4.26R, Messi SOA +1.56R), and team-contract discounts
(+18.53R). The product is those connect-the-dots moments surfaced to a user — not a firehose of prices.

---

## 0. The market ladder we're modeling (grounds "predict everything")

Coverage differs sharply by league — the model + product must respect this, it's not uniform:

| League class | Team/series ladder | Player props | Notes |
|---|---|---|---|
| **Soccer** (WC, EPL, UCL) | winner, advance, spread, total, BTTS, 1H/2H, correct score, MOV | ✅ **rich** — score-or-assist, anytime/1st goalscorer, shots, SOG, saves, assists, brace, hat-trick | full player granularity — "Gordon danger man" is directly priceable |
| **Traditional** (NBA/NFL/MLB/NHL) | winner, spread, total | ✅ **rich** — pts/reb/ast, pass/rush/rec yds, anytime TD, strikeouts, RBIs, goalscorer | LP already has `player_game_logs` (111k) + projection engine |
| **Esports** (CoD/CS2/LoL/Dota/Val/R6/RL) | tournament, series/game, **map winner**, **total maps** | ❌ **none anywhere** (Kalshi + Bovada) | finest granularity = MAP. Player/roster Intel expresses as a TEAM/MAP bet (the Riyadh Falcons 7% pattern) |

**Implication:** the model predicts a *ladder* — for esports it bottoms out at map-winner + series
length ("how many maps," exactly the Kalshi model Micah cited); for soccer/traditional it goes down to
per-player props. Brackets/lineups must offer whatever granularity the league actually has.

---

## Phase 1 — MARKET-TAPE CAPTURE (build now)

Goal: capture the price tape **only where it earns its place in the product** — where it powers a
prediction the user reads, or a signal we can surface. NOT "all props, whole game." Two gates decide
what we tape, and every market must pass at least one:

- **MODELED** — the market is (or will be) forecast by our model, so we're the ones the user compares
  the market against. If we don't predict it, capturing its tape shows the user nothing. This is the
  esports **ladder that matters**: map-winner, total-maps (series length), game/series winner, advance,
  tournament — plus soccer/traditional markets we forecast down to the liquid player props.
- **CONTESTED + LIQUID** — the market is priced away from the rails (`watch_live.py`'s `CONTESTED`
  band) AND has real volume (its `SERIES_THRESH` bar). Only here is "market vs our read" a *signal*
  rather than noise; against a thin, pinned prop there's nothing to say to a user.

Everything that passes neither gate — the dead, illiquid long tail of props that we don't model and
nobody trades — we **skip** (or sample at a slow heartbeat for coverage, not tape). The Codex result
above is the receipt: 33.5%-correct generic signal is exactly what over-capture buys.

Within that scope, tape the **full intra-game path** (not snapshots), because the three things it powers
are all path-dependent and all user-facing: the **prediction's calibration** (is our forecast honest),
the **discount-window signal** ("this got cheap *right now* — here's why"), and the **connect-the-dots
join** to a roster change or a booth call at that timestamp. A snapshot or settlement can show none of
those.

### 1a. Kalshi: generalize the live watcher to the full ladder
`prediction-market-trading/watch_live.py` today hardcodes `SERIES = [game/match/advance winners only]`
(line 25-31) and `collect_orderbook.py` snapshots each event's order book every 3s. Extend, don't
rewrite:
- **Expand the series universe** from winner-only to the whole ladder per league of interest:
  esports `KX{COD,CS2,LOL,DOTA2,VALORANT,R6,ROCKETLEAGUE}{,GAME,MAP,TOTALMAPS}`; soccer `KXWC*`
  player + team markets (`KXWCSOA, KXWCPLAYERGOALS, KXWCAST, KXWCSHOT, KXWCSOG, KXWCSAVE,
  KXWCFIRSTGOAL, KXWCBRACE, KXWCSPREAD, KXWCTOTAL, KXWCBTTS`, plus EPL/UCL equivalents in season);
  traditional player-prop series (`KXNBA3PT, KXNFLANYTD/PASSYDS/RECYDS, KXMLBRBI, KXNHL*GOAL`, etc.).
- **Auto-discovery instead of a static list:** each poll, enumerate `/series?category=Sports`, filter
  to a configured league allowlist, and for every open market whose event is in the live/upcoming
  window, subscribe. `collect_orderbook.py` already takes a comma list of tickers and groups by event —
  feed it *all* of an event's markets (winner + map + total-maps + props), not just the two winner
  sides. Keep the per-series volume thresholds (`SERIES_THRESH`) — props/esports trade ~100× thinner
  than NBA, so they need low bars (CoD already uses `active_delta=1000`).
- Reuse the existing `launch()` idempotency + near-start window; PBP resolve stays best-effort.
- **DoD:** a live CoD/soccer session captured end-to-end WITH its map + total-maps (+ soccer prop)
  order books, not just the game winner.

### 1b. Bovada: add a continuous "tape" mode
`legendarypicks/backend/bovada_scraper.py` already parses player props (MLB/NBA/NFL/NHL + WC
goalscorer) but is a one-shot snapshot → ingest. Add an interval poller that, during an event's window,
re-scrapes all of its markets (lines + props) every N seconds into a time-series jsonl, converting
American odds → de-vigged implied probability. Bovada gives far broader prop coverage + always-on lines
where Kalshi liquidity is thin; it's a book line (not a traded tape), graded from box score.

### 1c. Backfill what's recoverable
Kalshi won't backfill order books, but for settled markets pull `status=settled` **result** +
`/markets/trades?ticker=…` **trade prints** to seed a partial historical tape (e.g. the WC games we
have transcripts for). Ground-truth outcomes come free from ESPN / PandaScore / GRID box scores.

### 1d. Unified normalized store (the modeling substrate)
One schema across venues + market types, so modeling reads one shape:
`{ts, venue, league, event_id, market_type(winner|map|total_maps|spread|total|prop_*), subject(team|
player|threshold), side, prob, price, depth, volume, oi, result, source}`. Versioned dir
(`data/market_tape/<version>/…`) like the existing strategy-versioned ledger. This store is BOTH the
model's training/benchmark data AND the CLV yardstick (did our model beat the closing price).

---

## Phase 2 — MODELING (what the tape powers)

Predict the whole ladder, bottom-up, so higher markets are consistent with lower ones:
- **Primitives → composites:** map-winner + a **series-length model** ("how many maps", conditioned on
  team strength, map pool/veto, format Bo-N) → series winner → advance → tournament (chained down the
  bracket path). For soccer/traditional, player-prop primitives (goal/assist/yards) roll up to team
  totals. This is exactly the "Kalshi models total maps from game context" capability, generalized.
- **Reuse LP's engine:** projection engine + v3 strength prior + `player_game_logs`; add per-league
  adapters (esports team strength from PandaScore/GRID results; map-winner from map-history; soccer
  player rates from prior matches).
- **Context features:** roster/lineup changes (the roster-change feed — the alpha the Falcons play was),
  booth Intel (the broadcast corpus), bracket stakes, rest/travel, home/LAN.
- **Calibrate against the tape:** Brier / log-loss + **CLV** vs captured closing prices. (Prior LP
  projection build had calibration working but EV/CLV empty — the tape is precisely what fills them.)

---

## Phase 3 — PRODUCT SURFACES (the consumer)

Same modeling spine, two engagement surfaces (both auto-generate receipts, per the geoppls thesis):
- **Brackets** — playoff/tournament predictor. User fills the bracket; every node is priced by the model
  with a market-edge chip; the filled bracket is a *chained* prediction (map→game→series→advance→title).
  Grades live as the bracket resolves. Natural fit for playoffs (the discovery on-ramp).
- **Lineups** — pick-set builder, league-aware granularity: soccer/NBA/NFL → **player-prop** lineups
  (Underdog-style: "these 5 to score/hit their line"); esports → **team/map** lineups (no player props
  exist). Scored vs outcomes.

---

## Constraints & honest limits
- **Start capture NOW:** Kalshi order-book history is not backfillable; every day uncaptured is lost.
- **Esports has no player props anywhere** → esports models/lineups are team/map-granular by necessity.
- **Bovada = book line, not a traded tape**, and scraping carries ToS/rate risk; Kalshi API has caps.
- **Concurrency:** the capture shares `data/` with the existing `*/4` cron + live runners — respect the
  CLAUDE.md guardrail (don't race them; new tape writes go to a separate versioned dir).
- **Cross-repo contract:** capture lives in `prediction-market-trading`; modeling + product in
  `legendarypicks`; the normalized `market_tape` schema is the shared boundary.

## First actions (sequence)
1. **Extend `watch_live.py` to the full ladder + auto-discovery** (Phase 1a) — smallest diff, biggest
   unlock, and the clock-sensitive one. Verify a live CoD map + total-maps book captured.
2. Bovada tape mode (1b) → normalized store (1d) → settled backfill (1c).
3. Series-length + map-winner models (Phase 2), calibrated on the tape.
4. Brackets first (Phase 3), lineups second.
