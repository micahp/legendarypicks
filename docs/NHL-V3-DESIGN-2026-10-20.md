# NHL v3 design — two layers, written down for later

Status: **deferred design note only; v3 is not implemented.** The v2 model artifact
(`research/nhl/prospective-2026-27/frozen_models_2026-27_v2.json`), team-strength
module, and `run_pipeline.py` v2 wiring are present on `dev` as inspected
2026-10-20. Do not infer that the v2 session is active in a running environment
without verifying its deployed model/session version. Do not change frozen models,
ledger rows, or production services as part of this note.

Updated 2026-10-20 to separate existing data from model inference and document a
concrete eventual shot/shift/penalty backfill.

## What v2 actually is

One layer, one grain:

```
log mu_home = b0 + home_adv*(not neutral) + attack[home] - defence[away]
log mu_away = b0                + attack[away] - defence[home]
```

- **Grain:** one row per team per game. No periods, no shifts, no players, no goalies.
- **Target:** regulation + OT goals. Not shots, not xG, not goals by strength state.
- **Inputs:** the canonical game file only — 23,222 games, 2008-09 → 2025-26.
- **Output:** a home/away goal mean pair, turned into a Poisson score distribution.

Everything the model knows about shots, goalies and special teams is compressed into a single
attack and a single defence coefficient per team per fit. That is why the puck-line probability
barely moved when the model improved (0.2162 → 0.2154): the decisions we bet on need the
structure below, not a better team average.

## Layer 1 — team and period structure

The unit is the **period**, not the game. Each period carries its own script: a team leading 2-0
after 20 plays differently, takes fewer risks, and gives up different shot types than the same
team at 0-0.

What layer 1 needs:

| component | what it buys | data today |
| --- | --- | --- |
| period-level goal and shot rates | period markets, better first-period props, correct game-script priors | **missing** — canonical has game totals only |
| shot creation (attempts, unblocked, on-goal) by strength state | separates shot volume from shooting talent | partial — `home_attempts_for_5v5` game-level only |
| 5v5 xG and xGA, score- and venue-adjusted | already the strongest team signal we hold | **present** — `home_svi_xgf_5v5` etc., game-level |
| player plus-minus and on-ice shot differential | player-level value, line quality | **missing** |
| shift and line-change data | line matching, deployment, who plays with whom | **missing** — needs PBP with shift charts |
| score-state splits (leading/tied/trailing) | game-script dependence, blowout handling | **missing** |

The period grain is the important change. A game-level Poisson has to average a 3-goal first
period and a 1-goal third into one number, and then cannot say anything about a period market.

## Layer 2 — goaltending

**There is no goalie model today.** This is the honest answer to "how is our goalie model
structured": it isn't. Team defence absorbs whatever the goalie did, so a team that traded for a
Vezina-calibre starter and a team running a rookie look identical until the goals show up in the
record. The one attempt to get there — a pre-puck-drop starting-goalie feed — was surveyed on
2026-10-19 and closed as DROP: no reliable starter signal at lock time (heuristic 49.7%).

Layer 2 should be built from shots, not save percentages:

- **shot type** — wrist, snap, slap, backhand, tip, deflected, wrap-around
- **shot location** — x/y coordinates, which give distance, angle, and danger zones
- **strength state** — 5v5, 5v4, 4v5, 4v4, 3v3, empty net, penalty shot
- **pre-shot movement** — rebounds, rush vs cycle, cross-ice passes before the shot if available

The model is then a goalie × shot-type × danger-zone save probability, shrunk toward league
average by exposure, and updated as the season progresses. The output that matters is not a save
percentage — it is **a per-shot goal probability that can be fed into the simulator**, which is
what makes goalie quality propagate into the game total, the puck line and every prop.

**Blocker: the shot-level data is not on disk.** The canonical file is game-level. We need a
backfill of NHL play-by-play with coordinates; the NHL API publishes shot type, x/y, strength
state and on-ice players per event. Until that exists, layer 2 cannot start.

## Power play and special teams

The full simulator cannot work without PP/PEN structure, and it needs it deep:

