# Advanced Analytics by Sport — The "Worth Paying For" Layer

Not "did the prop hit." That's table stakes. The edge is explaining WHY — the
context that turns a hit rate into a prediction. Each sport has its own set of
metrics the sharp money uses. We ship all of them.

---

## NBA

| Metric | What it measures | Why it matters for props |
|--------|-----------------|--------------------------|
| **TS%** (True Shooting %) | Scoring efficiency accounting for FT, 2P, 3P value differences | Player in a slump? TS% tells you if it's bad shooting or bad volume. TS% dropping + usage rising = regression candidate |
| **USG%** (Usage Rate) | % of team plays a player consumes while on the floor | Injury to a star → USG% spike for remaining players. Lines lag behind — the window is 1-2 games |
| **Pace** | Possessions per 48 minutes | Per-game props are deceptive in fast/slow matchups. Normalize to per-100 before comparing to lines |
| **AST% / TOV%** | Assist rate, turnover rate relative to possessions | Predicts assist props. High AST% + high pace matchup = over candidate |
| **REB% / DREB%** | Rebound rate while on floor | Predicts rebound props. Opponent offensive rebound rate = missed shots available |
| **DFS / FPPM** | Fantasy points per minute | The universal translator. Covers everything in one number per minute played |
| **Opp DvP** | Defense vs Position — opponent's rank in allowing PTS/AST/REB to each position | Matchup-contextualized hit rate. The core of the Matchups tab |

**Data source:** `hoopR` + `nba_data_py` — play-by-play since 2002. ESPN box scores for live + cross-check.

**Approach:**
1. Compute TS%, USG%, Pace, REB%/AST%/TOV% from `hoopR` PBP (per-game + rolling 10-game)
2. Build Opp DvP tables from ESPN box scores (already have strength endpoint)
3. Correlation analysis: which metrics most predict over/under hit on points/rebounds/assists/threes props
4. Feature store: each player-game gets a row with all metrics + the prop line + the outcome

---

## NFL

| Metric | What it measures | Why it matters for props |
|--------|-----------------|--------------------------|
| **EPA** (Expected Points Added) | Value of every play relative to down/distance/field position | The king metric. EPA/play > yards. A RB with 50 yards but +5 EPA had a bigger impact than one with 100 yards and -2 EPA |
| **CPOE** (Completion % Over Expected) | QB accuracy vs difficulty of throws | Predicts passing yard props better than raw completion %. High CPOE + high aDOT = deep-ball offense = over on yardage props |
| **aDOT** (Average Depth of Target) | How far downfield passes travel | Deep aDOT = volatile yardage. Short aDOT = high-volume PPR props for RBs/TEs |
| **DVOA** (Defense-adjusted Value Over Average) | Per-play efficiency vs league average, adjusted for opponent | The gold standard. DVOA rankings by position tell you exactly which matchups to target |
| **Target Share / Air Yards %** | % of team targets + air yards a player commands | Predicts receiving props. Target share is the most stable week-to-week metric in fantasy |
| **YAC / YAC Over Expected** | Yards after catch vs what was expected | Predicts which receivers beat their lines. High YAC = breaks big plays regardless of target volume |
| **OL/DL win rate** | Pass block win rate, pass rush win rate | Predicts QB props (pressure → incompletions/ints) and RB props (run blocking → yards before contact) |

**Data source:** `nflfastR` / `nfl_data_py` — play-by-play since 1999, EPA + CPOE built in. ESPN for live.

**Approach:**
1. `nfl_data_py` imports PBP directly into our DB — EPA, CPOE, aDOT, air yards all pre-computed
2. Build target share / opportunity share tables from the PBP data
3. DVOA from Football Outsiders or compute our own adjusted efficiency
4. OL/DL win rate from ESPN's pass rush stats
5. Feature store: every player-week gets EPA, CPOE, aDOT, target share, air yards %, matchup DVOA

---

## MLB

| Metric | What it measures | Why it matters for props |
|--------|-----------------|--------------------------|
| **xwOBA** (Expected Weighted On-Base Average) | Quality of contact → expected offensive output | The single best hitter metric. Player's xwOBA vs pitcher's xwOBA allowed = the matchup that matters |
| **Barrel %** | Batted balls with ideal exit velo + launch angle (> .500 xSLG) | Predicts HR props. High barrel rate + low HR total = positive regression coming |
| **Exit Velocity / Hard Hit %** | How hard the ball is hit | Predicts hits/XBH props. Hard hit % is sticky — slumps with high exit velo are bad luck, not bad play |
| **Whiff % / K%** | Pitcher's ability to make batters miss | Predicts strikeout props. High whiff % + high chase rate = over on K props |
| **Launch Angle** | Angle ball leaves bat | Predicts HR + extra-base props. Optimal is 25-35°. Trends in launch angle = changes in approach |
| **xFIP** (Expected Fielding Independent Pitching) | What a pitcher's ERA should be based on K/BB/HR | Better predictor than ERA. Low xFIP + bad defense behind him = over on K props, under on earned runs |
| **Sprint Speed** | Feet per second | Predicts stolen base props + infield hit probability |
| **Pitch Mix / Velocity** | What pitches thrown, how fast | Predicts everything. Fastball velo dropping = fatigue/decline. Slider usage up = new approach |

