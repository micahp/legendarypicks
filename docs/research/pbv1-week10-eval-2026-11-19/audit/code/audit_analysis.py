"""Week 10 PBV1 allocation audit. Read-only.

Inputs:
  W10/<game>/out/runs/<arm>/*.boxscores.jsonl   box scores, all three arms, 20 seeds per game
  AUD/<game>/<arm>/choices.json.gz              per-play choices and named draws, arms B and C
  DB                                            frozen DB: actual player game logs and final scores
Writes OUT/analysis.json and prints the main tables.
"""
import collections, glob, gzip, json, os, random, re, sqlite3, statistics

W10 = '/root/tnf-batch/w10-eval'
AUD = '/root/tnf-batch/audit'
DB = '/root/tnf-batch/picks.frozen.db'
OUT = '/root/tnf-batch/audit/analysis'
ARMS = ['A-control', 'B-field', 'C-field-pbv1']
CHOICE_ARMS = ['B-field', 'C-field-pbv1']
GROUPS = ['RB', 'QB', 'WR', 'TE']
HIGH = 10  # actual carries in one game
NORM = {'WSH': 'WAS', 'LAR': 'LA'}  # boundary: nflverse codes everywhere
DRAW = re.compile(r'^([0-9a-f]+):(\d+):(\d+):(.*)$')
CAUSE_ORDER = ['intent', 'group', 'team', 'passer', 'rusher', 'receiver']  # decision order inside one play


def norm(t):
    return NORM.get(t, t)


def grp(pos):
    return pos if pos in GROUPS else 'other'


def mean(xs):
    return sum(xs) / len(xs) if xs else None


def r2(x):
    return None if x is None else round(x, 3)


def games():
    return sorted(os.path.basename(p) for p in glob.glob(f'{W10}/2026_10_*'))


def load_actual():
    con = sqlite3.connect(f'file:{DB}?mode=ro', uri=True)
    pinfo = {k: (n, p) for k, n, p in con.execute(
        'select nfl_gsis_id, name, position from players where nfl_gsis_id is not null')}
    finals = {}
    for gid, home, away, hs, as_ in con.execute(
            "select game_id, home_team, away_team, home_score, away_score from nfl_schedule "
            "where season=2026 and game_type='REG' and game_id like '2026_10_%'"):
        finals[gid] = {'home': norm(home), 'away': norm(away), 'home_points': hs, 'away_points': as_}
    logs = collections.defaultdict(dict)
    for gid, key, team, stats in con.execute(
            "select game_id, source_player_key, team, stats from player_game_logs where season=2026 and league='nfl' "
            "and game_id like '2026_10_%' and game_type='REG'"):
        s = json.loads(stats) if stats else {}
        name, pos = pinfo.get(key, ('UNK', None))
        logs[gid][key] = {'team': norm(team), 'name': name, 'pos': pos or 'UNK', 'carries': s.get('carries') or 0,
                          'targets': s.get('targets') or 0, 'off_pct': s.get('off_pct') or 0.0}
    con.close()
    return finals, logs


def sim_runs(game, arm):
    recs = []
    for path in sorted(glob.glob(f'{W10}/{game}/out/runs/{arm}/*.boxscores.jsonl')):
        with open(path) as f:
            for line in f:
                r = json.loads(line)
                if r.get('type') == 'game':
                    recs.append(r)
    return recs


def run_players(rec):
    return {p['stable_player_id']: {'team': norm(p['team']), 'name': p['name'], 'pos': p['position'] or 'UNK',
                                    'carries': p['rushing']['att'], 'targets': p['receiving']['tgt']}
            for p in rec['players']}


def sim_means(recs):
    n = len(recs)
    tot = {}
    for r in recs:
        for gsis, p in run_players(r).items():
            t = tot.setdefault(gsis, {'name': p['name'], 'team': p['team'], 'pos': p['pos'], 'carries': 0, 'targets': 0})
            t['carries'] += p['carries']
            t['targets'] += p['targets']
    for t in tot.values():
        t['carries'] /= n
        t['targets'] /= n
    return tot


def margin_rows(recs):
    out = {}
    for r in recs:
        pts = {norm(k): sum(v.values()) for k, v in r['points_by_period'].items()}
        home, away = norm(r['home_team']), norm(r['away_team'])
        out[r['seed']] = (pts[home] - pts[away], pts[home] + pts[away], int(pts[home] > pts[away]))
    return out


