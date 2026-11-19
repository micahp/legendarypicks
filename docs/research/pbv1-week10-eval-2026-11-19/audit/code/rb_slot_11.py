"""Who fills the single RB slot in group-11 plays? Read-only.

For each team-game, the lead RB is the RB with the most actual carries. Group-11 plays are split by whether the
lead RB holds the RB slot (slots[gsis] == 'RB'), and whether the lead is on the field.
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
    slots_per_play = collections.Counter()
    slot_holder = collections.Counter()
    lead_on = collections.Counter()
    total = 0
    for g in sorted(logs):
        plays = json.load(gzip.open('%s/%s/%s/choices.json.gz' % (AUD, g, arm), 'rt'))['plays']
        for team in {v[0] for v in logs[g].values()}:
            rbs = [(c, k) for k, (tt, c) in logs[g].items() if tt == team and pos.get(k) == 'RB']
            if not rbs:
                continue
            lead = max(rbs)[1]
            for p in plays:
                lu = p['lineup'] or {}
                if norm(p['team']) != team or lu.get('group') != '11':
                    continue
                total += 1
                slots = lu.get('slots') or {}
                rb_slot = [k for k, v in slots.items() if v == 'RB']
                slots_per_play[len(rb_slot)] += 1
                if rb_slot:
                    slot_holder['lead' if rb_slot[0] == lead else 'other RB'] += 1
                lead_on['on field' if lead in set(lu.get('on_field') or []) else 'off field'] += 1
    print(arm, 'group 11 plays (for these team-games):', total)
    print('   RB slots per play:', dict(slots_per_play))
    print('   RB slot held by:', dict(slot_holder))
    print('   lead RB:', dict(lead_on))
