"""Read-only historical splits for NFL teams and players, over the layer that layer.py builds.

Every result states its sample: games, covered seasons, the exact game IDs, the classifications that were missing,
and the shrinkage applied (none; these are raw results). Each split sits beside its baselines: the same statistics for
the team or player over all its games in the same seasons, and for the league. Descriptive splits are information for
display. Nothing here changes a simulation or a projection.

Filters (all optional; a game must match every filter it is given):
  seasons (lo, hi), game_type (REG default, POST, ALL), weekday, window_et / window_venue / window_body
  (early, late_afternoon, primetime), home_away, opponent, division, referee, official (any crew position),
  roof, surface, temp_min/temp_max, wind_min/wind_max, international, roles {QB|RB|WR: [status, ...]}

Role statuses: played, injured, officially_inactive, absent_no_reason, unidentified, not_played (any absence).

Examples:
  python3 splits_query.py team --team BUF --weekday Sunday --window_et late_afternoon --wind_min 15 --roof outdoors
  python3 splits_query.py team --team PHI --role WR=not_played --weekday Monday
  python3 splits_query.py player --gsis 00-0034857 --role QB=not_played
"""
import argparse
import json
import math
import sqlite3
import statistics

DEFAULT_LAYER = '/root/lp-snapshots/nfl-splits/layer-2026-10-27/splits_layer.sqlite'
THIN_N = 8
VERY_THIN_N = 3
NOT_PLAYED = ('officially_inactive', 'injured', 'absent_no_reason')
TEAM_METRICS = ('points_for', 'points_against', 'margin', 'yards', 'plays', 'yards_per_play', 'epa_per_play',
                'success_rate', 'pass_att', 'rush_att', 'sacks_taken', 'turnovers', 'penalties', 'penalty_yards')
PLAYER_METRICS = ('snaps', 'att', 'cmp', 'pass_yds', 'pass_td', 'intc', 'carries', 'rush_yds', 'rush_td',
                  'targets', 'rec', 'rec_yds', 'rec_td', 'fpts_ppr')


def connect(path):
    return sqlite3.connect(f'file:{path}?mode=ro', uri=True)


def _in(column, values):
    return f"{column} in ({','.join('?' * len(values))})", list(values)


def _role_clause(team_alias, role, statuses):
    wanted = []
    for status in statuses:
        wanted.extend(NOT_PLAYED if status == 'not_played' else (status,))
    marks = ','.join('?' * len(wanted))
    clause = (f"exists (select 1 from team_role r where r.game_id = {team_alias}.game_id "
              f"and r.team = {team_alias}.team and r.role = ? and r.status in ({marks}))")
    return clause, [role, *wanted]


def _calendar_clauses(f, a):
    """SQL clauses over team_game under alias a, for every filter that the database can answer exactly."""
    lo, hi = f.get('seasons', (2010, 2026))
    where, args = [f'{a}.season between ? and ?'], [lo, hi]
    game_type = f.get('game_type', 'REG')
    if game_type != 'ALL':
        where.append(f'{a}.game_type = ?')
        args.append(game_type)
    for key, column in (('weekday', 'weekday'), ('window_et', 'window_et'), ('window_venue', 'window_venue'),
                        ('window_body', 'window_body'), ('roof', 'roof'), ('surface', 'surface')):
        if f.get(key):
            clause, values = _in(f'{a}.{column}', f[key])
            where.append(clause)
            args += values
    if f.get('home_away'):
        where.append(f'{a}.home_away = ?')
        args.append(f['home_away'])
    if f.get('opponent'):
        where.append(f'{a}.opponent = ?')
        args.append(f['opponent'])
    if f.get('division') is not None:
        where.append(f'{a}.division = ?')
        args.append(1 if f['division'] else 0)
    if f.get('international') is not None:
        where.append(f'{a}.international = ?')
        args.append(1 if f['international'] else 0)
    return where, args


def _weather_ok(row, f):
    """(matches, missing) for the weather filters.

    Weather filters apply to outdoor games only. A dome or closed-roof game is not a match, and it is not missing
    either, because it has no weather to report. An outdoor game with no recorded value is missing.
    """
    checks = []
    if f.get('temp_min') is not None or f.get('temp_max') is not None:
        checks.append(('temp', f.get('temp_min'), f.get('temp_max')))
    if f.get('wind_min') is not None or f.get('wind_max') is not None:
        checks.append(('wind', f.get('wind_min'), f.get('wind_max')))
    if not checks:
        return True, False
    if row['roof'] not in ('outdoors', 'open'):
        return False, False
    for name, low, high in checks:
        value = row[name]
        if value is None:
            return False, True
        if low is not None and value < low:
            return False, False
        if high is not None and value > high:
            return False, False
    return True, False


