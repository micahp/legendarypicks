#!/usr/bin/env python3
"""Week 7 Madden 27 matchup experiment: research only, no trained model.

Inputs (all read-only):
  --zip          Madden ratings archive; the 2027 release is the 2026 NFL season
  --identity     identity_crosswalk.csv from scripts/madden/identity_crosswalk.py
  --picks-db     Legendary Picks dev database (schedule, projections, snap counts, players)

Outputs:
  --derived-dir  player-level rows (raw ratings): keep outside git
  --docs-json    team- and game-level aggregates only: commit-safe
  --frozen-json  pre-kickoff freeze record: inputs, timestamps, git revision

Method:
  1. Starters come from usage, not from ratings: average offense or defense snap share over
     NFL weeks 1-5 (the weeks with full coverage). Week 6 covers only 28 teams. Week 7 has not
     been played, so no week-7 production enters any weight.
  2. A starter is linked to Madden 27 only through a high-tier GSIS identity. Name-only
     matches are reported as review and never used. Missing players stay missing.
  3. Each attribute is a percentile within the Madden 27 population of the same position
     group, so scores are comparable across positions.
  4. Responsibility composites are fixed attribute lists (COMP). Within a unit, equal weights.
     A usage-weighted version runs alongside as the sensitivity check.
  5. Matchup differences are percentile-point differences. They are never converted into
     yards, points, spreads or probabilities.
"""

import argparse
import bisect
import csv
import datetime
import hashlib
import io
import json
import os
import sqlite3
import statistics
import subprocess
import sys
import zipfile
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..'))
from audit_madden_ratings import IDENTITY, POS_GROUP, norm_name  # noqa: E402
from identity_crosswalk import NFL_GROUP  # noqa: E402

SEASON = 2026
WEEK = 7
ROLES = {'QB': 1, 'RB': 1, 'WR': 3, 'TE': 1, 'OL': 5, 'DL': 4, 'LB': 3, 'DB': 5}
OFFENSE = {'QB', 'RB', 'WR', 'TE', 'OL'}
DEFENSE = {'DL', 'LB', 'DB'}
MIN_COVERAGE_SHARE = 0.6  # a dimension needs at least this share of its expected players on both sides

# Responsibility composites: fixed attribute lists.
COMP = {
    'QB': ['THP', 'TAS', 'TAM', 'TAD', 'PAC', 'TOR', 'TUP', 'AWR'],
    'REC': ['SPD', 'ACC', 'AGI', 'SRR', 'MRR', 'DRR', 'RLS', 'CTH', 'CIT', 'SPC'],
    'RB': ['SPD', 'ACC', 'COD', 'CAR', 'BCV', 'BTK', 'TRK', 'ELU'],
    'PBLK': ['PBK', 'PBP', 'PBF'],
    'RBLK': ['RBK', 'RBP', 'RBF'],
    'PRUSH': ['PMV', 'FMV', 'ACC'],
    'RDEF': ['BSH', 'STR', 'TAK'],
    'MAN': ['MCV', 'PRS', 'PRC', 'SPD', 'ACC'],
    'ZONE': ['ZCV', 'SPD', 'ACC'],
    'TACK': ['TAK', 'PUR', 'POW'],
}
COMP_ROLES = {
    'QB': ['QB'], 'REC': ['WR', 'TE'], 'RB': ['RB'], 'PBLK': ['OL'], 'RBLK': ['OL'],
    'PRUSH': ['DL'], 'RDEF': ['DL', 'LB'], 'MAN': ['DB'], 'ZONE': ['DB'], 'TACK': ['DB', 'LB'],
}
REPORTED_ONLY = {
    'IBL': 'impact blocking applies to run and pass, so it is not forced into either index',
    'TAC': 'historical label, not THA: never merged into a Gridiron rating',
    'TAS/TAM/TAD': 'used per depth in the QB profile, not averaged into one accuracy score',
    'SRR/MRR/DRR': 'route-running depths are kept separate inside the REC composite',
}
DIMS = [
    ('pass_protection_vs_pass_rush', 'PBLK', 'PRUSH'),
    ('run_blocking_vs_run_defense', 'RBLK', 'RDEF'),
    ('qb_vs_man_coverage', 'QB', 'MAN'),
    ('qb_vs_zone_coverage', 'QB', 'ZONE'),
    ('receivers_vs_man_coverage', 'REC', 'MAN'),
    ('receivers_vs_zone_coverage', 'REC', 'ZONE'),
    ('rb_vs_tackling', 'RB', 'TACK'),
]
NEUTRAL_MARGIN = 1.0  # LP margin inside this band is treated as a neutral projection
NEUTRAL_NET = 2.0     # percentile points: ratings net inside this band is neutral


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


