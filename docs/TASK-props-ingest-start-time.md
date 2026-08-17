# TASK (Codex): store game start_time on the /api/props/ingest path

Repo: **/root/legendarypicks** (this is the Legendary Picks repo, NOT the trading repo). Branch `dev`.

## Why
The props slate now shows a game TIME on each card (`prop_games.start_time`). It's populated for WC +
UFC (they ingest direct-to-DB via `_wc_direct_ingest` / `_ufc_direct_ingest`), but **API-ingested
leagues (MLB/NBA/NHL/NFL) show no time** (`start_time` stays NULL) because the `/api/props/ingest`
endpoint doesn't accept or store it. Fix that so those cards get times too.

The `prop_games.start_time` column already exists (TEXT, ISO datetime). `bovada_scraper._event_start_iso(prop)`
already derives an ISO kickoff from the Bovada startTime.

## Scope — exactly two files, additive only
1. **`backend/routers/props.py`**
   - Add an optional `start_time: Optional[str] = None` to the `PropIngest` pydantic model.
   - In `ingest_props` (~line 339): when INSERTing a new `prop_games` row, include `start_time` from
     the batch; when the game row already exists but has no `start_time` and the batch provides one,
     UPDATE it (backfill). Mirror exactly how `bovada_scraper._wc_direct_ingest` does the insert +
     backfill (SELECT includes start_time, `UPDATE prop_games SET start_time=? WHERE id=?`).
2. **`backend/bovada_scraper.py`**
   - In `main()`'s non-WC/UFC API branch (the `by_game[gkey] = {...}` dict), add
     `"start_time": _event_start_iso(p)` (derive from the game's first prop, like the direct paths).

## Verify (do this, paste results)
- `python3 -c "import ast; ast.parse(open('backend/routers/props.py').read()); ast.parse(open('backend/bovada_scraper.py').read())"`
- Restart the dev backend on :8096 (it runs `uvicorn sports_service:app`, env `LP_DB_PATH=/root/legendarypicks/backend/data/picks.dev.db`; kill the pid on :8096 and relaunch, no --reload).
- Run: `LP_DB_PATH=/root/legendarypicks/backend/data/picks.dev.db LP_API_BASE=http://127.0.0.1:8096 backend/venv/bin/python backend/bovada_scraper.py mlb --ingest`
- Confirm `curl -s http://127.0.0.1:8096/api/props/slate?league=mlb` returns a non-null `start_time`
  for the MLB games.

## Constraints
- Touch ONLY those two files. Additive: the model field is optional, so existing callers still work.
- The `_event_start_iso` annotation must stay PEP604-free (the ingest venv is Python 3.8 — `str | None`
  in an annotation crashes import; use no annotation or `Optional`).
- Do NOT commit or push (Claude owns git). Do NOT touch the trading repo. Report a diff summary + the
  verify output when done.
