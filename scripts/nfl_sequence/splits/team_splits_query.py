"""Read-only queries over the team splits store built by team_splits_build.py.

Every result states its sample, its games, its coverage, and its baseline. Results are raw, with no shrinkage.

Examples:
  python3 team_splits_query.py --team BUF                          all dimensions, both tiers
  python3 team_splits_query.py --team BUF --dimension weekday --scope tier_a
  python3 team_splits_query.py --team BUF --where weekday=Sunday --where window_et=early --where roof=outdoors
  python3 team_splits_query.py --team BUF --where official="Clete Blakeman" --games
  python3 team_splits_query.py --team BUF --coverage
  python3 team_splits_query.py --csv /path/out.csv                  every team, every dimension (no game ids)
"""
import argparse
import csv
import json
import sqlite3

import team_splits_build as build

DEFAULT_STORE = '/root/lp-snapshots/nfl-splits/team-splits-2026-10-27/team_splits.sqlite'
SCOPES = ('all', 'tier_a', 'tier_b')


def connect(path=DEFAULT_STORE):
    return sqlite3.connect(f'file:{path}?mode=ro', uri=True)


def _scope_clause(scope):
    if scope == 'all':
        return '', []
    tier = 'A' if scope == 'tier_a' else 'B'
    return ' and tier = ?', [tier]


def load_rows(con, team, scope='all'):
    """Every game row for a team in a scope, with the official names attached."""
    clause, args = _scope_clause(scope)
    cur = con.execute(f'select * from team_game_row where team = ?{clause} order by season, gameday', [team, *args])
    names = [c[0] for c in cur.description]
    rows = [dict(zip(names, values)) for values in cur.fetchall()]
    officials = {}
    for game_id, official_name in con.execute('select game_id, official_name from team_game_official where team = ?',
                                              [team]):
        officials.setdefault(game_id, []).append(official_name)
    for r in rows:
        r['officials'] = sorted(officials.get(r['game_id'], []))
    return rows


def matches(row, conditions):
    """True when the game falls under every (dimension, level) condition."""
    for dim, level in conditions:
        if level not in build.levels_of(dim, row):
            return False
    return True


def combined(con, team, conditions, scope='all'):
    """Results for the games matching every condition, against the team's own games in the same scope."""
    rows = load_rows(con, team, scope)
    selected = [r for r in rows if matches(r, conditions)]
    base = build.metrics(rows)
    result = build.metrics(selected)
    result['delta_margin_vs_team'] = (None if result['margin_mean'] is None or base['margin_mean'] is None
                                      else round(result['margin_mean'] - base['margin_mean'], 3))
    result['delta_win_pct_vs_team'] = (None if result['win_pct'] is None or base['win_pct'] is None
                                       else round(result['win_pct'] - base['win_pct'], 3))
    result['team_baseline'] = {k: base[k] for k in ('n', 'win_pct', 'margin_mean', 'pf_mean', 'pa_mean')}
    result['games'] = [{'game_id': r['game_id'], 'gameday': r['gameday'], 'opponent': r['opponent'],
                        'result': r['result'], 'points_for': r['points_for'], 'points_against': r['points_against']}
                       for r in sorted(selected, key=lambda r: r['gameday'] or '')]
    result['conditions'] = [f'{d}={v}' for d, v in conditions]
    return result


def dimension_table(con, team, dimension, scope='all'):
    """Stored rows for one dimension, most games first."""
    cur = con.execute("""select level, n, wins, losses, ties, win_pct, pf_mean, pa_mean, margin_mean, margin_se,
        pf_in_wins_mean, pf_in_losses_mean, pa_in_wins_mean, pa_in_losses_mean, seasons_from, seasons_to, sample_flag,
        delta_margin_vs_team, delta_win_pct_vs_team, delta_margin_vs_league, game_ids
        from team_split where team = ? and scope = ? and dimension = ? order by n desc, level""",
                      (team, scope, dimension))
    names = [c[0] for c in cur.description]
    out = []
    for values in cur.fetchall():
        row = dict(zip(names, values))
        row['game_ids'] = json.loads(row['game_ids'])
        out.append(row)
    return out


def coverage(con, team, scope='all'):
    cur = con.execute("""select dimension, n_known, n_missing, seasons_known_from, seasons_known_to
        from team_split_coverage where team = ? and scope = ?""", (team, scope))
    return [dict(zip(('dimension', 'n_known', 'n_missing', 'seasons_from', 'seasons_to'), r)) for r in cur.fetchall()]


def _fmt(value, digits=2):
    if value is None:
        return '-'
    if isinstance(value, float):
        return f'{value:.{digits}f}'
    return str(value)


