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
from typing import Optional


@dataclass(frozen=True)
class Result:
    week: int
    team: str
    opp: str
    pts_for: float
    pts_against: float
    home: bool
    tds_for: Optional[float] = None          # only for the net-touchdowns tiebreaker step
    tds_against: Optional[float] = None

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
    """teams_map: code -> (conference, division). games: rows (week, home, away, hs, as), optionally
    followed by (home_tds, away_tds) for the net-touchdowns tiebreaker.

    Only games with both scores and week <= through_week (if given) are used. Returns code -> Team.
    """
    teams = {code: Team(code, conf, div) for code, (conf, div) in teams_map.items()}
    for row in games:
        wk, home, away, hs, as_ = row[:5]
        htd, atd = (row[5], row[6]) if len(row) >= 7 else (None, None)
        if through_week is not None and wk > through_week:
            continue
        if home not in teams or away not in teams:
            raise KeyError("game references a team with no conference/division: %s/%s" % (home, away))
        hs, as_ = float(hs), float(as_)
        teams[home].results.append(Result(wk, home, away, hs, as_, True, htd, atd))
        teams[away].results.append(Result(wk, away, home, as_, hs, False, atd, htd))
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


# Strength of victory and of schedule, as the NFL defines them: the COMBINED won-lost-tied
# percentage of the teams beaten (victory) or played (schedule), each counted once per game, over
# their full records, ties as half a win (nfl.com "NFL Tiebreaking Procedures": "Tie games count
# as one-half win and one-half loss for both clubs"). An earlier version excluded the opponents'
# games against the team itself and counted ties as nothing in strength of victory; neither is in
# the NFL's definition.

def _combined_pct(codes, teams):
    w = l = t = 0
    for c in codes:
        cw, cl, ct = teams[c].record()
        w, l, t = w + cw, l + cl, t + ct
    n = w + l + t
    return (w + 0.5 * t) / n if n else 0.0


def strength_of_victory(team, teams):
    """Combined record of every team this team beat, once per win."""
    return _combined_pct([r.opp for r in team.results if r.outcome == "W"], teams)


def strength_of_schedule(team, teams):
    """Combined record of every opponent, once per game played."""
    return _combined_pct([r.opp for r in team.results], teams)