def _official_ok(official_rows, f):
    """(matches, missing) for the referee and official filters. A game with no official rows is missing."""
    if f.get('referee') is None and f.get('official') is None:
        return True, False
    if not official_rows:
        return False, True
    names = {name for _pos, name in official_rows}
    if f.get('referee') is not None and (dict(official_rows).get('Referee') != f['referee']):
        return False, False
    if f.get('official') is not None and f['official'] not in names:
        return False, False
    return True, False


def _official_map(con, game_ids):
    out = {}
    game_ids = list(game_ids)
    for start in range(0, len(game_ids), 500):
        chunk = game_ids[start:start + 500]
        marks = ','.join('?' * len(chunk))
        for gid, position, name in con.execute(
                f'select game_id, position, official_name from game_official where game_id in ({marks})', chunk):
            out.setdefault(gid, []).append((position, name))
    return out


def _dict_rows(con, sql, args):
    cur = con.execute(sql, args)
    names = [c[0] for c in cur.description]
    return [dict(zip(names, r)) for r in cur.fetchall()]


def _player_played_clause(gsis_id, played):
    """Team games in which a given player logged snaps (or snaps unknown), or did not.

    A game he did not play counts only in a season when he was on that team, so the comparison is his team's games
    while he was with it, not the team's games before he joined.
    """
    if played:
        return ("exists (select 1 from player_game p where p.game_id = t.game_id and p.team = t.team "
                "and p.gsis_id = ? and (p.snaps is null or p.snaps > 0))"), [gsis_id]
    return ("exists (select 1 from player_game p2 where p2.gsis_id = ? and p2.team = t.team and p2.season = t.season) "
            "and not exists (select 1 from player_game p where p.game_id = t.game_id and p.team = t.team "
            "and p.gsis_id = ? and (p.snaps is null or p.snaps > 0))"), [gsis_id, gsis_id]


def _expected_role_clause(role, gsis_id, mode):
    """Team games in which a player was the identified expected starter for a role.

    mode 'available'   he was the identified starter and played
    mode 'unavailable' he was the identified starter and did not play
    mode 'other'       someone else was the identified starter
    """
    base = f"exists (select 1 from team_role r where r.game_id = t.game_id and r.team = t.team and r.role = ? "
    if mode == 'available':
        return base + "and r.gsis_id = ? and r.status = 'played')", [role, gsis_id]
    if mode == 'unavailable':
        marks = ','.join('?' * len(NOT_PLAYED))
        return base + f"and r.gsis_id = ? and r.status in ({marks}))", [role, gsis_id, *NOT_PLAYED]
    if mode == 'other':
        return base + 'and r.gsis_id is not null and r.gsis_id <> ?)', [role, gsis_id]
    raise ValueError(f'unknown expected-role mode {mode!r}')


def _team_rows(con, team, f):
    where, args = _calendar_clauses(f, 't')
    where.append('t.team = ?')
    args.append(team)
    for role, statuses in (f.get('roles') or {}).items():
        clause, values = _role_clause('t', role, statuses)
        where.append(clause)
        args += values
    if f.get('player_played'):
        gsis_id, played = f['player_played']
        clause, values = _player_played_clause(gsis_id, played)
        where.append(clause)
        args += values
    if f.get('expected_role'):
        spec = f['expected_role']
        clause, values = _expected_role_clause(spec['role'], spec['gsis'], spec['mode'])
        where.append(clause)
        args += values
    return _dict_rows(con, f"select t.* from team_game t where {' and '.join(where)} order by t.season, t.week", args)


def _filter_weather_officials(con, rows, f):
    """Apply the weather and official filters in Python, counting games the layer cannot classify."""
    officials = _official_map(con, [r['game_id'] for r in rows])
    kept, missing = [], {'weather': [], 'officials': []}
    for row in rows:
        ok_w, miss_w = _weather_ok(row, f)
        if miss_w:
            missing['weather'].append(row['game_id'])
            continue
        if not ok_w:
            continue
        ok_o, miss_o = _official_ok(officials.get(row['game_id'], []), f)
        if miss_o:
            missing['officials'].append(row['game_id'])
            continue
        if ok_o:
            kept.append(row)
    return kept, missing


def _wilson(k, n, z=1.96):
    if n == 0:
        return None
    p = k / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return [round(centre - half, 3), round(centre + half, 3)]


def _mean(values):
    vals = [v for v in values if v is not None]
    return round(sum(vals) / len(vals), 3) if vals else None


def _se(values):
    vals = [v for v in values if v is not None]
    if len(vals) < 2:
        return None
    return round(statistics.stdev(vals) / math.sqrt(len(vals)), 3)


def _quantile(values, q):
    vals = sorted(v for v in values if v is not None)
    if not vals:
        return None
    pos = (len(vals) - 1) * q
    lo, hi = math.floor(pos), math.ceil(pos)
    return round(vals[lo] + (vals[hi] - vals[lo]) * (pos - lo), 3)


