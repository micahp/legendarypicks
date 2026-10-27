"""Build one canonical box-score record per team per completed game, derived from stored play-by-play.

Reads only: nfl_pbp, nfl_pbp_penalty, the splits layer's team_game (base results for every game, postseason included),
and the reconciliation sources (nfl_schedule, team_game_stats for 2025, player_game_logs, nfl_team_game_totals). Writes
one new SQLite file, refused if it exists. A statistic the stored data cannot support stays null. It is never zero.

Tables:
  team_box_score        one row per team per game
  team_box_coverage     non-null count and denominator for every field, by season
  team_box_reconciliation  each check against an independent source, by season

Derivation notes live in docs/NFL-TEAM-BOX-SCORE-SPEC-2026-10-27.md (section 8) and in FIELD_NOTES below.
"""
import argparse
import hashlib
import json
import os
import sqlite3
import statistics
from collections import defaultdict

DEV_DB = 'file:/root/legendarypicks/backend/data/picks.dev.db?mode=ro'
LAYER = '/root/lp-snapshots/nfl-splits/layer-2026-10-27/splits_layer.sqlite'
DEFAULT_OUT = '/root/lp-snapshots/nfl-splits/team-box-2026-10-27-rev3/team_box.sqlite'
SCHEMA_VERSION = 'lp-nfl-team-box-3'
# The validated nflverse extract (stage_nflverse_pbp.py). Used only where the dev database lacks penalty fields.
EXTRACT_DIR = '/root/lp-snapshots/nfl-backfill-2026-10-27/extract'
EXTRACT_SEASONS = range(2010, 2027)
SEASONS = range(2010, 2027)
PENALTY_TEAM = {'LA': 'LAR', 'WAS': 'WSH'}
SCRIM = ('pass', 'run')
DRIVE_PLAY = ('pass', 'run', 'punt', 'field_goal', 'qb_kneel', 'qb_spike', 'kickoff')
RESULT_PLAY = ('pass', 'run', 'punt', 'field_goal', 'qb_kneel', 'qb_spike', 'kickoff')

FIELD_NOTES = {
    'pts_derived': 'Sum of scoring events: offensive TD 6, defensive or return TD 6 to the scoring team, FG made 3, PAT '
                   'good 1, two-point good 2, safety 2 to the defense. Kickoff return TD to the receiving team, punt '
                   'return TD to the defense.',
    'pts_q': 'Derived points by quarter, from the same events, using the play quarter.',
    'plays_off': 'Pass and run plays with the team in possession, sacks included, kneels and spikes excluded.',
    'total_yards': 'Sum of yards gained on pass and run plays (net of sacks), as ESPN defines it.',
    'sack_yards': 'Yards lost on sacks, reported as a positive number.',
    'first_downs': 'Pass and run plays whose gain reached the distance, or a touchdown, plus penalty first downs. Penalty '
                   'first downs come from nfl_pbp_penalty (2015 to 2025) and the nflverse extract (2010 to 2014 and 2026). '
                   'Null only where neither source covers the season.',
    'third_att': 'Pass and run plays on third down.',
    'third_conv': 'Third-down plays that gained the distance or scored.',
    'fourth_att': 'Pass and run plays on fourth down (fourth-down punts and field goals are excluded).',
    'drives': 'Distinct drive index with the team in possession and at least one drive play.',
    'scoring_drives': 'Drives whose result (series_result on the last result play) is Touchdown or Field goal.',
    'three_and_outs': 'Punt-ending drives with at most three scrimmage plays and no first down.',
    'rz_trips': 'Drives with a scrimmage play inside the 20.',
    'possession_sec': 'Derived from the game clock at the first play of each drive. Not validated against an official '
                      'figure; reconciled only by the sum over both teams.',
    'punt_yards': 'Not stored: the play data records 0 yards on punts.',
    'return_yards': 'Not stored: the play data records 0 yards on kickoffs and punts.',
    'pen_accepted': 'Not stored: the play data flags penalties but not accept or decline.',
    'turnovers': 'Interceptions thrown plus fumbles lost on offense. Null for seasons where the fumble-lost column is null.',
    'fumbles_lost': 'Offensive fumbles lost on scrimmage plays. Null for seasons where the column is null.',
    'pen_yards': 'Yards from flagged penalties on the team: nfl_pbp_penalty for 2015 to 2025, the nflverse extract for 2010 to '
                 '2014 and 2026. Zero when a source covers the season and the team has no flagged penalty. Null otherwise.',
    'pen_flagged': 'Flagged penalties on the team, from the play data. For 2026 the flags come from the nflverse extract, '
                   'matched play by play (the dev play table has none for 2026).',
    'points_per_drive': 'Schedule final score less the points that derived events credit to defense and special teams, '
                        'divided by drives. Offensive points only.',
}

