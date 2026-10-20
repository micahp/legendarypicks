# NHL v3 design — two layers, written down for later

Status: design note only. Nothing here is built. v2 (team attack/defence Poisson, season-level
goals) is the current model on `research/nhl-team-strength-2026-10-19` @ `5ec4eec3`, not merged.

Written 2026-10-20 after measuring v2 against v1 and against the market.

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

Historical depth: the MoneyPuck-derived team data we already hold starts in 2008-09, and shot-level
coverage before that is not something this note verified. The backfill's first job is to measure
how far back complete shot events with coordinates and strength state actually go, and to report
the per-season coverage before anything is modelled on it.

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