def _team_metric_rows(rows):
    out = []
    for r in rows:
        margin = r['points_for'] - r['points_against']
        yards_per_play = (r['yards'] / r['plays']) if r['yards'] is not None and r['plays'] else None
        out.append({'points_for': r['points_for'], 'points_against': r['points_against'], 'margin': margin,
                    'yards': r['yards'], 'plays': r['plays'], 'yards_per_play': yards_per_play,
                    'epa_per_play': r['epa_per_play'], 'success_rate': r['success_rate'],
                    'pass_att': r['pass_att'], 'rush_att': r['rush_att'], 'sacks_taken': r['sacks_taken'],
                    'turnovers': r['turnovers'], 'penalties': r['penalties'], 'penalty_yards': r['penalty_yards'],
                    'result': r['result']})
    return out


def _sample_warning(n):
    if n == 0:
        return 'empty'
    if n < VERY_THIN_N:
        return 'very_thin'
    if n < THIN_N:
        return 'thin'
    return None


def summarize_team_rows(rows):
    metrics = _team_metric_rows(rows)
    n = len(rows)
    wins = sum(1 for m in metrics if m['result'] == 'W')
    losses = sum(1 for m in metrics if m['result'] == 'L')
    ties = sum(1 for m in metrics if m['result'] == 'T')
    summary = {'n': n, 'wins': wins, 'losses': losses, 'ties': ties,
               'win_pct': round(wins / n, 3) if n else None, 'win_pct_wilson95': _wilson(wins, n),
               'warning': _sample_warning(n),
               'seasons': sorted({r['season'] for r in rows}),
               'game_ids': [r['game_id'] for r in rows], 'shrinkage': 'none (raw)'}
    for key in TEAM_METRICS:
        values = [m[key] for m in metrics]
        summary[key] = {'mean': _mean(values), 'se': _se(values), 'median': _quantile(values, 0.5)}
    turnovers_known = [r for r in rows if r['turnovers'] is not None]
    summary['turnovers']['games_with_value'] = len(turnovers_known)
    return summary


def _missing_summary(missing):
    return {k: {'games': len(v), 'game_ids': v} for k, v in missing.items()}


def team_splits(con, team, f=None, baselines=True):
    f = dict(f or {})
    rows = _team_rows(con, team, f)
    kept, missing = _filter_weather_officials(con, rows, f)
    result = {'team': team, 'filters': f, 'split': summarize_team_rows(kept),
              'missing_classification': _missing_summary(missing)}
    if baselines:
        base_f = {k: v for k, v in f.items() if k in ('seasons', 'game_type')}
        base_rows = _team_rows(con, team, base_f)
        result['baseline_team_all_games'] = summarize_team_rows(base_rows)
        where, args = _calendar_clauses(base_f, 't')
        league_rows = _dict_rows(con, f"select t.* from team_game t where {' and '.join(where)}", args)
        result['baseline_league'] = summarize_team_rows(league_rows)
        result['baseline_team_by_season'] = {
            str(season): summarize_team_rows([r for r in base_rows if r['season'] == season])
            for season in sorted({r['season'] for r in base_rows})}
    return result