BASE_COLS = ('game_id', 'season', 'week', 'game_type', 'team', 'opponent', 'home_away', 'points_for', 'points_against',
             'result')

FIELDS = ('pts_for', 'pts_against', 'margin', 'result', 'pts_q1', 'pts_q2', 'pts_q3', 'pts_q4', 'pts_ot',
          'plays_off', 'pass_att', 'pass_comp', 'pass_yds', 'pass_td', 'pass_int', 'sacks', 'sack_yards',
          'net_pass_yds', 'rush_att', 'rush_yds', 'rush_td', 'ypc', 'total_yards', 'yards_per_play', 'epa_per_play',
          'success_rate', 'explosive_pass', 'explosive_run', 'first_downs', 'third_att', 'third_conv', 'fourth_att',
          'fourth_conv', 'drives', 'points_per_drive', 'scoring_drives', 'punts', 'punt_drives', 'three_and_outs',
          'turnover_drives', 'rz_trips', 'rz_scores', 'rz_td', 'fg_att', 'fg_made', 'fg_missed', 'kickoffs_kicked',
          'fumbles', 'fumbles_lost', 'turnovers', 'turnover_diff', 'pen_flagged', 'pen_yards', 'possession_sec',
          'punt_yards', 'return_yards', 'pen_accepted', 'pen_declined', 'pen_offsetting', 'offensive_snaps')
NULL_BY_DESIGN = ('punt_yards', 'return_yards', 'pen_accepted', 'pen_declined', 'pen_offsetting', 'offensive_snaps')


def new_team():
    t = defaultdict(float)
    t['pts_q'] = defaultdict(int)
    t['drive_list'] = []
    return t


def penalty_yards_for(season, key, pen_yards, pen_seasons):
    """Penalty yards for one team-game: zero where the penalty table covers the season, null where it does not."""
    if season not in pen_seasons:
        return None
    return pen_yards.get(key, 0)


def penalty_flags_for(season, flag_seasons, count):
    """Flagged penalties for one team-game: null where the play data has no penalty flags for the season."""
    return count if season in flag_seasons else None


def qkey(qtr):
    if qtr is None:
        return None
    if qtr in (1, 2, 3, 4):
        return f'q{qtr}'
    return 'ot' if qtr >= 5 else None


