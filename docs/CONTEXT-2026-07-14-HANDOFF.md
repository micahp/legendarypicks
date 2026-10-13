# CONTEXT HANDOFF — 2026-07-14 (Legendary Picks: Pick Desk shipped, team-stats takeover in progress)

Read this first on a fresh context. Two workstreams; the ACTIVE task is finishing 4-league team stats.

## Current focus / where you are

You just took over **Codex's leagues-hub / team-stats work** because Codex is **hard rate-limited
until Jul 19**. You paused to hand off having just surfaced the real blocker and **two decisions the
user still owes you** (see "BLOCKED ON" below). The Pick Desk workstream is basically done and live.

---

## Workstream A — Pick Desk (esports pick'em) — DONE, LIVE on the dev tunnel

**What it is:** free binary "pick the winner" game on `/predict`. Make a call → it locks → settles
against the real winner → builds a W-L record. Product direction: `docs/ESPORTS-PRODUCT-DIRECTION.md`,
spec `docs/SPEC-esports-pick-desk-mvp.md`, legality `docs/ESPORTS-LEGALITY-PRESSURE-TEST.md` (all on `dev`).

**Built + merged to `dev`** (branch `dev` in `/root/legendarypicks`; feat/pick-desk == dev == 83a7009):
- Backend `backend/routers/esports/picks.py`: pick ledger (SQLite `esports_picks`, anon `X-Device-Id`
  identity) + endpoints (POST/DELETE `/api/esports/picks`, GET `picks/me`, `crowd`, `leaderboard`,
  POST `picks/settle`) + `settle_finished()` (reads durable results store; pick `match_key` == slate
  `_key` = `teamA||teamB||title||league` = store top-level key → direct lookup; only definite a/b
  winner settles; resultUnknown left OPEN through a grace window; contrarian scoring
  `1 + K*(1 - crowd_share_on_your_side)`).
- `slate.py`: `matchKey` exposed on every board match.
- Frontend `pages/predict.tsx` = the Predict page: record header, callable match cards
  (Pick {team} → You picked {team}), **crowd "who's favored" revealed AFTER a pick** (Bovada
  `m.favorite` fallback when <5 picks, "Be the first" when none), **Watch ↗ → /esports** per card.
  Copy is deliberately PLAIN (user rejected "legendary" theatrics): title "Predict", "Track your
  record", section "History", badges Won/Lost/Void.
- Identity DECIDED: anon device id in localStorage, claim-to-account later.
- Also shipped earlier on dev: prod board warmer (`ESPORTS_WARMER_INTERVAL_S`=900), 7-day results
  retention (`_RESULTS_RETENTION_DAYS`), key self-hydration in `sports_service.py`.

**NOT built (F3+):** change-pick before lock, claim-to-account, deep-link Watch, Ultimate Team.

**All Pick Desk commits are LOCAL on `dev`, UNPUSHED** (origin/dev may not exist; 15 commits ahead).
Commit chain: `4f2594f` warmer, `4454aa2` retention, `d03886c` hydration, `dcde06e` ledger,
`085af92` settlement, `864c69d` matchKey, `b3fc176` F1, `0c6234e` F2, `83a7009` plain copy.

---

## Workstream B — Team stats for 4 leagues (THE ACTIVE TASK) — on `feat/leagues-hub`

