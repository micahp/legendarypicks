"""Current-season product readiness, assembled only from persisted evidence.

``team_stats_coverage`` certifies one league/season population.  It does not say
that the certified season is the one being played today.  This module joins that
registry to the season calendar, scoreboard snapshots, and the rows behind the
main product surfaces so an old green row cannot masquerade as current coverage.

The scoreboard ingest already records ESPN's season envelope and normalized game
phase, so this reader makes no network requests.  The two explicit 2026 windows
below preserve known phase boundaries when there is no nearby game snapshot.
NFL dates are from the published 2026 schedule; NHL dates are from the NHL's
published 2026-27 schedule and ESPN's persisted preseason/season envelope.
"""
from __future__ import annotations

import datetime as dt
import json
import sqlite3
from typing import Any


LEAGUES = (
    "atp", "lcup", "ligamx", "mlb", "mls", "nba", "ncaaf", "nfl",
    "nhl", "ufc", "wc", "wta",
)
VOUCHED = {"complete", "in_progress"}
UPCOMING_WARNING_DAYS = 45
CALENDAR_WARNING_DAYS = 60
MANIFEST_LEAGUES = {"mlb", "mls", "nba", "ncaaf", "nfl", "nhl"}
PLAYER_STATS_LEAGUES = MANIFEST_LEAGUES
GAME_LOG_LEAGUES = MANIFEST_LEAGUES | {"lcup", "ligamx", "ufc", "wc"}
TEAM_SCHEDULE_LEAGUES = MANIFEST_LEAGUES
ROSTER_FRESH_DAYS = {"nhl": 7}

# ESPN keys NBA/NHL by the year the season ends and the other leagues here by
# the year it starts (or by the sole calendar year).  See season_keys.py.
END_YEAR_SEASON_KEYS = {"nba", "nhl"}

STATIC_SEASONS = {
    "nba": ({
        "season": 2027,
        "season_start": "2026-10-03",
        "season_end": "2027-06-30",
        "phases": (
            ("preseason", "2026-10-03", "2026-10-19"),
            ("regular_season", "2026-10-20", "2027-04-11"),
            ("postseason", "2027-04-12", "2027-06-30"),
        ),
        "source": "NBA 2026-27 key dates",
    },),
    "nfl": ({
        "season": 2026,
        "season_start": "2026-08-06",
        "season_end": "2027-02-16",
        "phases": (
            ("preseason", "2026-08-06", "2026-09-08"),
            ("regular_season", "2026-09-09", "2027-01-10"),
            ("postseason", "2027-01-11", "2027-02-16"),
        ),
        "source": "NFL 2026 schedule + persisted ESPN season envelope",
    },),
    "nhl": ({
        "season": 2027,
        "season_start": "2026-09-19",
        "season_end": "2027-06-10",
        "phases": (
            ("preseason", "2026-09-19", "2026-09-28"),
            ("regular_season", "2026-09-29", "2027-04-10"),
            ("postseason", "2027-04-11", "2027-06-10"),
        ),
        "source": "NHL 2026-27 published season window",
    },),
}


def _day(value: Any) -> dt.date | None:
    if not value:
        return None
    try:
        return dt.date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def _tables(con: sqlite3.Connection) -> set[str]:
    return {row[0] for row in con.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    )}


def _static_window(league: str, as_of: dt.date) -> dict | None:
    for window in STATIC_SEASONS.get(league, ()):
        start = _day(window["season_start"])
        end = _day(window["season_end"])
        if start and end and start - dt.timedelta(days=UPCOMING_WARNING_DAYS) <= as_of <= end:
            phase = "in_season"
            if as_of < start:
                phase = "upcoming"
            else:
                for name, phase_start, phase_end in window["phases"]:
                    if _day(phase_start) <= as_of <= _day(phase_end):
                        phase = name
                        break
            return {
                **window,
                "phase": phase,
                "days_until_start": max(0, (start - as_of).days),
            }
    return None


