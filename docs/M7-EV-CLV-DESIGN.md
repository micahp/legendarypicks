# M7 — EV / CLV / Calibration Compute + Endpoints Design

**Author:** reasonix (deepseek-v4-pro)
**Date:** 2026-06-24
**Status:** READ-ONLY design — no code/DB writes. Consumed by M7-impl.
**Depends on:** M6 (odds-capture) — `prop_odds_snapshots` with `de_vig_status` column from review.

---

## 1. EV Compute

### 1.1 Inputs

Per settled prop (has both `props` row + `prop_results` row):

| Input | Source | Notes |
|-------|--------|-------|
| `odds` (American) | `prop_odds_snapshots.odds` — opening snapshot | First snapshot for the prop (`captured_at` ASC, `is_close = 0`) |
| `odds_opp` (American) | `prop_odds_snapshots.odds_opp` — opening snapshot | Opposite side from same capture |
| `de_vig_status` | `prop_odds_snapshots.de_vig_status` | `'paired'`, `'single'`, or `'stale'` (see M6 review Appendix §2) |
| `hit` (0/1) | `prop_results.hit` | 1 = over hit, 0 = under hit, NULL = void |

### 1.2 Algorithm

```
FUNCTION american_to_decimal(a):
    IF a > 0: RETURN 1 + a/100          # +110 → 2.10
    ELSE:     RETURN 1 + 100/abs(a)      # -110 → 1.90909…

FUNCTION implied_prob(american):
    RETURN 1 / american_to_decimal(american)

FUNCTION de_vig(odds, odds_opp, status):
    IF status = 'paired':
        p_side = implied_prob(odds)        # e.g., 0.5238 for Over at -110
        p_opp  = implied_prob(odds_opp)    # e.g., 0.5455 for Under at -120
        p_fair = p_side / (p_side + p_opp) # e.g., 0.5238 / 1.0693 = 0.4899
        confidence = 'high'
    ELIF status = 'single':
        p_fair = implied_prob(odds)        # raw implied — no de-vig possible
        confidence = 'low'
    ELSE:  # 'stale'
        p_fair = NULL
        confidence = NULL
    RETURN (p_fair, confidence)

FUNCTION ev(odds, p_fair):
    d = american_to_decimal(odds)
    RETURN p_fair × (d − 1) − (1 − p_fair) × 1
```

### 1.3 Worked Example

**Perez Over 4.5 K at -110 / Under 4.5 at -120:**
- `p_over_implied` = 1 / (1 + 100/110) = 1 / 1.90909 = 0.5238
- `p_under_implied` = 1 / (1 + 100/120) = 1 / 1.83333 = 0.5455
- Total = 1.0693 (vig ~6.5%)
- `p_fair` = 0.5238 / 1.0693 = **0.4899**
- `d_bet` = 1.90909
- **EV** = 0.4899 × 0.90909 − 0.5101 × 1 = 0.4454 − 0.5101 = **−0.0647**

Negative EV — the vig eats the edge at these odds.

**deGrom Over 6.5 at +105 / Under 6.5 at -135:**
- `p_over_implied` = 1 / 2.05 = 0.4878
- `p_under_implied` = 1 / (1 + 100/135) = 1 / 1.7407 = 0.5745
- Total = 1.0623
- `p_fair` = 0.4878 / 1.0623 = **0.4592**
- `d_bet` = 2.05
- **EV** = 0.4592 × 1.05 − 0.5408 × 1 = 0.4822 − 0.5408 = **−0.0586**

### 1.4 Which Snapshot to Use

- **Bet-time (opening) snapshot:** the EARLIEST `prop_odds_snapshots` row for the prop (first capture, typically at ingest). This is the "price we got."
- **EV is computed at settlement time** — join opening snapshot → de-vig → EV → pair with `prop_results.hit`.
- **Rationale:** The opening snapshot represents the actual odds when the prop was first captured. Using a later snapshot would be hindsight ("I would have bet at better odds"). The M6 review Appendix §1 confirmed this choice.

### 1.5 What M7 Computes (Not Pre-Stores)

EV is **computed on read**, not pre-stored. Rationale:
- The de-vig method may change (v2: Shin method instead of proportional)
- `p_fair` depends on de-vig method → pre-storing locks in v1
- EV queries are cheap (per-prop, single snapshot lookup + arithmetic)

