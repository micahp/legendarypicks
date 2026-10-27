"""Build team-based historical splits: each team's games, the conditions they were played under, and the results.

Tier A (2010 to 2026) comes from the splits layer: schedule, play-by-play, weather, officials and attendance. Tier B
(1920 to 2009) comes from the Elo game table, which has scores, weekday, home or away and playoff status but no kickoff
time, weather, officials or venue. Tier B games are the only evidence before 2010. Each dimension reports how many games
it could classify, so a split never counts an unknown condition as a known one.

Reads only: the splits layer, the dev database (attendance flags and the Elo table), and the 2026 venue capacity
snapshot. Writes one new SQLite file, refused if it already exists.

Tables:
  team_game_row       one row per team per game, with every condition and the result
  team_game_official  one row per team game and official (name and position)
  team_split          results by team, scope, dimension and level, with the games behind each row
  team_split_coverage how many of a team's games each dimension could classify, by scope

Usage: python3 team_splits_build.py [--out PATH]
"""
import argparse
import hashlib
import json
import math
import os
import sqlite3
import statistics
from collections import Counter, defaultdict
from datetime import datetime

LAYER = '/root/lp-snapshots/nfl-splits/layer-2026-10-27/splits_layer.sqlite'
DEV_DB = 'file:/root/legendarypicks/backend/data/picks.dev.db?mode=ro'
VENUES = '/root/lp-snapshots/nfl-game-info/2026/week08/2026-10-27T1900Z/venues.json'
DEFAULT_OUT = '/root/lp-snapshots/nfl-splits/team-splits-2026-10-27/team_splits.sqlite'
SCHEMA_VERSION = 'lp-nfl-team-splits-1'
TIER_A_FIRST = 2010
TIER_B_LAST = 2009
THIN_N = 8
VERY_THIN_N = 3
OUTDOOR_ROOFS = ('outdoors', 'open')
# Elo uses OAK for the Raiders through 2020. The current franchise code is LV.
ELO_TEAM = {'OAK': 'LV'}
# Renamed buildings: the same stadium under an older name. Only renames of the same building are listed here. Moves to a
# different building (Qualcomm to SoFi, Edward Jones Dome, Georgia Dome, the Oakland Coliseum, Candlestick) stay unmapped.
# Buffalo is deliberately absent. "New Era Field" (2016 to 2025) and "Ralph Wilson Stadium" are not the building now
# listed as Highmark Stadium (60,108, the 2026 name). Mapping them to that listing would give old games a capacity that
# was not theirs, so those games stay "no current capacity".
ALIASES = {
    'University of Phoenix Stadium': 'State Farm Stadium',
    'Cowboys Stadium': 'AT&T Stadium',
    'Invesco Field at Mile High': 'Empower Field at Mile High',
    'Sports Authority Field at Mile High': 'Empower Field at Mile High',
    'Paul Brown Stadium': 'Paycor Stadium',
    'Cleveland Browns Stadium': 'Huntington Bank Field',
    'FirstEnergy Stadium': 'Huntington Bank Field',
    'NRG Stadium': 'Reliant Stadium',
    'EverBank Field': 'EverBank Stadium',
    'TIAA Bank Stadium': 'EverBank Stadium',
    'GEHA Field at Arrowhead Stadium': 'Arrowhead Stadium',
    'Sun Life Stadium': 'Hard Rock Stadium',
    'Louisiana Superdome': 'Caesars Superdome',
    'Mercedes-Benz Superdome': 'Caesars Superdome',
    'New Meadowlands Stadium': 'MetLife Stadium',
    'Heinz Field': 'Acrisure Stadium',
    'Qwest Field': 'Lumen Field',
    'CenturyLink Field': 'Lumen Field',
    'LP Field': 'Nissan Stadium',
    'FedExField': 'Northwest Stadium',
}
DIMENSIONS = ('all', 'season', 'weekday', 'kickoff_et', 'window_et', 'window_venue', 'window_body', 'home_away',
              'opponent', 'division', 'game_type', 'international', 'roof', 'surface', 'temp_bin', 'wind_bin',
              'stadium', 'capacity_bin', 'attendance_bin', 'referee', 'official')