def build_rows(game, arm, sim, act):
    """One row per player-game that is in the simulation or has an actual touch. Actual players with no touch and no
    simulated appearance are not errors and are not rows."""
    out = []
    for gsis in set(sim) | set(act):
        s, x = sim.get(gsis), act.get(gsis)
        ac, at = (x['carries'], x['targets']) if x else (0, 0)
        if s and x:
            cat = 'matched' if (ac or at) else 'matched_nonparticipant'
        elif s:
            cat = 'sim_no_log_row'
        elif ac or at:
            cat = 'roster_omission'
        else:
            continue
        src = s or x
        out.append({'game': game, 'arm': arm, 'gsis': gsis, 'cat': cat, 'name': src['name'], 'team': src['team'],
                    'pos': grp(src['pos']), 'sc': s['carries'] if s else 0.0, 'st': s['targets'] if s else 0.0,
                    'ac': ac, 'at': at, 'starter': bool(x and x['off_pct'] >= 0.5)})
    return out


def reconcile(rows, arm, actual, G):
    sel = [r for r in rows if r['arm'] == arm]
    out = {}
    for cat in ['matched', 'matched_nonparticipant', 'sim_no_log_row', 'roster_omission']:
        c = [r for r in sel if r['cat'] == cat]
        out[cat] = {'player_games': len(c), 'sim_carries': r2(sum(r['sc'] for r in c)), 'act_carries': sum(r['ac'] for r in c),
                    'sim_targets': r2(sum(r['st'] for r in c)), 'act_targets': sum(r['at'] for r in c)}
    out['totals'] = {'sim_carries': r2(sum(r['sc'] for r in sel)), 'act_carries_in_rows': sum(r['ac'] for r in sel),
                     'act_carries_in_logs': sum(p['carries'] for g in G for p in actual[g].values()),
                     'sim_targets': r2(sum(r['st'] for r in sel)), 'act_targets_in_rows': sum(r['at'] for r in sel),
                     'act_targets_in_logs': sum(p['targets'] for g in G for p in actual[g].values())}
    return out


def group_errors(rows, arm, kind):
    s_key, a_key = ('sc', 'ac') if kind == 'c' else ('st', 'at')
    sel = [r for r in rows if r['arm'] == arm and (r[s_key] or r[a_key])]
    out = {}
    for g in GROUPS + ['other', 'all']:
        c = sel if g == 'all' else [r for r in sel if r['pos'] == g]
        signed = [r[s_key] - r[a_key] for r in c]
        act = sum(r[a_key] for r in c)
        out[g] = {'player_games': len(c), 'sim': r2(sum(r[s_key] for r in c)), 'act': act,
                  'signed_err': r2(sum(signed)), 'mae': r2(mean([abs(x) for x in signed])),
                  'abs_err': r2(sum(abs(x) for x in signed)),
                  'abs_err_over_act': r2(sum(abs(x) for x in signed) / act) if act else None}
    return out


def high_volume(rows, arm):
    sel = [r for r in rows if r['arm'] == arm and r['ac'] >= HIGH]
    return [{'game': r['game'], 'name': r['name'], 'pos': r['pos'], 'team': r['team'], 'sim': r2(r['sc']),
             'act': r['ac'], 'signed': r2(r['sc'] - r['ac'])} for r in sorted(sel, key=lambda r: -r['ac'])]


def team_shares(rows, arm):
    teams = collections.defaultdict(list)
    for r in rows:
        if r['arm'] == arm:
            teams[(r['game'], r['team'])].append(r)
    out = {'team_games': len(teams)}
    for kind, (s_key, a_key) in (('carries', ('sc', 'ac')), ('targets', ('st', 'at'))):
        team_err = share_err = player_err = 0.0
        for rs in teams.values():
            ts = sum(r[s_key] for r in rs)
            ta = sum(r[a_key] for r in rs)
            team_err += abs(ts - ta)
            player_err += sum(abs(r[s_key] - r[a_key]) for r in rs)
            if ts > 0 and ta > 0:
                share_err += sum(abs(r[s_key] / ts - r[a_key] / ta) * ta for r in rs)
        out[kind] = {'team_total_err': r2(team_err), 'share_err': r2(share_err), 'player_abs_err': r2(player_err),
                     'per_team_game_player_abs': r2(player_err / len(teams))}
    return out