def process_game(plays, fumble_lost_available):
    """Team totals for one game from its ordered plays. Returns ({team: stats}, special-teams TDs with no team)."""
    teams = {}

    def team(name):
        if name not in teams:
            teams[name] = new_team()
        return teams[name]

    def add_pts(name, q, n, offense=True):
        if name is None or q is None or n == 0:
            return
        t = team(name)
        t['pts'] = t.get('pts', 0) + n
        t['pts_q'][q] += n
        if not offense:
            t['st_pts'] += n

    drives = {}
    # Extra points still to come after a defensive or return touchdown. The team that scored kicks them.
    owed_pat = defaultdict(int)
    safety_drives = set()
    unassigned_st_td = 0
    for p in plays:
        pt, dt = p['posteam'], p['defteam']
        ptype = p['play_type']
        q = qkey(p['qtr'])
        yards = p['yards_gained'] or 0
        if pt and ptype in SCRIM:
            t = team(pt)
            t['plays_off'] += 1
            # Official passing attempts exclude sacks and two-point passes, and include spikes (see the spike rule below).
            if p['pass_attempt'] and not p['sack'] and p['two_point_attempt'] != 1:
                t['pass_att'] += 1
            t['pass_comp'] += p['complete_pass'] or 0
            t['pass_yds'] += p['passing_yards'] or 0
            t['pass_td'] += p['pass_touchdown'] or 0
            t['pass_int'] += p['interception'] or 0
            t['rush_att'] += p['rush_attempt'] or 0
            t['rush_yds'] += p['rushing_yards'] or 0
            t['rush_td'] += p['rush_touchdown'] or 0
            t['total_yards'] += yards
            if p['sack']:
                t['sacks'] += 1
                t['sack_yards'] += -yards if yards < 0 else 0
            if p['epa'] is not None:
                t['epa_sum'] += p['epa']
                t['epa_n'] += 1
            if p['success'] is not None:
                t['succ_sum'] += p['success']
                t['succ_n'] += 1
            if p['pass_attempt'] and yards >= 20:
                t['explosive_pass'] += 1
            if p['rush_attempt'] and yards >= 10:
                t['explosive_run'] += 1
            first = (p['ydstogo'] is not None and yards >= p['ydstogo']) or p['touchdown'] == 1
            if first:
                t['first_downs'] += 1
            if p['down'] == 3:
                t['third_att'] += 1
                t['third_conv'] += 1 if first else 0
            if p['down'] == 4:
                t['fourth_att'] += 1
                t['fourth_conv'] += 1 if first else 0
            if p['fumble']:
                t['fumbles'] += 1
            if fumble_lost_available and p['fumble_lost']:
                t['fumbles_lost'] += p['fumble_lost']
            if p['yardline_100'] is not None and p['yardline_100'] <= 20:
                t['rz_plays'] += 1
        if pt and ptype == 'qb_kneel':
            # A kneel is a rushing attempt and an offensive play in the official team stats, with the yards it lost.
            t = team(pt)
            t['rush_att'] += 1
            t['rush_yds'] += yards
            t['total_yards'] += yards
            t['plays_off'] += 1
        if pt and ptype == 'qb_spike':
            # A spike is an offensive play, and an incomplete pass in the official stats.
            t = team(pt)
            t['plays_off'] += 1
            if p['pass_attempt']:
                t['pass_att'] += 1
        if pt and ptype == 'kickoff' and p['fumble_lost'] and fumble_lost_available:
            # A receiving team that loses a fumble on a kickoff return commits a turnover.
            team(pt)['fumbles_lost'] += 1
        if pt and ptype == 'punt':
            team(pt)['punts'] += 1
        if pt and ptype == 'field_goal':
            t = team(pt)
            t['fg_att'] += 1
            if p['series_result'] == 'Field goal':
                t['fg_made'] += 1
            elif p['series_result'] == 'Missed field goal':
                t['fg_missed'] += 1
        if dt and ptype == 'kickoff':
            team(dt)['kickoffs_kicked'] += 1
        if p['penalty'] == 1 and p['penalty_team']:
            team(PENALTY_TEAM.get(p['penalty_team'], p['penalty_team']))['pen_flagged'] += 1
        # Points.
        if p['two_point_attempt'] == 1 and pt and p['success'] == 1:
            # A successful two-point play carries success = 1 and no touchdown flag.
            add_pts(pt, q, 2)
        if ptype in SCRIM and pt and p['touchdown'] == 1 and p['two_point_attempt'] != 1:
            if p['interception'] == 1 or p['fumble_lost'] == 1:
                add_pts(dt, q, 6, offense=False)
                owed_pat[dt] += 1
            elif p['pass_touchdown'] == 1 or p['rush_touchdown'] == 1:
                add_pts(pt, q, 6)
        if ptype == 'field_goal' and pt and p['series_result'] == 'Field goal':
            add_pts(pt, q, 3)
        if ptype == 'extra_point' and pt:
            owed = owed_pat[pt] > 0
            if owed:
                owed_pat[pt] -= 1
            if p['success'] == 1:
                add_pts(pt, q, 1, offense=not owed)
        if p['series_result'] == 'Safety' and dt and (pt, p['drive']) not in safety_drives:
            # The series result repeats on each play of the drive, so a safety is counted once per drive.
            safety_drives.add((pt, p['drive']))
            add_pts(dt, q, 2, offense=False)
        if ptype == 'kickoff' and pt and p['touchdown'] == 1:
            add_pts(pt, q, 6, offense=False)
            owed_pat[pt] += 1
        if ptype == 'punt' and dt and p['touchdown'] == 1:
            add_pts(dt, q, 6, offense=False)
            owed_pat[dt] += 1
        if ptype in ('kickoff', 'punt') and p['touchdown'] == 1 and not (pt or dt):
            unassigned_st_td += 1
        # Drives.
        if pt and ptype in DRIVE_PLAY:
            key = (pt, p['drive'])
            d = drives.get(key)
            if d is None:
                d = drives[key] = {'team': pt, 'first_play': p['play_id'], 'start_gsr': p['game_seconds_remaining'],
                                   'scrim': 0, 'firsts': 0, 'rz': False, 'result': None}
            if ptype in SCRIM:
                d['scrim'] += 1
                d['firsts'] += 1 if (p['ydstogo'] is not None and yards >= p['ydstogo']) or p['touchdown'] == 1 else 0
                if p['yardline_100'] is not None and p['yardline_100'] <= 20:
                    d['rz'] = True
            if p['series_result'] is not None and ptype in RESULT_PLAY:
                d['result'] = p['series_result']
            d['last_play'] = p['play_id']
    for d in drives.values():
        t = team(d['team'])
        t['drives'] += 1
        t['drive_list'].append(d)
        res = d['result']
        if res in ('Touchdown', 'Field goal'):
            t['scoring_drives'] += 1
        if res in ('Turnover', 'Turnover on downs', 'Opp touchdown'):
            t['turnover_drives'] += 1
        if res == 'Punt':
            t['punt_drives'] += 1
            if d['scrim'] <= 3 and d['firsts'] == 0:
                t['three_and_outs'] += 1
        if d['rz']:
            t['rz_trips'] += 1
            if res in ('Touchdown', 'Field goal'):
                t['rz_scores'] += 1
            if res == 'Touchdown':
                t['rz_td'] += 1
    # Possession time: each drive lasts until the next drive starts, using the game clock.
    order = sorted((d for t in teams.values() for d in t['drive_list']), key=lambda d: d['first_play'])
    for i, d in enumerate(order):
        if d['start_gsr'] is None:
            continue
        nxt = order[i + 1]['start_gsr'] if i + 1 < len(order) and order[i + 1]['start_gsr'] is not None else 0
        team(d['team'])['possession_sec'] += max(0, d['start_gsr'] - nxt)
    return teams, unassigned_st_td


