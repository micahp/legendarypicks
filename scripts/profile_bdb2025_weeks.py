"""Profile the 2025 Big Data Bowl tracking weeks 1-9 (staged by scripts/fetch_bdb2025_week.py).

One streaming pass per week. Reconciles play counts with plays.csv and tackle events with player_play.csv tackle flags.
Writes week_profiles.json and week<N>_tackle_event_plays.json under /root/nfl-tracking-data/bdb2025/ (outside git).
"""
import csv, json, collections, statistics as st
D = '/root/nfl-tracking-data/bdb2025/code-data'
OUT = '/root/nfl-tracking-data/bdb2025'
games = list(csv.DictReader(open(f'{D}/games.csv', newline='', encoding='utf-8')))
week_of = {r['gameId']: int(r['week']) for r in games}
pl = list(csv.DictReader(open(f'{D}/plays.csv', newline='', encoding='utf-8')))
pp = list(csv.DictReader(open(f'{D}/player_play.csv', newline='', encoding='utf-8')))
label_by_week = collections.defaultdict(set)
for r in pp:
    if r['soloTackle'] == '1' or r['tackleAssist'] == '1' or r['assistedTackle'] == '1':
        label_by_week[week_of[r['gameId']]].add((r['gameId'], r['playId']))
plays_by_week = collections.defaultdict(set)
for r in pl:
    plays_by_week[week_of[r['gameId']]].add((r['gameId'], r['playId']))
results = {}
for w in range(1, 10):
    path = f'{D}/tracking_week_{w}.csv'
    frame_types = collections.Counter(); events = collections.Counter(); ball_rows = 0; rows = 0
    plays = {}
    tackle_exact = set()
    with open(path, newline='', encoding='utf-8') as f:
        for row in csv.DictReader(f):
            rows += 1
            key = (row['gameId'], row['playId'])
            frame_types[row['frameType']] += 1
            ev = row['event']
            if ev != 'NA':
                events[ev] += 1
                if ev == 'tackle':
                    tackle_exact.add(key)
            if row['nflId'] in ('', 'NA'):
                ball_rows += 1
            fr = int(row['frameId'])
            p = plays.get(key)
            if p is None:
                plays[key] = {'min': fr, 'max': fr, 'n': 0}
                p = plays[key]
            p['min'] = min(p['min'], fr); p['max'] = max(p['max'], fr); p['n'] += 1
    span = [v['max'] - v['min'] + 1 for v in plays.values()]
    tracking_plays = set(plays)
    expected = plays_by_week[w]
    labels = label_by_week[w]
    results[w] = {
        'rows': rows, 'games': len({g for g, _ in tracking_plays}), 'plays': len(tracking_plays),
        'plays_csv_plays': len(expected), 'plays_match': tracking_plays == expected,
        'frame_types': dict(frame_types), 'ball_rows': ball_rows,
        'frames_per_play_min': min(span), 'frames_per_play_median': st.median(span), 'frames_per_play_max': max(span),
        'events': {k: events[k] for k in ['tackle', 'first_contact', 'out_of_bounds', 'ball_snap']},
        'exact_tackle_plays': len(tackle_exact), 'labelled_plays': len(labels),
        'tackle_and_labelled': len(tackle_exact & labels), 'tackle_event_only': len(tackle_exact - labels),
        'label_only': len(labels - tackle_exact),
    }
    json.dump({'week': w, 'exact_tackle_event_plays': sorted(list(k) for k in tackle_exact)},
              open(f'{OUT}/week{w}_tackle_event_plays.json', 'w'))
    print(f'week {w}:', json.dumps({k: results[w][k] for k in ['rows', 'games', 'plays', 'plays_csv_plays', 'plays_match', 'exact_tackle_plays', 'labelled_plays', 'tackle_and_labelled', 'tackle_event_only', 'label_only', 'ball_rows']}), flush=True)
json.dump(results, open(f'{OUT}/week_profiles.json', 'w'), indent=1)
print('done')