SCOPES = ('all', 'tier_a', 'tier_b')


def capacity_bin(listed):
    if listed is None:
        return None
    if listed < 65000:
        return 'under_65k'
    if listed < 70000:
        return '65k_to_69k'
    return '70k_plus'


def attendance_bin(attendance):
    if attendance is None:
        return None
    if attendance < 60000:
        return 'under_60k'
    if attendance < 75000:
        return '60k_to_74k'
    return '75k_plus'


def temp_bin(temp, roof):
    if roof is None:
        return None
    if roof not in OUTDOOR_ROOFS:
        return 'not_outdoors'
    if temp is None:
        return None
    if temp < 40:
        return 'under_40F'
    if temp < 60:
        return '40F_to_59F'
    if temp < 80:
        return '60F_to_79F'
    return '80F_plus'


def wind_bin(wind, roof):
    if roof is None:
        return None
    if roof not in OUTDOOR_ROOFS:
        return 'not_outdoors'
    if wind is None:
        return None
    if wind < 10:
        return 'under_10mph'
    if wind < 15:
        return '10_to_14mph'
    if wind < 20:
        return '15_to_19mph'
    return '20mph_plus'


def canonical_building(stadium, current_names):
    """The current venue name for a stadium, following a rename. None when the building has no current listing."""
    if not stadium:
        return None
    if stadium in current_names:
        return stadium
    alias = ALIASES.get(stadium)
    return alias if alias in current_names else None


# One referee, two spellings. The schedule says "Ron Torbert" for 151 games. The crew list says "Ronald Torbert".
# Surnames shared by different officials are not merged.
OFFICIAL_ALIASES = {'Ron Torbert': 'Ronald Torbert'}


def norm_name(name):
    """Official name with the spacing collapsed and the one confirmed spelling alias applied."""
    if name is None:
        return None
    collapsed = ' '.join(name.split())
    return OFFICIAL_ALIASES.get(collapsed, collapsed)


def load_venues(path):
    venues = json.load(open(path))['venues']
    return {v['stadium']: v['listed_capacity'] for v in venues.values()}


def layer_rows(layer, current, suspect_games, stats):
    """Tier A team rows from the splits layer.

    The referee is the crew list's Referee row where one exists (2015 onward), and the schedule's referee otherwise.
    Where both exist and disagree, the crew list is used and the disagreement is counted in stats.
    """
    official = defaultdict(set)
    referee_crew = {}
    for gid, position, name in layer.execute('select game_id, position, official_name from game_official'):
        if name:
            official[gid].add(norm_name(name))
        if position == 'Referee' and name:
            referee_crew[gid] = norm_name(name)
    rows = []
    cur = layer.execute("""select game_id, season, week, game_type, team, opponent, home_away, division, gameday,
        weekday, gametime_et, window_et, window_venue, window_body, international, stadium, roof, surface, temp, wind,
        referee, attendance, points_for, points_against, result from team_game""")
    names = [c[0] for c in cur.description]
    for values in cur.fetchall():
        r = dict(zip(names, values))
        canon = canonical_building(r['stadium'], current)
        listed = current.get(canon) if canon else None
        attendance = r['attendance']
        clean = attendance if attendance and attendance > 0 and r['game_id'] not in suspect_games else None
        schedule_ref = norm_name(r['referee'])
        crew_ref = referee_crew.get(r['game_id'])
        if crew_ref and schedule_ref and crew_ref != schedule_ref:
            stats['referee_sources_disagree'] += 1
        referee = crew_ref or schedule_ref
        rows.append({
            'game_id': r['game_id'], 'tier': 'A', 'season': r['season'], 'week': r['week'],
            'game_type': r['game_type'], 'gameday': r['gameday'], 'weekday': r['weekday'],
            'kickoff_et': r['gametime_et'], 'window_et': r['window_et'], 'window_venue': r['window_venue'],
            'window_body': r['window_body'], 'team': r['team'], 'opponent': r['opponent'],
            'home_away': r['home_away'],
            'division': None if r['division'] is None else ('division' if r['division'] else 'non_division'),
            'international': None if r['international'] is None else
            ('international' if r['international'] else 'domestic'),
            'playoff': None, 'stadium': r['stadium'], 'stadium_canonical': canon, 'capacity_listed': listed,
            'roof': r['roof'] or 'unknown', 'surface': r['surface'] or 'unknown', 'temp': r['temp'],
            'wind': r['wind'], 'referee': referee, 'attendance': clean,
            'points_for': r['points_for'], 'points_against': r['points_against'], 'result': r['result'],
            'officials': sorted(official.get(r['game_id'], set())),
            'temp_bin': temp_bin(r['temp'], r['roof']), 'wind_bin': wind_bin(r['wind'], r['roof']),
            'capacity_bin': capacity_bin(listed) if canon else 'no_current_capacity',
            'attendance_bin': attendance_bin(clean),
        })
    return rows


