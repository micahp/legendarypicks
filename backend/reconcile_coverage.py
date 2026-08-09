#!/usr/bin/env python3
"""Coverage-row writer for the reconcile suite.

Extracted from reconcile_totals.py 2026-08-08 (monolith split). Depends on
reconcile_core (season window / oracle) and reconcile_report (verdict). No
behavior change.
"""
import os
import re
import sqlite3
import sys
from datetime import datetime, timezone
from typing import Optional, Tuple

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from reconcile_core import OracleUnreachable, db_count, season_types
from reconcile_report import Report

def write_coverage(conn: sqlite3.Connection, rep: Report, league: str, season: int) -> str:
    """Write this (league, season)'s verdict into the enablement registry.

    This is the only writer of team_stats_coverage. It lives here, and not in the
    ingest, for one reason: the ingest's expectation of itself is its own output.
    `backfill_team_parity.run_league()` wrote
    `expected_games = fetched_games = paired_games = games_written` and a hardcoded
    `failure_count=0`, and so reported `complete` over a season missing four games —
    while the reasons those four failed sat in team_stats_ingestion_failures.

    Every number below comes from somewhere the run does not control: the publisher,
    or a separate SELECT over what actually landed.
    """
    status = rep.verdict(league, season)

    # The coverage row names the INGEST run it is judging, not this reconcile. That is
    # what makes `failure_count` checkable by anyone else:
    #   SELECT COUNT(*) FROM team_stats_ingestion_failures WHERE run_id = coverage.run_id
    # must equal it. Point the row at a run_id nothing was recorded under and the
    # column becomes unfalsifiable again, which is the whole defect.
    ingest_run = conn.execute(
        "SELECT run_id FROM team_game_stats WHERE league=?"
        " ORDER BY captured_at DESC LIMIT 1", (league,)
    ).fetchone()
    run_id = ingest_run[0] if ingest_run else (
        f"{league}-reconcile-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}"
    )

    def count(sql: str, args=()) -> int:
        try:
            return db_count(conn, sql, args)
        except sqlite3.Error:
            return 0

    fetched_games = count(
        "SELECT COUNT(DISTINCT game_id) FROM team_game_results WHERE league=? AND season=?",
        (league, season),
    )
    paired_games = count(
        "SELECT COUNT(*) FROM (SELECT game_id FROM team_game_results"
        " WHERE league=? AND season=? GROUP BY game_id HAVING COUNT(DISTINCT team)=2)",
        (league, season),
    )
    paired_stat_games = count(
        "SELECT COUNT(*) FROM (SELECT game_id FROM team_game_stats"
        " WHERE league=? GROUP BY game_id HAVING COUNT(DISTINCT team_abbrev)=2)",
        (league,),
    )
    fetched_teams = count(
        "SELECT COUNT(DISTINCT team) FROM team_game_results WHERE league=? AND season=?",
        (league, season),
    )
    if league == "ncaaf":
        # Coverage counts FBS teams, not every group-80 participant: FCS
        # buy-game opponents (Mercer etc.) play real games but are not FBS, and
        # the 146-id publisher list includes nine all-star/combine sides that
        # never play. Keep their rows; exclude them from the team count.
        from team_codes import is_canonical
        fetched_teams = len(
            [t for (t,) in conn.execute(
                "SELECT DISTINCT team FROM team_game_results WHERE league=? AND season=?",
                (league, season),
            ).fetchall() if is_canonical("ncaaf", t)]
        )
    fetched_players = count(
        "SELECT COUNT(DISTINCT player_id) FROM player_game_logs"
        " WHERE league=? AND season=? AND player_id IS NOT NULL",
        (league, season),
    )
    # The integrity count the column-presence guard in routers/nfl_offseason.py missed:
    # a column can exist, be filtered on, and hold nothing but NULLs.
    null_key_rows = count(
        "SELECT COUNT(*) FROM player_game_logs WHERE league=? AND season=?"
        " AND (game_type IS NULL OR team IS NULL OR game_id IS NULL)",
        (league, season),
    )
    if null_key_rows:
        status = "partial" if status == "complete" else status

    expected_games = _expected_games_from_report(rep, league, season, fetched_games)
    window_start, window_end = _published_season_window(league, season)

    # `checked_through` is what the row actually claims: every published game from
    # season_start up to this date is present and paired. Not "as of now" — as of the
    # last game we hold.
    checked_row = conn.execute(
        "SELECT MAX(game_date) FROM team_game_results WHERE league=? AND season=?",
        (league, season),
    ).fetchone()
    checked_through = (checked_row[0] or None) if checked_row else None

    # A season that passes every check but has not ended yet is `in_progress`, not
    # `complete`. Keeping them apart is the point: `complete` means the season is over
    # AND fully checked, and a caller that offers only `complete` would otherwise be
    # told a September-ending season was finished in August. It also stops the row
    # from having to lie in order to be offerable.
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    if status == "complete" and window_end and today <= window_end:
        status = "in_progress"

    # READ, never asserted. The previous writer passed a literal 0 here while the
    # same function was inserting rows into this exact table.
    failure_count = count(
        "SELECT COUNT(*) FROM team_stats_ingestion_failures WHERE run_id=?", (run_id,)
    )
    if failure_count and status == "complete":
        status = "partial"

    conn.execute("DELETE FROM team_stats_coverage WHERE league=? AND season=?",
                 (league, season))
    cov_columns = {r[1] for r in conn.execute("PRAGMA table_info(team_stats_coverage)")}
    cols = ("run_id,league,season,season_start,season_end,status,expected_teams,"
            "fetched_teams,expected_games,fetched_games,paired_games,paired_stat_games,"
            "failure_count,completed_at,source")
    vals = [run_id, league, season, window_start, window_end, status,
            fetched_teams, fetched_teams,
            expected_games, fetched_games, paired_games, paired_stat_games,
            failure_count,
            datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "reconcile_totals+espn_core_api"]
    # Tolerate a database that predates the column rather than refusing to write the
    # row: an older prod schema should degrade to the previous behaviour, not fail.
    if "checked_through" in cov_columns:
        cols += ",checked_through"
        vals.append(checked_through)
    conn.execute(
        f"INSERT INTO team_stats_coverage({cols}) "
        f"VALUES({','.join('?' * len(vals))})",
        vals,
    )
    conn.commit()
    return status

