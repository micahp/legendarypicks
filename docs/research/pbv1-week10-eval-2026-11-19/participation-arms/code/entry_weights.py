"""First-play RB entry, split by bench weight. Read-only.

For each team and seed, take the team's first offensive play. Its RB slot holder was chosen in the RB-class draw. The draw
log has each draw's candidates (ids), weights and chosen ids, keyed by seed and play index. Find the call that chose the RB
holder, then the lead RB's share of that call's weight, and whether he was chosen.
Lead RB = the RB with the most actual carries in that team-game (from the frozen DB). Used only to score.
"""
import collections, gzip, json, re, sqlite3, statistics

CAMP = '/root/tnf-batch/camp'
DB = '/root/tnf-batch/picks.frozen.db'
ARMS = {'B': 'B2', 'C': 'C2', 'H': 'H', 'HS': 'HS', 'HP': 'HP', 'HSP': 'HSP'}
NORM = {'WSH': 'WAS', 'LAR': 'LA'}


def norm(t):
    return NORM.get(t, t)


con = sqlite3.connect('file:%s?mode=ro' % DB, uri=True)
pos = {k: p for k, p in con.execute('select nfl_gsis_id, position from players where nfl_gsis_id is not null')}
logs = collections.defaultdict(dict)
for g, k, t, s in con.execute(
        "select game_id, source_player_key, team, stats from player_game_logs where season=2026 and league='nfl' "
        "and game_id like '2026_10_%' and game_type='REG'"):
    d = json.loads(s) if s else {}
    logs[g][k] = (norm(t), d.get('carries') or 0)
con.close()
GAMES = sorted(logs)

out = {}
for arm, folder in ARMS.items():
    rows = []
    no_call = no_lead = 0
    for g in GAMES:
        data = json.load(gzip.open('%s/%s/%s/choices.json.gz' % (CAMP, folder, g), 'rt'))
        plays, draws = data['plays'], data['draws']
        # index advance-draw calls by (seed, play index)
        calls = collections.defaultdict(list)
        for d in draws:
            m = re.search(r':(\d+):(\d+):field:advance$', d['draw'])
            if m:
                calls[(int(m.group(1)), int(m.group(2)))].append(d)
        for team in {v[0] for v in logs[g].values()}:
            rbs = [(c, k) for k, (t, c) in logs[g].items() if t == team and pos.get(k) == 'RB']
            if not rbs:
                continue
            lead = max(rbs)[1]
            by_seed = collections.defaultdict(list)
            for p in plays:
                if norm(p['team']) == team:
                    by_seed[p['seed']].append(p)
            for seed, seq in by_seed.items():
                first = min(seq, key=lambda p: p['index'])
                slots = (first['lineup'] or {}).get('slots') or {}
                holders = [k for k, v in slots.items() if v == 'RB']
                if not holders:
                    continue  # no RB slot at the first play
                holder = holders[0]
                cands = [c for c in calls.get((seed, first['index']), []) if holder in c['chosen']]
                if not cands:
                    no_call += 1
                    continue
                call = cands[0]
                if lead not in call['ids']:
                    no_lead += 1
                    continue
                w = call['weights']
                total = sum(w)
                share = w[call['ids'].index(lead)] / total if total else None
                rows.append({'share': share, 'picked': lead in call['chosen'], 'n': len(call['ids'])})
    if not rows:
        out[arm] = None
        continue
    shares = [r['share'] for r in rows if r['share'] is not None]
    # bins by lead weight share
    bins = collections.defaultdict(list)
    for r in rows:
        if r['share'] is None:
            continue
        b = min(int(r['share'] * 5), 4)  # 0-20, 20-40, 40-60, 60-80, 80-100 percent
        bins[b].append(r)
    out[arm] = {
        'cases': len(rows), 'no_rb_call_found': no_call, 'lead_not_in_candidates': no_lead,
        'mean_lead_weight_share': round(statistics.mean(shares), 4),
        'lead_picked_rate': round(sum(r['picked'] for r in rows) / len(rows), 4),
        'by_lead_weight_share': {
            f'{b*20}-{b*20+20}%': {'cases': len(v), 'mean_share': round(statistics.mean(x['share'] for x in v), 3),
                                   'picked_rate': round(sum(x['picked'] for x in v) / len(v), 3)}
            for b, v in sorted(bins.items())}}
print(json.dumps(out, indent=1))
json.dump(out, open(CAMP + '/entry_weights.json', 'w'), indent=1)
