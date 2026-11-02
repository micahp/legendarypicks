"""P1 team pass share for the SLC dropback rate (research flag `--playcall-p1-pass-share`, off by default).

The estimate is the frozen candidate C1 (docs/research/SLC-V2-M6-FREEZE-2026-11-02.md): a team's pass share per game is
(sum of its earlier usable pass shares this season + K * prior) / (n + K), K = 4. The prior is the head coach's prior-season mean
over at least 8 team-games, else the team's prior-season mean, else the league's. The coach is carried from the team's latest
usable game this season, else from its last game of the prior season. The target game's own schedule row never supplies the coach.

The SLC use is a log-odds shift: the estimate's deviation from its prior, added to the dropback rate with the score-state
splits' adjustment, so the artifact's situation rates are kept and only the team's deviation moves. A team with no usable game
this season has no shift, and every such case is counted.

Which games are usable is a rule passed in by the caller:
- `prior_weeks` (the SLC research default): same-season games in earlier weeks. Play-by-play publication time is not verified, so
  this is a labelled sensitivity for historical games, not a strict as-of result (SLC-V2-TIME-SAFE-AVAILABILITY-MATRIX).
- `lagged_kickoff` (the frozen rule, used by the equality test only): kickoff plus 10 hours at or before the target kickoff minus
  one hour. The 10-hour lag is an assumption, not a verified publication time.
"""
import collections
import datetime as dt
import math
import os
import sqlite3
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..'))
from nfl_team_codes import to_nflverse_team_code  # noqa: E402

K = 4
MIN_COACH_GAMES = 8
REG_WEEKS = 18
LAG = dt.timedelta(hours=10)
MODEL_VERSION = 'p1-team-pass-share-c1-frozen-2026-11-02'
PROB_CLAMP = 1e-6


def log_odds(p):
    p = min(max(p, PROB_CLAMP), 1.0 - PROB_CLAMP)
    return math.log(p / (1.0 - p))


def team_games(db, seasons):
    """(season, week, game_id, team, plays, passes) per team-game with run or pass plays, regular-season weeks only."""
    con = sqlite3.connect(f'file:{db}?mode=ro', uri=True, timeout=10)
    try:
        marks = ','.join('?' * len(seasons))
        rows = con.execute(
            f"SELECT season, week, game_id, posteam, COUNT(*), SUM(CASE WHEN play_type = 'pass' THEN 1 ELSE 0 END) "
            f"FROM nfl_pbp WHERE season IN ({marks}) AND week <= {REG_WEEKS} AND posteam IS NOT NULL "
            f"AND play_type IN ('run', 'pass') GROUP BY season, week, game_id, posteam", list(seasons)).fetchall()
    finally:
        con.close()
    return [(int(s), int(w), g, to_nflverse_team_code(t), int(n), int(p)) for s, w, g, t, n, p in rows]


def _nth_sunday(year, month, n):
    first = dt.date(year, month, 1)
    return first + dt.timedelta(days=(6 - first.weekday()) % 7 + 7 * (n - 1))


def kickoff_utc(gameday, gametime):
    """Kickoff in UTC from the schedule's Eastern local date and time, with the US daylight-saving rule (second Sunday of March
    to first Sunday of November). Matches docs/research/slc-v2-depth-adapter-2026-11-02/depth_adapter.py game_horizons, which the
    equality test checks on every 2025 game."""
    day = dt.date.fromisoformat(gameday)
    hour, minute = (int(part) for part in gametime.split(':')[:2])
    daylight = _nth_sunday(day.year, 3, 2) <= day < _nth_sunday(day.year, 11, 1)
    offset = dt.timedelta(hours=-4) if daylight else dt.timedelta(hours=-5)
    local = dt.datetime(day.year, day.month, day.day, hour, minute, tzinfo=dt.timezone(offset))
    return local.astimezone(dt.timezone.utc).replace(tzinfo=None)


