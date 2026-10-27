"""Attach historical splits to the frozen 2026 Week 8 games, using only games completed before the simulation cutoff.

This is context for display and review. It does not feed the simulator, and it does not change any frozen simulation
run, availability snapshot, or game-information snapshot. Every block is marked used_by_model: false.

Each game carries, for each team:
  calendar     the team's regular-season games on the same weekday, and in the same kickoff window (Eastern), and in the
               same home or away role, with the record and outcome measures
  weather      for outdoor games, the team's outdoor games with observed wind at or above 15 mph and below 15 mph, beside
               the frozen forecast wind for this game
  qb1          the expected QB1 from the frozen full-depth roster, after the frozen availability decision (the QB2 when
               the QB1 is excluded), and the team's results in the games where he was the identified expected starter
               and played, where he was the identified starter and did not play, and where someone else was
Officials are not assigned for Week 8 in the stored data, so no official split is attached and the output says so.

Usage: python3 week8_context.py --out PATH
"""
import argparse
import hashlib
import json
import os
import re
from datetime import datetime

import layer
import splits_query as q

DEFAULT_LAYER = q.DEFAULT_LAYER
GAMES_DIR = '/tmp/claude-0/-root/4a715766-ff4b-4980-99e5-dc209eaac7d4/scratchpad/w08/games'
FORECASTS = '/root/lp-snapshots/nfl-game-info/2026/week08/2026-10-27T1900Z/forecasts.json'
AVAILABILITY = '/root/lp-snapshots/nfl/nfl-2026-w08-20261027T182023Z-c9ad71877b.json'
SEASONS = (2010, 2026)
WIND_THRESHOLD = 15


def sha256_file(path):
    with open(path, 'rb') as handle:
        return hashlib.sha256(handle.read()).hexdigest()


def parse_wind(text):
    """The largest mph figure in a forecast wind string such as '5 mph' or '10 to 15 mph'."""
    numbers = [float(n) for n in re.findall(r'\d+(?:\.\d+)?', text or '')]
    return max(numbers) if numbers else None


def clock_hhmm(kickoff_local):
    """'2026-11-01 13:00 EST' -> '13:00'."""
    return kickoff_local.split()[1]


def roof_class(roof):
    """The layer's roof vocabulary, from the forecast file's labels: 'Open' is open-air, so it is 'outdoors'."""
    text = (roof or '').lower()
    if text == 'open':
        return 'outdoors'
    if text in ('fixed dome', 'dome'):
        return 'dome'
    if text == 'closed':
        return 'closed'
    return 'retractable_or_unknown'


def expected_qb1(depth, availability_rows, team_side):
    """(player, reason) for the QB the simulator would start: QB1 if available, else the best available QB backup.

    depth is the frozen full-depth roster. Its QB1 carries starter True, and its backups carry starter False.
    """
    players = depth['rosters'][team_side]['players']
    qbs = sorted((p for p in players if p.get('pos_abb') == 'QB'), key=lambda p: p['pos_rank'])
    qb1 = next((p for p in qbs if p.get('pos_rank') == 1 and p.get('starter')), None)
    if qb1 is None:
        return None, 'no starting QB1 in the frozen full-depth roster'
    row = availability_rows.get(qb1['gsis_id'])
    if row is None or row.get('include'):
        return qb1, 'frozen QB1 kept by availability'
    backup = next((p for p in qbs if p['pos_rank'] > 1 and availability_rows.get(p['gsis_id'], {}).get('include')),
                  None)
    if backup is None:
        return None, 'frozen QB1 excluded and no available QB backup'
    return backup, f"frozen QB1 excluded ({row.get('decision')}); QB backup takes the role"


SUMMARY_KEYS = ('n', 'wins', 'losses', 'ties', 'win_pct', 'win_pct_wilson95', 'warning', 'seasons', 'game_ids',
                'shrinkage', 'margin', 'yards_per_play', 'epa_per_play', 'success_rate', 'points_for',
                'points_against', 'penalties', 'turnovers')


def summarize(con, team, filters):
    result = q.team_splits(con, team, filters, baselines=False)
    return {'split': {k: result['split'][k] for k in SUMMARY_KEYS},
            'missing_classification': result['missing_classification']}


def assert_before_cutoff(con, game_ids, as_of):
    """Every historical game used must have kicked off before the cutoff. Chunked to stay under SQLite's limits."""
    game_ids = list(game_ids)
    for start in range(0, len(game_ids), 500):
        chunk = game_ids[start:start + 500]
        marks = ','.join('?' * len(chunk))
        late = con.execute(f'select game_id, kickoff_utc from team_game where game_id in ({marks}) '
                           'and kickoff_utc >= ?', [*chunk, as_of]).fetchall()
        if late:
            raise ValueError(f'historical games at or after the cutoff {as_of}: {late[:3]}')