An optional `ev_cache` materialized table can be populated nightly for dashboard performance:
```sql
CREATE TABLE ev_cache (
    prop_id INTEGER PRIMARY KEY REFERENCES props(id),
    p_fair REAL,
    ev REAL,
    confidence TEXT,          -- 'high', 'low', NULL
    de_vig_method TEXT,       -- 'proportional', 'shin', 'raw'
    computed_at TEXT
);
```

---

## 2. CLV Compute

### 2.1 Definition

**CLV (Closing Line Value)** = `p_close_implied − p_open_implied`

Where:
- `p_open_implied` = implied probability from the FIRST snapshot (earliest `captured_at`)
- `p_close_implied` = implied probability from the snapshot flagged `is_close = 1`

Both use the **implied** probability of the prop's side (NOT de-vigged). This isolates pure line movement without de-vig assumptions.

### 2.2 Interpretation

| CLV | Meaning |
|-----|---------|
| `> 0` | The closing line implies a HIGHER probability of the bet winning than when we captured it → **we got a better number** → positive CLV = edge |
| `= 0` | No line movement |
| `< 0` | Line moved against us |

**Example:** Prop captured at Over 4.5, -110. By game start, same line at -120.
- `p_open` = 1 / 1.909 = 0.5238
- `p_close` = 1 / (1 + 100/120) = 1 / 1.8333 = 0.5455
- **CLV = 0.5455 − 0.5238 = +0.0217** → we beat the market by ~2.2 cents

### 2.3 CLV Requires: Both Sides Captured

CLV uses ONLY the bet-side implied probability — it does NOT require de-vigging. This means:
- `de_vig_status = 'single'` snapshots CAN still produce CLV (only need `odds`, not `odds_opp`)
- `de_vig_status = 'stale'` snapshots should still be included — the odds changed on the SAME line, which IS the CLV signal

This is a correction to the M6 review assumption that stale snapshots should be skipped entirely. **Stale snapshots are the CLV signal** — the line didn't change, but the odds did. Only skip if both opening and closing are unavailable.

### 2.4 CLV Aggregation Query

```sql
WITH snapshots AS (
    SELECT 
        prop_id,
        FIRST_VALUE(odds) OVER (PARTITION BY prop_id ORDER BY captured_at ASC) AS odds_open,
        FIRST_VALUE(odds) OVER (PARTITION BY prop_id ORDER BY captured_at DESC) AS odds_close,
        COUNT(*) OVER (PARTITION BY prop_id) AS n_snapshots
    FROM prop_odds_snapshots
    WHERE de_vig_status != 'stale'  -- or include if odds changed on same line
),
clv AS (
    SELECT DISTINCT
        prop_id,
        1.0 / (1 + 100/ABS(odds_open))  - 1.0 / (1 + 100/ABS(odds_close)) AS clv,
        n_snapshots
    FROM snapshots
    WHERE odds_open IS NOT NULL AND odds_close IS NOT NULL
)
SELECT 
    AVG(clv) AS mean_clv,
    SUM(CASE WHEN clv > 0 THEN 1 ELSE 0 END) * 100.0 / COUNT(*) AS positive_clv_pct
FROM clv;
```

**Note on SQLite:** `FIRST_VALUE` is a window function. For simplicity in implementation, use two subqueries:
```sql
-- Opening
SELECT odds FROM prop_odds_snapshots WHERE prop_id = ? ORDER BY captured_at ASC LIMIT 1
-- Closing
SELECT odds FROM prop_odds_snapshots WHERE prop_id = ? AND is_close = 1 LIMIT 1
```

### 2.5 Tie to Prediction-Market-Trading v3 Reckoning

> "Edge is selection, not timing."

CLV is the **ex-post validation of selection quality**. If our prop capture consistently shows positive CLV, it means:
1. We're identifying props BEFORE the market moves to the efficient price
2. The market is incorporating information we captured early
3. Our selection process has a measurable edge

Conversely, if CLV mean-reverts around zero, we're capturing at market-efficient prices — no selection edge, just paying vig. The M7 `/api/props/clv` endpoint surfaces this metric league-by-league, market-by-market, so we know WHICH selections carry edge and WHICH don't.

---

## 3. Calibration

### 3.1 Definition

**Calibration** measures whether predicted probabilities match realized outcomes. A well-calibrated model: when it says "60% chance," the bet wins ~60% of the time.

### 3.2 Method

