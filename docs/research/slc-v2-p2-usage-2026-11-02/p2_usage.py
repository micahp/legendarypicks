"""P2: player usage component (SLC v2 Milestone 3), from the published weekly player logs.

A forecast for player p in game t uses only that player's logs from earlier games of the same season that are usable at the
final horizon of t. A game is usable when its kickoff plus the availability lag is at or before the cutoff. The lag is
AVAILABILITY_LAG_HOURS = 10. Publication timing for the weekly logs is not verified (see the availability matrix), so this
lag is an assumption and is recorded in every manifest.

Estimate: shrink the observed target share toward a prior with K pseudo-games. The prior is the player's own prior-season mean
when they have at least MIN_PRIOR_GAMES prior-season games, otherwise the prior-season mean of their position group.

Baseline (frozen): the prior-season position mean, with no player information.
"""
import collections
import csv
import datetime as dt
import json
import os
import sqlite3
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..', 'slc-v2-depth-adapter-2026-11-02'))
sys.path.insert(0, os.path.join(HERE, '..', 'pbv1-sampler-2026-11-02'))
import depth_adapter as da  # noqa: E402
from pbv1_sampler import game_bootstrap_ci  # noqa: E402,F401

DB = 'file:/root/legendarypicks/backend/data/picks.dev.db?mode=ro'
PLAYERS = '/root/gridiron-playbooks-research/data/raw/players.csv'
AVAILABILITY_LAG_HOURS = 10
MIN_PRIOR_GAMES = 4
K = 4
POSITIONS = ('WR', 'TE', 'RB', 'FB')


def usable(game, cutoff):
    return game['kickoff'] + dt.timedelta(hours=AVAILABILITY_LAG_HOURS) <= cutoff


def shrunk_mean(values, prior, k):
    return (sum(values) + k * prior) / (len(values) + k)


def position_group(position):
    if position is None:
        return 'UNKNOWN'
    return position if position in POSITIONS else 'OTHER'


def player_feature(history, target, prior_by_gsis, prior_pos, position, k=K, metric='target_share'):
    cutoff = target['kickoff'] - dt.timedelta(hours=1)
    rows = [g for g in history if g['gsis'] == target['gsis'] and g['season'] == target['season'] and usable(g, cutoff)]
    observed = [g for g in rows if g[metric] is not None]
    nulls = len(rows) - len(observed)
    prior_n, prior_value = prior_by_gsis.get(target['gsis'], (0, None))
    if prior_n >= MIN_PRIOR_GAMES:
        prior_source, prior = 'player_prior', prior_value
    else:
        prior_source, prior = 'position_mean', prior_pos
    values = [g[metric] for g in observed]
    return {
        'metric': metric,
        'gsis': target['gsis'], 'season': target['season'], 'game_id': target['game_id'],
        'games_used': len(values), 'game_ids_used': [g['game_id'] for g in observed],
        'null_target_share_games': nulls,
        'mean_observed': (sum(values) / len(values)) if values else None,
        'prior_source': prior_source, 'prior_value': prior,
        'estimate': shrunk_mean(values, prior, k), 'cutoff': cutoff,
    }


def position_group_of(gsis, positions):
    return position_group(positions.get(gsis))


def load_positions():
    positions = {}
    with open(PLAYERS, newline='', encoding='utf-8') as handle:
        for record in csv.DictReader(handle):
            if record['gsis_id']:
                positions[record['gsis_id']] = record['position'] or None
    return positions


def load_kickoffs():
    con = sqlite3.connect(DB, uri=True)
    try:
        rows = con.execute("select game_id, gameday, gametime from nfl_schedule where game_type = 'REG'").fetchall()
    finally:
        con.close()
    kickoffs = {}
    for game_id, gameday, gametime in rows:
        if gametime:
            kickoffs[game_id] = da.game_horizons(gameday, gametime)[1] + dt.timedelta(hours=1)
    return kickoffs


def load_logs(seasons):
    con = sqlite3.connect(DB, uri=True)
    try:
        query = ("select source_player_key, season, game_id, game_type, team, opponent, stats from player_game_logs "
                 "where league = 'nfl' and source = 'nflverse_weekly' and season in ({})").format(
            ','.join('?' * len(seasons)))
        records = con.execute(query, tuple(seasons)).fetchall()
    finally:
        con.close()
    logs = []
    for gsis, season, game_id, game_type, team, opponent, stats in records:
        data = json.loads(stats)
        logs.append({'gsis': gsis, 'season': season, 'game_id': game_id, 'game_type': game_type, 'team': team,
                     'opponent': opponent, 'target_share': data.get('target_share'), 'off_pct': data.get('off_pct'),
                     'targets': data.get('targets'), 'carries': data.get('carries')})
    return logs


def attach_kickoffs(logs, kickoffs):
    missing = collections.Counter()
    kept = []
    for row in logs:
        kickoff = kickoffs.get(row['game_id'])
        if kickoff is None:
            missing[row['game_id']] += 1
            continue
        kept.append(dict(row, kickoff=kickoff))
    return kept, missing
