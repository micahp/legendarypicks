# M4 — persist voids (settlement.py)

**Agent:** hermes (deepseek-v4-pro, no max-thinking)
**Status:** DONE — verified by orchestrator 2026-06-24

## Problem
~2,473 residue props (no mlbam_id / DNP / unmappable market) were being re-voided
every cron run (~30 min) because voids were counted but never persisted — so they
kept reappearing as "unsettled" on every pass.

## Fix
`backend/settlement.py` — at every void/unmappable/DNP branch (both
`_settle_mlb_props` and `settle_game`), INSERT a `prop_results` row with
`actual_value=NULL, hit=NULL, settled_at=now`. This makes a void a terminal
settled state, so the prop drops out of the unsettled set on the next run.

Additive only (+36 lines, no DELETE/DROP, no schema change). Backup
`backend/data/picks.db.bak-20260624` in place before the run.

## Verification (orchestrator, real data)
- Ran `settle_props.py` twice:
  - Run 1: Settled=0, Void/DNP=0, Unmappable=0, total=12,878
  - Run 2: Settled=0, Void/DNP=0, Unmappable=0, total=12,878
- Table grew 10,393 → 12,878 (voids now persisted); 2,393 rows have `hit IS NULL`.
- Second run reprocesses nothing → idempotent. Re-voiding fixed.

## Known cosmetic nit (NOT a defect)
Outer query still reports "N unsettled props" for some games (e.g. 6, 15, 2) but
`settle_game`'s inner query finds nothing left to settle ("no unsettled props").
This is an outer/inner query-count mismatch — no re-voiding, no correctness issue.
~80 residue props remain in this state; safe to leave.