1. For each settled prop: compute `p_fair` (de-vigged fair probability of the bet side) and `hit` (1 = won, 0 = lost)
2. Bucket props by `p_fair` into deciles: `[0.0–0.1), [0.1–0.2), …, [0.9–1.0]`
3. Per bucket: `mean_predicted = AVG(p_fair)`, `mean_realized = AVG(hit)`
4. **Reliability diagram:** plot `mean_predicted` (x) vs `mean_realized` (y) — should lie on the diagonal
5. **Brier score:** `mean((p_fair − hit)²)` — lower is better; 0.25 = coin-flip baseline

### 3.3 Query Shape

```sql
WITH ev_data AS (
    -- Compute p_fair per settled prop (from §1 algorithm, implemented in Python)
    -- Returns: prop_id, p_fair, hit, de_vig_status
    ...
)
SELECT
    CAST(FLOOR(p_fair * 10) / 10.0 AS TEXT) AS bucket_low,
    COUNT(*) AS n,
    ROUND(AVG(p_fair), 4) AS mean_predicted,
    ROUND(AVG(hit), 4) AS mean_realized,
    ROUND(AVG(p_fair) - AVG(hit), 4) AS calibration_error
FROM ev_data
WHERE de_vig_status == 'paired'
  AND hit IS NOT NULL
GROUP BY bucket_low
ORDER BY bucket_low;
```

### 3.4 Interpretation

| Pattern | Diagnosis | Action |
|---------|-----------|--------|
| Points above diagonal | Model is **underconfident** — props win more often than predicted | Increase position sizing on these buckets |
| Points below diagonal | Model is **overconfident** — props win less often than predicted | Reduce position sizing; check for adverse selection |
| S-curve (too flat) | Model is **underfitting** — probabilities cluster near 0.5 | Need a better prior (incorporate player-specific data) |
| Points on diagonal | **Well-calibrated** — model probabilities are trustworthy | Ship it |

### 3.5 Brier Score

```
Brier = (1/N) × Σ(p_fair_i − hit_i)²
```

- **0.0** = perfect calibration (impossible in practice)
- **0.25** = coin-flip baseline (always predict 0.5)
- **< 0.20** = usefully calibrated (meaningful edge over random)

Brier decomposes into **reliability** (calibration error per bucket) + **resolution** (how well buckets separate winners from losers) + **uncertainty** (base rate). The resolution component tells us whether our model actually discriminates.

---

## 4. Endpoints

All endpoints return JSON. Filters: `league`, `market`, `date_from`, `date_to`, `min_props` (min sample per bucket).

### 4.1 `GET /api/props/ev`

**Purpose:** List props with positive expected value.

```
GET /api/props/ev?league=mlb&market=strikeouts&min_ev=0.0&limit=50
```

**Response:**
```json
{
  "props": [
    {
      "prop_id": 12345,
      "player_name": "Jacob deGrom",
      "player_id": 567,
      "team": "TEX",
      "market": "strikeouts",
      "line": 6.5,
      "side": "Over",
      "odds_american": -110,
      "d_decimal": 1.909,
      "p_implied": 0.5238,
      "p_fair": 0.5410,
      "ev": 0.032,
      "de_vig_confidence": "high",
      "game_date": "2026-06-24",
      "home_team": "TEX",
      "away_team": "HOU",
      "settled": true,
      "hit": 1
    }
  ],
  "summary": {
    "total_props": 1040,
    "positive_ev_pct": 42.3,
    "mean_ev": -0.018,
    "mean_ev_positive_only": 0.047
  },
  "filters": {
    "league": "mlb",
    "market": "strikeouts",
    "min_ev": 0.0,
    "limit": 50
  }
}
```

**Implementation:** Python computes EV per prop from the opening snapshot (§1.2 algorithm), filters by `min_ev`, sorts descending. The `p_fair` uses proportional de-vig for `paired` snapshots, raw implied for `single`.

### 4.2 `GET /api/props/clv`

**Purpose:** Props ranked by closing-line value (line-movement edge).

```
GET /api/props/clv?league=mlb&min_clv=0.0&limit=50
```

**Response:**
```json
{
  "props": [
    {
      "prop_id": 12345,
      "player_name": "Jacob deGrom",
      "market": "strikeouts",
      "line": 6.5,
      "side": "Over",
      "p_open_implied": 0.4878,
      "p_close_implied": 0.5122,
      "clv": 0.0244,
      "odds_open": 105,
      "odds_close": -105,
      "snapshots_count": 8,
      "game_date": "2026-06-24"
    }
  ],
  "summary": {
    "mean_clv": 0.008,
    "positive_clv_pct": 54.2,
    "n_props": 420,
    "n_snapshots_total": 3120
  },
  "filters": {
    "league": "mlb",
    "min_clv": 0.0,
    "limit": 50
  }
}
```

