"""Database-derived NFL standings. Read-only: nothing is written and nothing is fetched.

The NHL standings are a published document, validated and stored as a snapshot when they are ingested. NFL has no
standings publisher in this database, but every regular-season score is in nfl_schedule. The table here is derived from
those scores and checked before it is returned:

- the season has exactly the clubs nfl_teams lists for it (32 by default);
- every scored game names two known clubs;
- league wins equal league losses, because each decided game has one winner and one loser.

A season with no scored regular-season game has no standings: read_standings returns None.

The rows carry the fields the story facts read (record, win percentage, streak, last ten, run differential), in the
shape ESPN's team strength rows use. Rank is the order by win percentage, then run differential, then abbreviation. ESPN
breaks win-percentage ties by its own order, so the two can differ where clubs are tied.
"""
from __future__ import annotations

EXPECTED_CLUBS = 32


class NFLStandingsError(RuntimeError):
    """The derived table cannot be trusted. Callers must not present it as standings."""


def latest_season(connection) -> int | None:
    row = connection.execute(
        "SELECT MAX(season) FROM nfl_schedule WHERE game_type='REG' "
        "AND home_score IS NOT NULL AND away_score IS NOT NULL").fetchone()
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
    return f"{recent.count('W')}-{recent.count('L')}" + (f"-{recent.count('T')}" if "T" in recent else "")


def read_standings(connection, season: int | None = None, as_of: str | None = None,
                   expected_clubs: int = EXPECTED_CLUBS) -> dict | None:
    """The season's standings from scored regular-season games, or None when there are none.

    `as_of` (YYYY-MM-DD) counts only games played on or before that day. A checked table is returned as
    {"league", "season", "as_of", "teams"}; a table that fails a check raises NFLStandingsError.
    """
    if season is None:
        season = latest_season(connection)
        if season is None:
            return None
    sql = ("SELECT week, gameday, home_team, away_team, home_score, away_score FROM nfl_schedule "
           "WHERE season=? AND game_type='REG' AND home_score IS NOT NULL AND away_score IS NOT NULL")
    params: list = [int(season)]
    if as_of:
        sql += " AND gameday <= ?"
        params.append(as_of)
    games = connection.execute(sql + " ORDER BY week, gameday, home_team", params).fetchall()
    if not games:
        return None
    clubs = {row["team"]: row for row in connection.execute(
        "SELECT team, conference, division, team_name FROM nfl_teams WHERE season=?", (int(season),)).fetchall()}
    if len(clubs) != expected_clubs:
        raise NFLStandingsError(f"nfl_teams has {len(clubs)} clubs for {season}, expected {expected_clubs}")
    table = {code: {"wins": 0, "losses": 0, "ties": 0, "for": 0, "against": 0, "results": []} for code in clubs}
    for game in games:
        home, away = game["home_team"], game["away_team"]
        home_score, away_score = int(game["home_score"]), int(game["away_score"])
        for team, mine, theirs in ((home, home_score, away_score), (away, away_score, home_score)):
            if team not in table:
                raise NFLStandingsError(f"{team} played in {season} but is not one of its clubs")
            record = table[team]
            record["for"] += mine
            record["against"] += theirs
            if mine > theirs:
                record["wins"] += 1
                record["results"].append("W")
            elif mine < theirs:
                record["losses"] += 1
                record["results"].append("L")
            else:
                record["ties"] += 1
                record["results"].append("T")
    wins = sum(record["wins"] for record in table.values())
    losses = sum(record["losses"] for record in table.values())
    if wins != losses:
        raise NFLStandingsError(f"{season}: league wins {wins} do not equal league losses {losses}")
    teams = []
    for code, record in table.items():
        played = record["wins"] + record["losses"] + record["ties"]
        win_pct = round((record["wins"] + 0.5 * record["ties"]) / played, 4) if played else None
        differential = round((record["for"] - record["against"]) / played, 2) if played else None
        tie_text = f"-{record['ties']}" if record["ties"] else ""
        teams.append({
            "abbrev": code,
            "name": clubs[code]["team_name"] or code,
            "conference": clubs[code]["conference"],
            "division": clubs[code]["division"],
            "wins": record["wins"],
            "losses": record["losses"],
            "ties": record["ties"],
            "record": f"{record['wins']}-{record['losses']}{tie_text}",
            "win_pct": win_pct,
            "differential": differential,
            "streak": _streak(record["results"]),
            "last10": _last_ten(record["results"]),
            "games_played": played,
        })
    teams.sort(key=lambda row: (-(row["win_pct"] if row["win_pct"] is not None else -1),
                                -(row["differential"] if row["differential"] is not None else -999),
                                row["abbrev"]))
    return {"league": "nfl", "season": int(season), "as_of": as_of, "teams": teams}
