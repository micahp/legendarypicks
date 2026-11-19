"""Week 10 participation experiment: metrics by arm, on the games complete for every arm requested. Read-only.

Arms: B and C (existing, audit records and w10-eval box scores), H, HS, HP, HSP (campaign runs, /root/tnf-batch/camp).
Departures and returns come from the on-field lineup of each play, so they are the same measure for every arm.
Usage: python3 camp_report.py ARM[,ARM...] OUT.json
"""
import collections, glob, gzip, json, os, random, sqlite3, sys

AUD = '/root/tnf-batch/audit'
W10 = '/root/tnf-batch/w10-eval'
CAMP = '/root/tnf-batch/camp'
DB = '/root/tnf-batch/picks.frozen.db'
NORM = {'WSH': 'WAS', 'LAR': 'LA'}
BASE = {'B': ('B-field', AUD), 'C': ('C-field-pbv1', AUD)}


def norm(t):
    return NORM.get(t, t)


def files(arm, game):
    if arm in BASE:
        name, _ = BASE[arm]
        choices = f'{AUD}/{game}/{name}/choices.json.gz'
        boxes = sorted(glob.glob(f'{W10}/{game}/out/runs/{name}/*.boxscores.jsonl'))
    else:
        choices = f'{CAMP}/{arm}/{game}/choices.json.gz'
        boxes = [f'{CAMP}/{arm}/{game}/run.boxscores.jsonl']
    return choices, boxes


def complete(arm, game):
    choices, boxes = files(arm, game)
    return os.path.exists(choices) and all(os.path.exists(b) for b in boxes) and boxes != []


def load_boxes(boxes):
    recs = []
    for path in boxes:
        with open(path) as f:
            recs += [json.loads(l) for l in f if json.loads(l).get('type') == 'game']
    return recs


def margin(r):
    pts = {norm(k): sum(v.values()) for k, v in r['points_by_period'].items()}
    return pts[norm(r['home_team'])] - pts[norm(r['away_team'])]


def main(arms, out):
    con = sqlite3.connect('file:%s?mode=ro' % DB, uri=True)
    pos = {k: p for k, p in con.execute('select nfl_gsis_id, position from players where nfl_gsis_id is not null')}
    logs = collections.defaultdict(dict)
    for g, k, t, s in con.execute(
            "select game_id, source_player_key, team, stats from player_game_logs where season=2026 and league='nfl' "
            "and game_id like '2026_10_%' and game_type='REG'"):
        d = json.loads(s) if s else {}
        logs[g][k] = (norm(t), d.get('carries') or 0)
    con.close()
    games = sorted(logs)
    use = [g for g in games if all(complete(a, g) for a in arms)]
    res = {'arms': arms, 'games': use, 'n_games': len(use), 'metrics': {}}
    per_arm = {a: collections.defaultdict(list) for a in arms}
    margins = {a: {} for a in arms}
    for a in arms:
        for g in use:
            choices, boxes = files(a, g)
            plays = json.load(gzip.open(choices, 'rt'))['plays']
            recs = load_boxes(boxes)
            for r in recs:
                margins[a][(g, r['seed'])] = margin(r)
            n = len(recs)
            team_carries = collections.Counter()
            lead_carries = collections.Counter()
            for r in recs:
                for p in r['players']:
                    if p['stable_player_id'] in {k for k in logs[g]}:
                        pass
            for team in {v[0] for v in logs[g].values()}:
                rbs = [(c, k) for k, (t, c) in logs[g].items() if t == team and pos.get(k) == 'RB']
                if not rbs:
                    continue
                lead = max(rbs)[1]
                actual_lead_carries = max(rbs)[0]
                sim_lead = 0.0
                for r in recs:
                    for p in r['players']:
                        if p['stable_player_id'] == lead:
                            sim_lead += p['rushing']['att']
                per_arm[a]['lead_carries_sim'].append(sim_lead / n)
                per_arm[a]['lead_carries_actual'].append(actual_lead_carries)
                by_seed = collections.defaultdict(list)
                for p in plays:
                    if norm(p['team']) == team:
                        by_seed[p['seed']].append(p)
                for seed, seq in by_seed.items():
                    seq.sort(key=lambda p: p['index'])
                    on = [lead in set((p['lineup'] or {}).get('on_field') or []) for p in seq]
                    per_arm[a]['onfield_rate'].append(sum(on) / len(on))
                    per_arm[a]['initial_on'].append(float(on[0]))
                    g11 = [p for p in seq if (p['lineup'] or {}).get('group') == '11']
                    if g11:
                        held = sum(1 for p in g11 if (p['lineup'] or {}).get('slots', {}).get(lead) == 'RB')
                        per_arm[a]['slot11_occupancy'].append(held / len(g11))
                    off_plays = 0
                    for i in range(1, len(on)):
                        if on[i - 1] and not on[i]:
                            per_arm[a]['departures'].append(1)
                        if on[i]:
                            pass
                    per_arm[a]['on_plays'].append(sum(on))
                    per_arm[a]['departure_count'].append(sum(1 for i in range(1, len(on)) if on[i - 1] and not on[i]))
                    # off spells that end in a return
                    spell = 0
                    for i, v in enumerate(on):
                        if not v:
                            spell += 1
                        elif spell:
                            per_arm[a]['return_after'].append(spell)
                            spell = 0
                    per_arm[a]['off_end_censored'].append(1 if spell else 0)
    for a in arms:
        d = per_arm[a]
        m = {}
        m['lead_onfield_rate'] = round(sum(d['onfield_rate']) / len(d['onfield_rate']), 4)
        m['lead_initial_on'] = round(sum(d['initial_on']) / len(d['initial_on']), 4)
        m['slot11_occupancy'] = round(sum(d['slot11_occupancy']) / len(d['slot11_occupancy']), 4)
        m['departures_per_100_on_plays'] = round(100 * sum(d['departure_count']) / sum(d['on_plays']), 3)
        m['mean_plays_off_before_return'] = round(sum(d['return_after']) / len(d['return_after']), 2) if d['return_after'] else None
        m['spells_not_ended_by_return'] = sum(d['off_end_censored'])
        m['lead_carries_sim_per_game'] = round(sum(d['lead_carries_sim']) / len(d['lead_carries_sim']), 2)
        m['lead_carries_actual_per_game'] = round(sum(d['lead_carries_actual']) / len(d['lead_carries_actual']), 2)
        res['metrics'][a] = m
    # paired margin differences against B and C, cluster bootstrap over games
    res['margin_vs'] = {}
    rng = random.Random(1)
    for a in arms:
        for base in ['B', 'C']:
            if base == a or base not in arms:
                continue
            per_game = collections.defaultdict(list)
            for (g, s), v in margins[a].items():
                if (g, s) in margins[base]:
                    per_game[g].append(v - margins[base][(g, s)])
            gm = [sum(v) / len(v) for v in per_game.values()]
            boots = sorted(sum(rng.choice(gm) for _ in gm) / len(gm) for _ in range(4000))
            res['margin_vs'][f'{a} minus {base}'] = {
                'paired_seeds': sum(len(v) for v in per_game.values()), 'mean': round(sum(gm) / len(gm), 3),
                'ci95_by_game': [round(boots[100], 3), round(boots[3899], 3)]}
    with open(out, 'w') as f:
        json.dump(res, f, indent=1)
    print(json.dumps(res, indent=1))


if __name__ == '__main__':
    main(sys.argv[1].split(','), sys.argv[2])
