# TASK — M5 FIX: make the backfill reproducible

**For:** hermes. M5 is functionally working (436 real rows, live endpoints) but the
backfill fails the idempotency criterion. This is the focused fix — don't redo M5.

## The defect (verified by orchestrator)
- Original run of `python backfill_team_stats.py` (default 30 days) produced **436
  rows** (MLB 176, NBA 150, NHL 110), 122 distinct games.
- Re-running the **identical command** inserted **0 rows**. It printed only 3 dates
  (`20260624`, `0614`, `0604`) each with "0 total rows"; the other 27 dates were
  silent (no ESPN scoreboard events found).
- So the backfill is NOT reproducible: if the table were emptied, re-running would
  not restore the data. It only "doesn't create dupes" (UPSERT guard holds).

## Root cause to diagnose (you have the ESPN-client context)
The per-date loop hits ESPN `…/scoreboard?dates=YYYYMMDD` for each of the last 30
days, but ~27/30 return no events. Figure out WHY the same command's output changed
between your run and the re-run, and make the backfill reliably re-discover the same
finished games. Candidate causes to rule in/out:
- ESPN `?dates=` param semantics (format? timezone off-by-one on `date.today()` vs
  the UTC `now`? does it need `dates=YYYYMMDD` for the *game* date or something else?).
- Is the loop actually iterating all 30 days, or `continue`-ing past most silently?
  (The printout suggests only event-bearing dates printed — confirm the loop covers
  all 30 and isn't early-returning.)
- ESPN drift: does a finished game's boxscore change shape a few hours later?

## Acceptance (orchestrator will re-verify)
1. Run `python backfill_team_stats.py` → note row count.
2. Run it AGAIN immediately → **same row count, same distinct games** (true
   idempotency: reproduces the set, not 0).
3. Pick ONE game_id already in the table and confirm its boxscore team-stats still
   parse on re-fetch (isolates discovery vs parse).

## GUARDRAILS (unchanged)
- Additive/UPSERT only — no DROP/DELETE/TRUNCATE. Backup `data/picks.db.bak-20260624`
  exists; back up again before any re-run if unsure.
- Curl real payloads to diagnose — don't guess. 200 ≠ working.
- **Write progress to `logs/AGENT-M5-hermes.md`** (overwrite the orchestrator's
  interim entry with your diagnosis + the fix + how you verified). This time,
  actually write the log.
- Do NOT commit/push/deploy. Bounded; no machine-wide greps.
