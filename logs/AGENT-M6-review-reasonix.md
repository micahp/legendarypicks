# AGENT-M6-review-reasonix — Odds-Capture Design Review Log

**Agent:** reasonix (deepseek-v4-pro)
**Task:** Adversarial review of `docs/ODDS-CAPTURE-DESIGN.md`
**Started:** 2026-06-24 07:15 UTC
**Status:** COMPLETE — review appended to design doc

## Recon steps

1. Read TASK-M6-review-reasonix.md — 5 review areas, read-only, append as appendix.
2. Read ODDS-CAPTURE-DESIGN.md — 164 lines, 9 sections.
3. Re-verified Bovada endpoint: HTTP 200, 1.6 MB (confirmed §2 claim).
4. Read `bovada_scraper.py` — verified line-number claims:
   - `price.american` extracted at line 122 ✓
   - `price.handicap` extracted at line 121 ✓
   - Odds omitted from ingest batch at lines 238-245 ✓
   - Both sides iterated in `parse_player_props` ✓
5. Read `sports_service.py:1070-1150` — verified INSERT at line 1127 has no `odds` column.
6. Traced `_resolve_player_for_ingest()` — resolves by ID, not name string (AGENTS §7 compliant).
7. Tested all math formulas against edge cases (pick'em, heavy favorite, push).
8. Wrote review appendix (appended to ODDS-CAPTURE-DESIGN.md).

## Verdict

**DESIGN IS SOUND.** 4 PASS, 2 ISSUE (both fixable without architectural change).

Two blocking fixes for M6-impl:
1. Add `de_vig_status` column for fallback when `odds_opp` is NULL.
2. Correct cadence math (36 not 6 req/day) + add canary query.

Four non-blocking improvements noted for post-ship.
