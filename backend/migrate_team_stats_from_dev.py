#!/usr/bin/env python3
"""migrate_team_stats_from_dev.py -- copy APPROVED league/season Team Stats
populations from the DEV database into a target database (disposable clone),
fail-closed.

Distinct from `migrate_team_stats.py` (the canonical-schema proof-DB builder,
commit c8198d8). This one moves approved windows between databases.

Why this exists
---------------
Production has no usable Team Stats populations: the prod DB carries only a
partial, duplicated `team_game_stats` (measured: mlb 176 rows = 16 keys x 11
copies; nba 486 rows with 32 dupes) and no `team_game_results` /
`team_stats_coverage` at all. The DEV database holds complete, verified
populations from the 2026-07-14 parity runs. v0.6.13 acceptance requires NBA,
NFL, and NHL Team Stats surfaces to return supported, non-empty, proof-backed
data. This migrates ONLY the approved league/season windows — never the whole
DEV database, never unbounded tables.

Approved windows (from CODEX-V0.6.13-RECUT-PLAN-2026-07-29.md):
  NBA: 2025-26 regular season   -> team_game_results.season = 2026 (1,227 games)
  NFL: 2025 regular season      -> team_game_results.season = 2025 (272 games)
  NHL: 2025-26 regular season   -> team_game_results.season = 2026 (1,311 games)

team_game_stats has no season column; rows are matched to the approved window
through their game_id against the approved team_game_results game_ids.

Fail-closed contract
--------------------
- Verify every expected count BEFORE opening the write transaction.
- Write results + stats + coverage for ALL THREE leagues in ONE transaction;
  any failure rolls everything back. No partial replacement.
- Idempotent: re-running on a target that already holds the population
  reports already-present counts and exits 0 without rewriting.
- Pre-existing partial/duplicated rows for the approved leagues are replaced
  wholesale; the unique index is only built after dedupe.
- The only source is the DEV DB (read-only). The only target is the DB given
  by --target (a disposable clone). Nothing here ever touches production.

Usage:
  cd backend && venv/bin/python migrate_team_stats_from_dev.py \
      --target /abs/path/rehearsal-v0.6.13.db
"""
from __future__ import annotations

import argparse
import os
import sqlite3
import sys

# ---------------------------------------------------------------------------
#  Scope — approved league/season windows and expected counts
#
#  REVISED 2026-08-02. The previous values were "measured 2026-07-14" — measured,
#  that is, from a run that had silently lost 4 NBA games and 1 NHL game to a
#  transaction bug (docs/DATA-COVERAGE-CONTRACT.md §9). Measuring the output of a
#  broken run and calling it the expectation is how a defect becomes the spec: this
#  table would have rejected the CORRECT data as out of scope.
#
#  The values below are derived independently of any run of ours:
#    nba 2026 — 30 teams x 82 games / 2 = 1230, + 1 NBA Cup final (played, does not
#               count toward 82) = 1231 games, 2462 result rows. Confirmed by the
#               per-team distribution: 28 teams at 82, NY and SA at 83.
#    nhl 2026 — 1312, the count player_game_logs already held while
#               team_game_results sat at 1311; exactly one game, and the failure
#               row naming it is in team_stats_ingestion_failures.
#    nfl 2025 — 272 = 32 x 17 / 2. Unaffected by the bug.
# ---------------------------------------------------------------------------

APPROVED: dict[str, dict] = {
    # league -> approved season + expected result rows (games * 2) + teams
    "nba": {"season": 2026, "results": 2462, "teams": 30, "games": 1231},
    "nfl": {"season": 2025, "results": 544, "teams": 32, "games": 272},
    "nhl": {"season": 2026, "results": 2624, "teams": 32, "games": 1312},
}


def _conn(path: str) -> sqlite3.Connection:
    con = sqlite3.connect(path)
    con.row_factory = sqlite3.Row
    return con


