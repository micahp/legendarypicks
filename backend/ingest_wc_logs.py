#!/usr/bin/env python3
"""Ingest per-match FIFA World Cup player logs from ESPN.

The props chart reads ``player_game_logs``. This script enumerates completed
World Cup matches by date, extracts each participant's goals, assists, shots,
and shots on target, and links the ESPN athlete to an existing WC player by
normalized name. Unresolved athletes are retained with ``player_id=NULL`` so
they can be re-resolved on a later idempotent run without creating duplicates.

Usage:
  python3 ingest_wc_logs.py [--days 60]
  python3 ingest_wc_logs.py --start 2026-06-11 --end 2026-07-18
"""
import datetime as dt
import json
import os
import sqlite3
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import espn_client as espn
from _core import _normalize_name
from ingest_nfl_logs import ensure_table  # shared player_game_logs schema


DB = os.environ.get("LP_DB_PATH") or os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "data", "picks.db"
)

_TARGET_STATS = {
    "goals": {"g", "goal", "goals", "totalgoals"},
    "assists": {"a", "assist", "assists", "goalassists"},
    "shots": {"sh", "shot", "shots", "totalshots"},
    "sot": {"sog", "sot", "shotsongoal", "shotsontarget"},
}


def _key(value) -> str:
    return "".join(ch for ch in str(value or "").lower() if ch.isalnum())


def _number(value):
    if isinstance(value, dict):
        value = value.get("value", value.get("displayValue"))
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _target_line(raw_stats) -> dict:
    """Normalize either ESPN stat objects or a name->value mapping."""
    values = {}
    if isinstance(raw_stats, dict):
        items = raw_stats.items()
    else:
        items = (
            (stat.get("name") or stat.get("abbreviation"), stat)
            for stat in (raw_stats or [])
            if isinstance(stat, dict)
        )
    for raw_name, raw_value in items:
        name = _key(raw_name)
        for target, aliases in _TARGET_STATS.items():
            if name in aliases:
                value = _number(raw_value)
                if value is not None:
                    values[target] = value
                break
    if not values:
        return {}
    return {name: values.get(name, 0) for name in ("goals", "assists", "shots", "sot")}


def _appeared(raw_stats) -> bool:
    """Exclude unused reserves when ESPN exposes an appearances=0 marker."""
    for stat in raw_stats or []:
        if not isinstance(stat, dict) or _key(stat.get("name")) != "appearances":
            continue
        value = _number(stat)
        return value is None or value > 0
    return True


def _boxscore_players(summary: dict):
    """Yield player lines from ESPN's generic boxscore.players contract."""
    for block in (summary.get("boxscore") or {}).get("players", []):
        team = (block.get("team") or {}).get("abbreviation") or ""
        home_away = block.get("homeAway")
        for stat_group in block.get("statistics", []):
            names = stat_group.get("names") or stat_group.get("labels") or []
            for row in stat_group.get("athletes", []):
                athlete = row.get("athlete") or {}
                athlete_id = athlete.get("id") or row.get("id")
                name = athlete.get("displayName") or athlete.get("fullName")
                if row.get("didNotPlay") is True:
                    stats = {"did_not_play": 1}
                else:
                    raw = dict(zip(names, row.get("stats") or []))
                    stats = _target_line(raw)
                if athlete_id and name and stats:
                    yield str(athlete_id), name, team, home_away, stats


def _roster_players(summary: dict):
    """Yield player lines from ESPN soccer summaries (the current WC shape)."""
    for block in summary.get("rosters", []):
        team = (block.get("team") or {}).get("abbreviation") or ""
        home_away = block.get("homeAway")
        for row in block.get("roster", []):
            raw_stats = row.get("stats") or []
            if not raw_stats:
                continue
            athlete = row.get("athlete") or {}
            athlete_id = athlete.get("id") or row.get("id")
            name = athlete.get("displayName") or athlete.get("fullName")
            stats = ({"did_not_play": 1} if not _appeared(raw_stats)
                     else _target_line(raw_stats))
            if athlete_id and name and stats:
                yield str(athlete_id), name, team, home_away, stats