def finish(name, t, base, fumble_lost_available, pen_yards):
    """A complete row for one team-game, with nulls where the data cannot support a value."""
    row = {c: base[c] for c in BASE_COLS}
    pts_for, pts_against = base['points_for'], base['points_against']
    row['margin'] = None if pts_for is None or pts_against is None else pts_for - pts_against
    pts_q = t['pts_q']
    row.update({'pts_q1': pts_q.get('q1', 0), 'pts_q2': pts_q.get('q2', 0), 'pts_q3': pts_q.get('q3', 0),
                'pts_q4': pts_q.get('q4', 0), 'pts_ot': pts_q.get('ot', 0)})
    row['pts_derived'] = t.get('pts', 0)
    row['pts_residual'] = None if pts_for is None else pts_for - row['pts_derived']
    plays = t['plays_off']
    row['plays_off'] = plays
    for k in ('pass_att', 'pass_comp', 'pass_yds', 'pass_td', 'pass_int', 'sacks', 'sack_yards', 'rush_att', 'rush_yds',
              'rush_td', 'total_yards', 'explosive_pass', 'explosive_run', 'first_downs', 'third_att', 'third_conv',
              'fourth_att', 'fourth_conv', 'drives', 'scoring_drives', 'punts', 'punt_drives', 'three_and_outs',
              'turnover_drives', 'rz_trips', 'rz_scores', 'rz_td', 'fg_att', 'fg_made', 'fg_missed',
              'kickoffs_kicked', 'pen_flagged'):
        row[k] = int(t[k])
    row['net_pass_yds'] = row['pass_yds'] - row['sack_yards']
    row['ypc'] = round(row['rush_yds'] / row['rush_att'], 3) if row['rush_att'] else None
    row['yards_per_play'] = round(row['total_yards'] / plays, 3) if plays else None
    row['epa_per_play'] = round(t['epa_sum'] / t['epa_n'], 4) if t['epa_n'] else None
    row['success_rate'] = round(t['succ_sum'] / t['succ_n'], 4) if t['succ_n'] else None
    # The final score stays authoritative. Only the derived defense and special-teams points are subtracted from it.
    off_pts = None if pts_for is None else pts_for - int(t['st_pts'])
    if off_pts is not None and off_pts < 0:
        # The derived defense and special-teams points exceed the final score, so the offensive share is unknown.
        off_pts = None
    row['points_per_drive'] = round(off_pts / row['drives'], 3) if off_pts is not None and row['drives'] else None
    row['fumbles'] = int(t['fumbles'])
    row['fumbles_lost'] = int(t['fumbles_lost']) if fumble_lost_available else None
    row['turnovers'] = (row['pass_int'] + row['fumbles_lost']) if fumble_lost_available else None
    row['possession_sec'] = int(t['possession_sec']) if t['drive_list'] else None
    row['pen_yards'] = pen_yards
    row['punt_yards'] = None
    row['return_yards'] = None
    row['pen_accepted'] = None
    row['pen_declined'] = None
    row['pen_offsetting'] = None
    row['offensive_snaps'] = None
    row['turnover_diff'] = None
    return row