- power-play opportunities per team per game, and PP goal rate per opportunity
- PP/PK xG per 60 at the shot level, split by 5v4 vs 5v3 and by unit
- penalty rates by team and by game state (a team trailing takes fewer penalties)
- the interaction with game script: PP time is not distributed evenly across periods

The 2026-10-19 special-teams experiment already showed PP/PK xG per 60 adds signal over 5v5-only
in the team model, but it failed the conjunctive keep rule on CRPS, so it was not adopted — that
is a team-average question, not a simulator question. For the simulator, PP must be modelled
structurally, not as a coefficient.

Historical depth: team-level canonical game data starts in 2008-09, while MoneyPuck's
public bulk shot download advertises 2,079,359 shots spanning **2007-08 through
2025-26** (2026-27 updated separately). Its shot sample excludes blocks.
Complete NHL PBP + shiftchart + penalty-state joins for the same historical range
are **not verified**. Inventory event, coordinate, situation, penalty and shift
coverage by season before selecting a training cutoff.

## How far v2 is from v3

| piece | v2 today | v3 needs | distance |
| --- | --- | --- | --- |
| grain | game | period + shift | new data + new model |
| team strength | goals, attack/defence | xG + shot creation + score state | extend, data present |
| players | none | on-ice, plus-minus, deployment | new data (PBP shifts) |
| goalies | none, implicit in team defence | per-shot-type save model | new data (shots + coordinates) |
| special teams | none | PP/PK structure, PP goals | new data (strength state) |
| output | win prob + 2 Poisson means | joint score + period + player props | new simulator |

Roughly: v2 is a solid **team-strength prior**. It is not a simulator, and none of the four
pieces above can be approximated from what is on disk. The shortest path to v3 is a shot-level
backfill, because it unlocks layer 2, PP structure and period splits at once.

## The standings claim, measured

"We should be able to make a profitable model purely off standings/points." Tested on 5,627 games
that overlap the SBR no-vig closing line, walk-forward, prior-season points percentage:

| model | Brier |
| --- | --- |
| log5 (points % only, fixed home edge) | 0.2459 |
| logistic on points % difference + home | 0.2431 |
| closing market | 0.2393 |

A points-only model is competitive with our full team model and still **0.0038 behind the
market**. It wins two of the five full seasons and loses three. Standings information is already
in the price; a profitable model needs something the market does not have at lock time — shot
quality, goalie identity, injuries, or deployment — not a better rearrangement of the table.


## Event-level v3 architecture (deferred, no code change)

**Layer 1 — team, period, skaters and game state.** Use a pregame team-strength
prior from v2 but transition to a period or event-grain possession/shot process.
At each state, condition shot-attempt arrival and on-goal probability on attacking
and defending teams, score differential, time/period, personnel, fatigue/shift
age, rink, and the manpower state. Separate **shot creation** (attempts,
unblocked attempts, shots on goal), **shot danger** (conditional xG), and
**finishing/goaltending** (goals per shot). Learn period-specific adjustments;
do not count a shot twice by mixing xG and a predicted goal derived from it.

**Plus/minus:** store conventional player plus/minus *and* infer each skater's
on-ice goals for/against and on-ice expected-goal differential per 60 from
shift/event joins. Conventional plus/minus excludes most power-play goals and
is noisy. Use shrinkage, opponent and teammate adjustment, and TOI exposure
rather than assuming raw +/- directly measures causal player skill. Shift
data must be joined via game ID, player ID, period, elapsed time and event
time, with explicit interval-boundary tests and timezone/clock normalization.
Missing shifts stay missing; never silently impute complete lines.

**Layer 2 — the goalie, conditional on the shots faced.** Fit a league shot
danger model (shot type, rink-adjusted x/y, distance/angle, rebound/rush,
previous event and time delta, manpower, pre-shot motion where present).
Calculate goalie residual performance as expected goals against from these
shots minus actual goals against (GSAx), estimated hierarchically or strongly
shrunk by shots faced, season, and shot-type/danger-zone sample size. Compare
goalie-specific features against a simple league-level goalie prior using
chronological holdouts and proper shot-level scores. When a starter is not
confirmed by the forecast cutoff, forecast a **probability mixture over
available goalies**, not an invented certainty. Record initial and confirmed
starter forecasts separately and never change pregame frozen forecast records.

