"""Does the participation field suppress lead RB snaps or run opportunities? Read-only.

1. Run share per team-game: actual (nfl_pbp run / (run + pass)) vs simulated (box rush_attempts / (rush + pass)) per arm.
2. Lead RB per team-game: actual = RB with most carries; simulated = RB with most mean carries across seeds.
   Counts agreement, and on-field rate of the actual lead RB (arms B and C, choice records).
"""
import collections, glob, gzip, json, sqlite3

W10 = '/root/tnf-batch/w10-eval'
AUD = '/root/tnf-batch/audit'
DB = '/root/tnf-batch/picks.frozen.db'
ARMS = ['A-control', 'B-field', 'C-field-pbv1']
CH = ['B-field', 'C-field-pbv1']
NORM = {'WSH': 'WAS', 'LAR': 'LA'}


def norm(t):
    return NORM.get(t, t)


con = sqlite3.connect('file:%s?mode=ro' % DB, uri=True)
pbp = {}
for gid, team, run, pss in con.execute(
        "select game_id, posteam, sum(case when play_type='run' then 1 else 0 end), "
        "sum(case when play_type='pass' then 1 else 0 end) from nfl_pbp where season=2026 and week=10 "
        "and posteam is not null group by game_id, posteam"):
    pbp[(gid, norm(team))] = (run, pss)
pos = {k: p for k, p in con.execute('select nfl_gsis_id, position from players where nfl_gsis_id is not null')}
logs = collections.defaultdict(dict)
for gid, key, team, stats in con.execute(
        "select game_id, source_player_key, team, stats from player_game_logs where season=2026 and league='nfl' "
        "and game_id like '2026_10_%' and game_type='REG'"):
    s = json.loads(stats) if stats else {}
    logs[gid][key] = {'team': norm(team), 'carries': s.get('carries') or 0}
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
    return recs


# 1. Run share
share = {}
for arm in ARMS:
    vals = []
    for g in GAMES:
        recs = box(g, arm)
        n = len(recs)
        rush = collections.Counter()
        pas = collections.Counter()
        for r in recs:
            for t in r['teams']:
                team = norm(t['team'])
                rush[team] += t['stats'].get('rush_attempts') or 0
                pas[team] += t['stats'].get('pass_attempts') or 0
        for team in rush:
            tot = rush[team] + pas[team]
            if tot:
                vals.append(rush[team] / tot)
    share[arm] = round(sum(vals) / len(vals), 4)
actual_share_vals = []
for g in GAMES:
    for (gg, team), (run, pss) in pbp.items():
        if gg == g and run + pss:
            actual_share_vals.append(run / (run + pss))
share['actual'] = round(sum(actual_share_vals) / len(actual_share_vals), 4)

# 2. Lead RB agreement and on-field rate
agree = 0
total = 0
on_rate = {a: [] for a in CH}
for g in GAMES:
    for team in {v['team'] for v in logs[g].values()}:
        rbs = [(v['carries'], k) for k, v in logs[g].items() if v['team'] == team and pos.get(k) == 'RB']
        if not rbs:
            continue
        actual_lead = max(rbs)[1]
        total += 1
        for a in CH:
            recs = box(g, a)
            n = len(recs)
            mean = collections.Counter()
            for r in recs:
                for p in r['players']:
                    if norm(p['team']) == team and p['position'] == 'RB':
                        mean[p['stable_player_id']] += p['rushing']['att'] / n
            sim_lead = max(mean, key=mean.get) if mean else None
            if a == CH[0] and sim_lead == actual_lead:
                agree += 1
            plays = json.load(gzip.open('%s/%s/%s/choices.json.gz' % (AUD, g, a), 'rt'))['plays']
            team_plays = sum(1 for p in plays if norm(p['team']) == team)
            seeds = len({p['seed'] for p in plays})
            on = sum(1 for p in plays if norm(p['team']) == team and actual_lead in set((p['lineup'] or {}).get('on_field') or []))
            if team_plays:
                on_rate[a].append(on / team_plays)
res = {'run_share': share,
       'lead_rb_team_games': total,
       'sim_lead_agrees_with_actual_B': agree,
       'actual_lead_on_field_rate_mean': {a: round(sum(v) / len(v), 4) for a, v in on_rate.items()}}
print(json.dumps(res, indent=1))
