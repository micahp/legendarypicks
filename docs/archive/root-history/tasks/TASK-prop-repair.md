# TASK — MLB prop data repair (step 1 of docs/SPEC-prop-loop-mlb.md)

## Objective
Repair the three data defects poisoning the prop hit-rate DB (D1 fused market strings,
D2 zero-settlement pollution, D3 duplicate conflicting settlements) per the spec's
"Repair the data" section. Read `docs/SPEC-prop-loop-mlb.md` FIRST — it has the evidence
and the acceptance criteria. Then fix the writer so new rows arrive clean.

## Scope — HARD LIMITS (read twice)
- WORK DIR: this worktree ONLY.
- **NEVER write to `backend/data/picks.dev.db`.** It is a symlink to the LIVE shared dev DB.
  First action: `cp backend/data/picks.dev.db backend/data/picks.repair.db` (copy resolves the
  symlink into a real file) and run EVERYTHING with `LP_DB_PATH=$PWD/backend/data/picks.repair.db`.
  Verify with `ls -la` that picks.repair.db is a regular file, NOT a symlink, before any write.
- CREATE ONLY: `backend/repair_props.py`, `backend/repair_props_report.txt`.
- EDIT ONLY: `backend/ingest_props.py` (the writer fix for D1 so new rows arrive clean).
- DO NOT touch: `_core.py`, `sports_service.py`, anything in `routers/`, any other ingest
  script, anything in `analytics/`, any frontend file, any file under `docs/`.
- DO NOT run git commands. DO NOT touch cron or tmux. DO NOT kill or restart any server.

## Method (order matters)
1. **D1 market strings**: parse `<market>___<player>_(<team>)` → bare market
   (`total_bases`, `hits_runs_rbis`, ...). Cross-check the parsed player name against the
   linked `players.name`; on mismatch, log to `unresolved_players` and leave the row —
   never guess. Same parse logic goes into the `ingest_props.py` writer.
2. **D3 duplicates**: dedupe `(game_id, player_id, market, line, side)` — keep the row whose
   settled actual matches the player's `player_game_logs` stat line for that game; delete
   conflicting siblings and their `prop_results` rows. Then add the UNIQUE index.
3. **D2 fake zeros**: NULL-out (in `prop_results`) every settlement where `actual=0` and
   there is no appearance evidence (batter PA>0 / pitcher outs>0 in `player_game_logs` for
   that game/date), and every settlement whose game was not final at settle time.
   Do NOT re-settle in this task — repair only; re-settlement is a separate task.
4. `repair_props.py` must be idempotent (safe to run twice) and print per-step counts:
   rows parsed / rows unresolved / dupes deleted / zeros nulled.

## Done =
`backend/repair_props_report.txt` contains, run against picks.repair.db AFTER repair:
- `SELECT COUNT(DISTINCT market) FROM props;` (target: ≤ ~10)
- Duplicate count on the unique key (target: 0)
- Settled total_bases zero-share before vs after (spec target after re-settlement is
  25–30%; after THIS task just report the number honestly)
- Over/under hit-rates before vs after
- 10 sample rows of repaired Harper/Kurtz props proving D1 parsing
- The per-step counts from repair_props.py
Plus the unified diff of your `ingest_props.py` change at the bottom of the report.
Do not summarize beyond that; the report is the deliverable.