**Special teams/period state machine:** reconstruct penalty starts, expiries,
overlaps, goals terminating minors, coincidental penalties, and transitions
among 5v5, 5v4, 5v3, 4v4, 3v3, short-handed and empty-net states.
Fit penalty opportunities, minutes at each strength, PP/PK shots, high-danger
xG/60 and PP-goal rates. Track **penalty opportunities and PP minutes**
separately: an opportunity is not a fixed two-minute scoring exposure. Model
power-play *shot creation*, *shot conversion*, and PK suppression separately.
Use league-wide priors and team/unit adjustments when data allows. Make
regulation, overtime, shootout and market settlement distinct simulations.

**Research input surfaces and sample audit:**

- Official NHL per-game play-by-play: `https://api-web.nhle.com/v1/gamecenter/{gameId}/play-by-play`
- Official NHL shift charts: `https://api.nhle.com/stats/rest/en/shiftcharts?cayenneExp=gameId={gameId}`
- MoneyPuck documented shot CSV/ZIP: `https://moneypuck.com/data.htm` (2007-08 onward, 124 attributes per shot, excludes blocked shots, commercial permission unresolved)
- Our current NHL team logs already include **game-level** `powerplay_goals`, `powerplay_opps`,
  player appearances/shifts count, and goalie saves/SA. These are useful
  baselines but **not** event-level PP/PK or per-shot goalie inference.
- For each season record matched games, PBP event count, shot type + valid x/y,
  shot-on-goal events, blocked attempts, penalty events, strength states,
  period splits, recovered shift intervals, goalie identities, and exact
  coverage of shot-to-shift joins. Document API and source terms/rights.

**Evaluation and adoption gates:** freeze chronological training and
postgame targets; compare v2, period-only, goalie-only, special-teams-only,
and progressively combined variants on *matched* games. Grade full-game
winner, regulation winner, goal count, exact score log likelihood,
5.5/6.5/full offered totals, +/-1.5 cover, PP goals and shot count,
plus per-period markets. Check shooter/goalie sample selection, starter
availability timestamps, team churn, rink-adjusted coordinates, and
calibration/resolution. Historical SBR **closing** prices are a
forecast benchmark rather than a reconstructable T-90 bet.
Prospective odds capture and push-correct settlement are required
for return/ROI statements.

**Standings-only question:** do not assume a good winner hit rate proves
profitability. The existing points-percentage report quotes 0.2431 Brier
for a points-only home-adjusted logistic model versus 0.2393 for the
matched closing market (5,627 games), and does not demonstrate positive
net returns. Reproduce that result, check the matching/sample and
source price timing, and assess a separately timestamped price-based
strategy if it becomes available. Keep standings-only as the smallest
baseline even when it loses to the market; a low-complexity benchmark
makes gains from event-level v3 interpretable.

**Deferred milestones, without interrupting current priorities:**
(0) make a source/rights and coverage inventory; (1) land immutable
shot/PBP/shift/penalty raw ingestion with tests; (2) prove shot danger,
goalie GSAx and starter-mixture forecast as independent challengers;
(3) add period/score-state shot arrivals and player on-ice features;
(4) add strength-state/PP/PK transitions and market settlement;
(5) combine into a seeded, reproducible full-game simulator.
Do not call the first team-strength Poisson model a full-game simulator.

## Ordering, when this is picked up

1. **Shot-level backfill** (NHL PBP with coordinates, strength state, on-ice players). Everything
   else is downstream of it.
2. **Layer 2 goalie model** on shot type × zone, shrunk by exposure. Highest expected value per
   unit of work, because goalie identity is the largest thing the market prices and our model
   ignores.
3. **Period grain for layer 1**, using the same events.
4. **PP/PK structure** into the simulator.
5. **Joint simulator** over periods, strength states and player deployment.

Do not start 2–5 before 1 lands. Every one of them is a data problem first.
