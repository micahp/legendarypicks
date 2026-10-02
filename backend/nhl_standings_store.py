"""Validated, database-backed NHL standings snapshots.

The NHL standings endpoint publishes the season identity, all 32 clubs, and
the league ordering directly. Keep that product intact instead of rebuilding
standings from whichever completed games happen to be in our logs.
"""
from __future__ import annotations

import json
import sqlite3
from typing import Any

from season_keys import normalize_season
from team_codes import UnknownTeamCode, normalize


SOURCE = "nhle.com:standings/now"
EXPECTED_TEAMS = 32

SCHEMA = """
CREATE TABLE IF NOT EXISTS league_standings_snapshots(
  league         TEXT NOT NULL,
  season         INTEGER NOT NULL,
  source_season  INTEGER NOT NULL,
  season_label   TEXT NOT NULL,
  standings_date TEXT NOT NULL,
  captured_at    TEXT NOT NULL,
  source         TEXT NOT NULL,
  team_count     INTEGER NOT NULL,
  payload        TEXT NOT NULL,
  PRIMARY KEY(league, season)
);
"""


class NHLStandingsError(RuntimeError):
    """The published NHL standings cannot safely replace the last snapshot."""


def ensure_table(connection: sqlite3.Connection) -> None:
    connection.execute(SCHEMA)


def _required_int(row: dict, key: str, team: str) -> int:
    value = row.get(key)
    if value is None or isinstance(value, bool):
        raise NHLStandingsError(f"{team}: standings missing integer {key}")
    try:
        return int(value)
    except (TypeError, ValueError):
        raise NHLStandingsError(
            f"{team}: standings has invalid integer {key}={value!r}"
        ) from None


def _nullable_float(row: dict, key: str, team: str) -> float | None:
    value = row.get(key)
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        raise NHLStandingsError(
            f"{team}: standings has invalid number {key}={value!r}"
        ) from None


def snapshot_from_document(
    document: dict[str, Any],
    *,
    source_season: int,
    expected_teams: int = EXPECTED_TEAMS,
) -> dict[str, Any]:
    """Validate and normalize one complete official standings document."""
    rows = document.get("standings") if isinstance(document, dict) else None
    if not isinstance(rows, list) or len(rows) != expected_teams:
        raise NHLStandingsError(
            f"standings published {len(rows) if isinstance(rows, list) else 0} "
            f"teams; expected {expected_teams}"
        )

    season = normalize_season("nhle.com", "nhl", source_season)
    start_year = str(source_season)[:4]
    season_label = f"{start_year}-{str(season)[-2:]}"
    teams: list[dict[str, Any]] = []
    seen: set[str] = set()
    dates: set[str] = set()

    for row in rows:
        raw_team = str(((row.get("teamAbbrev") or {}).get("default")) or "").strip()
        try:
            team = normalize("nhl", raw_team)
        except UnknownTeamCode as exc:
            raise NHLStandingsError(str(exc)) from exc
        if team in seen:
            raise NHLStandingsError(f"standings published duplicate team {team}")
        seen.add(team)

        published_season = _required_int(row, "seasonId", team)
        if published_season != int(source_season):
            raise NHLStandingsError(
                f"{team}: standings season {published_season} != {source_season}"
            )
        if _required_int(row, "gameTypeId", team) != 2:
            raise NHLStandingsError(f"{team}: standings are not regular season")

        standings_date = str(row.get("date") or "")[:10]
        if len(standings_date) != 10:
            raise NHLStandingsError(f"{team}: standings date is missing")
        dates.add(standings_date)

        games = _required_int(row, "gamesPlayed", team)
        wins = _required_int(row, "wins", team)
        losses = _required_int(row, "losses", team)
        ot_losses = _required_int(row, "otLosses", team)
        points = _required_int(row, "points", team)
        if games != wins + losses + ot_losses:
            raise NHLStandingsError(
                f"{team}: games {games} != W/L/OTL {wins}/{losses}/{ot_losses}"
            )
        if points != wins * 2 + ot_losses:
            raise NHLStandingsError(
                f"{team}: points {points} != 2*W+OTL {wins * 2 + ot_losses}"
            )

        streak_code = str(row.get("streakCode") or "").strip()
        streak_count = (
            None if row.get("streakCount") is None
            else _required_int(row, "streakCount", team)
        )
        if games and (not streak_code or streak_count is None):
            raise NHLStandingsError(f"{team}: played team is missing its streak")
        l10_games = _required_int(row, "l10GamesPlayed", team)
        l10_wins = _required_int(row, "l10Wins", team)
        l10_losses = _required_int(row, "l10Losses", team)
        l10_ot_losses = _required_int(row, "l10OtLosses", team)
        if l10_games != l10_wins + l10_losses + l10_ot_losses:
            raise NHLStandingsError(f"{team}: L10 games disagree with W/L/OTL")

        name = str(((row.get("teamName") or {}).get("default")) or "").strip()
        if not name:
            raise NHLStandingsError(f"{team}: standings team name is missing")
        teams.append({
            "rank": _required_int(row, "leagueSequence", team),
            "abbrev": team,
            "name": name,
            "games_played": games,
            "wins": wins,
            "losses": losses,
            "ot_losses": ot_losses,
            "points": points,
            "win_pct": _nullable_float(row, "winPctg", team),
            "point_pct": _nullable_float(row, "pointPctg", team),
            "differential": _required_int(row, "goalDifferential", team),
            "streak": (
                f"{streak_code}{streak_count}"
                if streak_code and streak_count is not None else None
            ),
            "last10": (
                f"{l10_wins}-{l10_losses}-{l10_ot_losses}"
                if l10_games else None
            ),
            "conference": str(row.get("conferenceName") or "").strip() or None,
            "division": str(row.get("divisionName") or "").strip() or None,
        })

    if len(dates) != 1:
        raise NHLStandingsError(f"standings rows disagree on date: {sorted(dates)}")
    ranks = [row["rank"] for row in teams]
    if sorted(ranks) != list(range(1, expected_teams + 1)):
        raise NHLStandingsError("standings leagueSequence is not a complete ranking")
    teams.sort(key=lambda row: row["rank"])
    return {
        "league": "nhl",
        "season": season,
        "source_season": int(source_season),
        "season_label": season_label,
        "standings_date": dates.pop(),
        "source": SOURCE,
        "teams": teams,
    }


