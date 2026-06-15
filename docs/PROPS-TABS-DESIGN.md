# Props Page — Tabs & Architecture

Inspired by props.cash. Five tabs ordered by dependency (each builds on the prior).

**Global:** League pills (All / MLB / NBA / NFL / NHL) filter every tab. Default: Slate tab, MLB.

---

## Tab 1: Lines

**What:** Today's props across sportsbooks, searchable by player.

```
┌──────────────────────────────────────────────────────────┐
│ Search player…                    League ▼  Market ▼    │
├──────────┬────────┬──────┬──────┬──────┬──────┬─────────┤
│ Player   │ Market │ Line │ Side │ Odds │ Book │ Game    │
├──────────┼────────┼──────┼──────┼──────┼──────┼─────────┤
│ Tatum    │ points │ 27.5 │ OVER │ -110 │ BVD  │ BOS@GSW │
│ Tatum    │ points │ 27.5 │UNDER │ -110 │ BVD  │ BOS@GSW │
│ Curry    │ threes │  4.5 │ OVER │ +105 │ BVD  │ BOS@GSW │
└──────────┴────────┴──────┴──────┴──────┴──────┴─────────┘
```

**Data source:** Bovada API → `/api/props/ingest` → `props` table.
**Backend:** Already exists (`GET /api/props`). Add sportsbook + game_desc fields.

---

## Tab 2: Performance (Player Stats Dashboard)

**What:** Player deep-dive. Search a player → see advanced metrics for their league + EMA-weighted hit rates. Doubles as the educational layer — each metric has a plain-English tooltip.

Weight decay: last 5 games ×0.5, next 5 ×0.25, next 10 ×0.15, rest ×0.1.

```
Player: Jayson Tatum                              L5  L10  L20  Season
────────────────────────────────────────────────── ───  ───  ───  ──────
Points OVER 27.5        14/20 settled  70.0%      80%  75%  70%   65%
Points UNDER 27.5        6/20 settled  30.0%      20%  25%  30%   35%
Rebounds OVER 8.5       11/18 settled  61.1%      60%  55%  61%   58%
Assists OVER 5.5         8/15 settled  53.3%      40%  50%  53%   52%
```

**Backend:** New endpoint `GET /api/props/player/{id}/performance?weights=ema`
- Join `props` + `prop_results` for settled rows
- Apply EMA buckets (L5/L10/L20/season)
- Also return trend direction (↑ improving, → flat, ↓ declining)

**Ready:** Once settlement data flows from ESPN box scores.

---

## Tab 3: Slate (Game Browser)

**What:** Pick a game → see every prop for both teams, sorted by player.

```
NBA — June 15, 2026
┌──────────────────────────────────────────────┐
│ BOS @ GSW  7:30 PM      MIA @ PHI  7:00 PM  │
│ 12 props                10 props             │
│ LAL @ DEN 10:00 PM      (3 more games)       │
│ 8 props                                       │
└──────────────────────────────────────────────┘

Select BOS @ GSW →

Boston Celtics
  Jayson Tatum     PTS O 27.5   REB O 8.5   AST O 5.5   3PT U 3.5
  Jaylen Brown      PTS O 24.5   REB O 6.5   AST U 4.5
Golden State Warriors
  Stephen Curry     PTS O 25.5   AST O 6.5   3PT O 4.5
  Draymond Green    REB O 7.5    AST O 5.5
```

**Backend:** `GET /api/props?group_by=game` or new `GET /api/props/slate?league=&date=`
- Groups props by game, then by team, then by player
- Returns nested JSON

**Ready now** — data already has game_desc, home_team, away_team.

---

## Tab 4: Matchups

**What:** Player performance vs specific opponent/defense.

This is the "worth paying for" differentiator — not just "did he hit" but WHY.

```
Tatum vs Milwaukee Bucks
─────────────────────────────────────────────────
Last 10 vs MIL:  31.2 pts avg  |  Line: 27.5  |  70% OVER hit

MIL defense vs SF (last 20 games):
  PTS allowed to position: 24.1 (rank 22nd)
  Pace: 97.3 (slow — suppresses volume)
  3PT% allowed: 36.2% (rank 24th)

Model adjustment:  -1.8 pts (pace penalty)
                 +2.1 pts (weak defense)
                 ─────────────────
                 Net: +0.3 vs baseline
```

**Backend:** `GET /api/props/player/{id}/matchup?opponent=MIL&market=points`
- Joins settled props filtered by opponent
- Pulls opponent defensive ranks from ESPN strength endpoint (already have `/api/{league}/strength`)
- Pace-adjusted using possession data from box scores

**Needs:** Opponent-level historical queries + defense-vs-position stats.

---

## Tab 5: Model (Projections)

**What:** Our projection vs the sportsbook line — the edge.

```
┌─────────────────────────────────────────────────────────────┐
│ Player         Market  Line  Model  Edge   Confidence  Bet? │
├─────────────────────────────────────────────────────────────┤
│ Tatum          PTS     27.5  28.3   +0.8   72%         O    │
│ Curry          3PT      4.5   3.7   -0.8   68%         U    │
│ Giannis        REB     11.5  12.1   +0.6   65%         O    │
│ Embiid         PTS     30.5  28.9   -1.6   81%        ★U    │
└─────────────────────────────────────────────────────────────┘
```

**Model stack (per blueprint):**
- LightGBM gradient boosted trees (not neural nets)
- Features from Tabs 1-4 + engineered: TS%, EPA, pace, usage rate, days rest, altitude
- Separate regression model per sport per market
- Output: projected value ± confidence interval

**Backend:** `GET /api/props/model?league=nba&date=2026-06-15`
- Returns props enriched with model_projection, edge, confidence
- Model trained nightly via cron, cached to DB

**Needs:** Full ML pipeline (training data, feature store, model registry).

---

## Implementation order

| Step | What | Depends on | Status |
|------|------|-----------|--------|
| 1 | **Lines tab** — search + filterable table | Bovada ingestion | ✅ data flowing |
| 2 | **Slate tab** — game browser + grouped view | Step 1 | 🔨 now |
| 3 | **Performance tab** — EMA hit rates | Settlement data (ESPN) | 🔜 needs settle step |
| 4 | **Matchups tab** — opponent-level history | Step 3 + strength API | 📋 planned |
| 5 | **Model tab** — projections vs line | Steps 1-4 + ML infra | 📋 planned |

---

## Data flow

```
Bovada API ──→ bovada_scraper.py ──→ POST /api/props/ingest ──→ props table
ESPN boxscore ──→ settle step ──→ prop_results (actual_value, hit BOOL)
                                                │
                    ┌───────────────────────────┤
                    ▼                           ▼
            Performance tab              Model training
            (EMA hit rates)              (LightGBM features)
                                               │
                    ┌──────────────────────────┤
                    ▼                           ▼
            Matchups tab                 Model tab
            (opponent history)           (projections vs line)
```
