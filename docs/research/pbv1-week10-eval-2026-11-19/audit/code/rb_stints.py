"""RB slot stints in the simulated lineups (arms B and C). Read-only.

For each game, seed and team, walk that team's offensive plays in order. Track the RB-slot holder on each play.
Report: how often the holder changes, split by whether the grouping changed; stint lengths (consecutive plays with
the same holder); and how the lead RB (most actual carries) does on stints.
"""
import collections, gzip, json, sqlite3

AUD = '/root/tnf-batch/audit'
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

for arm in ['B-field', 'C-field-pbv1']:
    pairs = collections.Counter()  # (group changed?, holder changed?) counts over consecutive team plays
    stints_all = []
    stints_lead = []
    lead_holds = collections.Counter()
    for g in sorted(logs):
        plays = json.load(gzip.open('%s/%s/%s/choices.json.gz' % (AUD, g, arm), 'rt'))['plays']
        for team in {v[0] for v in logs[g].values()}:
            rbs = [(c, k) for k, (tt, c) in logs[g].items() if tt == team and pos.get(k) == 'RB']
            if not rbs:
                continue
            lead = max(rbs)[1]
            by_seed = collections.defaultdict(list)
            for p in plays:
                if norm(p['team']) == team:
                    by_seed[p['seed']].append(p)
            for seed, seq in by_seed.items():
                seq.sort(key=lambda p: p['index'])
                holders = []
                groups = []
                for p in seq:
                    lu = p['lineup'] or {}
                    slots = lu.get('slots') or {}
                    rb = [k for k, v in slots.items() if v == 'RB']
                    holders.append(rb[0] if rb else None)
                    groups.append(lu.get('group'))
                for i in range(1, len(holders)):
                    grp_changed = groups[i] != groups[i - 1]
                    hold_changed = holders[i] != holders[i - 1]
                    pairs[(grp_changed, hold_changed)] += 1
                # stints of the same holder
                run = 1
                for i in range(1, len(holders) + 1):
                    if i < len(holders) and holders[i] == holders[i - 1]:
                        run += 1
                        continue
                    if holders[i - 1] is not None:
                        stints_all.append(run)
                        if holders[i - 1] == lead:
                            stints_lead.append(run)
                    run = 1
                for h in holders:
                    if h is not None:
                        lead_holds['lead' if h == lead else 'other'] += 1
    n_same_group = pairs[(False, False)] + pairs[(False, True)]
    n_changed_group = pairs[(True, False)] + pairs[(True, True)]
    print(arm)
    print('   consecutive plays, same grouping: %d; holder changed: %.3f' % (
        n_same_group, pairs[(False, True)] / n_same_group))
    print('   consecutive plays, grouping changed: %d; holder changed: %.3f' % (
        n_changed_group, pairs[(True, True)] / n_changed_group))
    print('   stint length, any RB holder: mean %.2f, n %d' % (sum(stints_all) / len(stints_all), len(stints_all)))
    print('   stint length, lead RB as holder: mean %.2f, n %d' % (sum(stints_lead) / len(stints_lead), len(stints_lead)))
    print('   plays with lead RB holding slot: %d of %d' % (lead_holds['lead'], lead_holds['lead'] + lead_holds['other']))
