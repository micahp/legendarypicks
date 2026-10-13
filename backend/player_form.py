"""player_form.py — recent player form from our own game logs, not from the prop board.

generate_game_story's form section was gated on `props`: it found the players with the most
prop markets for a game, then read their last five logs. That made sense when props were
the first real data we had. They are no longer the only data, and the gate now costs more
than it gives — dev holds 701 MLB prop games and 15 MLS ones, and none at all for the NBA,
NFL or NHL, so every story in those leagues was written with an empty form section while
232,669 player game logs sat unread one table over.

This reads the logs directly. `player_game_logs.team` is populated for every league except
UFC (which has no team), so the two clubs in a matchup are enough to find their players.

Two things it refuses to do:

  Guess at a headline stat. Each league declares its own, because "the number that says
  a soccer player is in form" is goals and "the number for an NBA player" is points, and
  a league with no entry here gets no lines rather than a column picked by shape.

  Pass off an old season as current. MLS logs stop at 2025 while the 2026 Leagues Cup is
  being played, so the season is stated in every line. A writer told "2025" cannot
  honestly call it recent form; a writer told nothing will.
"""
import json
import sqlite3
from contextlib import closing

# The stat each league is read on, and the label to print. First entry ranks the players;
# the rest ride along because a line with only one number reads thinner than it is.
HEADLINE_STATS = {
    "nba":   [("PTS", "points"), ("REB", "rebounds"), ("AST", "assists")],
    "nhl":   [("points", "points"), ("goals", "goals"), ("sog", "shots on goal")],
    "mlb":   [("H", "hits"), ("RBI", "RBI"), ("HR", "home runs")],
    "nfl":   [("fpts_ppr", "PPR points"), ("rush_yds", "rush yards"), ("rec_yds", "rec yards")],
    "ncaaf": [("rush_yds", "rush yards"), ("rec_yds", "rec yards"), ("rec", "receptions")],
    "mls":   [("goals", "goals"), ("shots", "shots"), ("assists", "assists")],
    "wc":    [("goals", "goals"), ("shots", "shots"), ("assists", "assists")],
    "lcup":  [("goals", "goals"), ("shots", "shots"), ("assists", "assists")],
}

_MIN_GAMES = 3       # fewer than this is not form, it is a sample
_PER_TEAM = 3
_RECENT = 5
# A gap this wide between a player's newest log and their own team's newest log is
# past a normal week off (soccer's longest scheduled gaps run 2-3 weeks for
# internationals) and into "no longer on this roster" territory -- transferred,
# long-term injury, or released. 21 days, not 35: the Cuypers case was a 4-month
# gap while teammates kept playing weekly, so this only needs to clear one normal
# international window, not guess at the exact length of every possible absence.
_STALE_DAYS = 21


def _parse_date(s):
    import datetime
    return datetime.date.fromisoformat(str(s)[:10])


def _today():
    import datetime
    return datetime.date.today()


def lines(league, teams, db_path=None, con=None, per_team=_PER_TEAM, as_of=None):
    """-> list of grounding strings, one per player. Empty for a league with no declared
    headline stat, no logs, or no team column. Never raises.

    `as_of`: the date to judge "current" against for the transfer/injury staleness
    filter in `_team_lines` -- the story's own game date when the caller has one,
    real today otherwise. Threading the game date through (rather than always
    reading the wall clock) is what makes this testable with fixed fixture dates,
    and is also more correct: a story pre-generated days before kickoff should
    judge staleness against the game it is written for, not the moment the batch
    job happened to run.
    """
    league = (league or "").lower()
    stats = HEADLINE_STATS.get(league)
    if not stats or not teams:
        return []
    if as_of is None:
        as_of = _today()
    try:
        owned = con is None
        if owned:
            con = sqlite3.connect(db_path)
            con.row_factory = sqlite3.Row
        try:
            season = _latest_season(con, league)
            if season is None:
                return []
            out = []
            for team in teams:
                out.extend(_team_lines(con, league, team, season, stats, per_team, as_of))
            return out
        finally:
            if owned:
                con.close()
    except Exception:
        return []


def _latest_season(con, league):
    row = con.execute("SELECT MAX(season) AS s FROM player_game_logs WHERE league=?",
                      (league,)).fetchone()
    return row["s"] if row and row["s"] is not None else None


def _team_lines(con, league, team, season, stats, per_team, as_of):
    """The team's most productive players on its headline stat, with their last five."""
    rows = con.execute(
        """SELECT l.player_id, p.name, l.stats, l.game_date, l.game_no
           FROM player_game_logs l LEFT JOIN players p ON p.id = l.player_id
           WHERE l.league=? AND l.season=? AND l.team=?
           ORDER BY COALESCE(l.game_date,'') DESC, CAST(l.game_no AS INTEGER) DESC""",
        (league, season, team)).fetchall()

    key, _label = stats[0]
    by_player = {}
    for r in rows:
        bucket = by_player.setdefault(r["player_id"], {"name": r["name"], "logs": [], "latest": None})
        if bucket["latest"] is None:
            bucket["latest"] = r["game_date"]  # rows are DESC, so the first hit is the newest
        if len(bucket["logs"]) < _RECENT:
            bucket["logs"].append(r["stats"])

    # A player transferred out (or on long-term injury) does not stop having played well
    # for this team -- their last five logs are real -- but naming them in a CURRENT
    # preview reads as if they are still on the roster. Reported 2026-08-30: a Chicago
    # Fire preview cited Hugo Cuypers, who had already been transferred to Monterrey;
    # his last MLS game log is from 2026-04-26, four months before the story ran, and
    # every other Chicago player's newest log was ALSO April 26 -- the whole team's
    # capture had stalled, not just his. A gap measured against teammates would have
    # missed this exact case (everyone tied at zero days apart), so this measures
    # against the real calendar: if a player's newest log is not within `_STALE_DAYS` of
    # today, they are not safe to call "in form" right now, whether that is because they
    # left or because our own capture for this team stopped. No roster-membership feed
    # is wired to this reader (`roster_snapshots` exists in the schema but has never been
    # published for mls) -- a player's own log recency is the only signal already in hand.
    def _is_current(info):
        if not info["latest"]:
            return True  # no date to compare against -- do not invent a reason to exclude
        try:
            gap = (as_of - _parse_date(info["latest"])).days
        except Exception:
            return True
        return gap <= _STALE_DAYS

    ranked = []
    for pid, info in by_player.items():
        values = _values(info["logs"], key)
        if len(values) < _MIN_GAMES or not info["name"] or not _is_current(info):
            continue
        ranked.append((sum(values) / len(values), pid, info))
    ranked.sort(key=lambda x: x[0], reverse=True)

    out = []
    for _avg, _pid, info in ranked[:per_team]:
        parts = []
        for key_i, label in stats:
            values = _values(info["logs"], key_i)
            # A secondary stat only rides along when it covers the same games. Otherwise a
            # quarterback's "rush yards [2]" sits beside five PPR scores and reads as a
            # five-game trend that collapsed, when it is one game that recorded the field.
            if len(values) >= _MIN_GAMES:
                parts.append(f"{label} {_fmt(values)}")
        if parts:
            out.append(f"{info['name']} ({team}, {season} logs, last {len(info['logs'])} "
                       f"games, most recent first): " + "; ".join(parts) + ".")
    return out


def _values(raw_logs, key):
    out = []
    for raw in raw_logs:
        try:
            v = json.loads(raw).get(key)
        except Exception:
            v = None
        if isinstance(v, (int, float)):
            out.append(v)
    return out


def _fmt(values):
    return "[" + ", ".join(f"{v:g}" for v in values) + "]"