**Note:** CLV moves are typically small (1–5 cents). Positive CLV in aggregate across >100 props is the credible signal, not individual prop CLV.

### 4.3 `GET /api/calibration`

**Purpose:** Reliability curve — predicted vs realized hit-rate by probability bucket.

```
GET /api/calibration?league=mlb&min_props_per_bucket=10
```

**Response:**
```json
{
  "buckets": [
    {"bucket": "0.40-0.45", "n": 87,  "mean_predicted": 0.432, "mean_realized": 0.414, "error": -0.018, "confidence": "ok"},
    {"bucket": "0.45-0.50", "n": 142, "mean_predicted": 0.478, "mean_realized": 0.493, "error": 0.015, "confidence": "ok"},
    {"bucket": "0.50-0.55", "n": 218, "mean_predicted": 0.524, "mean_realized": 0.509, "error": -0.015, "confidence": "ok"},
    {"bucket": "0.55-0.60", "n": 53,  "mean_predicted": 0.571, "mean_realized": 0.472, "error": -0.099, "confidence": "low"}
  ],
  "brier_score": 0.234,
  "brier_decomposition": {
    "reliability": 0.012,
    "resolution": 0.008,
    "uncertainty": 0.230
  },
  "n_total": 1040,
  "n_paired": 890,
  "n_single": 150,
  "league": "mlb"
}
```

`confidence` per bucket: `'ok'` if n ≥ `min_props_per_bucket`, else `'low'`.

### 4.4 `GET /api/kalshi/ev` (event-level crossover)

**Purpose:** Compare ESPN win-probability to Kalshi market price → find +EV event bets.

```
GET /api/kalshi/ev?league=mlb&min_edge=0.02
```

**Response:**
```json
{
  "events": [
    {
      "ticker": "KXMLBGAME-26JUN24NYYBOS",
      "espn_event_id": "401769999",
      "matchup": "NYY @ BOS",
      "kalshi_yes_mid": 0.580,
      "kalshi_yes_bid": 0.57,
      "kalshi_yes_ask": 0.59,
      "kalshi_spread": 0.02,
      "espn_win_prob_home": 0.615,
      "edge": 0.025,
      "side": "YES (BOS)",
      "captured_at": "2026-06-24T18:30:00Z"
    }
  ],
  "summary": {
    "n_events": 14,
    "n_positive_edge": 3,
    "mean_edge": 0.008
  }
}
```

**Data sources:**
- Kalshi mid-price: `(best_yes_bid + best_yes_ask) / 2` from `/root/prediction-market-trading/data/orderflow/`
- ESPN win-prob: from the `summary` endpoint's `winprobability` field (requires new capture — see §5.3)
- Join: `espn_resolve.py` Kalshi ticker → ESPN event ID

---

## 5. Kalshi-ESPN Crossover

### 5.1 Join Key

The join key is already implemented in `/root/prediction-market-trading/espn_resolve.py`:

```
Kalshi ticker:  KX{NBAGAME|MLBGAME|NHLGAME|NFLGAME}-YYMMMDD{TEAM1}{TEAM2}[-{SIDE}]
                  ↓  parse date + teams
                  ↓  query ESPN scoreboard for that date
                  ↓  match teams by abbreviation
ESPN event ID:  "401769999"
```

A Kalshi "YES" contract for `KXNBAGAME-26JUN03NYKSAS` is a bet that SAS (San Antonio) wins. The ticker suffix `-SAS` identifies the YES side. ESPN win-probability gives the home team's win probability — map the ticker side to home/away for comparison.

### 5.2 Data We Have (Prediction-Market-Trading Repo)

- **5,781 JSONL files** under `/root/prediction-market-trading/data/orderflow/`
- Each record: `ticker`, `best_yes_bid`, `best_yes_ask`, `spread`, `yes_depth`, `no_depth`, `imbalance`, `last_price`
- Capture appears continuous (multiple files per ticker per day)
- Files named: `{ticker_short}_{timestamp}.jsonl`

### 5.3 Data We Need to Capture (ESPN Win-Probability)

**Not currently captured** by any script in either repo.

The ESPN win-probability lives in the `summary` endpoint during live games:
```
GET https://site.api.espn.com/apis/site/v2/sports/{sport}/{league}/summary?event={id}
```

