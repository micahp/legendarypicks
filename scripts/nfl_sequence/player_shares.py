"""Per-play participant adapter: historical player shares of team targets and carries, for the frozen roster (SLC v1, research).

The adapter turns each player's share of his team's targets (pass plays) and carries (run plays) over the seasons before the cutoff
into weights, and the pre-event choice draws a target or ball carrier among the players on the frozen snapshot roster in
proportion to them. A rostered player with no prior-season sample keeps a small floor weight, so he is not excluded by a missing
history. A player who is not on the frozen roster is never chosen.

This is a first adapter. It uses each player's observed share, the quantity the research target-share and carry models
distribute over. It does not port those models' full distributions, which is open work.
"""
import sqlite3
from collections import Counter, defaultdict

FLOOR = 0.01  # the weight of a rostered player with no prior-season sample, before normalisation
TARGET_POSITIONS = ('WR', 'TE', 'RB')
CARRY_POSITIONS = ('RB', 'QB', 'WR', 'TE')
FIRST_SEASON = 2022  # the play window the rest of the reference uses


def load(db, cutoff_season):
    """{'receive': {(team, gsis): share}, 'carry': {(team, gsis): share}} from seasons before the cutoff, share within team."""
    seasons = range(FIRST_SEASON, int(cutoff_season))
    if not len(seasons):
        raise ValueError('no prior seasons before the cutoff')
    con = sqlite3.connect(f'file:{db}?mode=ro', uri=True, timeout=10)
    try:
        marks = ','.join('?' * len(seasons))
        receive = con.execute(
            f"SELECT posteam, receiver_player_id, COUNT(*) FROM nfl_pbp WHERE season IN ({marks}) AND week <= 18 "
            f"AND play_type = 'pass' AND receiver_player_id IS NOT NULL AND posteam IS NOT NULL "
            f"GROUP BY posteam, receiver_player_id", list(seasons)).fetchall()
        carry = con.execute(
            f"SELECT posteam, rusher_player_id, COUNT(*) FROM nfl_pbp WHERE season IN ({marks}) AND week <= 18 "
            f"AND play_type = 'run' AND rusher_player_id IS NOT NULL AND posteam IS NOT NULL "
            f"GROUP BY posteam, rusher_player_id", list(seasons)).fetchall()
    finally:
        con.close()
    return {'receive': _shares(receive), 'carry': _shares(carry), 'seasons': list(seasons)}


def _shares(rows):
    totals = Counter()
    for team, _player, count in rows:
        totals[team] += count
    return {(team, player): count / totals[team] for team, player, count in rows}


def weight(table, team, gsis, role):
    """The adapter weight for one rostered player: his prior share, or the floor when he has no prior sample."""
    return table[role].get((team, gsis), 0.0) + FLOOR


def eligible(players, positions):
    """Rostered players in the given positions, in the frozen snapshot's order (sorted, so the draw is reproducible)."""
    return sorted((p for p in players if p['pos_abb'] in positions), key=lambda p: (p['pos_rank'], p['gsis_id']))