def print_table(rows, dimension):
    header = (f"{'level':<26}{'n':>5}{'W-L-T':>10}{'win%':>7}{'pf':>7}{'pa':>7}{'margin':>8}{'se':>6}"
              f"{'pf|W':>7}{'pf|L':>7}{'d_mrg':>7}  flag / seasons")
    print(f'== {dimension}')
    print(header)
    for r in rows:
        record = f"{r['wins']}-{r['losses']}-{r['ties']}"
        seasons = f"{r['seasons_from']}-{r['seasons_to']}" if r['seasons_from'] else ''
        flag = r['sample_flag'] or ''
        print(f"{str(r['level'])[:25]:<26}{r['n']:>5}{record:>10}{_fmt(r['win_pct'], 3):>7}"
              f"{_fmt(r['pf_mean']):>7}{_fmt(r['pa_mean']):>7}{_fmt(r['margin_mean']):>8}{_fmt(r['margin_se']):>6}"
              f"{_fmt(r['pf_in_wins_mean']):>7}{_fmt(r['pf_in_losses_mean']):>7}"
              f"{_fmt(r['delta_margin_vs_team']):>7}  {flag} {seasons}".rstrip())
    print()


def print_combined(result):
    base = result['team_baseline']
    print('conditions:', ' AND '.join(result['conditions']) or '(none)')
    print(f"n={result['n']} record={result['wins']}-{result['losses']}-{result['ties']} "
          f"win%={_fmt(result['win_pct'], 3)} points for={_fmt(result['pf_mean'])} against={_fmt(result['pa_mean'])} "
          f"margin={_fmt(result['margin_mean'])} (se {_fmt(result['margin_se'])}) "
          f"pf in wins={_fmt(result['pf_in_wins_mean'])} in losses={_fmt(result['pf_in_losses_mean'])}")
    print(f"team baseline: n={base['n']} win%={_fmt(base['win_pct'], 3)} margin={_fmt(base['margin_mean'])} "
          f"delta margin={_fmt(result['delta_margin_vs_team'])}  flag={result['sample_flag'] or 'ok'}")


def parse_where(items):
    conditions = []
    for item in items or []:
        dim, _, level = item.partition('=')
        if dim not in build.DIMENSIONS or not level:
            raise SystemExit(f'bad --where {item!r}: use dimension=level with a dimension from {build.DIMENSIONS}')
        conditions.append((dim, level.strip('"')))
    return conditions


def export_csv(con, path):
    cur = con.execute("""select team, scope, dimension, level, n, wins, losses, ties, win_pct, pf_mean, pa_mean,
        margin_mean, margin_se, pf_in_wins_mean, pa_in_wins_mean, pf_in_losses_mean, pa_in_losses_mean,
        seasons_from, seasons_to, sample_flag, delta_margin_vs_team, delta_win_pct_vs_team,
        delta_margin_vs_league from team_split order by team, scope, dimension, n desc""")
    names = [c[0] for c in cur.description]
    with open(path, 'w', newline='') as handle:
        writer = csv.writer(handle)
        writer.writerow(names)
        writer.writerows(cur.fetchall())
    return path


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--store', default=DEFAULT_STORE)
    ap.add_argument('--team')
    ap.add_argument('--scope', default='all', choices=SCOPES)
    ap.add_argument('--dimension', choices=build.DIMENSIONS)
    ap.add_argument('--where', action='append', help='dimension=level, combined with AND')
    ap.add_argument('--games', action='store_true', help='list the games behind a combined result')
    ap.add_argument('--coverage', action='store_true')
    ap.add_argument('--csv', help='write the whole split table to this path and exit')
    args = ap.parse_args()
    con = connect(args.store)
    if args.csv:
        print(export_csv(con, args.csv))
        return
    if not args.team:
        raise SystemExit('--team is required unless --csv is given')
    if args.where:
        result = combined(con, args.team, parse_where(args.where), args.scope)
        print_combined(result)
        if args.games:
            for g in result['games']:
                print(f"  {g['gameday']}  {g['game_id']:<22} vs {g['opponent']:<4} {g['result']} "
                      f"{g['points_for']}-{g['points_against']}")
        return
    if args.coverage:
        for c in coverage(con, args.team, args.scope):
            print(c)
        return
    dims = [args.dimension] if args.dimension else [d for d in build.DIMENSIONS if d != 'all']
    if not args.dimension:
        print_table(dimension_table(con, args.team, 'all', args.scope), 'all')
    for dim in dims:
        print_table(dimension_table(con, args.team, dim, args.scope), dim)


if __name__ == '__main__':
    main()
