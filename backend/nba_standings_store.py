"""Database-derived NBA standings. Read-only: nothing is written and nothing is fetched.

NBA standings have no publisher in this database for the season in play, but every regular-season score is in
nba_schedule (nba.com). The table is derived from those scores and checked before it is returned:

- the season has exactly the clubs of TEAMS, the NBA's thirty franchises;
- every scored game names two of them;
- league wins equal league losses, because every decided game has one winner and one loser.

nba_schedule.season is ESPN's end year (2027 is 2026-27), the key the story path and the schedule ingest use. It is the
source because it covers the season in play: team_game_results stops at 2026-04-13, and it has no game type, so
preseason, play-in and Cup-final games sit beside the regular season in it.

The clubs are read from nba_teams, which seed_nba_teams.py fills. TEAMS is that seed: each club's ESPN display name and
its conference and division. The repo has no published alignment table, so the six-division alignment in TEAMS is
hand-entered (UNVERIFIED) and was checked against the 2025-26 schedule in the model history: every club plays 16 or 17 games against
its division, which a wrong grouping could not do. The table's source column says so.

A season with no scored regular-season game has no standings: read_standings returns None.
"""
from __future__ import annotations

import sqlite3

EXPECTED_CLUBS = 30

# Cup knockout games sit in the regular-season id block with no clubs yet, and they are not standings games.
# Cup group games are, and ESPN counts them in the table too. Shared by every reader of nba_schedule.
NOT_KNOCKOUT_SQL = "COALESCE(sub_label, '') NOT IN ('Quarterfinal', 'Semifinal')"

TEAMS = {
    "ATL": {"name": "Atlanta Hawks", "conference": "East", "division": "Southeast"},
    "BKN": {"name": "Brooklyn Nets", "conference": "East", "division": "Atlantic"},
    "BOS": {"name": "Boston Celtics", "conference": "East", "division": "Atlantic"},
    "CHA": {"name": "Charlotte Hornets", "conference": "East", "division": "Southeast"},
    "CHI": {"name": "Chicago Bulls", "conference": "East", "division": "Central"},
    "CLE": {"name": "Cleveland Cavaliers", "conference": "East", "division": "Central"},
    "DAL": {"name": "Dallas Mavericks", "conference": "West", "division": "Southwest"},
    "DEN": {"name": "Denver Nuggets", "conference": "West", "division": "Northwest"},
    "DET": {"name": "Detroit Pistons", "conference": "East", "division": "Central"},
    "GS": {"name": "Golden State Warriors", "conference": "West", "division": "Pacific"},
    "HOU": {"name": "Houston Rockets", "conference": "West", "division": "Southwest"},
    "IND": {"name": "Indiana Pacers", "conference": "East", "division": "Central"},
    "LAC": {"name": "LA Clippers", "conference": "West", "division": "Pacific"},
    "LAL": {"name": "Los Angeles Lakers", "conference": "West", "division": "Pacific"},
    "MEM": {"name": "Memphis Grizzlies", "conference": "West", "division": "Southwest"},
    "MIA": {"name": "Miami Heat", "conference": "East", "division": "Southeast"},
    "MIL": {"name": "Milwaukee Bucks", "conference": "East", "division": "Central"},
    "MIN": {"name": "Minnesota Timberwolves", "conference": "West", "division": "Northwest"},
    "NO": {"name": "New Orleans Pelicans", "conference": "West", "division": "Southwest"},
    "NY": {"name": "New York Knicks", "conference": "East", "division": "Atlantic"},
    "OKC": {"name": "Oklahoma City Thunder", "conference": "West", "division": "Northwest"},
    "ORL": {"name": "Orlando Magic", "conference": "East", "division": "Southeast"},
    "PHI": {"name": "Philadelphia 76ers", "conference": "East", "division": "Atlantic"},
    "PHX": {"name": "Phoenix Suns", "conference": "West", "division": "Pacific"},
    "POR": {"name": "Portland Trail Blazers", "conference": "West", "division": "Northwest"},
    "SA": {"name": "San Antonio Spurs", "conference": "West", "division": "Southwest"},
    "SAC": {"name": "Sacramento Kings", "conference": "West", "division": "Pacific"},
    "TOR": {"name": "Toronto Raptors", "conference": "East", "division": "Atlantic"},
    "UTAH": {"name": "Utah Jazz", "conference": "West", "division": "Northwest"},
    "WSH": {"name": "Washington Wizards", "conference": "East", "division": "Southeast"},
}


SEED_SOURCE = ("UNVERIFIED: hand-entered six-division alignment, checked against nba_model_history 2026; no published division source")


def ensure_table(connection) -> None:
    connection.execute("""CREATE TABLE IF NOT EXISTS nba_teams(
        season INTEGER NOT NULL, team TEXT NOT NULL, team_name TEXT, conference TEXT, division TEXT,
        source TEXT, PRIMARY KEY(season, team))""")