class WCPlayerResolver:
    """Resolve ESPN names to existing WC players without fabricating rows."""

    def __init__(self, con: sqlite3.Connection, allowed_player_ids=None):
        self.rows = [dict(row) for row in con.execute(
            "SELECT id, name, team, espn_id FROM players WHERE league='wc'"
        )]
        if allowed_player_ids is not None:
            allowed = {int(player_id) for player_id in allowed_player_ids}
            self.rows = [
                row for row in self.rows if int(row["id"]) in allowed
            ]
        for row in self.rows:
            row["name_norm"] = _normalize_name(row["name"])
            row["team_norm"] = (row.get("team") or "").upper()

    @staticmethod
    def _unique(rows, team):
        if team:
            team_rows = [row for row in rows if row["team_norm"] == team.upper()]
            if len(team_rows) == 1:
                return team_rows[0]["id"]
            if team_rows:
                rows = team_rows
        return rows[0]["id"] if len(rows) == 1 else None

    def resolve(self, name: str, team: str, athlete_id: str = ""):
        if athlete_id:
            source_matches = [
                row for row in self.rows
                if str(row.get("espn_id") or "") == str(athlete_id)
            ]
            if len(source_matches) == 1:
                return source_matches[0]["id"]
        normalized = _normalize_name(name)
        exact = [row for row in self.rows if row["name_norm"] == normalized]
        resolved = self._unique(exact, team)
        if resolved is not None:
            return resolved

        # Some prop-ingested names are clipped by one or more trailing letters
        # (e.g. "Alexis Mac Alliste"). Accept only a unique, team-scoped prefix.
        if len(normalized) < 7:
            return None
        prefix = [
            row for row in self.rows
            if len(row["name_norm"]) >= 7
            and (normalized.startswith(row["name_norm"]) or row["name_norm"].startswith(normalized))
        ]
        resolved = self._unique(prefix, team)
        if resolved is not None:
            return resolved

        # ESPN sometimes uses a short first name while the prop feed uses the
        # formal form ("Nico Gonzalez" vs "Nicolas Gonzalez"). Require the
        # same team, exact surname, and a first-name prefix so this cannot join
        # unrelated players who merely share a surname.
        parts = normalized.split()
        if not team or len(parts) < 2 or len(parts[0]) < 3:
            return None
        nickname = [
            row for row in self.rows
            if row["team_norm"] == team.upper()
            and len(row["name_norm"].split()) >= 2
            and row["name_norm"].split()[-1] == parts[-1]
            and (
                row["name_norm"].split()[0].startswith(parts[0])
                or parts[0].startswith(row["name_norm"].split()[0])
            )
        ]
        if len(nickname) == 1:
            return nickname[0]["id"]

        # Feed names can combine a nickname with a clipped surname while ESPN
        # uses the formal first name ("Alex Grimald" vs
        # "Alejandro Grimaldo"). Allow that only when the team, first initial,
        # and a surname prefix of at least five characters identify one row.
        initial_surname = []
        for row in self.rows:
            row_parts = row["name_norm"].split()
            if (
                row["team_norm"] != team.upper()
                or len(row_parts) < 2
                or row_parts[0][:1] != parts[0][:1]
            ):
                continue
            source_surname = parts[-1]
            row_surname = row_parts[-1]
            if (
                min(len(source_surname), len(row_surname)) >= 5
                and (
                    source_surname.startswith(row_surname)
                    or row_surname.startswith(source_surname)
                )
            ):
                initial_surname.append(row)
        return (
            initial_surname[0]["id"]
            if len(initial_surname) == 1
            else None
        )


def _opponent(team: str, home_away: str, home: str, away: str):
    if home_away == "home":
        return away
    if home_away == "away":
        return home
    if team and home and team.upper() == home.upper():
        return away
    if team and away and team.upper() == away.upper():
        return home
    return None