def elo_rows(dev):
    """Tier B team rows from the Elo table, for seasons before the schedule starts."""
    rows = []
    cur = dev.execute("""select date, cast(season as integer), team1, team2, cast(score1 as integer),
        cast(score2 as integer), neutral, playoff from nfl_elo_538 where cast(season as integer) <= ?""", (TIER_B_LAST,))
    for date, season, t1, t2, s1, s2, neutral, playoff in cur.fetchall():
        t1, t2 = ELO_TEAM.get(t1, t1), ELO_TEAM.get(t2, t2)
        weekday = datetime.strptime(date, '%Y-%m-%d').strftime('%A')
        is_neutral = neutral == '1'
        gid = f'elo:{date}:{t1}:{t2}'
        game_type = 'PLAYOFF' if playoff == '1' else 'REG'
        for team, opp, pf, pa, home in ((t1, t2, s1, s2, True), (t2, t1, s2, s1, False)):
            if is_neutral:
                side = 'neutral'
            else:
                side = 'home' if home else 'away'
            result = 'W' if pf > pa else ('L' if pf < pa else 'T')
            rows.append({
                'game_id': gid, 'tier': 'B', 'season': season, 'week': None, 'game_type': game_type,
                'gameday': date, 'weekday': weekday, 'kickoff_et': None, 'window_et': None, 'window_venue': None,
                'window_body': None, 'team': team, 'opponent': opp, 'home_away': side, 'division': None,
                'international': None, 'playoff': playoff == '1', 'stadium': None, 'stadium_canonical': None,
                'capacity_listed': None, 'roof': None, 'surface': None, 'temp': None, 'wind': None,
                'referee': None, 'attendance': None, 'points_for': pf, 'points_against': pa, 'result': result,
                'officials': [], 'temp_bin': None, 'wind_bin': None, 'capacity_bin': None,
                'attendance_bin': None,
            })
    return rows


def dimension_level(dim, r):
    if dim == 'all':
        return 'all_games'
    if dim == 'season':
        return str(r['season'])
    if dim == 'stadium':
        return r['stadium_canonical'] or r['stadium']
    return r.get(dim)


def levels_of(dim, r):
    """Every level a game falls under for a dimension. Empty means the condition is unknown for this game."""
    if dim == 'official':
        return list(r['officials'])
    level = dimension_level(dim, r)
    return [] if level is None else [level]


def metrics(rows):
    n = len(rows)
    wins = [r for r in rows if r['result'] == 'W']
    losses = [r for r in rows if r['result'] == 'L']
    ties = [r for r in rows if r['result'] == 'T']
    margins = [r['points_for'] - r['points_against'] for r in rows]
    se = round(statistics.stdev(margins) / math.sqrt(n), 3) if n > 1 else None

    def mean(values):
        return round(sum(values) / len(values), 3) if values else None

    seasons = [r['season'] for r in rows]
    return {
        'n': n, 'wins': len(wins), 'losses': len(losses), 'ties': len(ties),
        'win_pct': round(len(wins) / n, 3) if n else None,
        'pf_mean': mean([r['points_for'] for r in rows]),
        'pa_mean': mean([r['points_against'] for r in rows]),
        'margin_mean': mean(margins), 'margin_se': se,
        'pf_in_wins_mean': mean([r['points_for'] for r in wins]),
        'pa_in_wins_mean': mean([r['points_against'] for r in wins]),
        'pf_in_losses_mean': mean([r['points_for'] for r in losses]),
        'pa_in_losses_mean': mean([r['points_against'] for r in losses]),
        'seasons_from': min(seasons) if seasons else None, 'seasons_to': max(seasons) if seasons else None,
        'sample_flag': None if n >= THIN_N else ('very_thin' if n < VERY_THIN_N else 'thin'),
        'game_ids': sorted({r['game_id'] for r in rows}),
    }


