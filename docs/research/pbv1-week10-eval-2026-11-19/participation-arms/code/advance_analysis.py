"""Advance-log analysis for the lead RB, six arms: departure cause and first-play entry. Read-only.

Departure cause: each play's advance calls list leavers (hazard departures) and count_removed (forced personnel removals).
First-play entry: for each team, seed, the first offensive play. When an RB slot is filled there, how often is the actual
lead RB among the entrants (or on the field)?
Lead RB = the RB with the most actual carries in that team-game (from the frozen DB logs). Used only to score.
"""
import collections, gzip, json, sqlite3, sys

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
    on_plays = hazard = forced = 0
    first_total = first_slot = first_lead_entry = first_lead_on = 0
    for g in GAMES:
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
                for p in seq:
                    lu = p['lineup'] or {}
                    if lead in set(lu.get('on_field') or []):
                        on_plays += 1
                    for adv in p.get('advances') or []:
                        if lead in (adv.get('leavers') or []):
                            hazard += 1
                        if lead in (adv.get('count_removed') or []):
                            forced += 1
                first = seq[0]
                lu = first['lineup'] or {}
                first_total += 1
                slots = lu.get('slots') or {}
                rb_filled = any(v == 'RB' for v in slots.values())
                if rb_filled:
                    first_slot += 1
                    entrants = set()
                    for adv in first.get('advances') or []:
                        entrants |= set(adv.get('entrants') or [])
                    if lead in entrants:
                        first_lead_entry += 1
                    if lead in set(lu.get('on_field') or []):
                        first_lead_on += 1
    out[arm] = {
        'lead_on_field_plays': on_plays,
        'hazard_departures_per_100_on_plays': round(100 * hazard / on_plays, 2),
        'forced_removals_per_100_on_plays': round(100 * forced / on_plays, 2),
        'first_play_team_seeds': first_total,
        'first_play_rb_slot_filled_share': round(first_slot / first_total, 4),
        'first_play_lead_entered_given_slot': round(first_lead_entry / first_slot, 4) if first_slot else None,
        'first_play_lead_on_field_given_slot': round(first_lead_on / first_slot, 4) if first_slot else None,
    }
print(json.dumps(out, indent=1))
json.dump(out, open(CAMP + '/advance_analysis.json', 'w'), indent=1)