def git_rev():
    try:
        return subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=HERE, text=True).strip()
    except Exception as e:  # recorded, not swallowed
        return f'unavailable: {e}'


def load_madden(zip_path):
    zf = zipfile.ZipFile(zip_path)
    rows = list(csv.DictReader(io.StringIO(zf.read('out/madden_ratings_long.csv').decode('utf-8'))))
    attrs = list(rows[0].keys())[len(IDENTITY):]
    names_any = defaultdict(set)
    for r in rows:
        names_any[norm_name(r['player_name'])].add(int(r['madden_release']))
    rel = [r for r in rows if r['madden_release'] == '2027']
    stints = defaultdict(list)  # player_id -> 2027 rows (one per team stint)
    for r in rel:
        stints[r['player_id']].append(r)
    names_2027 = defaultdict(list)
    for r in rel:
        names_2027[norm_name(r['player_name'])].append(r)
    dup_ids = sorted(k for k, v in stints.items() if len(v) > 1)
    return rel, stints, attrs, dup_ids, names_any, names_2027


def load_identity(path):
    gsis_to_ids = defaultdict(set)
    with open(path, newline='') as f:
        for r in csv.DictReader(f):
            if r['tier'] == 'high_unique_name_position_match' and r['gsis_id']:
                gsis_to_ids[r['gsis_id']].add(r['player_id'])
    ambiguous = sorted(g for g, v in gsis_to_ids.items() if len(v) > 1)
    unique = {g: next(iter(v)) for g, v in gsis_to_ids.items() if len(v) == 1}
    return unique, ambiguous


def percentile_tables(madden_rows, attrs):
    pop = defaultdict(list)
    for r in madden_rows:
        g = POS_GROUP.get(r['POS'].strip().split('/')[0], 'OTHER')
        for a in attrs:
            v = r[a].strip()
            if v:
                pop[(g, a)].append(int(v))
    return {k: sorted(v) for k, v in pop.items()}


def pct(value, sorted_vals):
    return 100.0 * bisect.bisect_right(sorted_vals, value) / len(sorted_vals)


def composite(row, attrs_list, group, tables):
    """Mean percentile of the present attributes; (None, 0) when none are present."""
    vals = []
    for a in attrs_list:
        v = row.get(a, '').strip()
        if v and (group, a) in tables:
            vals.append(pct(int(v), tables[(group, a)]))
    if not vals:
        return None, 0
    return sum(vals) / len(vals), len(vals)


FINAL_EVENTS = {'2026_07_NE_CHI': '401873010'}  # ESPN event for the completed Thursday game


def final_score(picks_db, event_id, home, away):
    """Final score from the stored ESPN summary. Fails loudly if the event does not show these two teams."""
    con = sqlite3.connect('file:' + picks_db + '?mode=ro', uri=True)
    row = con.execute('select payload from game_summaries where espn_event_id=?', (event_id,)).fetchone()
    con.close()
    if row is None:
        raise SystemExit(f'FAIL: no game_summaries row for event {event_id}')
    data = json.loads(row[0])
    comp = (data.get('header', {}).get('competitions') or data.get('competitions') or [{}])[0]
    scores = {c['team']['abbreviation']: int(float(c['score'])) for c in comp.get('competitors', [])
              if c.get('score') not in (None, '')}
    if home not in scores or away not in scores:
        raise SystemExit(f'FAIL: event {event_id} does not show {home} and {away}: {sorted(scores)}')
    return {'home': scores[home], 'away': scores[away], 'margin_home_minus_away': scores[home] - scores[away],
            'source': f'game_summaries.espn_event_id={event_id}'}


