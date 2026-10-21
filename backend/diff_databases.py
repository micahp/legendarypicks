#!/usr/bin/env python3
"""What does PROD hold that DEV does not, and vice versa?

Every gate in this repo runs against whichever database you point it at, so a
green run proves nothing about the other one. On 2026-08-05 that cost five
separate defects, each of them correct in code and absent from production:

  * NFL `rush_td`/`rec_td` -- v0.7.3's headline feature, 0 rows in prod through
    three releases while dev had it
  * NBA season stats 2026 -- dev had 576 rows, prod served 2023
  * MLB `position_group` / `pitcher_role` -- dev migrated, prod had no column
  * NBA 2025 -- never ingested to prod
  * NHL season keys -- `migrate_nhl_season_keys.py` ran on dev 2026-08-02; prod
    still held 48,017 rows at nhle.com's raw `20252026`, so a season-scoped
    join returned 0 for NHL and 6k-52k for every other league

None of them raised. Both databases answered 200 throughout, and the audit was
green against dev. The only thing that distinguishes them is a diff nobody ran.

This is that diff. It reports three things with TWO severities:

  BLOCKING  (exit 1 -- a promotion did not happen, do not release over it)
  1. SCHEMA   -- a table or column one side has and the other does not
  2. SEASONS  -- a (league, season) present on one side and missing on the other

  ADVISORY  (printed, but exit 0 -- legitimate drift, should be a decision)
  3. VOLUME   -- a row count differing by more than --tolerance (default 5%)
  4. FEATURE  -- a table/column classified "feature not deployed to prod"
                (docs/SCHEMA-DRIFT-AUDIT-2026-07-28.md) or team-stats ingest
                columns; exists on dev before promotion by design

A migration-owned table, column or season present on one database and absent
from the other is never "dev is deliberately ahead" -- it is always a promotion
that did not happen. VOLUME and FEATURE are different: live odds
(`prop_odds_snapshots` prod 409,617 vs dev 3,526), dev-only mock drafts, and
feature tables under development are legitimate drift, so failing on them
would train people to skip the check. `--strict-volume` re-arms them for
manual use / CI that wants full equality.

Usage:
  cd backend && venv/bin/python diff_databases.py
  venv/bin/python diff_databases.py --prod data/picks.db --dev data/picks.dev.db
  venv/bin/python diff_databases.py --quiet      # only differences
  venv/bin/python diff_databases.py --strict-volume   # volume blocks too
"""
from __future__ import annotations

import argparse
import os
import sqlite3
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_PROD = os.path.join(HERE, "data", "picks.db")
DEFAULT_DEV = os.path.join(HERE, "data", "picks.dev.db")

# Tables whose divergence is expected and uninteresting: caches, scratch and
# anything a background timer rewrites on its own schedule.
SKIP = {"sqlite_sequence", "sqlite_stat1"}

# Feature tables classified "feature not deployed to prod" or
# "environment-local" by docs/SCHEMA-DRIFT-AUDIT-2026-07-28.md. A table or
# column in this set may legitimately exist on only one database while the
# feature is being developed on dev; it is ADVISORY drift (a decision to
# promote later), never a failed migration. The migration ledger
# (app_schema_migrations) is the source of truth for what MUST match.
FEATURE_TABLES = {
    "momentum_state": "momentum job -- feature not deployed to prod",
    "momentum_crosses": "momentum job -- feature not deployed to prod",
    "nfl_pbp": "retained-play feature not deployed to prod",
    "nfl_published_fantasy_points": "published-fantasy feature not deployed to prod",
    "schema_migrations": "team-stats proof integer registry (not the app registry)",
    "team_stats_ingestion_failures": "team-stats proof feature",
    "team_stats_team_inventory": "team-stats proof feature",
    "team_game_results": "team-stats proof feature",
    "settlement_attempts": "NCAAF CFBD settler (repair order step 5) -- durable attempt audit on DEV and PROD",
    "history_refresh_state": "environment-local scheduler state (prod-only)",
    "nfl_player_birth_dates": "dev-only NFL age research; no released app reader",
    "tennis_points": "Flashscore point-sequence archive for tennis research; no released app reader",
    "tennis_model_lock_distributions": "CP4 frozen count and total-games distributions; dev-only by design (the lock sweep creates it on picks.dev.db only); research reader only",
    "tennis_model_lock_distributions": "CP4 frozen count and total-games distributions; dev-only by design (the lock sweep creates it on picks.dev.db only); research reader only",
    "nba_sportsdataverse_games": "NBA SportsDataverse (hoopR) ingest -- not deployed to prod this release",
    "nba_sportsdataverse_releases": "NBA SportsDataverse (hoopR) ingest -- not deployed to prod this release",
    "player_game_logs_sportsdataverse": "NBA SportsDataverse (hoopR) ingest -- not deployed to prod this release",
}