def _activity_window(con: sqlite3.Connection, league: str, as_of: dt.date,
                     tables: set[str]) -> dict | None:
    if "league_activity" not in tables:
        return None
    row = con.execute(
        "SELECT calendar_type, season_start, season_end, windows,"
        " fetched_at, checked_at"
        " FROM league_activity WHERE league=?",
        (league,),
    ).fetchone()
    if row is None:
        return None
    start, end = _day(row["season_start"]), _day(row["season_end"])
    if not start or not end:
        return None
    season = end.year if league in END_YEAR_SEASON_KEYS else start.year
    phase = "in_season" if start <= as_of <= end else "offseason"
    # A list calendar publishes precise phase/event windows.  Its broad season
    # envelope is not permission to call the competition active between them.
    if phase == "in_season" and row["calendar_type"] == "list":
        try:
            windows = [(_day(lo), _day(hi)) for lo, hi in json.loads(row["windows"] or "[]")]
        except (TypeError, ValueError):
            windows = []
        valid = [(lo, hi) for lo, hi in windows if lo and hi]
        if valid and not any(lo <= as_of <= hi for lo, hi in valid):
            phase = "between_events"
    return {
        "season": season,
        "season_start": start.isoformat(),
        "season_end": end.isoformat(),
        "phase": phase,
        "phases": (),
        "source": "persisted ESPN league_activity",
        "calendar_fetched_at": row["fetched_at"],
        "calendar_checked_at": row["checked_at"],
    }


def _nearest_scoreboard_phase(con: sqlite3.Connection, league: str,
                              as_of: dt.date, tables: set[str]) -> str | None:
    if "scoreboard_snapshots" not in tables:
        return None
    rows = con.execute(
        "SELECT game_date, payload FROM scoreboard_snapshots"
        " WHERE league=? AND game_date BETWEEN ? AND ?"
        " ORDER BY ABS(julianday(game_date)-julianday(?)), game_date LIMIT 20",
        (league, (as_of - dt.timedelta(days=7)).isoformat(),
         (as_of + dt.timedelta(days=7)).isoformat(), as_of.isoformat()),
    ).fetchall()
    phases = []
    for row in rows:
        try:
            game = json.loads(row["payload"])
        except (TypeError, ValueError):
            continue
        slug = str(game.get("season_slug") or "").lower()
        if slug in ("preseason", "regular-season", "postseason"):
            phases.append(slug.replace("-", "_"))
    # A nearby publisher phase refines a coarse day-calendar envelope.  Refuse
    # an ambiguous mixed window instead of picking whichever row sorted first.
    return phases[0] if phases and len(set(phases)) == 1 else None


def _coverage_rows(con: sqlite3.Connection, tables: set[str]) -> list[dict]:
    if "team_stats_coverage" not in tables:
        return []
    columns = {row[1] for row in con.execute("PRAGMA table_info(team_stats_coverage)")}
    wanted = [name for name in (
        "league", "season", "status", "expected_teams", "fetched_teams",
        "expected_games", "fetched_games", "failure_count", "season_start",
        "season_end", "completed_at", "checked_through",
    ) if name in columns]
    if not {"league", "season", "status"} <= set(wanted):
        return []
    return [dict(row) for row in con.execute(
        f"SELECT {','.join(wanted)} FROM team_stats_coverage"
        " ORDER BY league, season"
    )]


def _count(con: sqlite3.Connection, tables: set[str], table: str, sql: str,
           params: tuple) -> int | None:
    if table not in tables:
        return None
    return int(con.execute(sql, params).fetchone()[0] or 0)


def _availability(count: int | None, phase: str, *, regular_only: bool = False) -> dict:
    if count is None:
        return {"status": "unverified", "count": None}
    if count:
        return {"status": "available", "count": count}
    if regular_only and phase in {"preseason", "upcoming"}:
        return {"status": "pending", "count": 0}
    return {"status": "missing", "count": 0}


def _not_applicable() -> dict:
    return {"status": "not_applicable", "count": None}


def _roster_snapshot_check(con: sqlite3.Connection, tables: set[str],
                           league: str, season: int, as_of: dt.date) -> dict:
    """Describe the one published current-roster snapshot without network I/O."""
    stale_after_days = ROSTER_FRESH_DAYS.get(league)
    if stale_after_days is None:
        return _not_applicable()
    if "roster_snapshots" not in tables:
        return {"status": "unverified", "season": None,
                "reason": "roster snapshot storage is unavailable"}
    row = con.execute(
        "SELECT season,source,captured_at,team_count,player_count"
        " FROM roster_snapshots WHERE league=? AND status='published'"
        " ORDER BY captured_at DESC LIMIT 1",
        (league,),
    ).fetchone()
    if row is None:
        return {"status": "missing", "season": None,
                "reason": f"no published roster snapshot exists for season {season}"}

    captured = _day(row["captured_at"])
    age_days = max(0, (as_of - captured).days) if captured else None
    check = {
        "status": "ready",
        "season": row["season"],
        "source": row["source"],
        "captured_at": row["captured_at"],
        "age_days": age_days,
        "stale_after_days": stale_after_days,
        "team_count": row["team_count"],
        "player_count": row["player_count"],
    }
    if row["season"] != season:
        check["status"] = "stale"
        check["reason"] = (
            f"latest roster snapshot is season {row['season']}; current season is {season}"
        )
    elif captured is None:
        check["status"] = "unverified"
        check["reason"] = "published roster snapshot has no valid capture date"
    elif age_days > stale_after_days:
        check["status"] = "stale"
        check["reason"] = (
            f"roster snapshot is {age_days} days old; maximum is {stale_after_days}"
        )
    return check


