"""What the snap-count update does to the first-play entry weights. Read-only.

For the same team, seed and first play, arm B2 (no snap update) and arm HS (snap update) start from the same empty
lineup, so the same RB candidates. Compare each candidate's logged weight across the two arms in group-11 cases where
both arms are in group 11 at that play. Lead RB = the most actual carries, used only to score.
"""
import collections, gzip, json, re, sqlite3, statistics

CAMP = '/root/tnf-batch/camp'
DB = '/root/tnf-batch/picks.frozen.db'
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


def first_calls(folder, g):
    data = json.load(gzip.open('%s/%s/%s/choices.json.gz' % (CAMP, folder, g), 'rt'))
    plays = data['plays']
    calls = collections.defaultdict(list)
    for d in data['draws']:
        m = re.search(r':(\d+):(\d+):field:advance$', d['draw'])
        if m:
            calls[(int(m.group(1)), int(m.group(2)))].append(d)
    firsts = {}
    by_team_seed = collections.defaultdict(list)
    for p in plays:
        by_team_seed[(norm(p['team']), p['seed'])].append(p)
    for key, seq in by_team_seed.items():
        firsts[key] = min(seq, key=lambda p: p['index'])
    return firsts, calls


ratios_lead, ratios_back, lead_b, lead_hs, n = [], [], [], [], 0
for g in sorted(logs):
    fb, cb = first_calls('B2', g)
    fh, ch = first_calls('HS', g)
    for (team, seed), pb in fb.items():
        ph = fh.get((team, seed))
        if ph is None or pb['index'] != ph['index']:
            continue
        if (pb['lineup'] or {}).get('group') != '11' or (ph['lineup'] or {}).get('group') != '11':
            continue
        rbs = [(c, k) for k, (t, c) in logs[g].items() if t == team and pos.get(k) == 'RB']
        if not rbs:
            continue
        lead = max(rbs)[1]
        # the RB-slot call in each arm: the call whose chosen list holds the RB slot holder, and that contains the lead
        def rb_call(p, calls):
            holders = [k for k, v in ((p['lineup'] or {}).get('slots') or {}).items() if v == 'RB']
            if not holders:
                return None
            for c in calls.get((seed, p['index']), []):
                if holders[0] in c['chosen'] and lead in c['ids']:
                    return c
            return None
        cbb = rb_call(pb, cb)
        chh = rb_call(ph, ch)
        if cbb is None or chh is None or cbb['ids'] != chh['ids']:
            continue
        ids = cbb['ids']
        wb = dict(zip(ids, cbb['weights']))
        wh = dict(zip(ids, chh['weights']))
        n += 1
        tb = sum(cbb['weights'])
        th = sum(chh['weights'])
        lead_b.append(wb[lead] / tb)
        lead_hs.append(wh[lead] / th)
        ratios_lead.append(wh[lead] / wb[lead] if wb[lead] > 0 else None)
        for i in ids:
            if pos.get(i) == 'RB' and i != lead and wb[i] > 0:
                ratios_back.append(wh[i] / wb[i])

print('cases (same candidates, group 11 in both arms):', n)
print('lead weight share  B2 %.3f   HS %.3f' % (statistics.mean(lead_b), statistics.mean(lead_hs)))
rl = [r for r in ratios_lead if r is not None]
print('lead weight ratio HS/B2: median %.2f, mean %.2f' % (statistics.median(rl), statistics.mean(rl)))
print('backup RB weight ratio HS/B2: median %.2f, mean %.2f, n %d' % (statistics.median(ratios_back), statistics.mean(ratios_back), len(ratios_back)))