def extract_penalty_plays(seasons):
    """(game_id, play_id) -> (penalty, penalty_team, penalty_yards, first_down_penalty) from the validated nflverse extract.

    Used only for seasons the dev database does not carry: the penalty table for 2010 to 2014 and 2026, and the play
    penalty flags for 2026. On 2015 to 2025 the extract matches the dev database exactly (validate_nflverse_penalty.py).
    """
    import pyarrow.parquet as pq
    out = {}
    for season in seasons:
        table = pq.read_table(f'{EXTRACT_DIR}/penalty_return_{season}.parquet',
                              columns=['game_id', 'play_id', 'penalty', 'penalty_team', 'penalty_yards',
                                       'first_down_penalty']).to_pylist()
        for r in table:
            out[(r['game_id'], int(r['play_id']))] = (r['penalty'], r['penalty_team'], r['penalty_yards'],
                                                      r['first_down_penalty'])
    return out


def penalty_sources(dev):
    """The seasons each source supplies. The dev database is used where it carries the field; the extract elsewhere."""
    dev_pen = {s for (s,) in dev.execute('select distinct season from nfl_pbp_penalty')}
    dev_flag = {s for (s,) in dev.execute('select distinct season from nfl_pbp where penalty is not null')}
    ext_pen = sorted(s for s in EXTRACT_SEASONS if s not in dev_pen)
    ext_flag = sorted(s for s in EXTRACT_SEASONS if s not in dev_flag)
    return dev_pen, dev_flag, ext_pen, ext_flag


def load_pen_totals(dev, extract_plays):
    """(game, penalty team) -> penalty yards and penalty first downs. The dev penalty table for its seasons, and the
    extract's flagged plays for the seasons it supplies (extract_plays holds only those seasons)."""
    yards, first = {}, {}
    for gid, team, y, f in dev.execute("""select game_id, penalty_team, sum(penalty_yards), sum(first_down_penalty)
            from nfl_pbp_penalty where penalty = 1 and penalty_team is not null group by game_id, penalty_team"""):
        key = (gid, PENALTY_TEAM.get(team, team))
        yards[key] = y or 0
        first[key] = f or 0
    for (gid, _), (pen, team, y, f) in extract_plays.items():
        if pen == 1 and team is not None:
            key = (gid, PENALTY_TEAM.get(team, team))
            yards[key] = yards.get(key, 0) + (y or 0)
            first[key] = first.get(key, 0) + (f or 0)
    return yards, first


