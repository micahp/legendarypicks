"""Check the run-share and lead-RB findings. Read-only.

A. Run share, same definition for actual and simulated: rush / (rush + pass attempts), from player logs
   (carries; QB 'att') and box-score team stats (rush_attempts, pass_attempts).
B. Lead RB on-field rate by lineup group (arms B and C), and how often each group is used.
"""
import collections, glob, gzip, json, sqlite3

W10 = '/root/tnf-batch/w10-eval'
AUD = '/root/tnf-batch/audit'
DB = '/root/tnf-batch/picks.frozen.db'
CH = ['B-field', 'C-field-pbv1']
ARMS = ['A-control'] + CH
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
    logs[g][k] = {'team': norm(t), 'carries': d.get('carries') or 0, 'att': d.get('att') or 0, 'off_snaps': d.get('off_snaps') or 0}
con.close()
GAMES = sorted(logs)

# A. run share, log definition (actual) vs box definition (simulated)
act = {}
for g in GAMES:
    for k, p in logs[g].items():
        t = p['team']
        act.setdefault((g, t), [0, 0])
        act[(g, t)][0] += p['carries']
        act[(g, t)][1] += p['att']
actual_vals = [r / (r + p) for r, p in act.values() if r + p]
sim = {}
for arm in ARMS:
    vals = []
    for g in GAMES:
        recs = []
        for path in sorted(glob.glob('%s/%s/out/runs/%s/*.boxscores.jsonl' % (W10, g, arm))):
            with open(path) as f:
                recs += [json.loads(l) for l in f if json.loads(l).get('type') == 'game']
        rush = collections.Counter()
        pas = collections.Counter()
        for r in recs:
            for t in r['teams']:
                tt = norm(t['team'])
                rush[tt] += t['stats'].get('rush_attempts') or 0
                pas[tt] += t['stats'].get('pass_attempts') or 0
        for tt in rush:
            if rush[tt] + pas[tt]:
                vals.append(rush[tt] / (rush[tt] + pas[tt]))
    sim[arm] = round(sum(vals) / len(vals), 4)
print('A. run share, box definition:', {'actual': round(sum(actual_vals) / len(actual_vals), 4), **sim})

# B. lead RB on-field rate by group, arms B and C
group_plays = {a: collections.Counter() for a in CH}
group_lead_on = {a: collections.Counter() for a in CH}
group_lead_rate = {a: collections.defaultdict(list) for a in CH}
for g in GAMES:
    for a in CH:
        plays = json.load(gzip.open('%s/%s/%s/choices.json.gz' % (AUD, g, a), 'rt'))['plays']
        for team in {v['team'] for v in logs[g].values()}:
            rbs = [(v['carries'], k) for k, v in logs[g].items() if v['team'] == team and pos.get(k) == 'RB']
            if not rbs:
                continue
            lead = max(rbs)[1]
            for p in plays:
                if norm(p['team']) != team:
                    continue
                grp = (p['lineup'] or {}).get('group') or 'none'
                group_plays[a][grp] += 1
                if lead in set((p['lineup'] or {}).get('on_field') or []):
                    group_lead_on[a][grp] += 1
for a in CH:
    total = sum(group_plays[a].values())
    print(a, 'groups (share of plays, lead RB on-field rate):')
    for grp, n in group_plays[a].most_common(12):
        print('   %-10s %6.3f  %6.3f' % (grp, n / total, group_lead_on[a][grp] / n))
