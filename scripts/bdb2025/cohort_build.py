import csv, glob, json, random, collections
AUD = '/root/nfl-tracking-data/bdb2025/audit'; D = '/root/nfl-tracking-data/bdb2025/code-data'
rng = random.Random(20261024)
sack = {tuple(x) for x in json.load(open(f'{AUD}/qb_sack_plays.json'))}
flags = {}
for r in csv.DictReader(open(f'{D}/player_play.csv', newline='', encoding='utf-8')):
    if r['soloTackle'] == '1': flags[(r['gameId'], r['playId'], r['nflId'])] = 'solo'
    elif r['tackleAssist'] == '1': flags[(r['gameId'], r['playId'], r['nflId'])] = 'tackleAssist'
    elif r['assistedTackle'] == '1': flags[(r['gameId'], r['playId'], r['nflId'])] = 'assistedTackle'
rows = []
for f in sorted(glob.glob(f'{AUD}/week*_plays_audit.csv')):
    rows += list(csv.DictReader(open(f, newline='', encoding='utf-8')))
def det(r): return json.loads(r['credited_detail'] or '[]')
def reasons(r):
    out = []
    if r['cat'].startswith('A'):
        d = det(r)
        if r['carrier_status'] != 'single': out.append('carrier_not_single')
        if r['carrier_status'] == 'single' and (not d or any(x.get('status') != 'ok' for x in d)): out.append('credited_not_tracked_at_tackle')
        if d and min(x['dist_m'] for x in d if x.get('status') == 'ok') > 3: out.append('credited_gt3m_at_tackle')
        if r.get('football_to_carrier_yd') not in ('', None) and float(r['football_to_carrier_yd']) > 2: out.append('football_carrier_gt2yd')
        if r['tackle_time_from_snap_s'] and float(r['tackle_time_from_snap_s']) > 15: out.append('tackle_after_15s')
        if (r['gameId'], r['playId']) in sack: out.append('qb_sack_event')
        if r['passResult'] == 'IN': out.append('incomplete_pass_tackle_event')
        if not r['snap'] or not r['T'] or int(r['T']) < int(r['snap']): out.append('no_valid_snap_or_tackle_frame')
    else:
        out.append('no_tackle_event' if r['cat'].startswith('C') else 'event_only_no_label')
    return out
for r in rows:
    r['reasons'] = reasons(r)
    r['primary_reason'] = r['reasons'][0] if r['reasons'] else 'eligible'
A = [r for r in rows if r['cat'].startswith('A')]
elig_A = [r for r in A if not r['reasons']]
print('A total', len(A), 'eligible', len(elig_A))
print('A exclusion reasons (any):', collections.Counter(x for r in A for x in r['reasons']).most_common())
print('A primary reasons:', collections.Counter(r['primary_reason'] for r in A).most_common())
# ---- visual cohort (week 1, exploratory): one play per category
w1 = [r for r in rows if r['week'] == '1']
def pick(cands, label):
    cands = sorted(cands, key=lambda r: (r['gameId'], r['playId']))
    return rng.choice(cands) if cands else None
def solo_typ(r): return r in elig_A and flags.get((r['gameId'], r['playId'], det(r)[0]['id'] if det(r) else ''), '') == 'solo' and len(det(r)) == 1
def assist_typ(kind):
    return lambda r: r in elig_A and any(flags.get((r['gameId'], r['playId'], x['id'])) == kind for x in det(r))
visual = []
spec = [
 ('V1 solo tackle, typical geometry', [r for r in w1 if r in elig_A and solo_typ(r)]),
 ('V2 tackleAssist, typical geometry', [r for r in w1 if assist_typ('tackleAssist')(r)]),
 ('V3 assistedTackle, typical geometry', [r for r in w1 if assist_typ('assistedTackle')(r)]),
 ('V4 two credited defenders', [r for r in w1 if r in elig_A and len(det(r)) == 2]),
 ('V5 unusual distance (credited > 3 m at tackle frame)', [r for r in w1 if r['cat'].startswith('A') and det(r) and min(x['dist_m'] for x in det(r) if x.get('status')=='ok') > 3]),
 ('V6 ambiguous: tackle event, no carrier label (incomplete pass)', [r for r in w1 if r['cat'].startswith('A') and r['carrier_status'] == 'none']),
 ('V7 ambiguous: event only, no credited defender', [r for r in w1 if r['cat'].startswith('B')]),
 ('V8 label only, out-of-bounds ending', [r for r in w1 if r['cat'].startswith('C') and r['oob_frame']]),
 ('V9 label only, no out-of-bounds or sack (unexplained)', [r for r in w1 if r['cat'].startswith('C') and not r['oob_frame'] and (r['gameId'], r['playId']) not in sack]),
]
for label, cands in spec:
    pk = pick(cands, label)
    if pk is None:
        print('NO CANDIDATE', label); continue
    visual.append((label, pk))
print('visual picked', len(visual))
# ---- development sample: weeks 2-5, eligible A, max 2 per game, 40 plays
pool = [r for r in elig_A if r['week'] in ('2', '3', '4', '5')]
rng.shuffle(pool)
per_game = collections.Counter(); dev = []
for r in sorted(pool, key=lambda r: (r['gameId'], r['playId'])):
    pass
rng.shuffle(pool)
for r in pool:
    if per_game[r['gameId']] >= 2: continue
    per_game[r['gameId']] += 1; dev.append(r)
    if len(dev) == 40: break
print('dev picked', len(dev), 'games', len(per_game))
holdout_games = sorted({g for g, w in [(r['gameId'], r['week']) for r in rows] if w in ('6', '7', '8', '9')})
json.dump({'visual': [[l, r['week'], r['gameId'], r['playId']] for l, r in visual],
           'dev': [[r['week'], r['gameId'], r['playId']] for r in dev],
           'holdout_games_weeks_6_9': len(holdout_games), 'seed': 20261024,
           'eligible_A': len(elig_A), 'A_total': len(A)}, open(f'{AUD}/cohort_selection.json', 'w'), indent=1)
# full table of all plays with reasons
fields = ['week','gameId','playId','cat','carrier_status','n_credited','credited_ids','passResult','snap','T','primary_reason','reasons']
with open(f'{AUD}/eligibility_all_plays.csv', 'w', newline='', encoding='utf-8') as f:
    w = csv.writer(f); w.writerow(fields)
    for r in rows:
        w.writerow([r['week'], r['gameId'], r['playId'], r['cat'], r['carrier_status'], r['n_credited'], r['credited_ids'], r['passResult'], r['snap'], r['T'], r['primary_reason'], ';'.join(r['reasons'])])
print('wrote eligibility_all_plays.csv', len(rows))
for label, r in visual: print(' ', label, '|', r['week'], r['gameId'], r['playId'], '| credited', r['credited_ids'], '| carrier', r['carrier_status'], '| reasons', r['reasons'])