def build_rows(dev, layer):
    """Every team-game: play-derived for the regular season, base results only for postseason games."""
    base = {}
    for r in layer.execute(f"select {', '.join(BASE_COLS)} from team_game"):
        base[(r[0], r[4])] = dict(zip(BASE_COLS, r))
    dev_pen, dev_flag, ext_pen, ext_flag = penalty_sources(dev)
    extract_plays = extract_penalty_plays(sorted(set(ext_pen) | set(ext_flag)))
    pen_yards, pen_first = load_pen_totals(dev, extract_plays)
    pen_seasons = set(dev_pen) | set(ext_pen)
    flag_seasons = set(dev_flag) | set(ext_flag)
    rows, st_unassigned = [], 0
    overlay_missing = 0
    for season in SEASONS:
        cur = dev.execute("""select game_id, play_id, posteam, defteam, qtr, down, ydstogo, yardline_100,
            game_seconds_remaining, play_type, epa, success, yards_gained, complete_pass, touchdown, pass_attempt,
            rush_attempt, passing_yards, rushing_yards, pass_touchdown, rush_touchdown, interception, fumble,
            fumble_lost, sack, two_point_attempt, penalty, penalty_team, series_result, drive
            from nfl_pbp where season = ? order by game_id, play_id""", (season,))
        names = [c[0] for c in cur.description]
        fl_nonnull = dev.execute('select count(*) from nfl_pbp where season = ? and fumble_lost is not null',
                                 (season,)).fetchone()[0]
        fumble_lost_available = fl_nonnull > 0
        games = defaultdict(list)
        for values in cur:
            p = dict(zip(names, values))
            if season in ext_flag:
                # The dev play table has no penalty flags for this season: take them from the extract, play by play.
                hit = extract_plays.get((p['game_id'], int(p['play_id'])))
                if hit is None:
                    overlay_missing += 1
                    continue
                p['penalty'], p['penalty_team'] = hit[0], hit[1]
            games[p['game_id']].append(p)
        if overlay_missing:
            raise SystemExit(f'{overlay_missing} plays in {season} have no row in the penalty extract')
        for gid, game_plays in games.items():
            teams, unassigned = process_game(game_plays, fumble_lost_available)
            st_unassigned += unassigned
            for name, t in teams.items():
                key = (gid, name)
                if key not in base:
                    continue
                penalty_yards = penalty_yards_for(season, key, pen_yards, pen_seasons)
                row = finish(name, t, base[key], fumble_lost_available, penalty_yards)
                row['pen_flagged'] = penalty_flags_for(season, flag_seasons, row['pen_flagged'])
                rows.append(row)
    # Penalty first downs: a defensive foul that gives the offense the first down counts toward the team that
    # gained it, which is the other team in the game.
    by_game = defaultdict(dict)
    for r in rows:
        by_game[r['game_id']][r['team']] = r
    for teams_in_game in by_game.values():
        for name, r in teams_in_game.items():
            gained = sum(pen_first.get((r['game_id'], other), 0) for other in teams_in_game if other != name)
            if r['first_downs'] is not None:
                # Null where the penalty table does not cover the season: the penalty first downs are then unknown.
                r['first_downs'] = r['first_downs'] + gained if r['season'] in pen_seasons else None
    # Turnover differential needs the opponent's turnovers in the same game.
    for teams_in_game in by_game.values():
        for r in teams_in_game.values():
            opps = [o for name, o in teams_in_game.items() if name != r['team']]
            if opps and r['turnovers'] is not None and opps[0]['turnovers'] is not None:
                r['turnover_diff'] = opps[0]['turnovers'] - r['turnovers']
    # Postseason games: base results only. Their play counts are not in the play-by-play archive.
    for (gid, name), b in base.items():
        if b['game_type'] != 'REG' and b['season'] in SEASONS:
            row = {c: b[c] for c in BASE_COLS}
            row['margin'] = None if b['points_for'] is None else b['points_for'] - b['points_against']
            for k in FIELDS:
                row.setdefault(k, None)
            row['pts_derived'] = None
            row['pts_residual'] = None
            rows.append(row)
    return rows, st_unassigned


def coverage(rows, columns):
    by_season = defaultdict(lambda: defaultdict(lambda: [0, 0]))
    for r in rows:
        for c in columns:
            by_season[r['season']][c][1] += 1
            if r.get(c) is not None:
                by_season[r['season']][c][0] += 1
    out = []
    for season in sorted(by_season):
        for c in columns:
            non_null, total = by_season[season][c]
            out.append((season, c, non_null, total))
    return out