def player_splits(con, gsis_id, f=None, baselines=True):
    """Per-game averages for one player over the team games he was on, split by the filters.

    Universe: every team game (in the player's team-seasons) that matches the calendar, team-role and weather filters.
    A game counts as played when the player has a logged line with snaps above zero, or with snaps unknown.
    """
    f = dict(f or {})
    teams = con.execute('select distinct season, team from player_game where gsis_id = ?', (gsis_id,)).fetchall()
    if not teams:
        raise ValueError(f'no player_game rows for {gsis_id}')
    player_name = con.execute('select player_name from player_game where gsis_id = ? limit 1', (gsis_id,)).fetchone()[0]
    lines = {(r[0], r[1]): r for r in con.execute(
        'select game_id, team, snaps, att, cmp, pass_yds, pass_td, intc, carries, rush_yds, rush_td, targets, rec, '
        'rec_yds, rec_td, fpts_ppr from player_game where gsis_id = ?', (gsis_id,))}
    cols = ('game_id', 'team', 'snaps', 'att', 'cmp', 'pass_yds', 'pass_td', 'intc', 'carries', 'rush_yds', 'rush_td',
            'targets', 'rec', 'rec_yds', 'rec_td', 'fpts_ppr')

    def universe(filters):
        where, args = _calendar_clauses(filters, 't')
        seasons_teams = [(s, t) for s, t in teams]
        clauses, team_args = [], []
        for season, team in seasons_teams:
            clauses.append('(t.season = ? and t.team = ?)')
            team_args += [season, team]
        where.append('(' + ' or '.join(clauses) + ')')
        args += team_args
        for role, statuses in (filters.get('roles') or {}).items():
            clause, values = _role_clause('t', role, statuses)
            where.append(clause)
            args += values
        if filters.get('player_played'):
            teammate, played = filters['player_played']
            clause, values = _player_played_clause(teammate, played)
            where.append(clause)
            args += values
        if filters.get('expected_role'):
            spec = filters['expected_role']
            clause, values = _expected_role_clause(spec['role'], spec['gsis'], spec['mode'])
            where.append(clause)
            args += values
        return _dict_rows(con, f"select t.* from team_game t where {' and '.join(where)} order by t.season, t.week", args)

    def summarize(filters):
        rows = universe(filters)
        kept, missing = _filter_weather_officials(con, rows, filters)
        played, missed, zero = [], [], []
        for row in kept:
            line = lines.get((row['game_id'], row['team']))
            if line is None:
                missed.append(row['game_id'])
            elif line[2] is not None and line[2] == 0:
                zero.append(row['game_id'])
            else:
                played.append((row, line))
        stats = {}
        for key in PLAYER_METRICS:
            idx = cols.index(key)
            values = [line[idx] for _row, line in played]
            stats[key] = {'mean': _mean(values), 'median': _quantile(values, 0.5), 'p25': _quantile(values, 0.25),
                          'p75': _quantile(values, 0.75), 'max': max((v for v in values if v is not None), default=None),
                          'total': sum(v for v in values if v is not None)}
        n = len(played)
        return {'games_played': n, 'games_missed_in_universe': len(missed), 'logged_zero_snaps': len(zero),
                'warning': _sample_warning(n), 'seasons': sorted({row['season'] for row, _ in played}),
                'game_ids': [row['game_id'] for row, _ in played],
                'missed_game_ids': missed, 'stats_per_game': stats, 'shrinkage': 'none (raw)',
                'missing_classification': _missing_summary(missing)}

    result = {'gsis_id': gsis_id, 'player_name': player_name, 'filters': f, 'split': summarize(f)}
    if baselines:
        result['baseline_player_all_games'] = summarize({k: v for k, v in f.items() if k in ('seasons', 'game_type')})
    return result


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--layer', default=DEFAULT_LAYER)
    sub = ap.add_subparsers(dest='kind', required=True)
    for name in ('team', 'player'):
        p = sub.add_parser(name)
        if name == 'team':
            p.add_argument('--team', required=True)
        else:
            p.add_argument('--gsis', required=True)
        p.add_argument('--season_from', type=int, default=2010)
        p.add_argument('--season_to', type=int, default=2026)
        p.add_argument('--game_type', default='REG')
        p.add_argument('--weekday', nargs='+')
        p.add_argument('--window_et', nargs='+')
        p.add_argument('--window_venue', nargs='+')
        p.add_argument('--window_body', nargs='+')
        p.add_argument('--home_away', choices=('home', 'away'))
        p.add_argument('--opponent')
        p.add_argument('--division', type=int, choices=(0, 1))
        p.add_argument('--international', type=int, choices=(0, 1))
        p.add_argument('--referee')
        p.add_argument('--official')
        p.add_argument('--roof', nargs='+')
        p.add_argument('--surface', nargs='+')
        p.add_argument('--temp_min', type=float)
        p.add_argument('--temp_max', type=float)
        p.add_argument('--wind_min', type=float)
        p.add_argument('--wind_max', type=float)
        p.add_argument('--role', action='append', default=[], help='ROLE=status[,status] e.g. QB=not_played')
        p.add_argument('--teammate', help='GSIS=played or GSIS=not_played: that player in the team game or not')
    args = ap.parse_args()
    f = {'seasons': (args.season_from, args.season_to), 'game_type': args.game_type}
    for key in ('weekday', 'window_et', 'window_venue', 'window_body', 'home_away', 'opponent', 'referee', 'official',
                'roof', 'surface', 'temp_min', 'temp_max', 'wind_min', 'wind_max'):
        value = getattr(args, key)
        if value is not None:
            f[key] = value
    if args.division is not None:
        f['division'] = bool(args.division)
    if args.international is not None:
        f['international'] = bool(args.international)
    roles = {}
    for item in args.role:
        role, _, statuses = item.partition('=')
        roles[role] = statuses.split(',')
    if roles:
        f['roles'] = roles
    if args.teammate:
        gsis_id, _, state = args.teammate.partition('=')
        f['player_played'] = (gsis_id, state == 'played')
    con = connect(args.layer)
    if args.kind == 'team':
        out = team_splits(con, args.team, f)
    else:
        out = player_splits(con, args.gsis, f)
    print(json.dumps(out, indent=1, sort_keys=True, default=str))


if __name__ == '__main__':
    main()
