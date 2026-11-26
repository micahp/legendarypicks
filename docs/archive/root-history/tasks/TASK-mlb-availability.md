# TASK — MLB availability (dev first, then prod)

> **Spec state: AUTHORITATIVE, corrected 2026-08-03 by Micah (three correction rounds).**
> Read every "STANDS" line below — the earlier "stand-down" message was RETRACTED by Micah:
> prod work is authorized (clone-rehearse-backup-swap-verify discipline), but the MLB
> coverage-row semantics and the season-type oracle rules are the part that matters.

## Goal

Make **MLB available on dev, then on prod** — `/leagues/mlb` must render a real hub
(standings/stats/schedule) instead of "isn't available yet", and stay available as the
2026 season progresses.

## Measured state (2026-08-03, dev DB `backend/data/picks.dev.db`)

| thing | value |
|---|---|
| `team_game_results` mlb, season 2026 | **3,364 rows = 1,682 distinct games** (2 rows/game) |
| mlb tgr date range | `2026-03-26` (Opening Day) .. `2026-08-02` |
| spring rows in dev | **none** (dates start 03-26 = type-2 regular season) |
| `team_stats_coverage` mlb row | **none** (this is why MLB is unavailable) |
| `team_game_stats` mlb | 16 rows (the COV-source red rows; separate from tgr) |
| prod | missing `team_stats_coverage`/`team_game_results` for mlb entirely |

`reconcile_totals.py` already has `season_types()` / `season_type_id()` (reads type ids
from the season document, not a constant) — use `season_type_id("mlb", 2026, "regular")`
for the oracle. Status is currently decided in `write_coverage()` (lines ~566-681) which
emits only `complete`/`partial`.

## Hard rules (Micah, verbatim intent — do NOT violate)

1. **(a) NEVER write `status=complete` for mlb 2026.** It is mid-season: ~1,682 of a
   ~2,430-game regular season, running to late September. `complete` claims the season is
   finished AND fully checked — false.
2. **(b) The row must claim a WINDOW, not an instant**, under a **distinct status
   (`in_progress`)**: *"every completed game from season_start through checked_through is
   present and paired"*. Why: `complete` FLAPS — games played last night but not yet
   ingested are played-and-absent, `explain_gap` classifies them as genuinely missing, the
   verdict hits the mismatch branch → `partial` → MLB goes UNAVAILABLE again a day later.
   Micah explicitly rejected that. A window claim survives the date advancing.
   **FRONTEND REQUIRED TOO (found 2026-08-03):** `components/Leagues/hooks/useCoverage.ts`
   currently maps any unrecognised status to `unverified` (line ~43) and
   `offeredLeagues`/`offerableSeasons` filter `status === 'complete'` ONLY (lines ~96/101).
   So a DB row with `in_progress` alone would STILL render "isn't available yet". The hook
   must (i) add `in_progress` to the `CoverageStatus` union + normalize allowlist, and
   (ii) offer leagues whose status is `in_progress` (the hub renders; the honest-data-ui
   surface should show the window claim / staleness instead of hiding the league).
3. **(c) There is NO refresh job for MLB `team_game_results` on this box.**
   `legendarypicks-mlb-capture.timer` runs `bovada_scraper.py mlb --capture` (Bovada prop
   odds, every 5 min) — it does NOT refresh team results. Without a refresh job,
   `checked_through` freezes the moment hand-running stops and the row drifts stale.
   **Add one** (a timer that re-runs the MLB results ingest, updating `checked_through`),
   plus a staleness budget for `in_progress`.
4. **(d) Scope the expected-count oracle to season type 2 (regular).** ESPN publishes
   **451 type-1 Spring Training events for MLB 2026** — any count keyed on season 2026
   WITHOUT a seasontype filter compares us against spring training too.
5. **(e) `team_game_results` has NO `game_type` column.** Do NOT add one and do NOT delete
   rows. The only thing separating spring from regular (if spring ever lands) is the
   `2026-03-26` date boundary. Adding the column / deleting rows is a pending product
   decision — not yours.
6. **Dev first, prod second.** Do not touch `backend/data/picks.db`, do not clone-and-swap
   prod, do not restart containers until the dev surface is proven and Micah re-authorizes
   the prod step (retracted stand-down notwithstanding — Micah must still green-light the
   specific prod promotion).

## Execution order

1. **Dev coverage row for mlb 2026** — write via the coverage writer (extend
   `write_coverage()` or the reconcile path) with:
   - `status = "in_progress"` (distinct from `complete`/`partial`)
   - `season_start = 2026-03-26`, `checked_through = 2026-08-02` (window, not season end)
   - oracle = published REG (type-2) completed games with date ≤ checked_through,
     **never** an unfiltered season count
   - `expected_games`/`fetched_games`/`paired_games` = the window claim, not season total
2. **Dev browser verify** — `/leagues/mlb` renders, `/api/coverage` shows mlb
   `in_progress`, 0 console/page errors, and the hub does NOT flap when the date advances
   (simulate by re-running the reconcile with a fresh `checked_through`).
3. **Frontend `useCoverage.ts`** — add `in_progress` to the `CoverageStatus` union + the
   normalize allowlist, and offer `in_progress` leagues in `offeredLeagues` /
   `offerableSeasons` (otherwise the DB row renders "isn't available yet" regardless —
   see hard rule (b)). Honest surface shows the window claim / staleness.
4. **Add the MLB results refresh timer** (the missing piece from (c)) so `checked_through`
   advances on its own; verify it actually updates the row.
5. **Prod promotion (only after Micah's explicit go)** — clone-rehearse-backup-swap-verify:
   clone `picks.db` → run the MLB migration → verify clone (`/api/coverage` + `/leagues/mlb`
   browser) → backup → swap → restart backend → verify live on legendarypicks.xyz.
   `migrate_team_stats_from_dev.py` needs an mlb entry (or a parallel path) and its
   `--target` guard requires a rehearsal/clone path.
6. **Gates** — COV-prod already asserts the deployed registry; extend or add an mlb
   assertion (window claim, not `complete`). COV-source stays red on purpose (NFL 2024 +
   the 16 mlb `team_game_stats` rows).

## References

- `docs/DATA-COVERAGE-CONTRACT.md` §4 (registry semantics) and §9 (explain_gap)
- `TASK-league-0-coverage-gate.md` — completed; the registry mechanism + `explain_gap()`
  already exist; "any new league's ingest must filter on `completed`"
- `backend/reconcile_totals.py` — `season_types()`, `season_type_id()`, `write_coverage()`
- `backend/migrate_team_stats_from_dev.py` — the dev→prod migration tool (fail-closed,
  atomic, idempotent; refuses prod-looking targets unless path has rehearsal/clone/test)
- `verify-gates.sh` — COV-api/COV-prod (asserts dev and deployed registries respectively)
- Skills: `published-first` (before touching the coverage writer), `honest-data-ui`
  (before the UI surface), `build-league-data-pipelines` (before the refresh timer)