# Columns on shared tables that belong to the team-stats feature and are
# added by its ingest (ingest_team_results / stamp_team_result_source), not
# by a numbered migration.
FEATURE_COLUMNS = {
    ("team_game_results", "run_id"): "team-stats ingest feature",
    ("team_game_results", "source"): "team-stats ingest feature",
    ("team_game_stats", "source"): "team-stats ingest feature",
}

# Season windows on shared tables that are dev-only research backfill, not a
# promotion that did not happen. prod deliberately serves only the live window;
# the historical seasons exist on dev for research and are built DEV-only by
# scripts/nfl-availability.sh. A season under the threshold is FEATURE
# (advisory), the same decision as FEATURE tables.
FEATURE_SEASONS_BEFORE = {
    ("player_game_availability", "nfl"): (
        2024,
        "pre-2024 NFL availability is dev-only player-splits research; prod serves 2024+",
    ),
}

BLOCKING_PREFIXES = ("SCHEMA", "SEASONS")
ADVISORY_PREFIXES = ("VOLUME", "FEATURE")


def _feature_season_reason(table, league, season):
    """Reason a (table, league, season) is dev-only research, or None."""
    entry = FEATURE_SEASONS_BEFORE.get((table, league))
    if not entry:
        return None
    threshold, reason = entry
    try:
        return reason if int(season) < threshold else None
    except (TypeError, ValueError):
        return None


def _open(path):
    if not os.path.exists(path):
        raise SystemExit(f"diff_databases: no such database: {path}")
    return sqlite3.connect(f"file:{path}?mode=ro", uri=True)


def _tables(con):
    return {
        r[0] for r in con.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")
    } - SKIP


def _columns(con, table):
    return {r[1] for r in con.execute(f'PRAGMA table_info("{table}")')}


def _count(con, table):
    try:
        return con.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]
    except sqlite3.Error:
        return None


def _seasons(con, table):
    """(league, season) pairs, or None if the table is not season-scoped."""
    cols = _columns(con, table)
    if not {"league", "season"} <= cols:
        return None
    return {
        (str(r[0]), str(r[1])) for r in con.execute(
            f'SELECT DISTINCT league, season FROM "{table}"')
        if r[0] is not None and r[1] is not None
    }