During live games, the response includes a `winprobability` array with per-play win-prob snapshots. This data is only available DURING the game — it's not retained in post-game summaries. A capture script must:
1. Poll the summary endpoint during live games (e.g., every 60 seconds)
2. Extract `winprobability` array
3. Store as time-series: `(espn_event_id, timestamp, home_win_prob, away_win_prob)`

**Recommended schema for ESPN win-prob capture:**
```sql
CREATE TABLE espn_win_prob (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    espn_event_id TEXT NOT NULL,
    captured_at TEXT NOT NULL,
    home_win_prob REAL,       -- 0.0–1.0
    away_win_prob REAL,       -- 0.0–1.0 (should = 1 − home_win_prob)
    period INTEGER,           -- inning/quarter
    clock TEXT,               -- game clock
    source TEXT DEFAULT 'espn'
);
CREATE INDEX idx_ewp_event ON espn_win_prob(espn_event_id, captured_at);
```

**Until ESPN win-prob is captured,** the Kalshi crossover endpoint returns Kalshi prices only, with `espn_win_prob_home: null` — partial but still useful (shows market-implied probabilities).

### 5.4 Micah / geoppls

The task notes "Micah = geoppls on Kalshi." This is the Kalshi account identity. The Kalshi data in the trading repo was presumably collected via this account's API access. For M7:
- Read Kalshi data from the trading repo's filesystem (same server — `/root/prediction-market-trading/data/orderflow/`)
- No additional Kalshi API integration needed for MVP — the data is already being captured
- If direct Kalshi API access is needed later (e.g., to pull open interest or historical prices not in our files), the `geoppls` account credentials are the gate

### 5.5 Kalshi Crossover Table (LP Schema)

```sql
CREATE TABLE kalshi_events (
    ticker TEXT PRIMARY KEY,         -- KXNBAGAME-26JUN03NYKSAS-SAS
    base_ticker TEXT NOT NULL,       -- KXNBAGAME-26JUN03NYKSAS (without side suffix)
    espn_event_id TEXT,              -- resolved via espn_resolve.py
    league TEXT NOT NULL,
    event_date TEXT NOT NULL,
    home_team TEXT,
    away_team TEXT,
    kalshi_side TEXT,                -- which team the YES contract represents
    first_seen TEXT,
    resolved_at TEXT
);

CREATE TABLE kalshi_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker TEXT NOT NULL REFERENCES kalshi_events(ticker),
    best_yes_bid REAL,
    best_yes_ask REAL,
    mid_price REAL,                  -- (bid + ask) / 2
    spread REAL,
    imbalance REAL,
    captured_at TEXT NOT NULL,
    source_file TEXT                 -- source JSONL file in trading repo
);
CREATE INDEX idx_ks_ticker_ts ON kalshi_snapshots(ticker, captured_at);
```

These tables are **populated by an import script** that reads the trading repo's JSONL files. The import runs daily (or on-demand) and is additive — new snapshots appended, existing ones skipped by `(ticker, captured_at)` uniqueness.

---

## 6. What M6 Must Expose (Gap Check)

### 6.1 Confirmed Sufficient

| M7 Need | M6 Provides | Verdict |
|---------|------------|---------|
| Opening odds per prop | `prop_odds_snapshots.odds` (first by `captured_at` ASC) | ✓ Sufficient |
| Closing odds for CLV | `prop_odds_snapshots` with `is_close = 1` | ✓ Sufficient |
| Opposite-side odds for de-vig | `prop_odds_snapshots.odds_opp` | ✓ Sufficient |
| De-vig fallback | `prop_odds_snapshots.de_vig_status` | **M6-impl must add this column** (blocker from review) |
| Settlement result | `prop_results.hit` (existing) | ✓ Already present |
| Prop identity | `props.player_id`, `props.market`, `props.line`, `props.side` | ✓ Already present |

### 6.2 Gaps for M6-Impl (coordinate via orchestrator)

