"""Week 10 PBV1 investigation, read-only.

1. High-volume runners: split carry share into snap share and carries per snap (team-relative), per arm.
   Arms B and C also get the on-field rate and the run-selection rate from the choice records.
2. Players with no log row who got carries: classify by published week 10 snap counts and injury reports.
"""
import collections, glob, gzip, json, os, sqlite3

W10 = '/root/tnf-batch/w10-eval'
AUD = '/root/tnf-batch/audit'
DB = '/root/tnf-batch/picks.frozen.db'
OUT = AUD + '/analysis'
ARMS = ['A-control', 'B-field', 'C-field-pbv1']
CH = ['B-field', 'C-field-pbv1']
NORM = {'WSH': 'WAS', 'LAR': 'LA'}
NAMED = ['Zach Charbonnet', 'Jahmyr Gibbs', 'Derrick Henry', 'Christian McCaffrey', 'Bijan Robinson', 'Jonathan Taylor']
HV = 10


def norm(t):
    return NORM.get(t, t)


def rate(num, den):
    return num / den if den else None


con = sqlite3.connect('file:%s?mode=ro' % DB, uri=True)
pinfo = {k: (n, p, i) for k, n, p, i in con.execute(
    'select nfl_gsis_id, name, position, id from players where nfl_gsis_id is not null')}
snap = collections.defaultdict(list)
for pid, offs, team in con.execute('select player_id, off_snaps, team from nfl_snap_counts where season=2026 and week=10'):
    snap[pid].append((offs, norm(team)))
inj = collections.defaultdict(list)
for gsis, rs, ps, team in con.execute(
        'select gsis_id, report_status, practice_status, team from injury_reports where season=2026 and week=10'):
    inj[gsis].append((rs, ps, norm(team)))
logs = collections.defaultdict(dict)
for gid, key, team, stats in con.execute(
        "select game_id, source_player_key, team, stats from player_game_logs where season=2026 and league='nfl' "
        "and game_id like '2026_10_%' and game_type='REG'"):
    s = json.loads(stats) if stats else {}
    logs[gid][key] = {'team': norm(team), 'carries': s.get('carries') or 0, 'off_snaps': s.get('off_snaps') or 0}
con.close()

GAMES = sorted(logs)


def box(game, arm):
    recs = []
    for path in sorted(glob.glob('%s/%s/out/runs/%s/*.boxscores.jsonl' % (W10, game, arm))):
        with open(path) as f:
            for line in f:
                r = json.loads(line)
                if r.get('type') == 'game':
                    recs.append(r)
    n = len(recs)
    players = {}
    team_snaps = collections.Counter()
    team_carries = collections.Counter()
    for r in recs:
        for p in r['players']:
            d = players.setdefault(p['stable_player_id'], {'snaps': 0.0, 'carries': 0.0, 'team': norm(p['team']),
                                                           'name': p['name']})
            d['snaps'] += p.get('snaps') or 0
            d['carries'] += p['rushing']['att']
            team_snaps[norm(p['team'])] += p.get('snaps') or 0
            team_carries[norm(p['team'])] += p['rushing']['att']
    for d in players.values():
        d['snaps'] /= n
        d['carries'] /= n
    for t in list(team_snaps):
        team_snaps[t] /= n
        team_carries[t] /= n
    return players, team_snaps, team_carries


# ---- Investigation 1 -------------------------------------------------------
hv_rows = []
named = {a: collections.defaultdict(collections.Counter) for a in ARMS}
named_act = collections.defaultdict(collections.Counter)
team_snap_check = []
for g in GAMES:
    act_ts = collections.Counter()
    act_tc = collections.Counter()
    for p in logs[g].values():
        act_ts[p['team']] += p['off_snaps']
        act_tc[p['team']] += p['carries']
    sims = {a: box(g, a) for a in ARMS}
    for t in act_ts:
        team_snap_check.append({'game': g, 'team': t, 'actual_team_off_snaps': act_ts[t],
                                'sim_team_snaps_control': round(sims['A-control'][1].get(t, 0), 1)})
    for k, p in logs[g].items():
        t = p['team']
        name = pinfo.get(k, ('?',))[0]
        if p['carries'] >= HV:
            row = {'game': g, 'gsis': k, 'name': name, 'team': t, 'act_carries': p['carries'],
                   'act_snaps': p['off_snaps'],
                   'act_snap_share': round(rate(p['off_snaps'], act_ts[t]), 4),
                   'act_carries_per_snap': round(rate(p['carries'], p['off_snaps']), 4)}
            for a in ARMS:
                players, ts, tc = sims[a]
                d = players.get(k, {'snaps': 0.0, 'carries': 0.0})
                row[a] = {'sim_carries': round(d['carries'], 2), 'sim_snaps': round(d['snaps'], 2),
                          'sim_snap_share': round(rate(d['snaps'], ts.get(t, 0)) or 0, 4),
                          'sim_carries_per_snap': round(rate(d['carries'], d['snaps']) or 0, 4)}
            hv_rows.append(row)
        if name in NAMED:
            named_act[name]['snaps'] += p['off_snaps']
            named_act[name]['carries'] += p['carries']
            named_act[name]['team_snaps'] += act_ts[t]
            named_act[name]['team_carries'] += act_tc[t]
            for a in ARMS:
                players, ts, tc = sims[a]
                d = players.get(k)
                if d:
                    named[a][name]['snaps'] += d['snaps']
                    named[a][name]['carries'] += d['carries']
                    named[a][name]['team_snaps'] += ts.get(t, 0)
                    named[a][name]['team_carries'] += tc.get(t, 0)

