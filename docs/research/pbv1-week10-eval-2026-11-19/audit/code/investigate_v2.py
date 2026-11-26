"""Week 10 PBV1 investigation, corrected denominators. Read-only.

Team offensive plays: nfl_pbp run and pass plays per posteam (actual), and choice-record plays per team per seed (sim).
Snap rate: player offensive snaps (nfl_logs off_snaps, sim box snaps) over team offensive plays.
Carries = P x F x R x S, where
  P = team offensive plays, F = P(on field | play), R = P(run | on field), S = P(rusher | run, on field).
Actual R is not observable per player; the team run rate is used, and S is the residual (stated in the output).
Availability: unlogged players the injury report lists as Out or Doubtful, checked against team injury articles dated
on or before the forecast cutoff.
"""
import collections, glob, gzip, json, os, sqlite3

W10 = '/root/tnf-batch/w10-eval'
AUD = '/root/tnf-batch/audit'
DB = '/root/tnf-batch/picks.frozen.db'
OUT = AUD + '/analysis'
CH = ['B-field', 'C-field-pbv1']
NORM = {'WSH': 'WAS', 'LAR': 'LA'}
NAMED = ['Zach Charbonnet', 'Jahmyr Gibbs', 'Derrick Henry', 'Christian McCaffrey', 'Bijan Robinson', 'Jonathan Taylor']
HV = 10
CUTOFF = '2026-11-14'  # snapshot as_of, 12:00 UTC on this date


def norm(t):
    return NORM.get(t, t)


def rate(a, b):
    return a / b if b else None


con = sqlite3.connect('file:%s?mode=ro' % DB, uri=True)
pbp = {}
for gid, team, n, runs in con.execute(
        "select game_id, posteam, count(*), sum(case when play_type='run' then 1 else 0 end) from nfl_pbp "
        "where season=2026 and week=10 and play_type in ('run','pass','no_play','qb_kneel','qb_spike') "
        "and posteam is not null group by game_id, posteam"):
    pbp[(gid, norm(team))] = (n, runs)
pinfo = {k: (n, p, i) for k, n, p, i in con.execute(
    'select nfl_gsis_id, name, position, id from players where nfl_gsis_id is not null')}
inj = collections.defaultdict(list)
for gsis, rs, team in con.execute(
        "select gsis_id, report_status, team from injury_reports where season=2026 and week=10"):
    inj[gsis].append((rs, norm(team)))
articles = [(d, norm(t), title) for d, t, title in con.execute(
    "select published_date, team, title from team_injury_articles where published_date >= '2026-10-01'")]
logs = collections.defaultdict(dict)
for gid, key, team, stats in con.execute(
        "select game_id, source_player_key, team, stats from player_game_logs where season=2026 and league='nfl' "
        "and game_id like '2026_10_%' and game_type='REG'"):
    s = json.loads(stats) if stats else {}
    logs[gid][key] = {'team': norm(team), 'carries': s.get('carries') or 0, 'off_snaps': s.get('off_snaps') or 0}
con.close()
GAMES = sorted(logs)
AS_OF = {}
for g in GAMES:
    with open('/root/tnf-batch/w10/snapshots/%s/prospective-1.json' % g) as f:
        AS_OF[g] = json.load(f)['as_of']


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
    team_plays = collections.Counter()
    for r in recs:
        for t in r['teams']:
            team_plays[norm(t['team'])] += t['stats'].get('plays') or 0
        for p in r['players']:
            d = players.setdefault(p['stable_player_id'], {'snaps': 0.0, 'carries': 0.0, 'team': norm(p['team']),
                                                           'name': p['name']})
            d['snaps'] += p.get('snaps') or 0
            d['carries'] += p['rushing']['att']
    for d in players.values():
        d['snaps'] /= n
        d['carries'] /= n
    for t in list(team_plays):
        team_plays[t] /= n
    return players, team_plays, n


# ---- Denominator reconciliation -------------------------------------------
recon = []
choice_cache = {}
for g in GAMES:
    for a in CH:
        choice_cache[(g, a)] = json.load(gzip.open('%s/%s/%s/choices.json.gz' % (AUD, g, a), 'rt'))['plays']
    box_plays_B = box(g, 'B-field')[1]
    for team in {t for (gg, t) in pbp if gg == g}:
        seeds = len({p['seed'] for p in choice_cache[(g, 'B-field')]})
        row = {'game': g, 'team': team, 'pbp_plays': pbp[(g, team)][0]}
        for a in CH:
            per_seed = collections.Counter(p['seed'] for p in choice_cache[(g, a)] if norm(p['team']) == team)
            row['sim_choice_plays_' + a[:1]] = round(sum(per_seed.values()) / seeds, 2)
        row['sim_box_plays_B'] = round(box_plays_B.get(team, 0), 2)
        recon.append(row)
recon_summary = {
    'team_games': len(recon),
    'mean_pbp_plays': round(sum(r['pbp_plays'] for r in recon) / len(recon), 2),
    'mean_sim_choice_plays_B': round(sum(r['sim_choice_plays_B'] for r in recon) / len(recon), 2),
    'mean_sim_choice_plays_C': round(sum(r['sim_choice_plays_C'] for r in recon) / len(recon), 2),
    'mean_sim_box_plays_B': round(sum(r['sim_box_plays_B'] for r in recon) / len(recon), 2),
    'mean_abs_gap_choice_vs_box_B': round(sum(abs(r['sim_choice_plays_B'] - r['sim_box_plays_B']) for r in recon) / len(recon), 2),
}