def build_game(con, game, starters, availability_rows, as_of, forecast_game):
    away, home = game['away'], game['home']
    weekday = forecast_game['weekday_local']
    window = layer.window_of(layer.minutes_of(clock_hhmm(forecast_game['kickoff_local'])))
    roof = roof_class(forecast_game.get('roof'))
    frozen = forecast_game.get('forecast') or {}
    wind = parse_wind(frozen.get('wind'))
    block = {'game_id': game['game_id'], 'sim_status': game['status'], 'kickoff_utc': game['kickoff_utc'],
             'weekday': weekday, 'window_et': window, 'roof': roof, 'venue': forecast_game.get('venue'),
             'forecast': {'wind_mph_max': wind, 'temperature_f': frozen.get('temperature_f'),
                          'available': bool(frozen),
                          'source': 'frozen NWS forecast in the 2026-10-27 game-information snapshot'},
             'teams': {}}
    for side, team in (('away', away), ('home', home)):
        base = {'seasons': SEASONS, 'game_type': 'REG'}
        calendar = {
            'weekday': summarize(con, team, {**base, 'weekday': [weekday]}),
            'weekday_window': summarize(con, team, {**base, 'weekday': [weekday], 'window_et': [window]}),
            'weekday_window_role': summarize(con, team, {**base, 'weekday': [weekday], 'window_et': [window],
                                                         'home_away': 'home' if side == 'home' else 'away'}),
        }
        team_block = {'calendar': calendar}
        if roof == 'outdoors':
            team_block['weather_outdoor'] = {
                'wind_15_plus': summarize(con, team, {**base, 'roof': ['outdoors'], 'wind_min': WIND_THRESHOLD}),
                'wind_under_15': summarize(con, team, {**base, 'roof': ['outdoors'], 'wind_max': WIND_THRESHOLD - 0.01}),
            }
        qb, reason = expected_qb1(starters, availability_rows, side)
        if qb is None:
            team_block['qb1'] = {'status': 'not_identified', 'reason': reason}
        else:
            def as_qb1(mode):
                return summarize(con, team, {**base, 'expected_role': {'role': 'QB', 'gsis': qb['gsis_id'],
                                                                       'mode': mode}})
            team_block['qb1'] = {'gsis_id': qb['gsis_id'], 'name': qb.get('player_name'), 'reason': reason,
                                 'expected_qb1_available': as_qb1('available'),
                                 'expected_qb1_unavailable': as_qb1('unavailable'),
                                 'other_expected_qb1': as_qb1('other')}
        team_block['officials'] = 'not assigned for this game in the stored data'
        block['teams'][side] = team_block
        for group in calendar.values():
            assert_before_cutoff(con, group['split']['game_ids'], as_of)
        for key in ('wind_15_plus', 'wind_under_15'):
            if roof == 'outdoors':
                assert_before_cutoff(con, team_block['weather_outdoor'][key]['split']['game_ids'], as_of)
        if qb is not None:
            for key in ('expected_qb1_available', 'expected_qb1_unavailable', 'other_expected_qb1'):
                assert_before_cutoff(con, team_block['qb1'][key]['split']['game_ids'], as_of)
    return block


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--layer', default=DEFAULT_LAYER)
    ap.add_argument('--out', required=True)
    args = ap.parse_args()
    if os.path.exists(args.out):
        raise SystemExit(f'refusing to overwrite {args.out}')
    manifest = json.load(open(os.path.join(GAMES_DIR, 'manifest.json')))
    as_of = manifest['as_of_utc']
    forecasts = json.load(open(FORECASTS))['games']
    if isinstance(forecasts, dict):
        forecast_by_id = forecasts
    else:
        forecast_by_id = {f"2026_08_{g['away']}_{g['home']}": g for g in forecasts}
    availability = json.load(open(AVAILABILITY))
    availability_rows = {p['gsis_id']: p for p in availability['players']}
    con = q.connect(args.layer)
    layer_meta = {key: json.loads(value) for key, value in con.execute('select key, value from meta')}
    blocks = []
    for game_id, info in sorted(manifest['games'].items()):
        if game_id not in forecast_by_id:
            raise ValueError(f'{game_id} is missing from the frozen forecasts')
        depth_path = os.path.join(GAMES_DIR, game_id, f'{game_id}-full-depth.json')
        depth = json.load(open(depth_path)) if os.path.exists(depth_path) else None
        forecast = forecast_by_id[game_id]
        game = {'game_id': game_id, 'away': forecast['away'], 'home': forecast['home'], 'status': info['status'],
                'kickoff_utc': forecast['kickoff_utc']}
        if depth is None:
            blocks.append({'game_id': game_id, 'sim_status': info['status'],
                           'note': 'no frozen full-depth roster; QB1 history not attached'})
            continue
        blocks.append(build_game(con, game, depth, availability_rows, as_of, forecast_by_id[game_id]))
    out = {'as_of_utc': as_of, 'used_by_model': False,
           'cutoff_rule': 'historical games with kickoff before the frozen as_of only (checked per split)',
           'inputs': {'layer': args.layer, 'layer_source_sha256': layer_meta['source_sha256'],
                      'layer_code_commit': layer_meta['code_commit'], 'availability': AVAILABILITY,
                      'availability_sha256': sha256_file(AVAILABILITY), 'forecasts': FORECASTS,
                      'forecasts_sha256': sha256_file(FORECASTS), 'manifest_sha256': sha256_file(
                          os.path.join(GAMES_DIR, 'manifest.json'))},
           'generated_utc': datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%SZ'), 'games': blocks}
    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, 'w') as handle:
        json.dump(out, handle, indent=1, sort_keys=True, default=str)
    print(json.dumps({'written': args.out, 'games': len(blocks)}))


if __name__ == '__main__':
    main()
