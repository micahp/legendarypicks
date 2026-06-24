# AGENT-M6impl-hermes — Odds Capture Implementation

## Changes Made

### Schema (additive, per design §3)
- `props.odds INTEGER` + `props.odds_captured_at TEXT` (ALTER TABLE)
- `prop_odds_snapshots` table: prop_id, side, odds, odds_opp, captured_at, is_close, de_vig_status
- UNIQUE index on (prop_id, side, captured_at) as backstop

### Review fixes incorporated
1. **de_vig_status column** (review §2 Gap 2): values 'paired'/'single'/'stale'
2. **EVEN odds handling**: Bovada uses "EVEN" for +100 — mapped to 100
3. **Odds-value-change dedup** (CEO directive): before INSERT, SELECT last snapshot for (prop_id, side); skip if odds + odds_opp unchanged. Stores ticks not polls.
4. **Side column** on snapshots (review §3 fix 5): denormalized from props

### Scraper changes (bovada_scraper.py)
- **4a**: `odds` added to ingest batch dict → persisted in props table
- **4b**: `--capture` mode — calls `/api/capture-odds`, writes snapshots for existing props
- **4c**: both sides (over/under) captured in parse_player_props (was already doing this)

### Ingest handler (sports_service.py)
- `/api/props/ingest`: INSERT now includes `odds` + `odds_captured_at` when present
- `/api/capture-odds`: matches scraped props to DB by (player_id, market, line, side), writes snapshots with odds-value-change dedup

### Self-creating DDL
- sports_service.py startup creates prop_odds_snapshots + indexes + tries ALTER TABLE

## Verification

### Ingest with odds
```
venv/bin/python bovada_scraper.py mlb --ingest
→ 128+ props ingested with non-NULL odds (e.g., -180, 135, -135, 105)
```

### Capture idempotency (odds-value-change dedup)
```
Run 1: Snapshots: 0 written (0 paired, 0 single)
Run 2: Snapshots: 0 written (0 paired, 0 single)
→ Table stable at 2,496 snapshots (1,990 paired)
```
No duplicate polls — only inserts when odds actually move vs last snapshot.

### Settlement pipeline unbroken
```
venv/bin/python settle_props.py
→ Pipeline complete: Settled: 0, Void/DNP: 0, Unmappable: 0
```

### DB state
- props: 14,745 rows (256 with odds)
- prop_odds_snapshots: 2,496 rows (1,990 paired, 506 single)
- prop_results: 13,264 rows

## NOT done (CEO gate)
- Cron entry NOT enabled (per design §5 — CEO sign-off gate)
- is_close capture at game start NOT implemented
- Market-name alias table NOT added (review §3 fix — follow-up)

---

## Orchestrator re-verification (2026-06-24, real data)
hermes's run-1/run-2 above were both 0 because odds were static between its two
immediate passes. Re-ran against live Bovada with real time elapsed — fuller result:
- **Capture #1:** 639 snapshots written (506 paired, 133 single) — genuine line
  movements since the prior pass. Count 2496 → 3135.
- **Capture #2 (seconds later):** **0 written** — odds-value-change dedup correctly
  skipped identical-odds re-polls. Count 3135 stable.
- Confirms both directions: movement writes rows, static re-polls do not.
- **Ingest path stores odds:** `sports_service.py:1134` `INSERT INTO
  props(...,odds,odds_captured_at)` fed from `bovada_scraper.py:257` (`"odds": odds`).
- **Settlement unbroken:** `settle_props.py` → Settled=0, Errors=0, prop_results
  14159/15499 stable (M4 void-persistence intact alongside new schema).
- **No live cron** — CEO gate intact (crontab clean, no capture process running).
- Current DB: prop_odds_snapshots 3135 rows (incl. paired de_vig_status); props
  with non-NULL odds growing as new ingests land (pre-existing rows predate the column).

**Verdict: M6-impl DONE + verified.** CEO gates remaining: enable live capture cron,
is_close at game start, market-alias table (review §3).
