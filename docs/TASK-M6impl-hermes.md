# TASK — M6-impl: build the odds capture

**For:** hermes. The design is final + adversarially reviewed (sound, 4 fixes). Build it.
Read `docs/ODDS-CAPTURE-DESIGN.md` (incl. the Appendix review) FIRST.

## Implementation order (from design §9, + the 4 review fixes)
1. **Backup first:** `cp backend/data/picks.db backend/data/picks.db.bak-20260624-m6`.
   Confirm the copy has the right row count before any DDL.
2. **Schema (additive only):**
   - `ALTER TABLE props ADD COLUMN odds INTEGER;`
   - `ALTER TABLE props ADD COLUMN odds_captured_at TEXT;`
   - `CREATE TABLE prop_odds_snapshots(...)` per design §3b, **PLUS the review's
     `de_vig_status` column** (values 'paired'|'single'|'stale') — review §2 Gap 2.
   Put DDL in `sports_service.py` (CREATE TABLE IF NOT EXISTS style, like
   `team_game_stats`) so it self-creates.
3. **Persist odds at ingest (4a):** add `odds` to the batch in
   `bovada_scraper.py:ingest_batch` + accept in the `/api/props/ingest` handler +
   the `props` INSERT. Verify a fresh ingest writes a non-NULL `odds`.
4. **Capture both sides (4c) + `--capture` mode (4b):** emit paired Over/Under odds
   in `parse_player_props`; add `bovada_scraper.py <league> --capture` that, for
   today's existing props, writes `prop_odds_snapshots` rows (matched by
   player_id+market+line+side, identity by ID never name). Line-moved → log+skip
   (don't rebind). Populate `de_vig_status` from whether both sides captured.
5. **De-vig note (review §2 Gap 1):** add a comment in the compute/§7 area that
   proportional de-vig is v1 (favorite-longshot bias); Shin/odds-ratio is v2.

## DO NOT (CEO gate)
- **Do NOT enable the live cron.** Build the `--capture` mode + a cron *entry
  script*, but the cron going live (§5 cadence, ~36 req/day per the review) is a
  CEO sign-off gate — it hits an external site. Leave the cron disabled / documented.
- Do NOT commit/push/deploy.

## Acceptance (orchestrator will verify against real data)
1. `props.odds` populated on a fresh ingest; `prop_odds_snapshots` + `de_vig_status`
   columns exist.
2. `--capture` run writes real snapshot rows for today's games (curl-verify a real
   Bovada prop lands with non-NULL odds + odds_opp where paired).
3. Idempotent: `--capture` twice → no duplicate snapshots for same prop+timestamp.
4. Existing settlement/props pipeline unbroken (run `settle_props.py` once → no
   errors, count sane).

## GUARDRAILS (unchanged)
- Additive/UPSERT only — no DROP/DELETE/TRUNCATE. Backup before DDL.
- Curl real Bovada + ESPN payloads; 200 ≠ working. Identity by ID.
- **Write `logs/AGENT-M6impl-hermes.md`** (diagnosis + changes + how verified).
  Bounded; no machine-wide greps/unbounded loops.
