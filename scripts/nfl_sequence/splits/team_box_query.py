"""Box-score distributions for one team under situational filters, against the team's and the league's baselines.

Filters come from the team splits store (the same dimensions and levels: weekday, window_et, roof, wind_bin, temp_bin,
referee, official, stadium, capacity_bin, attendance_share_bin and so on). The box-score values come from the team box
score store. Only regular-season games are used, and every null is excluded from its statistic and counted.

Examples:
  python3 team_box_query.py --team BUF --where roof=dome --fields rush_att turnovers drives pts_derived
  python3 team_box_query.py --team BUF --where roof=outdoors --where wind_bin=20mph_plus --fields rush_att turnovers
  python3 team_box_query.py --team BUF --where roof=outdoors --where wind_bin=20mph_plus --games
"""
import argparse
import os
import sqlite3
import statistics
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import team_splits_build as tb  # noqa: E402
import team_splits_query as tq  # noqa: E402

BOX = '/root/lp-snapshots/nfl-splits/team-box-2026-10-27-rev2/team_box.sqlite'
STORE = tq.DEFAULT_STORE
DEFAULT_FIELDS = ('plays_off', 'pass_att', 'pass_yds', 'rush_att', 'rush_yds', 'total_yards', 'first_downs',
                  'third_conv', 'turnovers', 'drives', 'pts_derived', 'pen_flagged')


def box_rows(con, team=None):
    """{(game_id, team): row} for regular-season box scores, for one team or for all teams."""
    cur = con.execute('select * from team_box_score where game_type = ?' + (' and team = ?' if team else ''),
                      ['REG'] + ([team] if team else []))
    names = [c[0] for c in cur.description]
    return {(r[0], r[4]): dict(zip(names, r)) for r in cur.fetchall()}


def distribution(values):
    vals = [v for v in values if v is not None]
    if not vals:
        return {'n': 0, 'nulls': len(values)}
    vals_sorted = sorted(vals)
    n = len(vals)
    q = statistics.quantiles(vals_sorted, n=4, method='inclusive') if n > 1 else [vals[0]] * 3
    return {'n': n, 'nulls': len(values) - n, 'mean': round(statistics.fmean(vals), 2),
            'median': round(statistics.median(vals), 2), 'p25': round(q[0], 2), 'p75': round(q[2], 2),
            'min': min(vals), 'max': max(vals)}


def query(team, conditions, fields=DEFAULT_FIELDS, store=STORE, box=BOX, before=None):
    """Distributions for one team's games under the conditions, against the team's and the league's baselines.

    before: a game date (YYYY-MM-DD). When given, only games played before that date are used, in the situation and in
    both baselines. That is the cutoff for a forecast made on that date. Dates are day-level, so a game on the same
    day is excluded. Scores and box fields are postgame results; the query does not make them pregame information.
    """
    store_con = tq.connect(store)
    box_con = sqlite3.connect(f'file:{box}?mode=ro', uri=True)
    team_rows = [r for r in tq.load_rows(store_con, team, 'tier_a') if r['game_type'] == 'REG']
    allowed = None
    if before:
        allowed = {gid for (gid,) in store_con.execute('select distinct game_id from team_game_row where gameday < ?',
                                                       (before,))}
        team_rows = [r for r in team_rows if r['game_id'] in allowed]
    team_box = box_rows(box_con, team)
    selected = [r for r in team_rows if tq.matches(r, conditions)]
    chosen = [team_box.get((r['game_id'], team)) for r in selected]
    chosen = [c for c in chosen if c is not None]
    baseline = [v for (gid, _), v in team_box.items() if allowed is None or gid in allowed]
    league = [v for (gid, _), v in box_rows(box_con).items() if allowed is None or gid in allowed]
    out = {'team': team, 'conditions': [f'{d}={v}' for d, v in conditions], 'games': [c['game_id'] for c in chosen],
           'fields': {}}
    for f in fields:
        out['fields'][f] = {
            'situation': distribution([c[f] for c in chosen]),
            'team_all_games': distribution([c[f] for c in baseline]),
            'league_all_games': distribution([c[f] for c in league]),
        }
    return out


def print_result(result):
    print(f"{result['team']}  conditions: {' AND '.join(result['conditions']) or '(none)'}  "
          f"games: {len(result['games'])}")
    print(f"{'field':<16}{'n':>5}{'nulls':>7}{'mean':>8}{'median':>8}{'p25':>7}{'p75':>7}"
          f"{'team mean':>11}{'league mean':>13}{'vs team':>9}")
    for f, block in result['fields'].items():
        s, t, lg = block['situation'], block['team_all_games'], block['league_all_games']
        if s['n'] == 0:
            print(f"{f:<16}{0:>5}{s['nulls']:>7}  (no non-null values)")
            continue
        delta = round(s['mean'] - t['mean'], 2) if t.get('mean') is not None else None
        print(f"{f:<16}{s['n']:>5}{s['nulls']:>7}{s['mean']:>8}{s['median']:>8}{s['p25']:>7}{s['p75']:>7}"
              f"{t['mean']:>11}{lg['mean']:>13}{delta!s:>9}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--team', required=True)
    ap.add_argument('--where', action='append', default=[], help='dimension=level, combined with AND')
    ap.add_argument('--fields', nargs='+', default=list(DEFAULT_FIELDS))
    ap.add_argument('--games', action='store_true', help='list the game IDs behind the result')
    ap.add_argument('--before', help='YYYY-MM-DD: use only games played before this date (forecast cutoff)')
    args = ap.parse_args()
    conditions = []
    for item in args.where:
        dim, _, level = item.partition('=')
        if dim not in tb.DIMENSIONS or not level:
            raise SystemExit(f'bad --where {item!r}')
        conditions.append((dim, level))
    result = query(args.team, conditions, tuple(args.fields), before=args.before)
    print_result(result)
    if args.games:
        print('\n'.join(result['games']))


if __name__ == '__main__':
    main()