def schedule(db, seasons):
    """{game_id: (kickoff_utc_or_None, {team: coach})} for regular-season schedule rows, team codes in nflverse form."""
    con = sqlite3.connect(f'file:{db}?mode=ro', uri=True, timeout=10)
    try:
        marks = ','.join('?' * len(seasons))
        rows = con.execute(
            f"SELECT game_id, gameday, gametime, home_team, away_team, home_coach, away_coach FROM nfl_schedule "
            f"WHERE game_type = 'REG' AND season IN ({marks})", list(seasons)).fetchall()
    finally:
        con.close()
    out = {}
    for game_id, gameday, gametime, home, away, home_coach, away_coach in rows:
        kickoff = kickoff_utc(gameday, gametime) if gametime else None
        out[game_id] = (kickoff, {to_nflverse_team_code(home): home_coach, to_nflverse_team_code(away): away_coach})
    return out


class Table:
    """The prior tables for one season, read once; `estimate` answers for one team and target game."""

    def __init__(self, games, sched, season):
        self.season = int(season)
        self.sched = sched
        prior_rows = [r for r in games if r[0] == self.season - 1]
        if not prior_rows:
            raise ValueError(f'no prior-season team-games before {season}: nothing to set a team prior from')
        self.games = [r for r in games if r[0] == self.season]
        by_team, by_coach, last_coach, values = collections.defaultdict(list), collections.defaultdict(list), {}, []
        for s, w, g, t, n, p in sorted(prior_rows, key=lambda r: (r[1], r[2])):
            share = p / n
            values.append(share)
            by_team[t].append(share)
            coach = sched.get(g, (None, {}))[1].get(t)
            if coach:
                by_coach[coach].append(share)
                last_coach[t] = coach
        self.league = sum(values) / len(values)
        self.coach_prior = {c: (len(v), sum(v) / len(v)) for c, v in by_coach.items()}
        self.team_prior = {t: sum(v) / len(v) for t, v in by_team.items()}
        self.last_coach = last_coach

    def estimate(self, team, target_week, target_kickoff, usable, kickoff_of=None):
        """The estimate for the team's target game, from its season games that `usable(row)` accepts.

        Returns None when the team has no usable game this season. Otherwise a dict with the estimate, the prior, the sources
        and the shift (log-odds of the estimate minus log-odds of the prior)."""
        earlier = sorted([r for r in self.games if r[3] == team and usable(r, target_week, target_kickoff, kickoff_of)],
                         key=lambda r: (r[1], r[2]))
        if not earlier:
            return None
        latest = earlier[-1]
        coach = self.sched.get(latest[2], (None, {}))[1].get(team)
        coach_source = 'usable_game'
        if not coach:
            coach = self.last_coach.get(team)
            coach_source = 'prior_season_last' if coach else 'none'
        if coach and coach in self.coach_prior and self.coach_prior[coach][0] >= MIN_COACH_GAMES:
            prior, prior_source = self.coach_prior[coach][1], 'coach_era'
        elif team in self.team_prior:
            prior, prior_source = self.team_prior[team], 'team_prior'
        else:
            prior, prior_source = self.league, 'league_prior'
        values = [p / n for _s, _w, _g, _t, n, p in earlier]
        estimate = (sum(values) + K * prior) / (len(values) + K)
        return {'estimate': estimate, 'prior': prior, 'prior_source': prior_source, 'coach': coach,
                'coach_source': coach_source, 'games_used': len(values),
                'shift': log_odds(estimate) - log_odds(prior)}


def usable_prior_weeks(row, target_week, target_kickoff, kickoff_of):
    return row[1] < int(target_week)


def usable_lagged_kickoff(row, target_week, target_kickoff, kickoff_of):
    kickoff = kickoff_of.get(row[2])
    return kickoff is not None and kickoff + LAG <= target_kickoff - dt.timedelta(hours=1)
