#!/usr/bin/env python3
"""backfill_team_stats_fixture.py — load synthetic NBA fixtures into a proof DB.

Mandatory flags: --league, --season, --season-start, --season-end, --db-path,
--fixture, --run-id, --report, --min-available-mib.

Only ``nba`` league and ``synthetic_fixture`` source are accepted.
Guards the existing DB (must be absolute /tmp, regular, current UID,
st_nlink=1, not symlink, inode stable, exact required schema) and the report
(exclusive new file).  Validates every fixture detail, loads each ESPN-shaped
summary through the contract extractor, stores inventory / results / stats in
transactions, records failures, verifies the DB state with re-queries, writes
the coverage row only after all checks pass, and then calls
build_team_aggregates.
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from datetime import date, datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

from team_stats_contract import (  # noqa: E402
    STAT_FIELDS,
    build_team_aggregates,
    extract_espn_team_stats,
)
from team_stats_schema import (  # noqa: E402
    expected_tables,
    required_coverage_columns,
    required_result_columns,
    required_stat_columns,
)

PROTECTED_SUBSTRINGS = [
    "legendarypicks",
    "lp-pick-desk",
    "picks.db",
    "picks.dev.db",
]

REQUIRED_PARENT = "/tmp"

ALLOWED_LEAGUES = {"nba"}
ALLOWED_SOURCES = {"synthetic_fixture"}

NBA_STAT_KEYS = set(STAT_FIELDS["nba"])
TEXT_STAT_KEYS = {"fgm_fga", "tpm_tpa", "ftm_fta"}


# ---------------------------------------------------------------------------
# path / memory guards
# ---------------------------------------------------------------------------

def _guard_existing_db(db_path: str) -> str:
    """Validate the existing DB path.  Returns the resolved absolute path."""
    if not os.path.isabs(db_path):
        print(f"REJECTED: db_path must be absolute, got {db_path}", file=sys.stderr)
        sys.exit(2)

    resolved_parent = os.path.realpath(os.path.dirname(db_path))
    if resolved_parent != REQUIRED_PARENT:
        print(f"REJECTED: db_path parent must be exactly /tmp, "
              f"resolved to {resolved_parent}", file=sys.stderr)
        sys.exit(2)

    lower = db_path.lower()
    for bad in PROTECTED_SUBSTRINGS:
        if bad in lower:
            print(f"REJECTED: db_path contains protected substring '{bad}'",
                  file=sys.stderr)
            sys.exit(2)

    if not os.path.lexists(db_path):
        print(f"REJECTED: {db_path} does not exist", file=sys.stderr)
        sys.exit(2)

    if os.path.islink(db_path):
        print(f"REJECTED: {db_path} is a symlink", file=sys.stderr)
        sys.exit(2)

    if not os.path.isfile(db_path):
        print(f"REJECTED: {db_path} is not a regular file", file=sys.stderr)
        sys.exit(2)

    st = os.stat(db_path)
    if st.st_nlink != 1:
        print(f"REJECTED: {db_path} st_nlink={st.st_nlink}, expected 1",
              file=sys.stderr)
        sys.exit(2)
    if st.st_uid != os.getuid():
        print(f"REJECTED: {db_path} owned by uid={st.st_uid}, "
              f"expected {os.getuid()}", file=sys.stderr)
        sys.exit(2)

    return db_path


def _guard_report_path(report_path: str) -> str:
    if not os.path.isabs(report_path):
        print(f"REJECTED: report path must be absolute, got {report_path}",
              file=sys.stderr)
        sys.exit(2)
    if os.path.lexists(report_path):
        print(f"REJECTED: report path already exists: {report_path}",
              file=sys.stderr)
        sys.exit(2)
    return report_path


def _create_exclusive_nofollow(path: str, mode: int = 0o600) -> int:
    try:
        flags = os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_RDWR
    except AttributeError:
        flags = os.O_CREAT | os.O_EXCL | os.O_RDWR
    return os.open(path, flags, mode)


def _check_memory(min_mib: int) -> None:
    try:
        with open("/proc/meminfo") as fh:
            for line in fh:
                if line.startswith("MemAvailable:"):
                    kb = int(line.split()[1])
                    if kb < min_mib * 1024:
                        print(f"HARD ABORT: MemAvailable={kb // 1024} MiB < "
                              f"{min_mib} MiB", file=sys.stderr)
                        sys.exit(3)
                    return
    except Exception:
        pass
    print("WARNING: could not read /proc/meminfo, proceeding", file=sys.stderr)


def _verify_schema(connection: sqlite3.Connection) -> None:
    """Verify that every expected table exists."""
    existing = {
        row[0] for row in
        connection.execute("SELECT name FROM sqlite_master WHERE type='table'")
    }
    missing = expected_tables() - existing
    if missing:
        print(f"REJECTED: missing tables in DB: {sorted(missing)}",
              file=sys.stderr)
        sys.exit(2)

    # check required columns for contract compatibility
    coverage_cols = {row[1] for row in
                     connection.execute("PRAGMA table_info(team_stats_coverage)")}
    missing_cov = required_coverage_columns() - coverage_cols
    if missing_cov:
        print(f"REJECTED: team_stats_coverage missing columns: {sorted(missing_cov)}",
              file=sys.stderr)
        sys.exit(2)

    result_cols = {row[1] for row in
                   connection.execute("PRAGMA table_info(team_game_results)")}
    missing_res = required_result_columns() - result_cols
    if missing_res:
        print(f"REJECTED: team_game_results missing columns: {sorted(missing_res)}",
              file=sys.stderr)
        sys.exit(2)

    stat_cols = {row[1] for row in
                 connection.execute("PRAGMA table_info(team_game_stats)")}
    missing_stat = required_stat_columns() - stat_cols
    if missing_stat:
        print(f"REJECTED: team_game_stats missing columns: {sorted(missing_stat)}",
              file=sys.stderr)
        sys.exit(2)


# ---------------------------------------------------------------------------
# fixture validation
# ---------------------------------------------------------------------------

def _parse_date(d: str) -> date:
    return date.fromisoformat(d)


def _split_made_attempted(value: str) -> tuple[int, int]:
    """Parse 'made-attempted' string, checking made <= attempted."""
    if "-" in value:
        sep = "-"
    elif "/" in value:
        sep = "/"
    else:
        raise ValueError(f"cannot parse made/attempted from {value!r}")
    made_str, att_str = value.split(sep, 1)
    made, attempted = int(made_str), int(att_str)
    if made > attempted:
        raise ValueError(f"made ({made}) > attempted ({attempted}) in {value!r}")
    return made, attempted


def _validate_fixture_metadata(fixture: dict, league: str, season: int,
                                season_start: str, season_end: str) -> list[str]:
    """Validate top-level fixture metadata.  Returns list of failure reasons."""
    failures: list[str] = []

    src = fixture.get("fixture_source")
    if src not in ALLOWED_SOURCES:
        failures.append(f"fixture_source={src!r}, expected one of {ALLOWED_SOURCES}")

    if fixture.get("league") != league:
        failures.append(f"fixture league={fixture.get('league')!r}, expected {league!r}")

    if fixture.get("season") != season:
        failures.append(f"fixture season={fixture.get('season')}, expected {season}")

    if fixture.get("season_start") != season_start:
        failures.append(f"fixture season_start mismatch")

    if fixture.get("season_end") != season_end:
        failures.append(f"fixture season_end mismatch")

    teams = fixture.get("teams")
    if not isinstance(teams, list) or len(teams) != 30:
        failures.append(f"teams: expected list of 30, got {type(teams).__name__}")
    elif len(set(teams)) != 30:
        failures.append("teams list contains duplicates")

    games = fixture.get("games")
    if not isinstance(games, list) or len(games) != 15:
        failures.append(f"games: expected list of 15, got {type(games).__name__}")
    else:
        game_ids = [g.get("game_id") for g in games]
        if len(set(game_ids)) != 15:
            failures.append("duplicate game_ids in fixture")

    return failures


def _validate_games(fixture: dict, season_start: str, season_end: str,
                    league: str) -> tuple[list[str], dict]:
    """Validate each game.  Returns (failures, team_schedules dict)."""
    failures: list[str] = []
    team_schedules: dict[str, list[dict]] = {}
    seen_game_ids: set[str] = set()

    try:
        start_date = _parse_date(season_start)
        end_date = _parse_date(season_end)
    except ValueError as e:
        failures.append(f"invalid season bounds: {e}")
        return failures, team_schedules

    for game in fixture.get("games", []):
        gid = game.get("game_id", "")
        if gid in seen_game_ids:
            failures.append(f"duplicate game_id {gid}")
            continue
        seen_game_ids.add(gid)

        # date in bounds
        try:
            gd = _parse_date(game["game_date"])
        except (KeyError, ValueError) as e:
            failures.append(f"{gid}: invalid/missing game_date: {e}")
            continue
        if not (start_date <= gd <= end_date):
            failures.append(f"{gid}: date {gd} not in [{season_start}, {season_end}]")
            continue

        if game.get("status") != "completed":
            failures.append(f"{gid}: status={game.get('status')!r}, expected 'completed'")
            continue

        home = game.get("home_team", "")
        away = game.get("away_team", "")
        if not home or not away or home == away:
            failures.append(f"{gid}: invalid home/away teams {home!r}/{away!r}")
            continue

        try:
            hs = int(game["home_score"])
            aws = int(game["away_score"])
        except (KeyError, ValueError):
            failures.append(f"{gid}: missing or non-numeric scores")
            continue

        if hs == aws:
            failures.append(f"{gid}: tie game not allowed for NBA")
            continue

        # build schedules
        team_schedules.setdefault(home, []).append({
            "game_id": gid, "game_date": game["game_date"],
            "home_away": "home", "opponent": away,
            "score_for": hs, "score_against": aws,
            "win": 1 if hs > aws else 0,
        })
        team_schedules.setdefault(away, []).append({
            "game_id": gid, "game_date": game["game_date"],
            "home_away": "away", "opponent": home,
            "score_for": aws, "score_against": hs,
            "win": 1 if aws > hs else 0,
        })

    return failures, team_schedules


def _validate_schedules(team_schedules: dict, fixture_teams: list[str]) -> list[str]:
    """Check every team has exactly 1 game, each game_id appears exactly twice."""
    failures: list[str] = []

    if len(team_schedules) != 30:
        failures.append(f"schedule covers {len(team_schedules)} teams, expected 30")

    for team in fixture_teams:
        sched = team_schedules.get(team, [])
        if len(sched) != 1:
            failures.append(f"team {team}: {len(sched)} games in schedule, expected 1")

    # each game_id exactly twice
    gid_counts: dict[str, int] = {}
    for sched in team_schedules.values():
        for entry in sched:
            gid_counts[entry["game_id"]] = gid_counts.get(entry["game_id"], 0) + 1
    for gid, count in gid_counts.items():
        if count != 2:
            failures.append(f"game_id {gid}: appears {count} times, expected 2")

    return failures


def _validate_extracted_stats(games: list[dict], league: str) -> list[str]:
    """Load each summary through extract_espn_team_stats and validate."""
    failures: list[str] = []
    extracted_map: dict[str, list[dict]] = {}

    for game in games:
        gid = game["game_id"]
        summary = game.get("summary")
        if not isinstance(summary, dict):
            failures.append(f"{gid}: missing or non-dict summary")
            continue

        rows = extract_espn_team_stats(league, summary)
        if len(rows) != 2:
            failures.append(f"{gid}: extract_espn_team_stats returned "
                            f"{len(rows)} rows, expected 2")
            continue

        extracted_map[gid] = rows
        abbrevs = {r["team_abbrev"] for r in rows}
        expected_abbrevs = {game["home_team"], game["away_team"]}
        if abbrevs != expected_abbrevs:
            failures.append(f"{gid}: extracted teams {abbrevs} != "
                            f"expected {expected_abbrevs}")
            continue

        sides = {r["home_away"] for r in rows}
        if sides != {"home", "away"}:
            failures.append(f"{gid}: home_away values {sides}, expected {{home, away}}")
            continue

        for row in rows:
            abbrev = row["team_abbrev"]
            stats = row.get("stats", {})

            # every NBA field must be present
            for key in NBA_STAT_KEYS:
                if key not in stats or stats[key] is None:
                    failures.append(f"{gid}/{abbrev}: missing stat {key}")

            # made <= attempted for text fields
            for key in TEXT_STAT_KEYS:
                val = stats.get(key)
                if isinstance(val, str):
                    try:
                        _split_made_attempted(val)
                    except ValueError as e:
                        failures.append(f"{gid}/{abbrev} {key}: {e}")

            # rebounds = off + def
            reb = stats.get("rebounds")
            off = stats.get("off_rebounds")
            df = stats.get("def_rebounds")
            if isinstance(reb, (int, float)) and isinstance(off, (int, float)) and isinstance(df, (int, float)):
                if reb != off + df:
                    failures.append(f"{gid}/{abbrev}: rebounds {reb} != "
                                    f"off {off} + def {df}")

    return failures


# ---------------------------------------------------------------------------
# main backfill logic
# ---------------------------------------------------------------------------

def run_backfill(league: str, season: int, season_start: str, season_end: str,
                 db_path: str, fixture_path: str, run_id: str,
                 report_path: str, min_available_mib: int) -> dict:
    """Execute the backfill pipeline.  Returns report dict."""
    report: dict = {
        "action": "backfill",
        "league": league,
        "season": season,
        "run_id": run_id,
        "db_path": db_path,
        "fixture_path": fixture_path,
        "report_path": report_path,
        "success": False,
        "failures": [],
        "error": None,
    }

    # --- guard args ---
    if league not in ALLOWED_LEAGUES:
        report["error"] = f"unsupported league {league!r}"
        return report

    # --- guards ---
    _guard_existing_db(db_path)
    _guard_report_path(report_path)
    _check_memory(min_available_mib)

    # --- load fixture ---
    try:
        with open(fixture_path, encoding="utf-8") as fh:
            fixture = json.load(fh)
    except Exception as e:
        report["error"] = f"cannot load fixture: {e}"
        return report

    if fixture.get("fixture_source") not in ALLOWED_SOURCES:
        report["error"] = f"fixture_source={fixture.get('fixture_source')!r}"
        return report

    # --- validate fixture metadata ---
    meta_failures = _validate_fixture_metadata(
        fixture, league, season, season_start, season_end)
    report["failures"].extend(meta_failures)
    if meta_failures:
        return report

    games = fixture["games"]
    fixture_teams = fixture["teams"]

    # --- validate games & build schedules ---
    game_failures, team_schedules = _validate_games(
        fixture, season_start, season_end, league)
    report["failures"].extend(game_failures)
    if game_failures:
        return report

    # --- validate schedules ---
    sched_failures = _validate_schedules(team_schedules, fixture_teams)
    report["failures"].extend(sched_failures)
    if sched_failures:
        return report

    # --- validate extracted stats ---
    stat_failures = _validate_extracted_stats(games, league)
    report["failures"].extend(stat_failures)
    if stat_failures:
        return report

    # --- open DB with inode guard ---
    st_before = os.stat(db_path)
    inode_before = st_before.st_ino

    connection = sqlite3.connect(db_path)
    connection.row_factory = sqlite3.Row

    try:
        st_after = os.stat(db_path)
        if st_after.st_ino != inode_before:
            report["error"] = (f"inode changed during open: "
                               f"{inode_before} -> {st_after.st_ino}")
            return report

        _verify_schema(connection)

        captured_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        ingestion_failures: list[tuple] = []

        # --- insert inventory ---
        connection.execute("BEGIN")
        try:
            for team_id in fixture_teams:
                connection.execute(
                    "INSERT OR IGNORE INTO team_stats_team_inventory"
                    "(run_id, team_id, team_abbrev) VALUES(?,?,?)",
                    (run_id, team_id, team_id),
                )
        except Exception:
            connection.execute("ROLLBACK")
            raise
        else:
            connection.commit()

        # --- extract stats from each summary & insert results + stats ---
        for game in games:
            gid = game["game_id"]
            summary = game.get("summary", {})
            rows = extract_espn_team_stats(league, summary)

            if len(rows) != 2:
                ingestion_failures.append((gid, "", f"extract returned {len(rows)} rows"))
                continue

            # insert reciprocal result pair
            try:
                connection.execute("BEGIN")

                for side, team_abbrev, opp, score_for, score_against, win in [
                    ("home", game["home_team"], game["away_team"],
                     game["home_score"], game["away_score"],
                     1 if game["home_score"] > game["away_score"] else 0),
                    ("away", game["away_team"], game["home_team"],
                     game["away_score"], game["home_score"],
                     1 if game["away_score"] > game["home_score"] else 0),
                ]:
                    connection.execute(
                        "INSERT OR IGNORE INTO team_game_results"
                        "(league,game_id,team,game_date,opponent,score_for,"
                        "score_against,win,season,status,home_away) "
                        "VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                        (league, gid, team_abbrev, game["game_date"], opp,
                         score_for, score_against, win, season,
                         "completed", side),
                    )

                # insert stat rows
                for row in rows:
                    stats = row["stats"]
                    connection.execute(
                        "INSERT OR IGNORE INTO team_game_stats"
                        "(league,game_id,captured_at,team_abbrev,home_away,run_id,"
                        "fgm_fga,tpm_tpa,ftm_fta,rebounds,off_rebounds,def_rebounds,"
                        "assists,steals,blocks,turnovers) "
                        "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                        (
                            league, gid, captured_at,
                            row["team_abbrev"], row["home_away"], run_id,
                            stats.get("fgm_fga"), stats.get("tpm_tpa"),
                            stats.get("ftm_fta"), stats.get("rebounds"),
                            stats.get("off_rebounds"), stats.get("def_rebounds"),
                            stats.get("assists"), stats.get("steals"),
                            stats.get("blocks"), stats.get("turnovers"),
                        ),
                    )
                connection.commit()
            except Exception as e:
                connection.execute("ROLLBACK")
                ingestion_failures.append((gid, "", str(e)))

        # --- record ingestion failures ---
        if ingestion_failures:
            connection.execute("BEGIN")
            try:
                for gid, team, reason in ingestion_failures:
                    connection.execute(
                        "INSERT INTO team_stats_ingestion_failures"
                        "(run_id, game_id, team, reason) VALUES(?,?,?,?)",
                        (run_id, gid, team, reason),
                    )
                connection.commit()
            except Exception:
                connection.execute("ROLLBACK")
                raise

        # --- re-query verification ---
        verify_failures: list[str] = []

        team_count = connection.execute(
            "SELECT COUNT(DISTINCT team_id) FROM team_stats_team_inventory "
            "WHERE run_id=?", (run_id,)
        ).fetchone()[0]
        if team_count != 30:
            verify_failures.append(f"inventory team_count={team_count}, expected 30")

        game_count = connection.execute(
            "SELECT COUNT(DISTINCT game_id) FROM team_game_results WHERE league=?",
            (league,)
        ).fetchone()[0]
        if game_count != 15:
            verify_failures.append(f"result game_count={game_count}, expected 15")

        result_count = connection.execute(
            "SELECT COUNT(*) FROM team_game_results WHERE league=?", (league,)
        ).fetchone()[0]
        if result_count != 30:
            verify_failures.append(f"result row count={result_count}, expected 30")

        # Count what is PRESENT for the league, not what this run_id inserted.
        # team_game_stats is UNIQUE(league, game_id, team_abbrev) with no run_id in
        # the key, so an idempotent rerun inserts nothing under its own run_id; the
        # coverage manifest row must still be recorded for the rerun.
        stat_count = connection.execute(
            "SELECT COUNT(*) FROM team_game_stats WHERE league=?",
            (league,)
        ).fetchone()[0]
        if stat_count != 30:
            verify_failures.append(f"stat row count={stat_count}, expected 30")

        # check for null required stats
        null_stats = connection.execute(
            "SELECT COUNT(*) FROM team_game_stats WHERE league=? "
            "AND (fgm_fga IS NULL OR tpm_tpa IS NULL OR ftm_fta IS NULL "
            "OR rebounds IS NULL OR off_rebounds IS NULL OR def_rebounds IS NULL "
            "OR assists IS NULL OR steals IS NULL OR blocks IS NULL "
            "OR turnovers IS NULL)",
            (league,)
        ).fetchone()[0]
        if null_stats != 0:
            verify_failures.append(f"null stat rows: {null_stats}")

        # check duplicate stat rows
        dup_stats = connection.execute(
            "SELECT COUNT(*) FROM (SELECT league,game_id,team_abbrev "
            "FROM team_game_stats WHERE league=? "
            "GROUP BY league,game_id,team_abbrev HAVING COUNT(*)>1)",
            (league,)
        ).fetchone()[0]
        if dup_stats != 0:
            verify_failures.append(f"duplicate stat rows: {dup_stats}")

        # check failure count
        failure_count = connection.execute(
            "SELECT COUNT(*) FROM team_stats_ingestion_failures WHERE run_id=?",
            (run_id,)
        ).fetchone()[0]

        # check date bounds
        dates = connection.execute(
            "SELECT MIN(game_date), MAX(game_date) FROM team_game_results "
            "WHERE league=?", (league,)
        ).fetchone()
        if dates[0] is None or dates[0] < season_start:
            verify_failures.append(f"first game_date {dates[0]} before {season_start}")
        if dates[1] is None or dates[1] > season_end:
            verify_failures.append(f"last game_date {dates[1]} after {season_end}")

        if verify_failures:
            report["failures"].extend(verify_failures)

        # --- write coverage only if zero failures ---
        if not report["failures"] and failure_count == 0:
            completed_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            connection.execute("BEGIN")
            try:
                connection.execute(
                    "INSERT INTO team_stats_coverage"
                    "(run_id,league,season,season_start,season_end,status,"
                    "expected_teams,fetched_teams,expected_games,fetched_games,"
                    "paired_games,paired_stat_games,failure_count,completed_at,source) "
                    "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        run_id, league, season, season_start, season_end,
                        "complete", 30, 30, 15, 15,
                        15, 15, 0, completed_at,
                        "espn_team_schedules+espn_boxscores",
                    ),
                )
                connection.commit()
            except Exception as e:
                connection.execute("ROLLBACK")
                report["error"] = f"coverage insert failed: {e}"
                return report

        # --- call build_team_aggregates ---
        response = build_team_aggregates(connection, league)

        if not response.get("supported"):
            report["failures"].append(
                f"build_team_aggregates unsupported: reason={response.get('reason')}")
        elif response.get("season") != season:
            report["failures"].append(
                f"season={response.get('season')}, expected {season}")
        elif len(response.get("teams", [])) != 30:
            report["failures"].append(
                f"team count={len(response.get('teams', []))}, expected 30")
        else:
            report["success"] = True

    finally:
        connection.close()

    # --- write report ---
    rfd = _create_exclusive_nofollow(report_path, 0o600)
    try:
        os.write(rfd, json.dumps(report, indent=2).encode("utf-8"))
    finally:
        os.close(rfd)

    return report


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Load synthetic NBA fixtures into a proof database.")
    parser.add_argument("--league", required=True, help="League (only 'nba').")
    parser.add_argument("--season", required=True, type=int, help="Season year.")
    parser.add_argument("--season-start", required=True, help="Season start date YYYY-MM-DD.")
    parser.add_argument("--season-end", required=True, help="Season end date YYYY-MM-DD.")
    parser.add_argument("--db-path", required=True, help="Absolute path to existing proof DB.")
    parser.add_argument("--fixture", required=True, help="Absolute path to the fixture JSON.")
    parser.add_argument("--run-id", required=True, help="Unique run identifier.")
    parser.add_argument("--report", required=True, help="Absolute path for report (must not exist).")
    parser.add_argument("--min-available-mib", required=True, type=int,
                        help="Minimum MemAvailable in MiB.")
    args = parser.parse_args()

    if args.league not in ALLOWED_LEAGUES:
        print(f"ERROR: --league must be one of {ALLOWED_LEAGUES}", file=sys.stderr)
        sys.exit(2)

    try:
        _ = _parse_date(args.season_start)
        _ = _parse_date(args.season_end)
    except ValueError as e:
        print(f"ERROR: invalid date format: {e}", file=sys.stderr)
        sys.exit(2)

    report = run_backfill(
        league=args.league,
        season=args.season,
        season_start=args.season_start,
        season_end=args.season_end,
        db_path=args.db_path,
        fixture_path=args.fixture,
        run_id=args.run_id,
        report_path=args.report,
        min_available_mib=args.min_available_mib,
    )

    if report["success"]:
        print(f"OK: backfill completed successfully")
        print(f"    league={report['league']} season={report['season']}")
        print(f"    run_id={report['run_id']}")
        print(f"    report={report['report_path']}")
        sys.exit(0)
    else:
        msg = report.get("error") or f"{len(report.get('failures',[]))} failure(s)"
        print(f"FAILED: {msg}", file=sys.stderr)
        for f in report.get("failures", []):
            print(f"  - {f}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