def scoped(rows, scope):
    if scope == 'all':
        return rows
    if scope == 'tier_a':
        return [r for r in rows if r['tier'] == 'A']
    return [r for r in rows if r['tier'] == 'B']


def build_splits(team_rows):
    """(team_split rows, coverage rows) for every team, scope and dimension."""
    league = {scope: scoped(team_rows, scope) for scope in SCOPES}
    league_metrics = {scope: metrics(rows) for scope, rows in league.items()}
    by_team = defaultdict(list)
    for r in team_rows:
        by_team[r['team']].append(r)
    splits, coverage = [], []
    for team, rows_all in sorted(by_team.items()):
        for scope in SCOPES:
            rows = scoped(rows_all, scope)
            if not rows:
                continue
            team_base = metrics(rows)
            for dim in DIMENSIONS:
                groups = defaultdict(list)
                known = []
                for r in rows:
                    levels = levels_of(dim, r)
                    if levels:
                        known.append(r)
                    for level in levels:
                        groups[level].append(r)
                coverage.append({
                    'team': team, 'scope': scope, 'dimension': dim, 'n_known': len(known),
                    'n_missing': len(rows) - len(known),
                    'seasons_known_from': min((r['season'] for r in known), default=None),
                    'seasons_known_to': max((r['season'] for r in known), default=None),
                })
                for level, group in groups.items():
                    m = metrics(group)
                    m.update({
                        'team': team, 'scope': scope, 'dimension': dim, 'level': level,
                        'delta_margin_vs_team': None if m['margin_mean'] is None or team_base['margin_mean'] is None
                        else round(m['margin_mean'] - team_base['margin_mean'], 3),
                        'delta_win_pct_vs_team': None if m['win_pct'] is None or team_base['win_pct'] is None
                        else round(m['win_pct'] - team_base['win_pct'], 3),
                        'delta_margin_vs_league': None if m['margin_mean'] is None
                        or league_metrics[scope]['margin_mean'] is None
                        else round(m['margin_mean'] - league_metrics[scope]['margin_mean'], 3),
                    })
                    splits.append(m)
    return splits, coverage


SPLIT_COLUMNS = ('team', 'scope', 'dimension', 'level', 'n', 'wins', 'losses', 'ties', 'win_pct', 'pf_mean', 'pa_mean',
                 'margin_mean', 'margin_se', 'pf_in_wins_mean', 'pa_in_wins_mean', 'pf_in_losses_mean',
                 'pa_in_losses_mean', 'seasons_from', 'seasons_to', 'sample_flag', 'delta_margin_vs_team',
                 'delta_win_pct_vs_team', 'delta_margin_vs_league', 'game_ids')

SCHEMA = """
create table meta (key text primary key, value text);
create table team_game_row (
    game_id text not null, tier text not null, season integer not null, week integer, game_type text,
    gameday text, weekday text, kickoff_et text, window_et text, window_venue text, window_body text,
    team text not null, opponent text, home_away text, division text, international text, playoff integer,
    stadium text, stadium_canonical text, capacity_listed integer, roof text, surface text, temp real, wind real,
    temp_bin text, wind_bin text, referee text, attendance integer, attendance_bin text, capacity_bin text,
    points_for integer, points_against integer, result text,
    primary key (game_id, team));
create index team_game_row_team on team_game_row (team, season);
create table team_game_official (
    game_id text not null, team text not null, official_name text not null,
    primary key (game_id, team, official_name));
create table team_split (
    team text not null, scope text not null, dimension text not null, level text not null,
    n integer, wins integer, losses integer, ties integer, win_pct real,
    pf_mean real, pa_mean real, margin_mean real, margin_se real,
    pf_in_wins_mean real, pa_in_wins_mean real, pf_in_losses_mean real, pa_in_losses_mean real,
    seasons_from integer, seasons_to integer, sample_flag text,
    delta_margin_vs_team real, delta_win_pct_vs_team real, delta_margin_vs_league real,
    game_ids text not null,
    primary key (team, scope, dimension, level));
create index team_split_dim on team_split (dimension, scope);
create table team_split_coverage (
    team text not null, scope text not null, dimension text not null, n_known integer, n_missing integer,
    seasons_known_from integer, seasons_known_to integer,
    primary key (team, scope, dimension));
"""


