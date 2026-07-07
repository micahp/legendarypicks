# SPEC — The Momentum Engine (multi-timeframe Wilder crossovers, every level, every sport)

**Date:** 2026-07-07 (Micah's design, ARG–EGY night). **Status:** implementation plan.

## The idea, formalized

A granular hot/cold model that works like a **multi-timeframe golden cross**: two Wilder
moving averages (Wilder smoothing = EMA with α = 1/n, the RSI-style smoother) of the same
stat on a fast and a slow window — MACD-style, e.g. fast 5 / slow 26 units. When the fast
average crosses above the slow, the entity is *heating* on that stat; crossing below, *cooling*.
The crossover is an EVENT (timestamped, alertable); the spread between the averages is a
continuous momentum score.

Run it at **every level of the game**:

| Level | Series unit | Example |
|---|---|---|
| **Player** | per game (per PA/shot later) | Betts total bases, fast-5 vs slow-26 games |
| **Team** | per game | runs scored, run diff, shots created |
| **Game (live)** | per event window within a match | shots last 15' vs match rate; scoring runs |

Plus the second axis on everything: **expected vs actual**. Hot on actuals while flat on
expecteds = luck (fade candidate). Cold on actuals while flat on expecteds = mispriced
quality (buy candidate — the discount doctrine at the stat level). Hot on BOTH = real form.

## How this compares to the current system (honest inventory)

| Signal | Today | Momentum engine |
|---|---|---|
| Team form | `last10` W-L string + streak; binary `_is_cold` gate | Dual-MA crossovers on the underlying performance stats (not just outcomes), continuous score + cross events |
| Player form | `projections.py` Marcel-lite: ONE recency-weighted mean — answers "how good lately," has **no direction** | Fast/slow separation distinguishes *good-but-declining* from *average-but-surging* — slope and regime change, not just level |
| Expected vs actual | Nowhere (calibration exists for props, not luck-adjustment) | First-class overlay: Statcast xwOBA/xBA (MLB), nflverse EPA/CPOE/xYAC (NFL), our own projections as the "expected" baseline everywhere else |
| Live game momentum | Score + inning + Kalshi price; `_rally_evidence` = runners-on snapshot | Rolling event-window series from PBP (shot clusters, run expectancy, scoring runs) — the witching hour grounded in play data |
| Game stories | Narrate last-5 raw numbers | Narrate cross events ("Schwarber's fast-5 TB crossed above his season line 4 games ago") |

The deep difference: everything today measures **level**; this measures **turn**. It is
PHILOSOPHY.md ("spot the inflection while it's happening") expressed as arithmetic.

## Architecture — ONE engine, sports as adapters (never fork)

- **`backend/analytics/momentum.py`** — pure math core: `wilder(series, n)`,
  `cross_state(series, fast_n, slow_n)` → `{fast, slow, spread, state: hot|cold|neutral,
  crossed_at, games_since_cross}`. Window pairs configurable per (league, stat) — 5/26 is the
  default long-season pair; NFL uses 3/10 (17-game seasons); live windows are event-count or
  minute-based.
- **Stat adapters** — per league, a declared stat matrix (below): which fields of
  `player_game_logs.stats` / `team_game_stats` to track, and where "expected" comes from.
- **Storage** — nightly job (same cron block as the prop loop) computes and upserts
  `momentum_state(league, entity_type, entity_id, stat, fast, slow, spread, state,
  crossed_at, expected_spread, computed_at)`. Series stay derivable from logs; only current
  state + cross history are materialized. `momentum_crosses` append-only log = the alert feed
  and the backtest record.
- **API** — `/api/momentum/{league}/player/{id}`, `/api/momentum/{league}/team/{ab}`,
  `/api/momentum/{league}/crosses?since=&state=hot` (the "who just turned" feed).

## Per-sport stat matrix (v1)

| League | Player stats (fast/slow per game) | Team stats | Expected source |
|---|---|---|---|
| **MLB** | TB, H, HR, BB/K; pitchers: K, ER, outs | runs, run diff | **Statcast xwOBA/xBA/xSLG** (ingest exists) — actual-vs-expected native |
| **NBA** | PTS, FG%, 3P%, REB, AST, TS% | pts, pt diff, pace | our projections as expected (no free xStats); TS% vs own baseline |
| **NFL** | QB: yds, TD, **CPOE**; skill: yds, **xYAC vs YAC**, targets/snap share | EPA/play off+def | **nflverse EPA/CPOE/xYAC** — native expected |
| **NHL** | G, A, SOG, TOI | GF, GD, SOG diff | shots-based proxy (G vs SOG × league finish rate); MoneyPuck xG later |
| **Soccer/WC** | goals vs **shots created** (finishing form: shots missed = cooling), key passes | goals, shots, shots-on-target trend | shots-based xG proxy v1 (shot count × conversion baseline, honestly labeled); real xG scrape later |
| **Esports** | K/D/A per map (GRID/PS per-player), first-blood rate | round diff, map win rate | series-odds-implied baseline |

Structural signals ride along where free (usage: batting order, snap share, minutes, TOI) —
role changes are the most durable "momentum" there is.

## The live (within-game) level

Same math, event-window series instead of game series: MLB run-expectancy delta per
half-inning; NBA rolling 5-minute scoring margin; soccer shot events per 15' window
(ESPN keyEvents/PBP, already fetched). Output feeds the widget directly — this generalizes
`_rally_evidence` from a boolean snapshot into a continuous momentum score, and gives
Class B (witching hour) a real "who has the run" input where no WP exists.

## Validation harness FIRST (the gate everything passes before it feeds decisions)

The hot-hand literature says most raw stat momentum is noise; expected-vs-actual regression
is the defensible core. So nothing adjusts projections, widget gates, or trading selection
until it passes backtests **we can already run on data we own**:

1. **Prop test** (after the prop-loop repair, `SPEC-prop-loop-mlb.md`): do players in a
   fresh golden cross beat their prop lines more often than base rate? 33k settled props =
   the harness. Report in hit-rate points and R.
2. **Team test**: post-cross game results vs market prices (our archived Kalshi/Bovada
   pregame prices) — does a hot cross carry edge the market misses, or is it priced in?
3. **Luck test**: actual≫expected divergence → does regression follow within N games?
   (This one should pass — it's physics.)

Whatever fails stays display-only ("who's hot" is honest content even if it isn't edge).
Whatever passes graduates into the widget/trading selection with its own receipt trail.

## Rollout order (data-driven, not sport-preference)

1. **Core math + MLB player/team** (Statcast expecteds + prop DB validation + season live) — the full loop provable end-to-end.
2. **Soccer/WC team+player** (World Cup is NOW; shots-created proxy; feeds gift-fade/witching context).
3. **Esports** (GRID per-map stats; EWC running).
4. **NFL** (September; nflverse expecteds are the richest — CPOE trend on QBs is the marquee demo).
5. **NBA/NHL** (at season start; NBA gets the flashiest UI story — shooting form).
6. **Live within-game level** (after game-level validates; feeds the widget).

## Integration points (in dependency order)
- Widget: `_is_cold` binary → cross-state + spread (a cold gate with degrees).
- Game stories: cross events into the grounding pack (stakes engine pattern).
- Projections: momentum-adjusted only post-validation, as a separate labeled variant.
- Trading: selection prior for swing-regime legs (momentum measured to FADE overreactions
  against it, per the buy-discount doctrine — never to chase).
- "Who's hot" board / player Model tab: the consumer surface of the same state table.


## The unifying frame (Micah, Jul-7 night): a game contains the entire crash cycle

Consensus → shock → denial → panic → capitulation → reversal → melt-up → settlement — every
live game runs the full market cycle, compressed into a fixed clock and terminated by a binary
settlement. Two structural edges over real markets: the cycle MUST complete (hard expiry =
visible theta, forced repricing every scoreless minute), and it repeats thousands of times a
season with logged price paths and ground-truth outcomes — a crash-cycle laboratory at a
sample size macro traders never get.

Implication for this engine's live level: its output is a **phase label per live game**
(consensus / shock / panic / capitulation / reversal / melt-up), derived from the price path
(knife falling→stabilizing = capitulation) plus in-game event momentum (reversal evidence).
The widget's classes then become phase-keyed entries: Class C fires in panic overshoot,
gift-fade in denial, rally/momentum in reversal, and the swing-regime note governs the
melt-up exit (sell into maximum agreement, look for the next leg). ARG–EGY (Jul-7) ran every
phase on schedule and is the reference case.

## Risks, stated plainly
- Raw outcome-stat crossovers will mostly track noise; the expected-vs-actual axis and
  usage/role signals carry the real weight. The validation gate exists for this reason.
- Small samples (WC group stage = 3 games) need the same small-sample guards the cold gate
  just learned; window pairs must respect season length.
- V3's lesson (edge is SELECTION not timing) was about price-timing; this is stat-state.
  Where they meet (live level), momentum is an input to fading the market's overreaction,
  not a chase signal.