def starter_moves(rows, base, other):
    idx = collections.defaultdict(dict)
    for r in rows:
        if r['arm'] in (base, other):
            idx[(r['game'], r['gsis'])][r['arm']] = r
    per = collections.defaultdict(lambda: {'name': None, 'pos': None, 'team': None, 'sim_base': 0.0, 'sim_other': 0.0, 'act': 0})
    for (game, gsis), d in idx.items():
        any_r = next(iter(d.values()))
        if not any_r['starter']:
            continue
        e = per[gsis]
        e['name'], e['pos'], e['team'] = any_r['name'], any_r['pos'], any_r['team']
        e['sim_base'] += d[base]['sc'] if base in d else 0.0
        e['sim_other'] += d[other]['sc'] if other in d else 0.0
        e['act'] += any_r['ac']
    moved = [dict(v, gsis=k, sim_base=r2(v['sim_base']), sim_other=r2(v['sim_other']),
                  delta=r2(v['sim_other'] - v['sim_base'])) for k, v in per.items()]
    lost = sorted([m for m in moved if m['delta'] < 0], key=lambda m: m['delta'])[:10]
    gained = sorted([m for m in moved if m['delta'] > 0], key=lambda m: -m['delta'])[:10]
    return {'starter_sim_base': r2(sum(m['sim_base'] for m in moved)),
            'starter_sim_other': r2(sum(m['sim_other'] for m in moved)),
            'starter_act': sum(m['act'] for m in moved), 'lost': lost, 'gained': gained}


def cluster_ci(game_means, iters=4000):
    rng = random.Random(1)
    vals = list(game_means.values())
    n = len(vals)
    boots = sorted(sum(rng.choice(vals) for _ in range(n)) / n for _ in range(iters))
    return boots[int(0.025 * iters)], boots[int(0.975 * iters) - 1]


def paired_scores(G, margins):
    out = {}
    for x, y in [('A-control', 'B-field'), ('B-field', 'C-field-pbv1'), ('A-control', 'C-field-pbv1')]:
        per_game, seeds_n, seeds_diff = {}, 0, 0
        for g in G:
            mx, my = margins[(g, x)], margins[(g, y)]
            shared = sorted(set(mx) & set(my))
            dm = [mx[s][0] - my[s][0] for s in shared]
            dt = [mx[s][1] - my[s][1] for s in shared]
            dw = [mx[s][2] - my[s][2] for s in shared]
            per_game[g] = {'seeds': len(shared), 'margin': mean(dm), 'total': mean(dt), 'home_win': mean(dw)}
            seeds_n += len(shared)
            seeds_diff += sum(1 for v in dm if v)
        block = {'paired_seeds': seeds_n, 'seeds_with_different_margin': seeds_diff}
        for metric in ('margin', 'total', 'home_win'):
            vals = {g: v[metric] for g, v in per_game.items()}
            lo, hi = cluster_ci(vals)
            block[metric] = {'mean': r2(mean(list(vals.values()))), 'ci95_by_game': [r2(lo), r2(hi)]}
        block['per_game'] = {g: {k: r2(v) for k, v in d.items()} for g, d in per_game.items()}
        out[f'{x} minus {y}'] = block
    return out


def load_choices(game, arm):
    d = json.load(gzip.open(f'{AUD}/{game}/{arm}/choices.json.gz', 'rt'))
    by_seed = collections.defaultdict(list)
    for p in sorted(d['plays'], key=lambda p: (p['seed'], p['index'])):
        by_seed[p['seed']].append(p)
    draws, by_pos, dup = {}, collections.defaultdict(list), 0
    for x in d['draws']:
        if x['draw'] in draws:
            dup += 1
            continue
        draws[x['draw']] = x
        m = DRAW.match(x['draw'])
        if m:
            by_pos[(int(m.group(2)), int(m.group(3)))].append({'name': m.group(4), 'chosen': x['chosen'],
                                                              'n_ids': len(x['ids']), 'ids': x['ids'], 'weights': x['weights']})
    return by_seed, draws, by_pos, dup


def sig(p):
    return {'intent': p['intent'], 'team': p['team'], 'passer': (p['passer'] or {}).get('gsis'),
            'rusher': (p['rusher'] or {}).get('gsis'), 'receiver': (p['receiver'] or {}).get('gsis'),
            'group': (p['lineup'] or {}).get('group')}


def first_divergence(pb, pc, fields=CAUSE_ORDER):
    for i, (x, y) in enumerate(zip(pb, pc)):
        sx, sy = sig(x), sig(y)
        if sx != sy:
            kind = next((f for f in fields if sx[f] != sy[f]), None)
            if kind is None:
                continue
            return i, kind, x, y
    if len(pb) != len(pc):
        return min(len(pb), len(pc)), 'length', None, None
    return None