def file_sha256(path):
    digest = hashlib.sha256()
    with open(path, 'rb') as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b''):
            digest.update(chunk)
    return digest.hexdigest()


def build(out, layer_path=LAYER, dev_uri=DEV_DB, venues_path=VENUES):
    if os.path.exists(out):
        raise SystemExit(f'refusing to overwrite {out}')
    os.makedirs(os.path.dirname(out), exist_ok=True)
    layer = sqlite3.connect(f'file:{layer_path}?mode=ro', uri=True)
    dev = sqlite3.connect(dev_uri, uri=True)
    current = load_venues(venues_path)
    suspect = {gid for (gid,) in dev.execute('select game_id from nfl_game_context where attendance_suspect = 1')}
    stats = Counter()
    tier_a = layer_rows(layer, current, suspect, stats)
    tier_b = elo_rows(dev)
    team_rows = tier_a + tier_b
    splits, coverage = build_splits(team_rows)

    db = sqlite3.connect(out)
    db.executescript(SCHEMA)
    row_cols = ('game_id', 'tier', 'season', 'week', 'game_type', 'gameday', 'weekday', 'kickoff_et', 'window_et',
                'window_venue', 'window_body', 'team', 'opponent', 'home_away', 'division', 'international',
                'playoff', 'stadium', 'stadium_canonical', 'capacity_listed', 'roof', 'surface', 'temp', 'wind',
                'temp_bin', 'wind_bin', 'referee', 'attendance', 'attendance_bin', 'capacity_bin', 'points_for',
                'points_against', 'result')
    db.executemany(f'insert into team_game_row ({",".join(row_cols)}) values ({",".join("?" * len(row_cols))})',
                   [tuple(r[c] for c in row_cols) for r in team_rows])
    db.executemany('insert into team_game_official values (?,?,?)',
                   [(r['game_id'], r['team'], name) for r in tier_a for name in r['officials']])
    db.executemany(f'insert into team_split ({",".join(SPLIT_COLUMNS)}) values ({",".join("?" * len(SPLIT_COLUMNS))})',
                   [tuple((json.dumps(s[c]) if c == 'game_ids' else s[c]) for c in SPLIT_COLUMNS) for s in splits])
    db.executemany('insert into team_split_coverage values (?,?,?,?,?,?,?)',
                   [(c['team'], c['scope'], c['dimension'], c['n_known'], c['n_missing'], c['seasons_known_from'],
                     c['seasons_known_to']) for c in coverage])
    meta = {
        'schema': SCHEMA_VERSION, 'layer': layer_path, 'layer_sha256': file_sha256(layer_path),
        'venues': venues_path, 'venues_sha256': file_sha256(venues_path),
        'tier_a_rows': len(tier_a), 'tier_b_rows': len(tier_b), 'split_rows': len(splits),
        'coverage_rows': len(coverage), 'suspect_attendance_games_excluded': len(suspect),
        'capacity_venues': len(current), 'aliases': len(ALIASES), 'official_aliases': len(OFFICIAL_ALIASES),
        'referee_sources_disagree_team_games': stats['referee_sources_disagree'],
    }
    for key, value in meta.items():
        db.execute('insert into meta values (?, ?)', (key, json.dumps(value)))
    db.commit()
    db.close()
    return meta


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--out', default=DEFAULT_OUT)
    args = ap.parse_args()
    print(json.dumps(build(args.out), indent=1, sort_keys=True))


if __name__ == '__main__':
    main()