**Data source:** `baseballr` — Statcast data since 2008. xwOBA, barrel %, exit velo, sprint speed all included.

**Approach:**
1. `baseballr` pulls Statcast data directly — we get xwOBA, barrel %, exit velo, launch angle, sprint speed per player per game
2. Pitcher-vs-batter matchup tables: hitter xwOBA vs pitcher xwOBA allowed, broken down by pitch type
3. Rolling 15-day trends for all metrics (Statcast data is noisy in small samples, 15-day rolling is the sweet spot)
4. Ballpark factors: Coors Field adds 25% to HR rate. Yankee Stadium is a launching pad for lefties. Normalize everything.
5. Feature store: every player-game-batter gets matchup pitcher's K%, whiff %, xFIP + ballpark factor

---

## NHL

| Metric | What it measures | Why it matters for props |
|--------|-----------------|--------------------------|
| **Corsi (CF%)** | Shot attempt differential (goals + saves + misses + blocks) at 5v5 | Possession proxy. High Corsi team = more shots = over on shots props. Leading teams play defensive → score-adjusted Corsi matters |
| **Fenwick (FF%)** | Like Corsi but excludes blocked shots | Cleaner than Corsi. Blocked shots are a defensive skill, not random. Fenwick isolates offensive generation |
| **xG** (Expected Goals) | Shot quality × location → probability of goal | Predicts goal props. High xG + low actual goals = regression candidate. xG per 60 is the per-minute rate you want |
| **PDO** | Shooting % + Save % (should regress to 100) | Luck detector. PDO above 102 = team is getting lucky. Below 98 = unlucky. Players on high-PDO lines score above their talent |
| **ixG** (Individual Expected Goals) | Player's own shot quality | Predicts goal scorer props better than raw shots. Sorts true snipers from volume-shooters |
| **Offensive Zone Start %** | % of shifts starting in O-zone | Context for all shot metrics. 60% O-zone start = sheltered minutes = inflated Corsi. 40% = tough deployment = underrated |
| **IPP** (Individual Points %) | % of goals scored while on ice that the player got a point on | Predicts point streak sustainability. A player with 85% IPP is running hot (NHL average is ~70%) |
| **SH%** (Shooting %) | Goals / shots | League average ~10%. Players above 15% are running hot and will regress. Players below 6% are due |

**Data source:** `fastRhockey` — play-by-play since 2010. Corsi, Fenwick, xG all pre-computed or derivable.

**Approach:**
1. `fastRhockey` → Corsi/Fenwick/xG per player per game, plus O-zone start %
2. Score-adjusted metrics (filter out score effects — leading teams play defense)
3. Line combination tracking: who's playing with who matters more in NHL than any other sport. Line changes → production changes
4. PDO and SH% regression flags: flag players due for positive/negative regression
5. Feature store: every player-game gets Corsi, xG, PDO, O-zone%, line combo, opponent xGA

---

## Cross-Sport Framework

Every prop bet is asking: "Will this player exceed this number?" Our answer needs three layers:

```
Layer 1: THE LINE         ← Bovada API (what the market says)
Layer 2: THE OUTCOME      ← ESPN + nflverse/hoopR/baseballr (what happened)
Layer 3: THE CONTEXT      ← Advanced metrics above (WHY it happened)
```

Layer 3 is the product. Layer 1+2 is a database. The tabs map cleanly:

| Tab | Layers used |
|-----|-------------|
| Lines | Layer 1 only |
| Performance | Layer 1+2 with EMA |
| Slate | Layer 1 grouped by game |
| Matchups | Layer 1+2+3 (opponent-specific metrics) |
| Model | Layer 1+2+3 + ML |

---

## Implementation Priority

Since `nfl_data_py` has the deepest free dataset (1999, EPA built in), NFL first:

1. **Week 1:** `nfl_data_py` import pipeline → PostgreSQL (or keep SQLite for now)
2. **Week 2:** Compute rolling advanced metrics (EPA, CPOE, target share, aDOT)
3. **Week 3:** Correlation analysis — which metrics predict over/under hits
4. **Week 4:** Opponent-adjusted rankings (DVOA-style)
5. **Then:** NBA via `hoopR`, MLB via `baseballr`, NHL via `fastRhockey`

Each sport's pipeline is independent — we can ship NFL props with full context while
the other sports are still on basic Lines/Performance tabs.