def _published_season_window(league: str, season: int) -> Tuple[str, str]:
    """The season's date window, read from `seasons/<year>` — never from our own rows.

    `season_start`/`season_end` are NOT NULL, and the first draft of this writer passed
    `None, None` for both, which raised on the very first row it tried to write. The
    tempting repair is `MIN(game_date)/MAX(game_date)` over `team_game_results` — but
    that answers "when did the games we happen to hold start", which is the ingest
    describing its own output again, the exact defect this function exists to prevent.
    A season missing its first week would silently redefine when the season began.

    The regular-season type publishes `startDate`/`endDate`; a single-type competition
    (soccer) publishes them on its one type. Both are already in the document
    `season_types()` fetched, so this costs no extra request.
    """
    types = season_types(league, season)
    chosen = None
    for key, value in types.items():
        if "regular" in key:
            chosen = value
            break
    if chosen is None:
        # No phase named "regular": either one type IS the season, or the league names
        # its phases differently. Take the widest published window over real types —
        # an empty type (MLS "Combined", 0 events) publishes no useful dates.
        dated = [v for v in types.values() if v.get("startDate") and v.get("endDate")]
        if not dated:
            raise OracleUnreachable(
                f"{league} {season} publishes no season type with dates"
            )
        starts = min(str(v["startDate"]) for v in dated)
        ends = max(str(v["endDate"]) for v in dated)
        return starts[:10], ends[:10]
    start, end = chosen.get("startDate"), chosen.get("endDate")
    if not start or not end:
        raise OracleUnreachable(
            f"{league} {season} regular-season type publishes no date range"
        )
    return str(start)[:10], str(end)[:10]

def _expected_games_from_report(rep: Report, league: str, season: int, fallback: int) -> int:
    """The publisher's expected total, recovered from the check that read it.

    Falls back to what landed only when no games check ran — and in that case the
    verdict is already `unverified`, so the number is never load-bearing.
    """
    needle = f"{league} {season} games in team_game_results"
    for _status, name, detail, _note in rep.rows:
        if name == needle:
            m = re.search(r"published=(\d+)", detail)
            if m:
                return int(m.group(1))
    return fallback