def publish_snapshot(
    connection: sqlite3.Connection,
    snapshot: dict[str, Any],
    *,
    captured_at: str,
) -> None:
    """Write one already-validated snapshot inside the caller's transaction."""
    teams = snapshot.get("teams") or []
    connection.execute(
        """INSERT INTO league_standings_snapshots(
             league,season,source_season,season_label,standings_date,captured_at,
             source,team_count,payload
           ) VALUES(?,?,?,?,?,?,?,?,?)
           ON CONFLICT(league,season) DO UPDATE SET
             source_season=excluded.source_season,
             season_label=excluded.season_label,
             standings_date=excluded.standings_date,
             captured_at=excluded.captured_at,
             source=excluded.source,
             team_count=excluded.team_count,
             payload=excluded.payload""",
        (
            snapshot["league"], snapshot["season"], snapshot["source_season"],
            snapshot["season_label"], snapshot["standings_date"], captured_at,
            snapshot["source"], len(teams), json.dumps(snapshot, sort_keys=True),
        ),
    )


def read_snapshot(
    connection: sqlite3.Connection,
    *,
    league: str,
    season: int | None = None,
) -> dict[str, Any] | None:
    """Read the latest stored season without mutating or contacting a publisher."""
    table = connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' "
        "AND name='league_standings_snapshots'"
    ).fetchone()
    if not table:
        return None
    if season is None:
        row = connection.execute(
            "SELECT payload,captured_at,source FROM league_standings_snapshots "
            "WHERE league=? ORDER BY season DESC LIMIT 1",
            (league.lower(),),
        ).fetchone()
    else:
        row = connection.execute(
            "SELECT payload,captured_at,source FROM league_standings_snapshots "
            "WHERE league=? AND season=?",
            (league.lower(), int(season)),
        ).fetchone()
    if not row:
        return None
    try:
        payload = json.loads(row["payload"])
    except (TypeError, json.JSONDecodeError) as exc:
        raise NHLStandingsError("stored standings payload is invalid JSON") from exc
    teams = payload.get("teams") if isinstance(payload, dict) else None
    if not isinstance(teams, list) or len(teams) != EXPECTED_TEAMS:
        raise NHLStandingsError("stored NHL standings snapshot is incomplete")
    available = [
        int(item[0]) for item in connection.execute(
            "SELECT season FROM league_standings_snapshots "
            "WHERE league=? ORDER BY season DESC",
            (league.lower(),),
        )
    ]
    payload["available_seasons"] = available
    payload["captured_at"] = row["captured_at"]
    payload["source"] = row["source"]
    return payload