def _scoreboard_only_coverage(con, table, league, season):
    """Explain coverage markers that do not represent a team-stats population.

    The release season gate compares product data populations. A manually
    recorded scoreboard progress marker for a league with no teams or paired
    stats is useful telemetry, but there is no team-stats season to promote.
    Keep the exception narrow and data-backed; complete/reconciled coverage
    rows remain blocking when they are missing from the other database.
    """
    if table != "team_stats_coverage":
        return None
    columns = _columns(con, table)
    required = {
        "league", "season", "status", "source", "expected_teams",
        "fetched_teams", "paired_stat_games",
    }
    if not required.issubset(columns):
        return None
    rows = con.execute(
        "SELECT status, source, expected_teams, fetched_teams, paired_stat_games "
        "FROM team_stats_coverage WHERE LOWER(league)=LOWER(?) "
        "AND CAST(season AS TEXT)=?",
        (league, str(season)),
    ).fetchall()
    if rows and all(
        status == "in_progress"
        and source == "scoreboard_snapshots"
        and expected_teams == 0
        and fetched_teams == 0
        and paired_stat_games == 0
        for status, source, expected_teams, fetched_teams, paired_stat_games in rows
    ):
        return "scoreboard progress only; no team-stat population"
    return None


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--prod", default=DEFAULT_PROD)
    ap.add_argument("--dev", default=DEFAULT_DEV)
    ap.add_argument("--tolerance", type=float, default=0.05,
                    help="row-count difference to ignore, as a fraction (default 0.05)")
    ap.add_argument("--quiet", action="store_true",
                    help="print only differences")
    ap.add_argument("--strict-volume", action="store_true",
                    help="treat VOLUME drift as blocking too (default: advisory)")
    args = ap.parse_args(argv)

    prod, dev = _open(args.prod), _open(args.dev)
    findings: list[str] = []

    # 1. SCHEMA ---------------------------------------------------------------
    pt, dt = _tables(prod), _tables(dev)
    for name in sorted(dt - pt):
        if name in FEATURE_TABLES:
            findings.append(
                f"FEATURE  table {name!r} exists in DEV, missing from PROD "
                f"({FEATURE_TABLES[name]})")
            continue
        findings.append(f"SCHEMA   table {name!r} exists in DEV, missing from PROD")
    for name in sorted(pt - dt):
        if name in FEATURE_TABLES:
            findings.append(
                f"FEATURE  table {name!r} exists in PROD, missing from DEV "
                f"({FEATURE_TABLES[name]})")
            continue
        findings.append(f"SCHEMA   table {name!r} exists in PROD, missing from DEV")

    shared = sorted(pt & dt)
    for table in shared:
        pc, dc = _columns(prod, table), _columns(dev, table)
        for col in sorted(dc - pc):
            key = (table, col)
            if key in FEATURE_COLUMNS:
                findings.append(
                    f"FEATURE  {table}.{col} exists in DEV, missing from PROD "
                    f"({FEATURE_COLUMNS[key]})")
                continue
            findings.append(f"SCHEMA   {table}.{col} exists in DEV, missing from PROD")
        for col in sorted(pc - dc):
            key = (table, col)
            if key in FEATURE_COLUMNS:
                findings.append(
                    f"FEATURE  {table}.{col} exists in PROD, missing from DEV "
                    f"({FEATURE_COLUMNS[key]})")
                continue
            findings.append(f"SCHEMA   {table}.{col} exists in PROD, missing from DEV")

    # 2. SEASONS --------------------------------------------------------------
    # The highest-signal check: a season present on one side and absent on the
    # other is what "the ingest ran on dev" looks like from the outside. A
    # season divergence in a feature table is feature drift (advisory), the
    # same decision as FEATURE tables.
    for table in shared:
        ps, ds = _seasons(prod, table), _seasons(dev, table)
        if ps is None or ds is None:
            continue
        for league, season in sorted(ds - ps):
            telemetry = _scoreboard_only_coverage(dev, table, league, season)
            if telemetry:
                findings.append(
                    f"FEATURE  {table}: ({league}, {season}) in DEV, missing from "
                    f"PROD ({telemetry})")
                continue
            feature_reason = _feature_season_reason(table, league, season)
            if feature_reason:
                findings.append(
                    f"FEATURE  {table}: ({league}, {season}) in DEV, missing from "
                    f"PROD ({feature_reason})")
                continue
            if table in FEATURE_TABLES:
                findings.append(
                    f"FEATURE  {table}: ({league}, {season}) in DEV, missing from "
                    f"PROD ({FEATURE_TABLES[table]})")
                continue
            findings.append(
                f"SEASONS  {table}: ({league}, {season}) in DEV, missing from PROD")
        for league, season in sorted(ps - ds):
            telemetry = _scoreboard_only_coverage(prod, table, league, season)
            if telemetry:
                findings.append(
                    f"FEATURE  {table}: ({league}, {season}) in PROD, missing from "
                    f"DEV ({telemetry})")
                continue
            feature_reason = _feature_season_reason(table, league, season)
            if feature_reason:
                findings.append(
                    f"FEATURE  {table}: ({league}, {season}) in PROD, missing from "
                    f"DEV ({feature_reason})")
                continue
            if table in FEATURE_TABLES:
                findings.append(
                    f"FEATURE  {table}: ({league}, {season}) in PROD, missing from "
                    f"DEV ({FEATURE_TABLES[table]})")
                continue
            findings.append(
                f"SEASONS  {table}: ({league}, {season}) in PROD, missing from DEV")

    # 3. VOLUME ---------------------------------------------------------------
    for table in shared:
        pn, dn = _count(prod, table), _count(dev, table)
        if pn is None or dn is None or pn == dn:
            continue
        denominator = max(pn, dn) or 1
        drift = abs(pn - dn) / denominator
        if drift > args.tolerance:
            findings.append(
                f"VOLUME   {table}: prod={pn} dev={dn} "
                f"({drift * 100:.0f}% apart)")

    if not args.quiet:
        print(f"prod: {args.prod}")
        print(f"dev : {args.dev}")
        print(f"tables: {len(pt)} prod / {len(dt)} dev, {len(shared)} shared")
        print()

    if not findings:
        print("no divergence: schema, seasons and row counts agree")
        return 0

    for line in findings:
        print(line)
    print()

    blocking = [f for f in findings if f.startswith(BLOCKING_PREFIXES)]
    advisory = [f for f in findings if f.startswith(ADVISORY_PREFIXES)]
    if blocking:
        print(f"{len(blocking)} blocking difference(s) (SCHEMA/SEASONS): a table, "
              "column or season present on one database and absent from the other "
              "is a promotion that did not happen -- resolve before releasing.")
        return 1
    if advisory and args.strict_volume:
        print(f"{len(advisory)} difference(s) (VOLUME/FEATURE) over --tolerance "
              "and --strict-volume is set.")
        return 1
    print(f"{len(advisory)} advisory difference(s) (VOLUME/FEATURE). Drift is "
          "often legitimate -- live odds and dev-only mock drafts differ by "
          "design, and feature tables exist on dev before promotion. It should "
          "be a decision, not a discovery; re-run with --strict-volume to make "
          "it blocking.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
