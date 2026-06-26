# Projections Methodology — how season-long stats & fantasy points are projected

Reference doc. How the industry (ESPN, FantasyPros, PFF, EstablishTheRun; ZiPS /
Steamer / PECOTA / THE BAT in baseball) actually builds full-season stat and
fantasy projections — and how Legendary Picks' data maps onto it.

Key principle up front: **nobody projects a final number directly.** Fantasy
points are always a *derived* output of a projected stat line run through a
scoring formula. The work is projecting the stat line.

---

## The pipeline (every credible system is the same 8 steps)

### 1. Weighted multi-year baseline
Start from the player's last ~3 seasons, weighted toward recent. Baseball's
*Marcel* (Tom Tango's deliberately-minimal benchmark every other system must
beat) uses 5/4/3 weighting on the last three years. This is the prior.

### 2. Regress to the mean — per stat (the big one)
Not all stats are equally "real":
- **Efficiency stats** (TD rate, yards-per-target, BABIP, shooting %) are mostly
  noise → pull them *hard* toward league/positional average.
- **Volume stats** (targets, carries, snaps, plate appearances, minutes) are
  sticky → barely move them.

A player who scored 15 TDs on an unsustainable rate gets projected *down* even if
nothing else changed. Stats "stabilize" at different sample sizes (K% ~60 PA,
BABIP needs 800+ PA); trust the slow-stabilizing ones less.

### 3. Aging curve
Each position has an empirical curve — NFL RBs peak 25–27 then fall off a cliff,
WRs peak later, QBs plateau for years; MLB hitters peak ~26–28. Shift the baseline
by where the player sits on the curve.

### 4. Opportunity / volume model — ~70% of the fantasy signal
Project the *role* before the production: snap share, target share, carry share,
depth-chart position, red-zone usage, batting-order spot, power-play time.
Usually top-down — project the team's total plays and pass/run split, then
distribute the pie to players. **Volume × efficiency = counting stats.**

### 5. Context & change
Coaching/scheme, O-line, QB up/downgrade, new teammates competing for touches,
pace, park factors. Offseason moves (free agency, draft) redraw the opportunity pie.

### 6. Games-played / availability
A full-season number is **per-game rate × projected games**. Project games played
from durability, age, injury history.

### 7. Apply the scoring formula
Run the projected stat line through the league's fantasy scoring (e.g. 0.1/yd,
6/TD, 1/rec PPR) and sum the components. Fantasy points fall out of the stat line.

### 8. Distribution, not a point
The best systems Monte-Carlo the inputs → a **floor / median / ceiling**
distribution, not a single number. That distribution is what feeds DFS optimizers,
best-ball, and prop edges (P(over the line)).

---

## Rookies (no pro history)
Swap steps 1–3 for a prospect model:
- **Draft capital** — where they were drafted predicts opportunity better than
  anything else.
- **College production**, translated through a prospect/production model.
- **Athletic testing** (combine).
- **Landing spot / depth chart** — team need + competition for touches.
- **Comparables** — outcomes of similar past prospects.

---

## The modern edge: process metrics (step 2 inputs)
Use *process* metrics that predict future results better than past *results* do:
- **Baseball:** Statcast — exit velo, barrel%, xwOBA, xBA. These "expected" stats
  stabilize faster than outcome stats.
- **Football:** EPA, CPOE, air yards, target share.
- **Basketball:** usage rate, true shooting, pace, shot quality.

This is where ZiPS/Steamer/THE BAT and PFF/ESTR earn their keep over a raw Marcel.

---

## Baseball's canonical systems (for reference)
- **Marcel** — the monkey; minimal baseline (3-yr weighted + regression + age).
  The benchmark.
- **ZiPS** (Szymborski/FanGraphs) — comparables + growth/decline via similarity.
- **Steamer** — regressed component skills, heavy on rate stabilization.
- **PECOTA** (Baseball Prospectus) — nearest-neighbor comparables + percentiles.
- **THE BAT / THE BAT X** (Derek Carty) — Statcast-driven, park & weather adjusted.

---

## How Legendary Picks' data maps onto this

| Pipeline step | Our data asset | Status |
|---|---|---|
| 1. Multi-year baseline | `player_game_logs` (per-game) + season history | NFL 2024 + MLB live ingested; NHL/NBA pending |
| 2. Regression / stabilization | Statcast (exit velo, xwOBA), NFL EPA already pulled | have inputs, model TODO |
| 3. Aging curve | `players` (age via DOB — needs backfill) | partial |
| 4. Opportunity / volume | `team_game_stats` (team context), snap/target shares | team-level have; player-share TODO |
| 5. Context / matchup | `espn_client.team_strength()` (quality prior) | have |
| 6. Games-played | game-log counts + injury status | derivable |
| 7. Fantasy scoring | scoring formula per league | trivial once stat line exists |
| 8. Distribution | per-game variance from `player_game_logs` | have the raw variance |

## Build path (Model tab)
1. **Marcel-grade baseline first** — weighted recent form + regression + age. Very
   achievable on the per-game logs we now have. This is the honest floor.
2. **Add opportunity share** — distribute team-level volume projections to players.
3. **Add process metrics** — Statcast/EPA into the regression step.
4. **Monte-Carlo for distribution** — floor/median/ceiling → P(over line) for props.

Note from the NFL proof: a naive *mean* projection is skewed by outlier games
(Ja'Marr Chase 2024: mean ~100 yds, but two 190+/264 games pull it up; median ~86).
Use median / trimmed-mean / explicit distribution, not the raw mean.