# choice level for the high-volume player-games, arms B and C
hv_keys = {(r['game'], r['gsis']): r for r in hv_rows}
choice = {a: collections.Counter() for a in CH}
for g in GAMES:
    keys_here = {k[1] for k in hv_keys if k[0] == g}
    if not keys_here:
        continue
    for a in CH:
        d = json.load(gzip.open('%s/%s/%s/choices.json.gz' % (AUD, g, a), 'rt'))
        for p in d['plays']:
            on = set((p['lineup'] or {}).get('on_field') or [])
            for gsis in keys_here:
                if logs[g][gsis]['team'] != p['team']:
                    continue
                c = choice[a]
                c[(g, gsis, 'team_plays')] += 1
                if gsis in on:
                    c[(g, gsis, 'on_field')] += 1
                    if p['intent'] == 'run':
                        c[(g, gsis, 'run_on_field')] += 1
                        if (p['rusher'] or {}).get('gsis') == gsis:
                            c[(g, gsis, 'run_chosen')] += 1
choice_rows = {}
for a in CH:
    rows = []
    for (g, gsis), r in sorted(hv_keys.items()):
        c = choice[a]
        tp = c[(g, gsis, 'team_plays')]
        onf = c[(g, gsis, 'on_field')]
        ro = c[(g, gsis, 'run_on_field')]
        rc = c[(g, gsis, 'run_chosen')]
        rows.append({'game': g, 'name': r['name'], 'on_field_rate': round(rate(onf, tp), 4) if tp else None,
                     'run_selection_given_on_field': round(rate(rc, ro), 4) if ro else None,
                     'run_plays_on_field': ro})
    choice_rows[a] = rows

# ---- Investigation 2 -------------------------------------------------------
cls = {a: collections.Counter() for a in CH}
cls_carry = {a: collections.Counter() for a in CH}
cls_examples = {a: collections.defaultdict(list) for a in CH}
inj_status = {a: collections.Counter() for a in CH}
for g in GAMES:
    for a in CH:
        players, ts, tc = box(g, a)
        for k, d in players.items():
            if k in logs[g] or d['carries'] <= 0:
                continue
            pid = pinfo.get(k, (None, None, None))[2]
            pos_snaps = [s for s, t in snap.get(pid, []) if t == d['team']]
            injrows = [(rs, ps) for rs, ps, t in inj.get(k, []) if t == d['team']]
            for rs, ps in injrows:
                inj_status[a][rs] += 1
            if any(s and s > 0 for s in pos_snaps):
                c = 'published_snaps_but_no_log_row'
            elif any(rs in ('Out', 'Doubtful', 'Injured Reserve', 'Inactive') for rs, ps in injrows):
                c = 'injury_report_out_or_doubtful_or_ir'
            elif injrows:
                c = 'injury_report_other_status'
            elif pos_snaps:
                c = 'snap_count_zero_no_injury_row'
            else:
                c = 'no_snap_or_injury_row'
            cls[a][c] += 1
            cls_carry[a][c] += d['carries']
            if len(cls_examples[a][c]) < 4:
                cls_examples[a][c].append((g, d['name'], d['team'], round(d['carries'], 1)))

res = {
    'inv1_high_volume': hv_rows,
    'inv1_named_sim': {a: {k: {m: round(v, 2) for m, v in dict(c).items()} for k, c in named[a].items()} for a in ARMS},
    'inv1_named_actual': {k: dict(v) for k, v in named_act.items()},
    'inv1_choice_level': choice_rows,
    'inv2_class_counts': {a: dict(cls[a]) for a in CH},
    'inv2_class_carries': {a: {k: round(v, 1) for k, v in cls_carry[a].items()} for a in CH},
    'inv2_class_examples': {a: {k: v for k, v in cls_examples[a].items()} for a in CH},
    'inv2_injury_statuses': {a: dict(inj_status[a]) for a in CH},
    'team_snap_check': team_snap_check[:6],
    'pid_with_snap_rows': sum(1 for k in pinfo if pinfo[k][2] in snap),
}
os.makedirs(OUT, exist_ok=True)
with open(OUT + '/investigation.json', 'w') as f:
    json.dump(res, f, indent=1, default=str)
print('written', OUT + '/investigation.json')