# ---- Carry decomposition for high-volume player-games ---------------------
hv = []
for g in GAMES:
    boxes = {a: box(g, a) for a in CH}
    for k, p in logs[g].items():
        if p['carries'] < HV:
            continue
        t = p['team']
        P_a, R_a = pbp[(g, t)]
        F_a = rate(p['off_snaps'], P_a)
        run_rate = rate(R_a, P_a)
        row = {'game': g, 'gsis': k, 'name': pinfo.get(k, ('?',))[0], 'team': t,
               'named': pinfo.get(k, ('?',))[0] in NAMED,
               'actual': {'P': P_a, 'F': round(F_a, 4), 'R_team_rate': round(run_rate, 4),
                          'S_implied': round(rate(p['carries'], p['off_snaps'] * run_rate), 4),
                          'carries': p['carries'], 'snaps': p['off_snaps']}}
        for a in CH:
            plays = choice_cache[(g, a)]
            per_seed = collections.defaultdict(lambda: collections.Counter())
            seeds = set()
            for q in plays:
                seeds.add(q['seed'])
                if norm(q['team']) != t:
                    continue
                c = per_seed[q['seed']]
                c['P'] += 1
                on = k in set((q['lineup'] or {}).get('on_field') or [])
                if on:
                    c['on'] += 1
                    if q['intent'] == 'run':
                        c['run_on'] += 1
                        if (q['rusher'] or {}).get('gsis') == k:
                            c['rusher'] += 1
                if q['intent'] == 'run':
                    c['run'] += 1
            n = len(seeds)
            tot = collections.Counter()
            for s in seeds:
                tot.update(per_seed[s])
            P = tot['P'] / n
            F = rate(tot['on'], tot['P'])
            R = rate(tot['run_on'], tot['on'])
            S = rate(tot['rusher'], tot['run_on'])
            players, team_plays, _ = boxes[a]
            d = players.get(k, {'carries': 0.0, 'snaps': 0.0})
            row[a[:1]] = {'P': round(P, 2), 'F': round(F or 0, 4), 'R': round(R or 0, 4), 'S': round(S or 0, 4),
                          'rusher_per_game': round(tot['rusher'] / n, 2), 'box_carries': round(d['carries'], 2),
                          'box_snaps': round(d['snaps'], 2), 'team_run_rate': round(rate(tot['run'], tot['P']) or 0, 4)}
        hv.append(row)

def agg(rows, arm):
    if arm == 'A':
        P = sum(r['actual']['P'] for r in rows)
        on = sum(r['actual']['snaps'] for r in rows)
        car = sum(r['actual']['carries'] for r in rows)
        return {'F': round(on / P, 4), 'carries': car}
    P = sum(r[arm]['P'] for r in rows)
    on = sum(r[arm]['F'] * r[arm]['P'] for r in rows)
    car = sum(r[arm]['box_carries'] for r in rows)
    return {'F': round(on / P, 4), 'carries': round(car, 2)}

summary = {'all_29': {'actual': agg(hv, 'A'), 'B': agg(hv, 'B'), 'C': agg(hv, 'C')},
           'named_6': {'actual': agg([r for r in hv if r['named']], 'A'),
                       'B': agg([r for r in hv if r['named']], 'B'), 'C': agg([r for r in hv if r['named']], 'C')}}

# ---- Availability: Out or Doubtful, unlogged, arm B and arm C ---------------
avail = {a: collections.Counter() for a in CH}
avail_carries = {a: collections.Counter() for a in CH}
avail_rows = {a: [] for a in CH}
for g in GAMES:
    for a in CH:
        players, team_plays, n = box(g, a)
        for k, d in players.items():
            if k in logs[g] or d['carries'] <= 0:
                continue
            statuses = [s for s, t in inj.get(k, []) if t == d['team']]
            if not any(s in ('Out', 'Doubtful') for s in statuses):
                continue
            name = d['name']
            hits = [(dt, title) for dt, t, title in articles if name in title]
            cut = AS_OF[g][:10]
            pre = [h for h in hits if h[0] <= cut]
            cat = 'article_on_or_before_cutoff' if pre else ('article_after_cutoff_only' if hits else 'no_article_found')
            avail[a][cat] += 1
            avail_carries[a][cat] += d['carries']
            avail_rows[a].append({'game': g, 'name': name, 'team': d['team'], 'status': statuses,
                                  'carries': round(d['carries'], 2), 'cutoff': AS_OF[g],
                                  'article_dates': [h[0] for h in hits][:4],
                                  'article_titles': [h[1] for h in hits][:4], 'category': cat})
as_of = set(AS_OF.values())
f_over_one = [(r['name'], r['actual']['F']) for r in hv if r['actual']['F'] > 1]

res = {'denominator_reconciliation': recon_summary, 'recon_rows': recon,
       'high_volume_decomposition': hv, 'summary': summary,
       'availability_out_or_doubtful': {a: dict(avail[a]) for a in CH},
       'availability_carries': {a: {k: round(v, 2) for k, v in avail_carries[a].items()} for a in CH},
       'availability_rows': avail_rows, 'snapshot_as_of_values': sorted(as_of),
       'actual_snap_rate_over_one': f_over_one, 'actual_max_snap_rate': max(r['actual']['F'] for r in hv),
       'injury_ingest': 'all week 10 injury_reports rows ingested 2026-11-17T15:30:15Z'}
os.makedirs(OUT, exist_ok=True)
with open(OUT + '/investigation_v2.json', 'w') as f:
    json.dump(res, f, indent=1, default=str)
print('written', OUT + '/investigation_v2.json')