def reconcile(dev, rows):
    """Checks against independent sources. Each returns (check, season, compared, matched, median_abs_error, note)."""
    out = []
    reg = [r for r in rows if r['game_type'] == 'REG']
    by_key = {(r['game_id'], r['team']): r for r in reg}
    # 1. Points against the schedule's final score.
    sched = {}
    for gid, season, home, away, hs, as_ in dev.execute(
            'select game_id, season, home_team, away_team, home_score, away_score from nfl_schedule '
            'where home_score is not null and game_type = ?', ('REG',)):
        sched[gid] = (home, away, hs, as_)
    for season in SEASONS:
        errs, match, n = [], 0, 0
        for (gid, team), r in by_key.items():
            if r['season'] != season or gid not in sched:
                continue
            home, away, hs, as_ = sched[gid]
            final = hs if team == home else as_
            if r['pts_derived'] is None:
                continue
            n += 1
            err = abs(r['pts_derived'] - final)
            errs.append(err)
            match += err == 0
        if n:
            out.append(('points_derived_vs_schedule', season, n, match,
                        statistics.median(errs), 'exact match on the final score'))
    # 2. Team-game yards, plays and first downs against ESPN's 2025 team totals (the only ESPN NFL team box in the store).
    # team_game_stats is keyed by ESPN event ID, so the nfl_game_xwalk table maps each event to the nflverse game ID.
    xwalk = dict(dev.execute('select espn, game_id from nfl_game_xwalk where espn is not null'))
    espn = {}
    for espn_id, team, plays, yards, net_pass, rush, first_downs, turnovers in dev.execute(
            """select game_id, team_abbrev, total_offensive_plays, total_yards, net_passing_yards, rushing_yards,
            first_downs, turnovers from team_game_stats where league = 'nfl'"""):
        gid = xwalk.get(espn_id)
        if gid is None:
            continue
        espn[(gid, team)] = (plays, yards, net_pass, rush, first_downs, turnovers)
    for check, idx, label in (('espn_total_plays', 0, 'plays_off'), ('espn_total_yards', 1, 'total_yards'),
                              ('espn_net_passing_yards', 2, 'net_pass_yds'), ('espn_rushing_yards', 3, 'rush_yds'),
                              ('espn_first_downs', 4, 'first_downs'), ('espn_turnovers', 5, 'turnovers')):
        errs, match, n = [], 0, 0
        for key, vals in espn.items():
            r = by_key.get(key)
            if r is None or r['season'] != 2025 or vals[idx] is None or r[label] is None:
                continue
            n += 1
            err = abs(r[label] - vals[idx])
            errs.append(err)
            match += err == 0
        if n:
            out.append((check, 2025, n, match, statistics.median(errs),
                        'ESPN team total; derived field compared'))
    # 3. Passing and rushing yards, attempts and touchdowns against the player game logs (team sums).
    logs = defaultdict(lambda: defaultdict(float))
    for gid, team, season, stats in dev.execute("""select l.game_id, l.team, l.season, l.stats from player_game_logs l
            where l.league = 'nfl' and l.source = 'nflverse_weekly' and l.game_type in ('REG','POST')"""):
        s = json.loads(stats)
        for k in ('pass_yds', 'rush_yds', 'att', 'carries', 'pass_td', 'rush_td', 'intc', 'sacks_taken'):
            logs[(gid, team)][k] += s.get(k) or 0
    for check, label, log_key in (('logs_pass_yards', 'pass_yds', 'pass_yds'),
                                  ('logs_rush_yards', 'rush_yds', 'rush_yds'),
                                  ('logs_pass_attempts', 'pass_att', 'att'),
                                  ('logs_rush_attempts', 'rush_att', 'carries'),
                                  ('logs_pass_td', 'pass_td', 'pass_td'),
                                  ('logs_rush_td', 'rush_td', 'rush_td'),
                                  ('logs_interceptions', 'pass_int', 'intc'),
                                  ('logs_sacks', 'sacks', 'sacks_taken')):
        by_season = defaultdict(lambda: [0, 0, []])
        for key, r in by_key.items():
            if key not in logs or r[label] is None:
                continue
            ref = logs[key][log_key]
            entry = by_season[r['season']]
            entry[0] += 1
            err = abs(r[label] - ref)
            entry[2].append(err)
            entry[1] += err == 0
        for season, (n, match, errs) in sorted(by_season.items()):
            out.append((check, season, n, match, statistics.median(errs),
                        'team sum of player game logs; nflverse weekly'))
    # 4. Carries and targets against nflverse team totals (2025 and 2026).
    for check, label, col in (('nflverse_team_carries', 'rush_att', 'carries'),
                              ('nflverse_team_targets', None, 'targets')):
        if label is None:
            continue
        by_season = defaultdict(lambda: [0, 0, []])
        for gid, team, season, val in dev.execute(
                'select game_id, team, season, carries from nfl_team_game_totals'):
            r = by_key.get((gid, team))
            if r is None or r[label] is None or val is None:
                continue
            entry = by_season[season]
            entry[0] += 1
            err = abs(r[label] - val)
            entry[2].append(err)
            entry[1] += err == 0
        for season, (n, match, errs) in sorted(by_season.items()):
            out.append((check, season, n, match, statistics.median(errs), 'nflverse team totals'))
    return out


