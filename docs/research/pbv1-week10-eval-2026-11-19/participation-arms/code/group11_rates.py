"""Why is the lead RB's entry weight near 47% in group 11? Read-only.

Rebuild each RB's rate from the field file with the code's formula:
  rate = (appearances[pid, team, group] + 20 * prior[pos, group]) / (team_plays[team, group] + 20)
Check it against the weights logged in arm B (no snap update there, so the logged weight should equal the rate).
Then compare the lead RB with the other RB candidates in group 11 first-play cases.
"""
import collections, gzip, json, re, sqlite3, statistics

CAMP = '/root/tnf-batch/camp'
DB = '/root/tnf-batch/picks.frozen.db'
FIELD = '/root/tnf-batch/field/out/field_rebuild_base.json'
PRIOR_PLAYS = 20.0
NORM = {'WSH': 'WAS', 'LAR': 'LA'}


def norm(t):
    return NORM.get(t, t)


f = json.load(open(FIELD))
app = {(p, t, g): v for p, t, g, v in f['appearances']}
tp = {(t, g): v for t, g, v in f['team_plays']}
prior = {(pos, g): v for pos, g, v in f['position_prior']}


def rate(pid, team, group, pos):
    return (app.get((pid, team, group), 0.0) + PRIOR_PLAYS * prior.get((pos, group), 0.0)) / (tp.get((team, group), 0.0) + PRIOR_PLAYS)


con = sqlite3.connect('file:%s?mode=ro' % DB, uri=True)
pos = {k: p for k, p in con.execute('select nfl_gsis_id, position from players where nfl_gsis_id is not null')}
logs = collections.defaultdict(dict)
for g, k, t, s in con.execute(
        "select game_id, source_player_key, team, stats from player_game_logs where season=2026 and league='nfl' "
        "and game_id like '2026_10_%' and game_type='REG'"):
    d = json.loads(s) if s else {}
    logs[g][k] = (norm(t), d.get('carries') or 0)
con.close()

data = json.load(gzip.open('%s/B2/%s/choices.json.gz' % (CAMP, '2026_10_KC_ATL'), 'rt'))  # sanity load
checked = mismatch = 0
lead_rates, backup_rates, lead_app, backup_app, lead_w, backup_w = [], [], [], [], [], []
lead_is_top = 0
cases = 0
for g in sorted(logs):
    data = json.load(gzip.open('%s/B2/%s/choices.json.gz' % (CAMP, g), 'rt'))
    plays, draws = data['plays'], data['draws']
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
            lu = first['lineup'] or {}
            if lu.get('group') != '11':
                continue
            slots = lu.get('slots') or {}
            holders = [k for k, v in slots.items() if v == 'RB']
            if not holders:
                continue
            cands = [c for c in calls.get((seed, first['index']), []) if holders[0] in c['chosen']]
            if not cands or lead not in cands[0]['ids']:
                continue
            call = cands[0]
            cases += 1
            total = sum(call['weights'])
            rb_ids = [i for i in call['ids'] if pos.get(i) == 'RB']
            for i in call['ids']:
                if pos.get(i) != 'RB':
                    continue
                w = call['weights'][call['ids'].index(i)]
                r = rate(i, team, '11', 'RB')
                checked += 1
                if abs(r - w) > 1e-9:
                    mismatch += 1
            r_lead = rate(lead, team, '11', 'RB')
            lead_rates.append(r_lead)
            lead_app.append(app.get((lead, team, '11'), 0.0))
            lead_w.append(call['weights'][call['ids'].index(lead)])
            others = [i for i in rb_ids if i != lead]
            if others:
                backup_rates.append(statistics.mean(rate(i, team, '11', 'RB') for i in others))
                backup_app.append(statistics.mean(app.get((i, team, '11'), 0.0) for i in others))
                backup_w.append(statistics.mean(call['weights'][call['ids'].index(i)] for i in others))
                if r_lead >= max(rate(i, team, '11', 'RB') for i in others):
                    lead_is_top += 1

print('cases with lead in group 11 and an RB slot:', cases)
print('RB weights rebuilt from field file: checked', checked, 'mismatches', mismatch)
print('lead RB rate (formula): mean %.3f' % statistics.mean(lead_rates))
print('backup RB rate (formula): mean %.3f' % statistics.mean(backup_rates))
print('lead RB appearances (field file): mean %.3f' % statistics.mean(lead_app))
print('backup RB appearances (field file): mean %.3f' % statistics.mean(backup_app))
print('lead RB logged weight: mean %.3f' % statistics.mean(lead_w))
print('backup RB logged weight: mean %.3f' % statistics.mean(backup_w))
print('cases where lead RB has the highest formula rate:', lead_is_top, 'of', len(backup_rates))