def draw_summary(draws, key):
    out = []
    for d in draws.get(key, []):
        w = d['weights'][d['ids'].index(d['chosen'])] if d['chosen'] in d['ids'] else None
        out.append({'name': d['name'], 'chosen': d['chosen'], 'n_candidates': d['n_ids'], 'chosen_weight': w})
    return out


def same_draw(db, dc):
    c = collections.Counter()
    for k, x in db.items():
        y = dc.get(k)
        if y is None:
            c['only_in_B'] += 1
            continue
        c['shared'] += 1
        if x['chosen'] == y['chosen']:
            c['same_chosen'] += 1
            if x['weights'] == y['weights'] and x['ids'] == y['ids']:
                c['same_chosen_same_candidates'] += 1
        else:
            c['different_chosen'] += 1
            if x['ids'] != y['ids']:
                c['different_candidate_list'] += 1
            elif x['weights'] != y['weights']:
                c['same_list_different_weights'] += 1
            else:
                c['same_list_same_weights'] += 1
    c['only_in_C'] = sum(1 for k in dc if k not in db)
    return dict(c)


def lineup_check(plays):
    checked = viol = qb_rush = 0
    status, sizes, examples = collections.Counter(), collections.Counter(), []
    for p in plays:
        lu = p['lineup'] or {}
        status[lu.get('status')] += 1
        on = set(lu.get('on_field') or [])
        sizes[len(on)] += 1
        checks = []
        if p['rusher']:
            if p['rusher']['pos'] == 'QB':
                qb_rush += 1
            else:
                checks.append(('rusher', p['rusher']['gsis']))
        if p['receiver']:
            checks.append(('receiver', p['receiver']['gsis']))
        for role, gsis in checks:
            checked += 1
            if gsis not in on:
                viol += 1
                if len(examples) < 5:
                    examples.append({'seed': p['seed'], 'index': p['index'], 'role': role, 'gsis': gsis,
                                     'status': lu.get('status'), 'group': lu.get('group')})
    return {'plays': len(plays), 'eligibility_checked': checked, 'violations': viol, 'qb_rushes_not_checked': qb_rush,
            'lineup_status': dict(status), 'on_field_sizes': dict(sizes), 'examples': examples}


