"""Split the lead RB's exits from the field into hazard leaves, forced removals and other. Read-only.

An exit is a play where the lead was on the field on the previous team play and is not on the field on this one. The
cause is read from that play's advance calls: leavers (hazard) or count_removed (forced personnel change).
"""
import collections, gzip, json, sqlite3

CAMP = '/root/tnf-batch/camp'
DB = '/root/tnf-batch/picks.frozen.db'
ARMS = {'B': 'B2', 'C': 'C2', 'H': 'H', 'HS': 'HS', 'HP': 'HP', 'HSP': 'HSP', 'HE': 'HE'}
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

out = {}
for arm, folder in ARMS.items():
    exits = collections.Counter()
    on_plays = 0
    for g in sorted(logs):
        plays = json.load(gzip.open('%s/%s/%s/choices.json.gz' % (CAMP, folder, g), 'rt'))['plays']
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
                seq.sort(key=lambda p: p['index'])
                prev = False
                for i, p in enumerate(seq):
                    now = lead in set((p['lineup'] or {}).get('on_field') or [])
                    if now:
                        on_plays += 1
                    if prev and not now:
                        advs = p.get('advances') or []
                        if any(lead in (a.get('count_removed') or []) for a in advs):
                            exits['forced'] += 1
                        elif any(lead in (a.get('leavers') or []) for a in advs):
                            exits['hazard'] += 1
                        else:
                            exits['other'] += 1
                    prev = now
    total = sum(exits.values())
    out[arm] = {'exits': total, 'hazard_share': round(exits['hazard'] / total, 3) if total else None,
                'forced_share': round(exits['forced'] / total, 3) if total else None,
                'other_share': round(exits['other'] / total, 3) if total else None,
                'exits_per_100_on_plays': round(100 * total / on_plays, 2) if on_plays else None,
                'hazard_per_100_on_plays': round(100 * exits['hazard'] / on_plays, 2) if on_plays else None,
                'forced_per_100_on_plays': round(100 * exits['forced'] / on_plays, 2) if on_plays else None}
print(json.dumps(out, indent=1))
json.dump(out, open(CAMP + '/exit_split.json', 'w'), indent=1)