def ingest(start: str, end: str) -> int:
    start_date = dt.datetime.strptime(start, "%Y-%m-%d").date()
    end_date = dt.datetime.strptime(end, "%Y-%m-%d").date()
    if start_date > end_date:
        raise ValueError("start date must not be after end date")

    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    ensure_table(con)
    resolver = WCPlayerResolver(con)

    ingested = 0
    resolved = 0
    unresolved = 0
    completed_games = 0
    day = start_date
    while day <= end_date:
        date_text = day.isoformat()
        try:
            games = [game for game in espn.games("wc", date_text) if game.get("state") == "post"]
        except Exception as exc:
            print(f"  {date_text}: scoreboard failed ({exc})")
            day += dt.timedelta(days=1)
            continue

        for game in games:
            game_id = str(game.get("game_id") or "")
            if not game_id:
                continue
            try:
                summary = espn.summary("wc", game_id)
            except Exception as exc:
                print(f"  {date_text}: summary {game_id} failed ({exc})")
                continue

            # Support both the generic contract named in the task and ESPN's
            # current soccer roster contract. Roster rows win if both exist.
            player_lines = {}
            for line in _boxscore_players(summary):
                player_lines[line[0]] = line
            for line in _roster_players(summary):
                player_lines[line[0]] = line

            home = (game.get("home") or {}).get("abbrev") or ""
            away = (game.get("away") or {}).get("abbrev") or ""
            game_date = str(game.get("date") or date_text)[:10]
            season = int(game_date[:4])
            for athlete_id, name, team, home_away, stats in player_lines.values():
                if not home_away:
                    if team and home and team.upper() == home.upper():
                        home_away = "home"
                    elif team and away and team.upper() == away.upper():
                        home_away = "away"
                player_id = resolver.resolve(name, team, athlete_id)
                if player_id is None:
                    unresolved += 1
                else:
                    resolved += 1
                con.execute(
                    """INSERT INTO player_game_logs
                       (player_id, league, season, game_no, game_id, game_date, team,
                        opponent, home_away, stats, source, source_player_key)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
                       ON CONFLICT(league, source_player_key, season, game_no) DO UPDATE SET
                         player_id=excluded.player_id,
                         game_id=excluded.game_id,
                         game_date=excluded.game_date,
                         team=excluded.team,
                         opponent=excluded.opponent,
                         home_away=excluded.home_away,
                         stats=excluded.stats,
                         source=excluded.source,
                         ingested_at=datetime('now')""",
                    (
                        player_id, "wc", season, game_id, game_id, game_date, team,
                        _opponent(team, home_away, home, away), home_away,
                        json.dumps(stats, separators=(",", ":")), "espn", athlete_id,
                    ),
                )
                ingested += 1
            completed_games += 1
            time.sleep(0.05)

        con.commit()
        if games:
            print(f"  {date_text}: {len(games)} completed games, {ingested} running logs")
        day += dt.timedelta(days=1)

    total, linked = con.execute(
        "SELECT COUNT(*), COUNT(player_id) FROM player_game_logs WHERE league='wc'"
    ).fetchone()
    prop_players = con.execute(
        """SELECT COUNT(DISTINCT l.player_id)
           FROM player_game_logs l
           JOIN props p ON p.player_id = l.player_id
           JOIN players pl ON pl.id = l.player_id
           WHERE l.league='wc' AND pl.league='wc'"""
    ).fetchone()[0]
    con.close()
    print(
        f"Done. {ingested} WC logs from {completed_games} games "
        f"({resolved} resolved rows, {unresolved} unresolved rows)."
    )
    print(f"WC table now has {total} logs, {linked} linked; {prop_players} prop players have history.")
    return ingested


if __name__ == "__main__":
    today = dt.date.today()
    days = 60
    if "--days" in sys.argv:
        days = int(sys.argv[sys.argv.index("--days") + 1])
    start = (today - dt.timedelta(days=days)).isoformat()
    end = today.isoformat()
    if "--start" in sys.argv:
        start = sys.argv[sys.argv.index("--start") + 1]
    if "--end" in sys.argv:
        end = sys.argv[sys.argv.index("--end") + 1]
    ingest(start, end)