def main():
    os.makedirs(OUT, exist_ok=True)
    finals, actual = load_actual()
    G = games()
    rows, margins, recs_of = [], {}, {}
    seeds = {}
    for g in G:
        for a in ARMS:
            recs = sim_runs(g, a)
            recs_of[(g, a)] = recs
            seeds[f'{g}|{a}'] = len(recs)
            margins[(g, a)] = margin_rows(recs)
            rows += build_rows(g, a, sim_means(recs), actual[g])
    logged = [r for r in rows if r['cat'] != 'sim_no_log_row']  # players with a log row, or actual players the sim missed
    res = {'games': len(G), 'seeds_per_game_arm': seeds}
    res['reconcile'] = {a: reconcile(rows, a, actual, G) for a in ARMS}
    res['carry_errors'] = {a: group_errors(rows, a, 'c') for a in ARMS}
    res['target_errors'] = {a: group_errors(rows, a, 't') for a in ARMS}
    res['carry_errors_logged_only'] = {a: group_errors(logged, a, 'c') for a in ARMS}
    res['target_errors_logged_only'] = {a: group_errors(logged, a, 't') for a in ARMS}
    res['high_volume_carries'] = {a: high_volume(rows, a) for a in ARMS}
    res['team_shares'] = {a: team_shares(rows, a) for a in ARMS}
    res['team_shares_logged_only'] = {a: team_shares(logged, a) for a in ARMS}
    res['starter_moves'] = {'A->B': starter_moves(rows, 'A-control', 'B-field'),
                            'B->C': starter_moves(rows, 'B-field', 'C-field-pbv1')}
    res['paired_scores'] = paired_scores(G, margins)

    # Choice records (arms B and C)
    all_plays = {a: [] for a in CHOICE_ARMS}
    box_check = {a: collections.Counter() for a in CHOICE_ARMS}
    divergence_kinds = collections.Counter()
    divergence_index = []
    divergence_examples = []
    outcome_kinds = collections.Counter()
    outcome_index = []
    receiver_events = {a: collections.Counter() for a in CHOICE_ARMS}
    same = collections.Counter()
    dup_total = 0
    for g in G:
        loaded = {a: load_choices(g, a) for a in CHOICE_ARMS}
        dup_total += sum(loaded[a][3] for a in CHOICE_ARMS)
        for a in CHOICE_ARMS:
            by_seed, _draws, _pos, _dup = loaded[a]
            box = {r['seed']: r for r in recs_of[(g, a)]}
            for s, plays in by_seed.items():
                all_plays[a] += plays
                box_check[a]['seeds'] += 1
                box_check[a]['rush_plays'] += sum(1 for p in plays if p['rusher'])
                box_check[a]['box_carries'] += sum(p['rushing']['att'] for p in box[s]['players'])
                for p in plays:
                    if p['receiver']:
                        receiver_events[a][box[s]['realism']['plays'][p['index']]['event_type']] += 1
                box_check[a]['target_plays'] += sum(1 for p in plays if p['receiver'])
                box_check[a]['box_targets'] += sum(p['receiving']['tgt'] for p in box[s]['players'])
                if sum(1 for p in plays if p['rusher']) != sum(p['rushing']['att'] for p in box[s]['players']):
                    box_check[a]['seeds_carry_mismatch'] += 1
                if sum(1 for p in plays if p['receiver']) != sum(p['receiving']['tgt'] for p in box[s]['players']):
                    box_check[a]['seeds_target_mismatch'] += 1
        same.update(same_draw(loaded['B-field'][1], loaded['C-field-pbv1'][1]))
        bseeds, cseeds = loaded['B-field'][0], loaded['C-field-pbv1'][0]
        for s in sorted(set(bseeds) & set(cseeds)):
            fd = first_divergence(bseeds[s], cseeds[s])
            if fd is None:
                divergence_kinds['none'] += 1
                continue
            i, kind, x, y = fd
            divergence_kinds[kind] += 1
            divergence_index.append(i)
            ofd = first_divergence(bseeds[s], cseeds[s], fields=['intent', 'passer', 'rusher', 'receiver'])
            if ofd is None:
                outcome_kinds['none'] += 1
            else:
                outcome_kinds[ofd[1]] += 1
                outcome_index.append(ofd[0])
            if len(divergence_examples) < 12:
                divergence_examples.append({
                    'game': g, 'seed': s, 'index': i, 'kind': kind,
                    'B': {'intent': x and x['intent'], 'group': x and (x['lineup'] or {}).get('group'),
                          'rusher': x and (x['rusher'] or {}).get('gsis'), 'receiver': x and (x['receiver'] or {}).get('gsis'),
                          'draws': draw_summary(loaded['B-field'][2], (s, x and x['index']))} if x else None,
                    'C': {'intent': y and y['intent'], 'group': y and (y['lineup'] or {}).get('group'),
                          'rusher': y and (y['rusher'] or {}).get('gsis'), 'receiver': y and (y['receiver'] or {}).get('gsis'),
                          'draws': draw_summary(loaded['C-field-pbv1'][2], (s, y and y['index']))} if y else None})
    res['choice_box_check'] = {a: dict(box_check[a]) for a in CHOICE_ARMS}
    res['lineup_eligibility'] = {a: lineup_check(all_plays[a]) for a in CHOICE_ARMS}
    res['shared_draws_B_vs_C'] = dict(same)
    res['duplicate_draw_keys'] = dup_total
    res['first_divergence_B_vs_C'] = {
        'seeds': sum(divergence_kinds.values()), 'kinds': dict(divergence_kinds),
        'index_median': statistics.median(divergence_index) if divergence_index else None,
        'index_min': min(divergence_index) if divergence_index else None,
        'index_max': max(divergence_index) if divergence_index else None,
        'examples': divergence_examples}
    res['first_outcome_divergence_B_vs_C'] = {
        'kinds': dict(outcome_kinds),
        'index_median': statistics.median(outcome_index) if outcome_index else None,
        'index_min': min(outcome_index) if outcome_index else None,
        'index_max': max(outcome_index) if outcome_index else None}
    res['receiver_pick_event_types'] = {a: dict(receiver_events[a]) for a in CHOICE_ARMS}
    with open(os.path.join(OUT, 'analysis.json'), 'w') as f:
        json.dump(res, f, indent=1, default=str)
    print('written', os.path.join(OUT, 'analysis.json'))


if __name__ == '__main__':
    main()
