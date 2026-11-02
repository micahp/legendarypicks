"""P2 weekly target share as the receiving base of the Dirichlet layer (research flag `--playcall-p2-weekly-shares`, off by default).

The estimate is the frozen candidate C2 (docs/research/SLC-V2-M6-FREEZE-2026-11-02.md), applied to the published weekly target
share in player_game_logs (source nflverse_weekly). A player's estimate is (sum of his earlier in-season target shares + K * prior)
/ (n + K), K = 4. The prior is his prior-season mean over at least 4 regular-season games, else the prior-season mean of his
position group (WR, TE, RB, FB, else OTHER). A player with no prior-season and no in-season sample has no estimate.

The estimate replaces the Dirichlet layer's receiving base shares for the game's two rosters. The Dirichlet concentration is still the
season fit, and game_shares still normalises the base over the eligible roster. A rostered player with no estimate keeps the
layer's floor weight, as before, and is counted. The SLC use is a research sensitivity for historical games, because the
publication time of weekly logs is not verified; the prospective lock uses the games present in the database at lock time.
"""
import collections
import datetime as dt
import os
import sqlite3
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..'))
from nfl_team_codes import to_nflverse_team_code  # noqa: E402

K = 4
MIN_PRIOR_GAMES = 4
POSITIONS = ('WR', 'TE', 'RB', 'FB')
MODEL_VERSION = 'p2-weekly-target-share-c2-frozen-2026-11-02'


def position_group(position):
    if position is None:
        return 'UNKNOWN'
    return position if position in POSITIONS else 'OTHER'


def logs(db, seasons):
    """(gsis, season, week, game_id, game_type, team, target_share) for every weekly log row of the seasons."""
    import json
    con = sqlite3.connect(f'file:{db}?mode=ro', uri=True, timeout=10)
    try:
        marks = ','.join('?' * len(seasons))
        rows = con.execute(
            f"SELECT source_player_key, season, game_id, game_type, team, stats FROM player_game_logs "
            f"WHERE league = 'nfl' AND source = 'nflverse_weekly' AND season IN ({marks})", list(seasons)).fetchall()
    finally:
        con.close()
    out = []
    for gsis, season, game_id, game_type, team, stats in rows:
        share = json.loads(stats).get('target_share')
        out.append((gsis, int(season), int(game_id.split('_')[1]), game_id, game_type,
                    to_nflverse_team_code(team), None if share is None else float(share)))
    return out


def positions(db):
    """{gsis: position} from the players table, the first position for each id."""
    from share_distributions import player_positions  # the same identity source the Dirichlet layer already uses
    return player_positions(db)


class Table:
    """Prior tables for one season, read once. `estimate(gsis, usable)` answers for one player and target game."""

    def __init__(self, rows, position_of, season):
        self.season = int(season)
        self.position_of = position_of
        prior = [r for r in rows if r[1] == self.season - 1 and r[4] == 'REG' and r[6] is not None]
        if not prior:
            raise ValueError(f'no prior-season weekly target shares before {season}')
        by_gsis, by_group = collections.defaultdict(list), collections.defaultdict(list)
        for gsis, _s, _w, _g, _t, _team, share in prior:
            by_gsis[gsis].append(share)
            by_group[self.group(gsis)].append(share)
        self.prior_by_gsis = {g: (len(v), sum(v) / len(v)) for g, v in by_gsis.items()}
        self.prior_pos = {grp: sum(v) / len(v) for grp, v in by_group.items()}
        self.in_season = collections.defaultdict(list)
        self.with_history = set(by_gsis)
        for r in rows:
            if r[1] == self.season and r[4] == 'REG' and r[6] is not None:
                self.in_season[r[0]].append(r)
                self.with_history.add(r[0])

    def group(self, gsis):
        return position_group(self.position_of.get(gsis))

    def estimate(self, gsis, usable):
        """The estimate for one player from his in-season rows that `usable(row)` accepts. None when he has no history."""
        if gsis not in self.with_history:
            return None
        earlier = [r for r in self.in_season.get(gsis, []) if usable(r)]
        prior_n, prior_value = self.prior_by_gsis.get(gsis, (0, None))
        if prior_n >= MIN_PRIOR_GAMES:
            prior, prior_source = prior_value, 'player_prior'
        else:
            group = self.group(gsis)
            prior = self.prior_pos.get(group, self.prior_pos.get('OTHER', 0.0))
            prior_source = 'position_mean'
        values = [r[6] for r in earlier]
        return {'estimate': (sum(values) + K * prior) / (len(values) + K), 'prior': prior, 'prior_source': prior_source,
                'games_used': len(values)}


def usable_prior_weeks(target_week):
    return lambda row: row[2] < int(target_week)


def usable_before_cutoff(kickoff_of, cutoff):
    """The frozen lagged rule (equality test only): kickoff plus 10 hours at or before the cutoff."""
    lag = dt.timedelta(hours=10)
    return lambda row: kickoff_of.get(row[3]) is not None and kickoff_of[row[3]] + lag <= cutoff


def base_for_rosters(table, rosters, usable_for, usage):
    """{(team, gsis): estimate} for every rostered player with an estimate, the Dirichlet base key. `rosters` is a list of
    (team, gsis); usable_for(row) builds the per-game usable predicate. Counts are added to `usage`."""
    base = {}
    for team, gsis in rosters:
        result = table.estimate(gsis, usable_for)
        if result is None:
            usage['no_history_floor'] += 1
            continue
        usage[f'prior_source_{result["prior_source"]}'] += 1
        usage['estimated'] += 1
        base[(team, gsis)] = result['estimate']
    return base