def pick_stint(stints, team_code, slug_to_code):
    """Choose the 2027 row for a player. Multi-stint players get the row whose team matches the snapshot."""
    if not stints:
        return None, 'no_2027_row'
    same = [r for r in stints if slug_to_code.get(r['team'].strip().lower()) == team_code]
    if len(same) == 1:
        return same[0], 'stint_team_match'
    if len(stints) == 1:
        return stints[0], 'single_row'
    return stints[0], 'stint_unresolved'


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--zip', required=True)
    ap.add_argument('--identity', required=True)
    ap.add_argument('--picks-db', required=True)
    ap.add_argument('--derived-dir', required=True)
    ap.add_argument('--docs-json', required=True)
    ap.add_argument('--frozen-json', required=True)
    ap.add_argument('--include-review-name-team-position', action='store_true',
                    help='sensitivity only: include starters whose name, team and position agree in 2027 '
                         'but who have no high-tier GSIS link')
    args = ap.parse_args()
    os.makedirs(args.derived_dir, exist_ok=True)

    now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    madden_rel, stints_by_id, attrs, dup_ids, names_any, names_2027 = load_madden(args.zip)
    gsis_map, gsis_ambiguous = load_identity(args.identity)
    tables = percentile_tables(madden_rel, attrs)

    con = sqlite3.connect('file:' + args.picks_db + '?mode=ro', uri=True)
    q = con.execute
    team_code = {}
    for code, name in q("select team, team_name from nfl_teams where season=?", (SEASON,)):
        team_code[name.split()[-1].lower()] = code
    slug_to_code, unmapped_slugs = {}, set()
    for r in madden_rel:
        s = r['team'].strip().lower()
        if s:
            if s in team_code:
                slug_to_code[s] = team_code[s]
            else:
                unmapped_slugs.add(s)
    lp_players = {pid: dict(name=n, team=t, pos=p, gsis=g)
                  for pid, n, t, p, g in q("select id, name, team, position, nfl_gsis_id from players "
                                           "where league='nfl' and nfl_gsis_id is not null")}
    snaps = defaultdict(lambda: {'weeks': set(), 'off': [], 'def': [], 'team': None, 'team_week': -1})
    for pid, week, team, off, dfn in q(
            "select player_id, week, team, off_pct, def_pct from nfl_snap_counts "
            "where season=? and week between 1 and 5", (SEASON,)):
        s = snaps[pid]
        s['weeks'].add(week)
        if off is not None:
            s['off'].append(off)
        if dfn is not None:
            s['def'].append(dfn)
        if week > s['team_week']:
            s['team'], s['team_week'] = team, week
    injuries = {}
    for gsis, week, status in q("select gsis_id, week, report_status from injury_reports where season=?",
                                (SEASON,)):
        if gsis not in injuries or week > injuries[gsis][0]:
            injuries[gsis] = (week, status)
    week7_injury_rows = q("select count(*) from injury_reports where season=? and week=?",
                          (SEASON, WEEK)).fetchone()[0]
    txns = dict(q("select team_abbr, count(*) from nfl_transactions where txn_date >= '2026-08-04' "
                  "group by team_abbr"))
    games = q("select game_id, weekday, gameday, gametime, away_team, home_team from nfl_schedule "
              "where season=? and week=? order by gameday, gametime", (SEASON, WEEK)).fetchall()
    proj = {}
    for row in q("""select g.game_id, g.home, g.away, g.proj_home, g.proj_away, g.proj_margin, g.proj_total,
                    g.p_home_win, g.market_spread, g.market_total, g.run_id
                    from game_projections g
                    join (select game_id, max(run_id) rid from game_projections
                          where season=? and week=? and run_id like 'nfl-preview-v1-%' group by game_id) m
                      on m.game_id=g.game_id and m.rid=g.run_id""", (SEASON, WEEK)):
        proj[row[0]] = dict(zip(['home', 'away', 'proj_home', 'proj_away', 'proj_margin', 'proj_total',
                                 'p_home_win', 'market_spread', 'market_total', 'run_id'], row[1:]))
    lp_proj_week6 = q("select count(distinct player_id) from player_projections where league='nfl' and season=? "
                      "and week=?", (SEASON, WEEK - 1)).fetchone()[0]
    lp_proj_week7 = q("select count(*) from player_projections where league='nfl' and season=? and week=?",
                      (SEASON, WEEK)).fetchone()[0]
    con.close()

    # Starters by usage (weeks 1-5), then linked to Madden 27 through identity only.
    candidates = defaultdict(list)
    for pid, s in snaps.items():
        if pid not in lp_players or len(s['weeks']) < 2 or s['team'] is None:
            continue
        p = lp_players[pid]
        group = NFL_GROUP.get(p['pos'] or '')
        if group is None or group not in ROLES:
            continue
        if group in OFFENSE and s['off']:
            usage = statistics.mean(s['off'])
        elif group in DEFENSE and s['def']:
            usage = statistics.mean(s['def'])
        else:
            usage = 0.0
        candidates[(s['team'], group)].append((usage, pid))

    lineup = defaultdict(lambda: defaultdict(list))
    for (team, group), items in candidates.items():
        items.sort(reverse=True)
        for usage, pid in items[:ROLES[group]]:
            p = lp_players[pid]
            madden_id = gsis_map.get(p['gsis'])
            if madden_id:
                mrow, stint = pick_stint(stints_by_id.get(madden_id, []), team, slug_to_code)
            else:
                mrow, stint = None, 'no_high_tier_identity'
            if mrow is not None:
                status = 'matched_2027'
            elif madden_id:
                status = 'high_identity_no_2027_row'
            else:
                same_name_2027 = names_2027.get(norm_name(p['name']), [])
                tp_rows = [r for r in same_name_2027
                           if slug_to_code.get(r['team'].strip().lower()) == team and
                           POS_GROUP.get(r['POS'].strip().split('/')[0], 'OTHER') == group]
                if tp_rows:
                    status = 'review_name_team_position_in_2027'
                    if args.include_review_name_team_position:
                        # Sensitivity only: name, team and position agree, but no high-tier GSIS link exists.
                        mrow, stint = tp_rows[0], 'review_name_team_position'
                        status = 'review_included_name_team_position'
                elif same_name_2027:
                    status = 'review_name_only_in_2027'
                elif norm_name(p['name']) in names_any:
                    status = 'no_identity_name_in_other_release'
                else:
                    status = 'no_identity_name_absent_from_archive'
            mgroup = POS_GROUP.get(mrow['POS'].strip().split('/')[0], 'OTHER') if mrow else None
            lineup[team][group].append({
                'lp_player_id': pid, 'name': p['name'], 'gsis': p['gsis'], 'lp_position': p['pos'],
                'role': group, 'usage': round(usage, 2), 'weeks_seen': len(snaps[pid]['weeks']),
                'madden_player_id': madden_id, 'stint': stint, 'status': status,
                'madden_team_blank': bool(mrow and not mrow['team'].strip()),
                'madden_group': mgroup,
                'position_agrees': (mgroup == group) if mrow else None,
                'injury_last_known': injuries.get(p['gsis'], (None, None)),
                'attr_row': mrow,
            })

    team_units, coverage_rows = {}, []
    for code in sorted(set(team_code.values())):
        starters = [e for role in ROLES for e in lineup[code].get(role, [])]
        matched = [e for e in starters if e['attr_row'] is not None]
        comp_eq, comp_usage, comp_n = {}, {}, {}
        for comp, roles in COMP_ROLES.items():
            contrib = []
            for role in roles:
                for e in lineup[code].get(role, []):
                    if e['attr_row'] is None:
                        continue
                    val, n = composite(e['attr_row'], COMP[comp], role, tables)
                    if val is not None:
                        contrib.append((val, e['usage'], n))
            if contrib:
                comp_eq[comp] = round(statistics.mean(v for v, _, _ in contrib), 2)
                tot = sum(u for _, u, _ in contrib)
                comp_usage[comp] = round(sum(v * u for v, u, _ in contrib) / tot, 2) if tot > 0 else None
            else:
                comp_eq[comp], comp_usage[comp] = None, None
            comp_n[comp] = len(contrib)
        team_units[code] = {'equal': comp_eq, 'usage': comp_usage, 'n': comp_n}
        status_counts = Counter_(e['status'] for e in starters)
        coverage_rows.append({
            'team': code,
            'starters_identified': len(starters),
            'matched_2027': len(matched),
            'matched_share': round(len(matched) / len(starters), 2) if starters else None,
            'status': dict(sorted(status_counts.items())),
            'madden_team_blank_among_matched': sum(1 for e in matched if e['madden_team_blank']),
            'stint_unresolved': sum(1 for e in matched if e['stint'] == 'stint_unresolved'),
            'position_group_disagreements': sum(1 for e in matched if e['position_agrees'] is False),
            'low_usage_starters': sum(1 for e in starters if e['weeks_seen'] < 3),
            'last_known_out_or_doubtful': sum(1 for e in starters
                                              if (e['injury_last_known'][1] or '') in ('Out', 'Doubtful')),
            'transactions_since_2026_08_04': txns.get(code, 0),
        })

    def expected(comp):
        return sum(ROLES[r] for r in COMP_ROLES[comp])

    game_out = []
    for gid, weekday, gameday, gametime, away, home in games:
        completed = gameday < '2026-10-25'  # the Thursday NE-CHI game is a retrospective only

        def side(off, dfn):
            dims = {}
            for label, o, d in DIMS:
                a, b = team_units[off]['equal'].get(o), team_units[dfn]['equal'].get(d)
                au, bu = team_units[off]['usage'].get(o), team_units[dfn]['usage'].get(d)
                na, nb = team_units[off]['n'].get(o, 0), team_units[dfn]['n'].get(d, 0)
                low = (na / expected(o) < MIN_COVERAGE_SHARE) or (nb / expected(d) < MIN_COVERAGE_SHARE)
                dims[label] = {
                    'equal': None if a is None or b is None else round(a - b, 2),
                    'usage': None if au is None or bu is None else round(au - bu, 2),
                    'n_offense': na, 'n_defense': nb,
                    'coverage_flag': 'low' if low else 'ok',
                }
            eq = [v['equal'] for v in dims.values() if v['equal'] is not None and v['coverage_flag'] == 'ok']
            us = [v['usage'] for v in dims.values() if v['usage'] is not None and v['coverage_flag'] == 'ok']
            return dims, (round(statistics.mean(eq), 2) if eq else None), (round(statistics.mean(us), 2) if us else None)

        hd, _, _ = side(home, away)
        ad, _, _ = side(away, home)
        # Paired net: a dimension counts only when both sides are ok, so the two sides are compared
        # over the same labels rather than over different subsets.
        paired_eq, paired_us = [], []
        for label, _, _ in DIMS:
            h, a = hd[label], ad[label]
            if h['coverage_flag'] == 'ok' and a['coverage_flag'] == 'ok':
                if h['equal'] is not None and a['equal'] is not None:
                    paired_eq.append(h['equal'] - a['equal'])
                if h['usage'] is not None and a['usage'] is not None:
                    paired_us.append(h['usage'] - a['usage'])
        net_eq = round(statistics.mean(paired_eq), 2) if paired_eq else None
        net_us = round(statistics.mean(paired_us), 2) if paired_us else None
        lp = proj.get(gid)
        lp_margin = lp['proj_margin'] if lp else None
        if lp_margin is None or net_eq is None:
            agreement = 'not computable'
        elif abs(net_eq) < NEUTRAL_NET or abs(lp_margin) < NEUTRAL_MARGIN:
            agreement = 'neutral'
        else:
            agreement = 'agree' if (net_eq > 0) == (lp_margin > 0) else 'conflict'
        flat = []
        for side_name, dims in (('home_offense', hd), ('away_offense', ad)):
            for label, v in dims.items():
                if v['equal'] is not None and v['coverage_flag'] == 'ok':
                    flat.append({'side': side_name, 'dimension': label, 'diff': v['equal']})
        flat.sort(key=lambda x: -abs(x['diff']))
        unmatched = {t: sum(1 for r in ROLES for e in lineup[t].get(r, []) if e['attr_row'] is None)
                     for t in (home, away)}
        retro = None
        if completed:
            retro = final_score(args.picks_db, FINAL_EVENTS[gid], home, away)
        game_out.append({
            'game_id': gid, 'weekday': weekday, 'gameday': gameday, 'gametime_as_stored': gametime,
            'away': away, 'home': home,
            'completed_before_experiment': completed,
            'retrospective_final': retro,
            'retrospective_margin_agrees_with_ratings_net': (
                None if retro is None or net_eq is None or retro['margin_home_minus_away'] == 0
                else (net_eq > 0) == (retro['margin_home_minus_away'] > 0)),
            'lp_projection': lp, 'lp_margin_home_minus_away': lp_margin,
            'ratings_net_home_minus_away_equal': net_eq,
            'ratings_net_home_minus_away_usage': net_us,
            'paired_dimensions_used': len(paired_eq),
            'agreement_with_lp_direction': agreement,
            'dimensions_home_offense': hd, 'dimensions_away_offense': ad,
            'top_three_observed_differences': flat[:3],
            'uncertainties': {
                'unmatched_starters': unmatched,
                'madden_team_blank_starters': {t: sum(1 for r in ROLES for e in lineup[t].get(r, [])
                                                      if e['madden_team_blank']) for t in (home, away)},
                'review_name_team_position_starters': {t: sum(1 for r in ROLES for e in lineup[t].get(r, [])
                                                              if e['status'] == 'review_name_team_position_in_2027')
                                                       for t in (home, away)},
                'week7_injury_report_rows': week7_injury_rows,
                'transactions_since_2026_08_04': {'away': txns.get(away, 0), 'home': txns.get(home, 0)},
                'usage_weeks': '1-5',
            },
        })

    player_rows_path = os.path.join(args.derived_dir, 'week7_starters.csv')
    with open(player_rows_path, 'w', newline='') as f:
        w = csv.writer(f)
        w.writerow(['team', 'role', 'name', 'gsis', 'lp_player_id', 'usage', 'weeks_seen', 'status', 'stint',
                    'madden_player_id', 'madden_team_blank', 'madden_group', 'position_agrees',
                    'injury_last_known_week', 'injury_last_known_status'] + list(attrs))
        for team in sorted(lineup):
            for role in ROLES:
                for e in lineup[team].get(role, []):
                    row = e['attr_row'] or {}
                    w.writerow([team, role, e['name'], e['gsis'], e['lp_player_id'], e['usage'], e['weeks_seen'],
                                e['status'], e['stint'], e['madden_player_id'], e['madden_team_blank'],
                                e['madden_group'], e['position_agrees'], e['injury_last_known'][0],
                                e['injury_last_known'][1]] + [row.get(a, '') for a in attrs])

    docs = {
        'schema': 'madden-week7-matchups-2026/v2',
        'generated_at_utc': now,
        'season': SEASON, 'week': WEEK,
        'madden_release_label': 2027, 'madden_season_mapped': 2026,
        'coverage_rule': f'a dimension is flagged low when either side has under {MIN_COVERAGE_SHARE:.0%} of its expected players',
        'team_units': team_units,
        'coverage_by_team': coverage_rows,
        'games': game_out,
        'composites': COMP, 'composite_roles': COMP_ROLES,
        'dimensions': [{'label': l, 'offense': o, 'defense': d} for l, o, d in DIMS],
        'reported_only_attributes': REPORTED_ONLY,
        'unmapped_madden_team_slugs': sorted(unmapped_slugs),
        'ambiguous_gsis_dropped': len(gsis_ambiguous),
        'madden27_multi_stint_player_ids': len(dup_ids),
        'week7_injury_report_rows': week7_injury_rows,
        'player_projection_rows_week7': lp_proj_week7,
        'player_projection_distinct_players_week6': lp_proj_week6,
    }
    os.makedirs(os.path.dirname(args.docs_json), exist_ok=True)
    with open(args.docs_json, 'w') as f:
        json.dump(docs, f, indent=2)
        f.write('\n')
    frozen = {
        'frozen_at_utc': now,
        'before_first_kickoff': now < '2026-10-26T00:00:00+00:00',
        'madden_archive_sha256': sha256_file(args.zip),
        'identity_crosswalk_sha256': sha256_file(args.identity),
        'git_revision': git_rev(),
        'ratings_edition': 'Madden NFL 27 (dataset label 2027, covers the 2026 season)',
        'snapshot_timing': 'unverified: archive has no snapshot date; post-launch updates confirmed for Madden 27',
        'roster_cutoff': {'roster_snapshot_published': '2026-08-04', 'transactions_through': '2026-10-21',
                          'depth_chart_snapshot_max': '2026-10-19', 'player_game_logs_through': '2026-10-19'},
        'nfl_schedule_rows_week7': len(games),
        'projection_model': 'nfl-ratings-v1 preview (nfl-preview-v1), latest run per game',
        'official_lock_runs_week7': 'nfl-lock-2026-w07 covers NE-CHI only (completed Thursday game)',
        'read_only_database': args.picks_db,
    }
    with open(args.frozen_json, 'w') as f:
        json.dump(frozen, f, indent=2)
        f.write('\n')
    statuses = Counter_(e['status'] for r in ROLES for t in lineup for e in lineup[t].get(r, []))
    print('starter status:', dict(sorted(statuses.items())))
    print(f'games: {len(game_out)}; unmapped slugs: {sorted(unmapped_slugs)}; '
          f'ambiguous gsis dropped: {len(gsis_ambiguous)}; multi-stint 2027 players: {len(dup_ids)}')
    print(f'week-7 injury rows: {week7_injury_rows}; week-7 player projection rows: {lp_proj_week7}')
    return 0


def Counter_(items):
    out = defaultdict(int)
    for x in items:
        out[x] += 1
    return out


if __name__ == '__main__':
    sys.exit(main())
