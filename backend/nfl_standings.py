"""nfl_standings.py -- regular-season standings and the records tiebreakers need (SPEC A, 5.2-5.3).

Pure given rows; the database functions only read.

Team membership: conference and division come from `nfl_teams` (season 2026, A1). Using that map
for 2024 and 2025 is an assumption, and it is checked: the schedule's own `div_game` flag agrees
with the 2026 division map on every 2024 and 2025 regular-season game (0 disagreements). A season
with a disagreement must not use this map.

Ties are counted as half a win for the strength measures and as ties in the records.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Result:
    week: int
    team: str
    opp: str
    pts_for: float
    pts_against: float
    home: bool

    @property
    def outcome(self):
        if self.pts_for > self.pts_against:
            return "W"
        if self.pts_for < self.pts_against:
            return "L"
        return "T"


@dataclass
class Team:
    code: str
    conference: str
    division: str
    results: list = field(default_factory=list)

    def record(self, subset=None):
        rs = self.results if subset is None else [r for r in self.results if subset(r)]
        w = sum(1 for r in rs if r.outcome == "W")
        l = sum(1 for r in rs if r.outcome == "L")
        t = sum(1 for r in rs if r.outcome == "T")
        return w, l, t

    @property
    def wins(self):
        return self.record()[0]

    @property
    def losses(self):
        return self.record()[1]

    @property
    def ties(self):
        return self.record()[2]

    @property
    def pct(self):
        w, l, t = self.record()
        n = w + l + t
        return (w + 0.5 * t) / n if n else 0.0


def conference_of(division_name):
    """'NFC East' -> 'NFC'."""
    return division_name.split()[0]


def build(teams_map, games, through_week=None):
    """teams_map: code -> (conference, division). games: rows (week, home, away, hs, as).

    Only games with both scores and week <= through_week (if given) are used. Returns code -> Team.
    """
    teams = {code: Team(code, conf, div) for code, (conf, div) in teams_map.items()}
    for wk, home, away, hs, as_ in games:
        if through_week is not None and wk > through_week:
            continue
        if home not in teams or away not in teams:
            raise KeyError("game references a team with no conference/division: %s/%s" % (home, away))
        hs, as_ = float(hs), float(as_)
        teams[home].results.append(Result(wk, home, away, hs, as_, True))
        teams[away].results.append(Result(wk, away, home, as_, hs, False))
    return teams


def division_record(team, teams):
    return team.record(lambda r: teams[r.opp].division == team.division)


def conference_record(team, teams):
    return team.record(lambda r: teams[r.opp].conference == team.conference)


def head_to_head(a, b):
    """Record of team a against team b (a's results vs b). None if they did not play."""
    rs = [r for r in a.results if r.opp == b.code]
    if not rs:
        return None
    w = sum(1 for r in rs if r.outcome == "W")
    l = sum(1 for r in rs if r.outcome == "L")
    t = sum(1 for r in rs if r.outcome == "T")
    return w, l, t


def opponents(team):
    return {r.opp for r in team.results}


def common_opponents(a, b):
    return opponents(a) & opponents(b)


def common_games_record(a, b, teams, minimum=4):
    """Record of a in games against opponents both a and b played. None if fewer than `minimum`
    common opponents (the NFL requires four for this tiebreaker)."""
    common = common_opponents(a, b)
    if len(common) < minimum:
        return None
    return a.record(lambda r: r.opp in common)


def strength_of_victory(team, teams):
    """Combined winning percentage of the teams this team beat, ties not counted as wins.
    Games those opponents played against this team are excluded from their records."""
    beaten = [r.opp for r in team.results if r.outcome == "W"]
    if not beaten:
        return 0.0
    return sum(_pct_excluding(teams[o], team.code, ties_as_half=False) for o in beaten) / len(beaten)


def strength_of_schedule(team, teams):
    """Combined winning percentage of all opponents, games against this team excluded."""
    opps = [r.opp for r in team.results]
    if not opps:
        return 0.0
    return sum(_pct_excluding(teams[o], team.code, ties_as_half=True) for o in opps) / len(opps)


def _pct_excluding(opponent, excluded_code, ties_as_half):
    rs = [r for r in opponent.results if r.opp != excluded_code]
    w = sum(1 for r in rs if r.outcome == "W")
    l = sum(1 for r in rs if r.outcome == "L")
    t = sum(1 for r in rs if r.outcome == "T")
    if ties_as_half:
        n = w + l + t
        return (w + 0.5 * t) / n if n else 0.0
    return w / (w + l) if (w + l) else 0.0