def _manifest_check(rows: list[dict], league: str, season: int,
                    as_of: dt.date, active: bool) -> dict:
    league_rows = [row for row in rows if str(row.get("league", "")).lower() == league]
    current = next((row for row in league_rows if row.get("season") == season), None)
    latest = max(league_rows, key=lambda row: row.get("season") or 0, default=None)
    if current is None:
        return {
            "status": "stale" if latest else "missing",
            "season": latest.get("season") if latest else None,
            "reason": (
                f"latest certified season is {latest.get('season')}; current season is {season}"
                if latest else f"no coverage manifest exists for current season {season}"
            ),
        }
    check = dict(current)
    if current.get("status") not in VOUCHED:
        check["reason"] = f"current manifest is {current.get('status') or 'unverified'}"
        return check
    checked = _day(current.get("checked_through"))
    if active and current.get("status") == "in_progress" and (
        checked is None or checked < as_of - dt.timedelta(days=2)
    ):
        check["status"] = "stale"
        check["reason"] = (
            f"in-progress coverage was checked through {checked.isoformat()}"
            if checked else "in-progress coverage has no checked-through date"
        )
        return check
    check["status"] = "ready"
    check["manifest_status"] = current.get("status")
    return check


def build_readiness(con: sqlite3.Connection, as_of: dt.date | None = None) -> dict:
    """Return the current-season readiness contract without network access."""
    as_of = as_of or dt.date.today()
    con.row_factory = sqlite3.Row
    tables = _tables(con)
    coverage = _coverage_rows(con, tables)
    output = []
    warnings = []

    for league in LEAGUES:
        window = _static_window(league, as_of) or _activity_window(
            con, league, as_of, tables
        )
        if window is None:
            latest = max(
                (row for row in coverage if row.get("league") == league),
                key=lambda row: row.get("season") or 0,
                default=None,
            )
            output.append({
                "league": league,
                "status": "unverified",
                "phase": "unknown",
                "expected_season": latest.get("season") if latest else None,
                "reasons": ["no persisted season calendar is available"],
                "checks": {},
            })
            continue

        phase = window["phase"]
        nearby_phase = _nearest_scoreboard_phase(con, league, as_of, tables)
        if nearby_phase:
            phase = nearby_phase
        season = int(window["season"])
        active = phase not in {"offseason", "between_events", "upcoming"}
        start, end = window["season_start"], window["season_end"]

        manifest = (
            _manifest_check(coverage, league, season, as_of, active)
            if league in MANIFEST_LEAGUES
            else {"status": "not_applicable", "season": season}
        )
        scoreboard_count = _count(
            con, tables, "scoreboard_snapshots",
            "SELECT COUNT(*) FROM scoreboard_snapshots WHERE league=?"
            " AND game_date BETWEEN ? AND ?",
            (league, (as_of - dt.timedelta(days=1)).isoformat(),
             (as_of + dt.timedelta(days=1)).isoformat()),
        )
        scoreboard = _availability(scoreboard_count, phase)
        if "scoreboard_refresh" in tables:
            refresh_row = con.execute(
                "SELECT COUNT(*) AS observations, COALESCE(SUM(game_count),0) AS games,"
                " MAX(fetched_at) AS refreshed_at FROM scoreboard_refresh WHERE league=?"
                " AND game_date BETWEEN ? AND ?",
                (league, (as_of - dt.timedelta(days=1)).isoformat(),
                 (as_of + dt.timedelta(days=1)).isoformat()),
            ).fetchone()
            if refresh_row["observations"]:
                scoreboard = {
                    "status": "available",
                    "count": int(refresh_row["games"]),
                    "observations": int(refresh_row["observations"]),
                    "refreshed_at": refresh_row["refreshed_at"],
                }

        # team_game_results holds COMPLETED results. Counting its distinct
        # games is a results inventory, never a schedule inventory: a zero
        # here says no completed game has been ingested, not that the
        # publisher has no schedule.
        schedule_count = _count(
            con, tables, "team_game_results",
            "SELECT COUNT(DISTINCT game_id) FROM team_game_results"
            " WHERE LOWER(league)=? AND season=?",
            (league, season),
        ) if league in TEAM_SCHEDULE_LEAGUES else None
        stats_count = _count(
            con, tables, "player_stats",
            "SELECT COUNT(*) FROM player_stats WHERE LOWER(league)=? AND season=?",
            (league, season),
        ) if league in PLAYER_STATS_LEAGUES else None
        logs_count = _count(
            con, tables, "player_game_logs",
            "SELECT COUNT(*) FROM player_game_logs WHERE LOWER(league)=? AND season=?",
            (league, season),
        ) if league in GAME_LOG_LEAGUES else None
        prop_count = _count(
            con, tables, "prop_games",
            "SELECT COUNT(*) FROM props p JOIN prop_games g ON g.id=p.game_id"
            " WHERE LOWER(g.league)=? AND g.date BETWEEN ? AND ?",
            (league, start, end),
        ) if "props" in tables else None
        settled_count = _count(
            con, tables, "prop_results",
            "SELECT COUNT(*) FROM prop_results r JOIN props p ON p.id=r.prop_id"
            " JOIN prop_games g ON g.id=p.game_id"
            " WHERE LOWER(g.league)=? AND g.date BETWEEN ? AND ?"
            " AND r.actual_value IS NOT NULL",
            (league, start, end),
        ) if {"props", "prop_games"} <= tables else None

        checks = {
            "coverage_manifest": manifest,
            "scoreboard": scoreboard,
            "roster_snapshot": _roster_snapshot_check(
                con, tables, league, season, as_of
            ),
            # Named for what the rows ARE. The former key `schedule` invited
            # the preseason-zero reading "the publisher has no schedule",
            # which the source contradicts.
            "completed_team_results": (
                _availability(schedule_count, phase)
                if league in TEAM_SCHEDULE_LEAGUES else _not_applicable()),
            "player_stats": (_availability(stats_count, phase, regular_only=True)
                             if league in PLAYER_STATS_LEAGUES else _not_applicable()),
            "game_logs": (_availability(logs_count, phase, regular_only=True)
                          if league in GAME_LOG_LEAGUES else _not_applicable()),
            "props": _availability(prop_count, phase),
            "settlement": _availability(settled_count, phase, regular_only=True),
        }
        reasons = []
        if phase == "upcoming":
            message = (
                f"season {season} begins in {window.get('days_until_start')} days; "
                f"current manifest status is {manifest['status']}"
            )
            reasons.append(message)
            warnings.append({
                "league": league,
                "code": "season_starting",
                "message": message,
                "starts_on": start,
                "days_until_start": window.get("days_until_start"),
            })
        if active and league in MANIFEST_LEAGUES and manifest["status"] != "ready":
            message = manifest.get("reason") or "current coverage manifest is not ready"
            reasons.append(message)
            warnings.append({
                "league": league,
                "code": "current_coverage_not_ready",
                "message": message,
            })
        if active and scoreboard["status"] in {"missing", "unverified"}:
            reasons.append("no scoreboard snapshot is stored around today")
        roster = checks["roster_snapshot"]
        if active and roster["status"] in {"missing", "stale", "unverified"}:
            reasons.append(roster.get("reason") or "current roster snapshot is not ready")
        season_end = _day(end)
        has_future_static = any(
            (_day(candidate["season_start"]) or dt.date.min) > as_of
            for candidate in STATIC_SEASONS.get(league, ())
        )
        if (active and season_end and 0 <= (season_end - as_of).days <= CALENDAR_WARNING_DAYS
                and not has_future_static):
            message = (
                f"the stored season calendar ends {end}; the next season is not registered"
            )
            warnings.append({
                "league": league,
                "code": "next_calendar_missing",
                "message": message,
            })
        idle_status = "between_events" if phase == "between_events" else "offseason"
        if phase == "upcoming":
            status = "attention"
        else:
            status = idle_status if not active else ("degraded" if reasons else "ready")
        output.append({
            "league": league,
            "status": status,
            "phase": phase,
            "expected_season": season,
            "season_start": start,
            "season_end": end,
            "calendar_source": window["source"],
            "reasons": reasons,
            "checks": checks,
        })

    return {
        # v3 adds current-roster freshness. v2 renamed `schedule` to
        # `completed_team_results` because those rows are completed games,
        # never a schedule inventory.
        "contract": "league-readiness-v3",
        "as_of": as_of.isoformat(),
        "warnings": warnings,
        "leagues": output,
    }