def seed(connection, season: int, source: str = SEED_SOURCE) -> None:
    """Write the thirty clubs of TEAMS as the season's clubs. Re-running it rewrites the same rows."""
    ensure_table(connection)
    with connection:
        connection.executemany(
            "INSERT INTO nba_teams(season, team, team_name, conference, division, source) VALUES(?,?,?,?,?,?) "
            "ON CONFLICT(season, team) DO UPDATE SET team_name=excluded.team_name, conference=excluded.conference, "
            "division=excluded.division, source=excluded.source",
            [(int(season), code, row["name"], row["conference"], row["division"], source)
             for code, row in TEAMS.items()])


def load_teams(connection, season: int) -> dict:
    """The season's clubs from nba_teams: {code: {"name", "conference", "division"}}. Empty when none are seeded."""
    try:
        rows = connection.execute(
            "SELECT team, team_name, conference, division FROM nba_teams WHERE season=?", (int(season),)).fetchall()
    except sqlite3.OperationalError:  # no nba_teams table yet: the caller refuses the season, it is not a silent empty
        return {}
    return {row[0]: {"name": row[1] or row[0], "conference": row[2], "division": row[3]} for row in rows}


class NBAStandingsError(RuntimeError):
    """The derived table cannot be trusted. Callers must not present it as standings."""


def latest_season(connection) -> int | None:
    row = connection.execute(
        "SELECT MAX(season) FROM nba_schedule WHERE season_type='REG' "
        f"AND home_score IS NOT NULL AND away_score IS NOT NULL AND {NOT_KNOCKOUT_SQL}").fetchone()
    return int(row[0]) if row and row[0] is not None else None


def _streak(results: list[str]) -> str | None:
    if not results:
        return None
    last = results[-1]
    count = 0
    for result in reversed(results):
        if result != last:
            break
        count += 1
    return f"{last}{count}"


def _last_ten(results: list[str]) -> str | None:
    if not results:
        return None
    recent = results[-10:]
    return f"{recent.count('W')}-{recent.count('L')}"


def read_standings(connection, season: int | None = None, as_of: str | None = None,
                   expected_clubs: int = EXPECTED_CLUBS) -> dict | None:
    """The season's standings from scored regular-season games, or None when there are none.

    `as_of` (YYYY-MM-DD) counts only games played on or before that day. A checked table is returned as
    {"league", "season", "as_of", "teams"}; a table that fails a check raises NBAStandingsError.
    """
    if season is None:
        season = latest_season(connection)
        if season is None:
            return None
    sql = ("SELECT game_date, home_team, away_team, home_score, away_score FROM nba_schedule "
           f"WHERE season=? AND season_type='REG' AND home_score IS NOT NULL AND away_score IS NOT NULL "
           f"AND {NOT_KNOCKOUT_SQL}")
    params: list = [int(season)]
    if as_of:
        sql += " AND game_date <= ?"
        params.append(as_of)
    games = connection.execute(sql + " ORDER BY game_date, game_id", params).fetchall()
    if not games:
        return None
    clubs = load_teams(connection, season)
    if len(clubs) != expected_clubs:
        raise NBAStandingsError(f"nba_teams lists {len(clubs)} clubs for {season}, expected {expected_clubs}; "
                                f"run seed_nba_teams.py")
    table = {code: {"wins": 0, "losses": 0, "for": 0, "against": 0, "results": []} for code in clubs}
    for game in games:
        home, away = game["home_team"], game["away_team"]
        home_score, away_score = int(game["home_score"]), int(game["away_score"])
        if home_score == away_score:
            raise NBAStandingsError(f"{season}: {home} and {away} tied, which an NBA game cannot do")
        for team, mine, theirs in ((home, home_score, away_score), (away, away_score, home_score)):
            if team not in table:
                raise NBAStandingsError(f"{team} played in {season} but is not one of its clubs")
            record = table[team]
            record["for"] += mine
            record["against"] += theirs
            if mine > theirs:
                record["wins"] += 1
                record["results"].append("W")
            else:
                record["losses"] += 1
                record["results"].append("L")
    wins = sum(record["wins"] for record in table.values())
    losses = sum(record["losses"] for record in table.values())
    if wins != losses:
        raise NBAStandingsError(f"{season}: league wins {wins} do not equal league losses {losses}")
    teams = []
    for code, record in table.items():
        played = record["wins"] + record["losses"]
        win_pct = round(record["wins"] / played, 4) if played else None
        differential = round((record["for"] - record["against"]) / played, 2) if played else None
        teams.append({
            "abbrev": code,
            "name": clubs[code]["name"],
            "wins": record["wins"],
            "losses": record["losses"],
            "win_pct": win_pct,
            "differential": differential,
            "streak": _streak(record["results"]),
            "last10": _last_ten(record["results"]),
            "games_played": played,
        })
    teams.sort(key=lambda row: (-(row["win_pct"] if row["win_pct"] is not None else -1),
                                -(row["differential"] if row["differential"] is not None else -999),
                                row["abbrev"]))
    return {"league": "nba", "season": int(season), "as_of": as_of, "teams": teams}