Worktree `/root/lp-leagues-hub` (branch `feat/leagues-hub` @ `819b174`). This is Codex's work; you're
finishing it directly (reasonix, its DeepSeek worker, exited on its own — don't rely on it).

**Definition of done (user, explicit): team stats for all 4 leagues (MLB/NBA/NFL/NHL).**

### The real blocker: only MLB is in-season
Actual data in the shared dev DB (`/root/legendarypicks/backend/data/picks.dev.db`, read-only checked):
- **MLB**: team_game_results 2888, team_game_stats 176 — in-season (2026), real current data.
- **NBA**: team_game_stats 488, **results 0** — 2025-26 season ended ~June, offseason.
- **NHL**: team_game_stats 492, **results 0** — offseason.
- **NFL**: **nothing** — offseason (2025 ended Feb; 2026 starts Sept). `backfill_nfl()` exists but NFL
  has no current games.
- The NEW coverage-manifest schema (`team_stats_coverage`) is **NOT on the dev DB** — only proven on a
  `/tmp` copy. Dev DB has the OLD `team_game_results`/`team_game_stats` tables.

So "4 leagues" can only mean **season-appropriate**: MLB current, NBA/NHL 2025-26, NFL 2025 (last
completed). ESPN has completed-season data, so it's gettable — but it's a product choice + a dev-DB write.

### APPROVED by user 2026-07-14 ("yes and yes") — DO NOT re-ask, proceed:
1. **Season-appropriateness = last completed season** for the offseason three (NBA/NHL 2025-26,
   NFL 2025); MLB current (2026). CONFIRMED.
2. **Migrate + backfill the shared dev DB is APPROVED.** Still: take a SQLite-safe backup + verify
   `PRAGMA integrity_check` FIRST, and do NOT touch prod (prod is a separate approved promotion).

### To finish (the plan once approved):
1. **Fix 2 failing team-stats tests** (35 pass, 2 fail — both diagnosed; run
   `cd /root/lp-leagues-hub/backend && venv/bin/python -m pytest test_backfill_team_stats_fixture.py -q`):
   - `test_report_path_must_not_exist`: `migrate_team_stats.create_database()` calls
     `_validate_report_path()` which does `sys.exit(2)` when the report path exists, but the test (and
     the CLI `main`) expect a returned `{"success": False}` dict, not a SystemExit. Fix: make
     create_database catch/convert the validation failure into a `success=False` report (or make
     `_validate_report_path` raise and have callers handle it).
   - `test_rerun_safety`: `team_stats_coverage.run_id` is PRIMARY KEY (one row per run). Test runs the
     backfill twice → expects 2 coverage rows, gets 1. Cause: game stats are `INSERT OR IGNORE` keyed
     by game, so the 2nd run inserts nothing under ITS run_id; the coverage verification counts by
     `(league, run_id)` (in `backfill_team_stats_fixture.py` ~line 595-648), sees 0 for run 2, and
     skips writing coverage. Fix: base the coverage decision on what's PRESENT for (league, season),
     not what THIS run_id inserted, so an idempotent rerun still records its manifest row.
2. Apply new schema to dev DB + backfill MLB (current) / NBA / NHL (2025-26) / NFL (2025) — season-
   appropriate, results + stats + coverage. NBA/NHL currently have stats but no results (need those).
3. Commit the untracked team-stats files (schema/migration/contract/backfill/fixtures/tests) +
   Codex's WIP (games.py, GameCard.tsx, test_team_aggregates_contract.py). Note the 0-byte
   `backend/backfill_team_stats_proof.py` — leftover, probably delete.
4. Merge `feat/leagues-hub` → `dev` (this restores `/leagues` on the dev tunnel — it 404s now because
   dev lacks Codex's leagues pages). Then close out the worktree.

**MLB IDENTITY REPAIR = COMPLETE + PARKED. DO NOT TOUCH** (`docs/MLB-IDENTITY-REPAIR-HANDOFF-2026-07-14.md`).
It's fully proven on a `/tmp` copy, never applied to shared/prod. Not part of the team-stats task.

---

## Environment / running state
- **Dev tunnel (Pick Desk, dev code):** https://itunes-digest-salvation-wednesday.trycloudflare.com
  → `:3096` (worktree `/root/lp-pick-desk`, feat/pick-desk==dev). `/predict` works; `/leagues` 404s
  until B merges. cloudflared log `/tmp/devtunnel-3096.log`. The old `:3095` tunnel was KILLED per user.
- **Pick-desk worktree** `/root/lp-pick-desk`: frontend `:3096`, backend `:8096`
  (`LP_DB_PATH=/root/legendarypicks/backend/data/picks.dev.db`). HERMES-TASK*.md files here (delegation artifacts).
- **Leagues-hub worktree** `/root/lp-leagues-hub`: frontend `:3095`, backend `:8095` — still up (for the team-stats work).
- **Prod** (containers, unaffected): backend `127.0.0.1:8100→8000`, frontend `3100→3000`, `legendarypicks.xyz`.
- **Shared dev DB:** `/root/legendarypicks/backend/data/picks.dev.db` — symlinked into both worktrees;
  holds Pick Desk `esports_picks` + the team-stats tables + everything. A team-stats backfill writing
  it is the ONE cross-workstream collision point → back up first.
- **Box is tight:** ~1.4–2.4 GiB available, swapping. Other LEGIT services running (do NOT kill):
  Plane (`/app/apps/space`), weatherbot (`weatherbot-paper`), trading bots (`esports_price_tape.py`,
  `live_valuefade.py`, `collect_orderbook.py`), mnlakes tileserver.
- **Codex + Hermes agents were killed by the user** (freed ~1GB); their tmux sessions remain as empty
  shells. reasonix session exists but its agent exited. Codex rate-limited till Jul 19.

## Gotchas (learned this session)
- `pkill -f`/`pgrep -f "uvicorn…"` or `"cloudflared…localhost:3095"` **self-matches the running shell**
  → exit 144 / kills your own shell. Kill by PID (from `ss -ltnp` / `pgrep -x cloudflared`), never `-f <pattern>`.
- Restart a dev backend by PID then relaunch: `LP_DB_PATH=/root/legendarypicks/backend/data/picks.dev.db
  setsid nohup venv/bin/uvicorn sports_service:app --port <8096|8095> --host 127.0.0.1 >log 2>&1 </dev/null &`
  (not `--reload`; wait ~6s; board cold-rebuilds, poll until matches>0).
- Verify-before-merge everything from delegated agents; run the actual endpoints/tests yourself.
- Merging `feat/leagues-hub` ↔ `dev` conflicts on `slate.py`/`sports_service.py`/`GameCard.tsx` (both
  branches changed them) — the agreed model is `feat/leagues-hub` merges INTO `dev` (dev is the
  integration branch + the tunnel target).

## Immediate next step (UNBLOCKED — user approved both, "yes and yes")
Proceed directly, no re-asking:
1. Fix the 2 team-stats tests (both diagnosed above).
2. Back up the shared dev DB (copy + `PRAGMA integrity_check`) BEFORE any write.
3. Apply the new team-stats schema (incl. `team_stats_coverage`) to the dev DB.
4. Season-appropriate backfill: MLB (2026), NBA (2025-26), NHL (2025-26), NFL (2025) — results + stats
   + coverage. NBA/NHL currently have stats but no results (backfill those); NFL is empty (2025 season).
5. Verify the `/api/.../stats` contract + the `/leagues` pages show all 4 leagues (season-labeled).
6. Commit all team-stats files + Codex WIP on `feat/leagues-hub`; merge `feat/leagues-hub` → `dev`
   (restores `/leagues` on the tunnel); verify on the dev tunnel; then tear down the leagues-hub worktree.
Keep the Pick Desk (`:3096`/`:8096` + its tunnel) and prod untouched throughout.
