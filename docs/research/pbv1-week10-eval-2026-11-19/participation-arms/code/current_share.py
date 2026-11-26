"""Current-season snap share (weeks 1 to 9) of the lead RB vs the backups, in group-11 first-play cases. Read-only.

Share = the player's offensive snaps over his team's offensive snaps, summed over weeks 1 to 9. Same cases as
group11_rates.py: arm B2, group 11 at the team's first play, an RB slot filled, the lead RB among the candidates.
"""
import collections, gzip, json, re, sqlite3, statistics

CAMP = '/root/tnf-batch/camp'
DB = '/root/tnf-batch/picks.frozen.db'
SNAPS = '/root/tnf-batch/field/out/snapcounts_2026_w9.json'
NORM = {'WSH': 'WAS', 'LAR': 'LA'}


def norm(t):
    return NORM.get(t, t)


sn = json.load(open(SNAPS))
team_plays = collections.Counter()
for team, week, total in sn['team_snaps']:
    team_plays[norm(team)] += total
player_snaps = collections.Counter()
for team, week, gsis, pos_, snaps in sn['player_snaps']:
    player_snaps[gsis] += snaps
share = lambda gsis, team: player_snaps.get(gsis, 0.0) / team_plays[team] if team_plays[team] else 0.0

con = sqlite3.connect('file:%s?mode=ro' % DB, uri=True)
pos = {k: p for k, p in con.execute('select nfl_gsis_id, position from players where nfl_gsis_id is not null')}
logs = collections.defaultdict(dict)
for g, k, t, s in con.execute(
        "select game_id, source_player_key, team, stats from player_game_logs where season=2026 and league='nfl' "
        "and game_id like '2026_10_%' and game_type='REG'"):
    d = json.loads(s) if s else {}
    logs[g][k] = (norm(t), d.get('carries') or 0)
con.close()

lead_share, backup_share, lead_top, cases = [], [], 0, 0
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
            holders = [k for k, v in (lu.get('slots') or {}).items() if v == 'RB']
            if not holders:
                continue
            cands = [c for c in calls.get((seed, first['index']), []) if holders[0] in c['chosen']]
            if not cands or lead not in cands[0]['ids']:
                continue
            ids = cands[0]['ids']
            rb = [i for i in ids if pos.get(i) == 'RB']
            others = [i for i in rb if i != lead]
            cases += 1
            ls = share(lead, team)
            lead_share.append(ls)
            if others:
                bs = [share(i, team) for i in others]
                backup_share.append(statistics.mean(bs))
                if ls >= max(bs):
                    lead_top += 1

print('cases:', cases)
print('lead RB current-season snap share (weeks 1-9): mean %.3f' % statistics.mean(lead_share))
print('backup RB current-season snap share: mean %.3f' % statistics.mean(backup_share))
print('cases where the lead has the highest current share:', lead_top, 'of', len(backup_share))