def _ensure_schema(con: sqlite3.Connection) -> None:
    """Create the three Team Stats tables if the target lacks them, and make the
    pre-existing state safe to build the unique index on.

    The production copy can arrive with partial, duplicated team_game_stats
    (measured: mlb 176 rows = 16 keys x 11 copies; nba 486 rows with 32 dupes).
    Deduplicate to MIN(rowid) per (league, game_id, team_abbrev) — the same
    rule backfill_team_parity.py applies — then drop the approved leagues'
    partial rows so the DEV population replaces them wholesale.
    """
    con.executescript(
        """
        CREATE TABLE IF NOT EXISTS team_game_results(
            league TEXT NOT NULL, game_id TEXT NOT NULL, team TEXT NOT NULL,
            game_date TEXT, opponent TEXT, home_away TEXT,
            score_for REAL, score_against REAL, win INTEGER,
            ingested_at TEXT DEFAULT (datetime('now')), season INTEGER, status TEXT,
            PRIMARY KEY(league, game_id, team));
        CREATE INDEX IF NOT EXISTS idx_tgr_team
            ON team_game_results(league, team, game_date);
        CREATE TABLE IF NOT EXISTS team_game_stats(
            league TEXT NOT NULL, game_id TEXT NOT NULL, captured_at TEXT NOT NULL,
            team_abbrev TEXT NOT NULL, home_away TEXT NOT NULL,
            fgm_fga TEXT, fg_pct REAL, tpm_tpa TEXT, tp_pct REAL,
            ftm_fta TEXT, ft_pct REAL, rebounds INTEGER, off_rebounds INTEGER,
            def_rebounds INTEGER, assists INTEGER, steals INTEGER, blocks INTEGER,
            turnovers INTEGER, fouls INTEGER, pts_off_to INTEGER,
            fast_break_pts INTEGER, pts_in_paint INTEGER, largest_lead INTEGER,
            lead_changes INTEGER, lead_pct REAL,
            shots INTEGER, blocked_shots INTEGER, hits INTEGER,
            takeaways INTEGER, giveaways INTEGER, faceoffs_won INTEGER,
            faceoff_pct REAL, powerplay_goals INTEGER, powerplay_opps INTEGER,
            powerplay_pct REAL, shorthanded_goals INTEGER,
            penalties INTEGER, penalty_min INTEGER, run_id TEXT, first_downs INTEGER,
            total_offensive_plays INTEGER, total_yards INTEGER, net_passing_yards INTEGER,
            rushing_yards INTEGER, defensive_special_teams_tds INTEGER);
        CREATE TABLE IF NOT EXISTS team_stats_coverage (
            run_id TEXT PRIMARY KEY, league TEXT NOT NULL, season INTEGER NOT NULL,
            season_start TEXT NOT NULL, season_end TEXT NOT NULL, status TEXT NOT NULL,
            expected_teams INTEGER NOT NULL, fetched_teams INTEGER NOT NULL,
            expected_games INTEGER, fetched_games INTEGER, paired_games INTEGER,
            paired_stat_games INTEGER, failure_count INTEGER NOT NULL DEFAULT 0,
            completed_at TEXT, source TEXT NOT NULL
        );
        """
    )
    # Dedupe partial pre-existing rows so the unique index can be built.
    con.execute(
        "DELETE FROM team_game_stats WHERE rowid NOT IN "
        "(SELECT MIN(rowid) FROM team_game_stats "
        " GROUP BY league, game_id, team_abbrev)"
    )
    # Approved leagues are replaced wholesale by the DEV population.
    ph = ",".join("?" for _ in APPROVED)
    con.execute(
        f"DELETE FROM team_game_stats WHERE league IN ({ph})",
        tuple(APPROVED.keys()),
    )
    con.execute(
        f"DELETE FROM team_game_results WHERE league IN ({ph})",
        tuple(APPROVED.keys()),
    )
    con.execute(
        f"DELETE FROM team_stats_coverage WHERE league IN ({ph})",
        tuple(APPROVED.keys()),
    )
    con.executescript(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS idx_tgs_unique
            ON team_game_stats(league, game_id, team_abbrev);
        """
    )
    con.commit()


def _col_names(con: sqlite3.Connection, table: str) -> list[str]:
    return [r[1] for r in con.execute(f"PRAGMA table_info({table})")]


def _copy_rows(src: sqlite3.Connection, dst: sqlite3.Connection, table: str,
               where: str, params: tuple) -> int:
    """Copy rows matching `where` from src to dst (column-intersection)."""
    src_cols = _col_names(src, table)
    dst_cols = set(_col_names(dst, table))
    cols = [c for c in src_cols if c in dst_cols]
    collist = ", ".join(cols)
    rows = src.execute(
        f"SELECT {collist} FROM {table} WHERE {where}", params
    ).fetchall()
    if not rows:
        return 0
    placeholders = ", ".join("?" for _ in cols)
    dst.executemany(
        f"INSERT OR REPLACE INTO {table} ({collist}) VALUES ({placeholders})",
        [tuple(r[c] for c in cols) for r in rows],
    )
    return len(rows)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--target", required=True,
                    help="disposable clone DB to populate (never production)")
    ap.add_argument("--source", default=os.environ.get(
        "LP_SOURCE_DB_PATH",
        "/root/legendarypicks/backend/data/picks.dev.db"))
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)

    if args.target == args.source:
        print("ERROR: --target must differ from --source", file=sys.stderr)
        return 2
    if "picks.db" in os.path.basename(args.target) and "rehearsal" not in args.target \
            and "clone" not in args.target and "test" not in args.target:
        print("ERROR: refusing a target that looks like a production/DEV picks.db "
              "(--target={})".format(args.target), file=sys.stderr)
        return 2

    src = _conn(args.source)
    dst = _conn(args.target)
    try:
        # 0. Idempotency guard FIRST: if the target already holds all approved
        #    windows at the expected counts, do nothing (before any cleanup or
        #    rewrite).
        tables = {r[0] for r in dst.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
        if {"team_game_results", "team_game_stats",
                "team_stats_coverage"}.issubset(tables):
            already = {
                league: dst.execute(
                    "SELECT COUNT(*) FROM team_game_results WHERE league=? AND season=?",
                    (league, spec["season"])).fetchone()[0]
                for league, spec in APPROVED.items()
            }
            if all(v == APPROVED[l]["results"] for l, v in already.items()):
                print("Target already holds all approved populations: {} — "
                      "nothing to do.".format(already))
                return 0

        _ensure_schema(dst)

        # 1. Measure source counts for every approved window BEFORE any write.
        for league, spec in APPROVED.items():
            season = spec["season"]
            n_results = src.execute(
                "SELECT COUNT(*) FROM team_game_results WHERE league=? AND season=?",
                (league, season)).fetchone()[0]
            game_ids = [r[0] for r in src.execute(
                "SELECT DISTINCT game_id FROM team_game_results WHERE league=? AND season=?",
                (league, season))]
            if game_ids:
                ph = ",".join("?" for _ in game_ids)
                n_stats = src.execute(
                    f"SELECT COUNT(*) FROM team_game_stats WHERE league=? AND game_id IN ({ph})",
                    (league, *game_ids)).fetchone()[0]
            else:
                n_stats = 0
            n_coverage = src.execute(
                "SELECT COUNT(*) FROM team_stats_coverage WHERE league=? AND season=?",
                (league, season)).fetchone()[0]
            print(f"  {league} season={season}: results={n_results} "
                  f"stats={n_stats} coverage={n_coverage} "
                  f"(expected results={spec['results']})")

            if n_results != spec["results"]:
                print(f"ERROR: {league} result count {n_results} != expected "
                      f"{spec['results']} — aborting before any write",
                      file=sys.stderr)
                return 1
            if n_stats == 0 or n_coverage == 0:
                print(f"ERROR: {league} stats={n_stats} coverage={n_coverage} "
                      f"cannot be empty — aborting", file=sys.stderr)
                return 1

        if args.dry_run:
            print("dry-run: all source measurements passed; no write performed")
            return 0

        # 2. Write everything in ONE transaction (fail-closed).
        try:
            dst.execute("BEGIN")
            for league, spec in APPROVED.items():
                season = spec["season"]
                n1 = _copy_rows(
                    src, dst, "team_game_results",
                    "league=? AND season=?", (league, season))
                game_ids = [r[0] for r in src.execute(
                    "SELECT DISTINCT game_id FROM team_game_results "
                    "WHERE league=? AND season=?", (league, season))]
                ph = ",".join("?" for _ in game_ids)
                n2 = _copy_rows(
                    src, dst, "team_game_stats",
                    f"league=? AND game_id IN ({ph})", (league, *game_ids))
                n3 = _copy_rows(
                    src, dst, "team_stats_coverage",
                    "league=? AND season=?", (league, season))
                print(f"  wrote {league}: results={n1} stats={n2} coverage={n3}")
                if n1 != spec["results"] or n2 == 0 or n3 == 0:
                    raise RuntimeError(
                        f"{league} post-copy verification failed "
                        f"(results={n1} stats={n2} coverage={n3})")
            dst.execute("COMMIT")
            print("Team Stats migration committed atomically.")
        except Exception as exc:
            dst.execute("ROLLBACK")
            print(f"FAILED — rolled back everything: {exc}", file=sys.stderr)
            return 1

        # 3. Final integrity: PRAGMA quick_check on the target.
        qc = dst.execute("PRAGMA quick_check").fetchone()[0]
        print(f"target quick_check: {qc}")
        return 0 if qc == "ok" else 1
    finally:
        src.close()
        dst.close()


if __name__ == "__main__":
    sys.exit(main())