def file_sha(path):
    digest = hashlib.sha256()
    with open(path, 'rb') as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b''):
            digest.update(chunk)
    return digest.hexdigest()


SCHEMA = """
create table meta (key text primary key, value text);
create table team_box_score (
    game_id text not null, season integer not null, week integer, game_type text, team text not null,
    opponent text, home_away text, points_for integer, points_against integer, margin integer, result text,
    pts_derived integer, pts_residual integer,
    pts_q1 integer, pts_q2 integer, pts_q3 integer, pts_q4 integer, pts_ot integer,
    plays_off integer, pass_att integer, pass_comp integer, pass_yds integer, pass_td integer, pass_int integer,
    sacks integer, sack_yards integer, net_pass_yds integer, rush_att integer, rush_yds integer, rush_td integer,
    ypc real, total_yards integer, yards_per_play real, epa_per_play real, success_rate real,
    explosive_pass integer, explosive_run integer, first_downs integer,
    third_att integer, third_conv integer, fourth_att integer, fourth_conv integer,
    drives integer, points_per_drive real, scoring_drives integer, punts integer, punt_drives integer,
    three_and_outs integer, turnover_drives integer, rz_trips integer, rz_scores integer, rz_td integer,
    fg_att integer, fg_made integer, fg_missed integer, kickoffs_kicked integer,
    fumbles integer, fumbles_lost integer, turnovers integer, turnover_diff integer,
    pen_flagged integer, pen_yards integer, possession_sec integer,
    punt_yards integer, return_yards integer, pen_accepted integer, pen_declined integer, pen_offsetting integer,
    offensive_snaps integer,
    primary key (game_id, team));
create table team_box_coverage (
    season integer not null, field text not null, non_null integer not null, total integer not null,
    primary key (season, field));
create table team_box_reconciliation (
    check_name text not null, season integer not null, compared integer not null, matched integer not null,
    median_abs_error real, note text,
    primary key (check_name, season));
"""


def build(out, dev_uri=DEV_DB, layer_path=LAYER):
    if os.path.exists(out):
        raise SystemExit(f'refusing to overwrite {out}')
    os.makedirs(os.path.dirname(out), exist_ok=True)
    dev = sqlite3.connect(dev_uri, uri=True)
    layer = sqlite3.connect(f'file:{layer_path}?mode=ro', uri=True)
    rows, st_unassigned = build_rows(dev, layer)
    cov = coverage(rows, FIELDS + ('pts_derived', 'pts_residual'))
    recon = reconcile(dev, rows)
    db = sqlite3.connect(out)
    db.executescript(SCHEMA)
    cols = ['game_id', 'season', 'week', 'game_type', 'team', 'opponent', 'home_away', 'points_for', 'points_against',
            'margin', 'result', 'pts_derived', 'pts_residual'] + list(FIELDS[4:])
    cols = [c for c in cols if c not in ('points_for_placeholder',)]
    values = []
    for r in rows:
        values.append(tuple(r.get(c) for c in cols))
    db.executemany(f'insert into team_box_score ({",".join(cols)}) values ({",".join("?" * len(cols))})', values)
    db.executemany('insert into team_box_coverage values (?,?,?,?)', cov)
    db.executemany('insert into team_box_reconciliation values (?,?,?,?,?,?)', recon)
    meta = {'schema': SCHEMA_VERSION, 'layer_sha256': file_sha(layer_path), 'rows': len(rows),
            'regular_season_rows': sum(1 for r in rows if r['game_type'] == 'REG'),
            'postseason_rows': sum(1 for r in rows if r['game_type'] != 'REG'),
            'special_teams_td_plays_without_team': st_unassigned,
            'field_notes': FIELD_NOTES}
    for key, value in meta.items():
        db.execute('insert into meta values (?, ?)', (key, json.dumps(value)))
    db.commit()
    db.close()
    return meta


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--out', default=DEFAULT_OUT)
    args = ap.parse_args()
    meta = build(args.out)
    print(json.dumps({k: v for k, v in meta.items() if k != 'field_notes'}, indent=1, sort_keys=True))


if __name__ == '__main__':
    main()