| # | Gap | Severity | Fix |
|---|-----|----------|-----|
| 1 | `de_vig_status` column missing from M6 schema | **BLOCKER** — EV can't distinguish paired vs single snapshots | Add column to `prop_odds_snapshots`: `de_vig_status TEXT DEFAULT 'paired'`. M6 scraper sets: `'paired'` when both sides captured, `'single'` when only one side, `'stale'` when line changed. |
| 2 | No `is_open` flag — must infer opening snapshot by `MIN(captured_at)` | Minor — SQL works but fragile (what if ingest snapshot arrives after first capture snapshot?) | Add `is_open INTEGER DEFAULT 0` to `prop_odds_snapshots`. Set `is_open = 1` on the FIRST snapshot written (at ingest or first capture). |
| 3 | No `side` denormalized in snapshots | Minor — requires JOIN to `props` for every query | Add `side TEXT` to `prop_odds_snapshots`, populated at insert time from `props.side`. |
| 4 | `is_close` flag — how does M6 cron know "game has started"? | Medium — `is_close` is critical for CLV | M6 cron checks ESPN `status.state == 'in'` or Bovada `startTime` has passed. If neither available, set `is_close = 1` on the LAST snapshot before a configurable cutoff (e.g., 5 min after scheduled start). |

### 6.3 What M7 Does NOT Need from M6 (Avoid Scope Creep)

- Per-snapshot `p_fair` or `ev` — computed in M7, not stored in M6
- Vig percentage — derivable from `odds + odds_opp` in M7
- Pre-bucketed calibration data — computed in M7 from raw snapshots

---

## 7. Implementation Notes (for M7-impl)

### 7.1 Compute-on-Read vs Materialized

| Metric | Compute-on-Read | Materialized Cache |
|--------|-----------------|-------------------|
| EV | ✓ (default) — one snapshot lookup + arithmetic | `ev_cache` table (nightly batch) for dashboard |
| CLV | ✓ (default) — two snapshot lookups per prop | Not needed — CLV is aggregate, not per-prop |
| Calibration | ✗ — requires full scan of settled props | `calibration_cache` table (nightly batch), invalidated on new settlements |

### 7.2 Python Module Structure

```
backend/
  analytics/
    __init__.py
    ev.py              # american_to_decimal, implied_prob, de_vig, ev
    clv.py             # clv from snapshots
    calibration.py     # bucketing, brier, reliability
    kalshi.py          # kalshi_import (reads trading repo JSONL)
```

All heavy computation in Python; SQL queries are thin (fetch snapshots, return aggregated results).

### 7.3 Performance Budget

- EV per prop: 1 snapshot lookup + 4 float ops → <1ms
- CLV aggregate (league, last 30 days): ~500 props × 2 lookups → <50ms
- Calibration (league, full history): ~10,000 props scanned, Python bucketing → <500ms
- Kalshi EV (today's games): ~14 events × file read → <200ms

All well within the FastAPI response budget.

### 7.4 Recalculation Triggers

- **EV:** recompute on new settlement (when `prop_results` row is inserted/updated)
- **CLV:** recompute on new close snapshot OR new settlement
- **Calibration:** recompute nightly (batch); incremental on new settlement
- **Kalshi EV:** on-demand (always reads latest Kalshi file + ESPN win-prob DB)

---

## Appendix A: Quick-Reference Formula Card

```
DECIMAL(american):
  american > 0  →  1 + american/100
  american < 0  →  1 + 100/abs(american)

IMPLIED(decimal):
  1 / decimal

DE_VIG(odds_side, odds_opp, status):
  status = 'paired'  →  p_side / (p_side + p_opp)
  status = 'single'  →  p_side
  status = 'stale'   →  NULL

EV(odds_side, p_fair):
  d = DECIMAL(odds_side)
  p_fair × (d − 1) − (1 − p_fair)

CLV(odds_open, odds_close):
  IMPLIED(DECIMAL(odds_close)) − IMPLIED(DECIMAL(odds_open))

BRIER(p_fair_array, hit_array):
  mean((p_fair_i − hit_i)²)
```

## Appendix B: Edge Cases Handled

| Case | Handling |
|------|----------|
| Prop has no snapshots (`prop_odds_snapshots` empty) | EV = NULL, excluded from calibration |
| Prop has opening but no close (`is_close = 1` missing) | CLV = NULL; EV still computable from opening |
| `de_vig_status = 'stale'` (line changed) | EV = NULL (can't de-vig); CLV = computable if odds changed on same line |
| Prop settled as void (`hit IS NULL`) | Excluded from EV/calibration; CLV still computable |
| `props.odds` populated but no `prop_odds_snapshots` rows | EV from `props.odds` with `de_vig_status = 'single'` (no opp); CLV = NULL |
| Bucket has < 10 settled props | Flagged `confidence: 'low'` in calibration response |
| Kalshi ticker can't resolve to ESPN event | Logged; event excluded from crossover endpoint |
