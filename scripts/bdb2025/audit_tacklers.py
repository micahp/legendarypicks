import csv, json, math, collections, sys, re, time
D = '/root/nfl-tracking-data/bdb2025/code-data'
OUT = '/root/nfl-tracking-data/bdb2025/audit'
YD = 0.9144
HDR = ['gameId','playId','nflId','displayName','frameId','frameType','time','jerseyNumber','club','playDirection','x','y','s','a','dis','o','dir','event']
week = int(sys.argv[1])
t0 = time.time()

games = {r['gameId']: int(r['week']) for r in csv.DictReader(open(f'{D}/games.csv', newline='', encoding='utf-8'))}
pls = {}
for r in csv.DictReader(open(f'{D}/plays.csv', newline='', encoding='utf-8')):
    if games.get(r['gameId']) == week:
        pls[(r['gameId'], r['playId'])] = r
pp = collections.defaultdict(dict)
for r in csv.DictReader(open(f'{D}/player_play.csv', newline='', encoding='utf-8')):
    if games.get(r['gameId']) == week:
        pp[(r['gameId'], r['playId'])][r['nflId']] = r

# Pass 1: frame of every event, from event rows only (cheap). Event is the last field.
events = collections.defaultdict(lambda: collections.defaultdict(set))
with open(f'{D}/tracking_week_{week}.csv', newline='', encoding='utf-8') as f:
    for line in f:
        s = line.rstrip('\r\n')
        if s.startswith('"gameId"'):
            continue
        ev = s.rsplit(',', 1)[1].strip('"')
        if ev == 'NA':
            continue
        row = next(csv.reader([s]))
        events[(row[0], row[1])][ev].add(int(row[4]))
print(f'pass1 done {time.time()-t0:.0f}s', flush=True)

def first(key, ev):
    fr = events[key].get(ev)
    return min(fr) if fr else None

plays = {}
for key, p in pls.items():
    labs = pp.get(key, {})
    credited = {n: r for n, r in labs.items() if r['soloTackle'] == '1' or r['tackleAssist'] == '1' or r['assistedTackle'] == '1'}
    carriers = [n for n, r in labs.items() if r['teamAbbr'] == p['possessionTeam'] and (r['hadRushAttempt'] == '1' or r['hadPassReception'] == '1')]
    tf = first(key, 'tackle')
    if tf is None and not credited:
        continue
    cat = 'A_event_and_label' if (tf is not None and credited) else ('B_event_only' if tf is not None else 'C_label_only')
    plays[key] = {'cat': cat, 'T': tf, 'credited': sorted(credited), 'carriers': carriers,
                  'snap': first(key, 'ball_snap'), 'fc': sorted(events[key].get('first_contact', [])),
                  'oob': first(key, 'out_of_bounds'), 'desc': p['playDescription'], 'tflr': sum(1 for n in credited if labs[n]['tackleForALoss'] == '1'),
                  'passResult': p['passResult'], 'possessionTeam': p['possessionTeam']}
print('eligible plays', len(plays), collections.Counter(v['cat'] for v in plays.values()), flush=True)

# Pass 2: positions needed for each eligible play.
want_players = collections.defaultdict(set)
for key, v in plays.items():
    for n in v['credited'] + v['carriers']:
        want_players[key].add(n)
rows_at = collections.defaultdict(dict)   # key -> frame -> {nflId: (x,y,club)} for needed frames
ball = collections.defaultdict(dict)      # key -> frame -> (x,y)
with open(f'{D}/tracking_week_{week}.csv', newline='', encoding='utf-8') as f:
    for line in f:
        g, pid, _ = line.split(',', 2)
        key = (g, pid)
        if key not in plays:
            continue
        s = line.rstrip('\r\n')
        r = next(csv.reader([s]))
        fr = int(r[4])
        v = plays[key]
        if v['T'] is not None and abs(fr - v['T']) > 3 and v['cat'] != 'C_label_only':
            continue
        if r[2] in ('', 'NA'):
            ball[key][fr] = (float(r[10]), float(r[11]))
            continue
        if v['cat'] == 'C_label_only' or abs(fr - (v['T'] or -99)) <= 3:
            rows_at[key].setdefault(fr, {})[r[2]] = (float(r[10]), float(r[11]), r[8])
print(f'pass2 done {time.time()-t0:.0f}s', flush=True)

def vel(key, n, fr):
    a = rows_at[key].get(fr - 1, {}).get(n); b = rows_at[key].get(fr, {}).get(n)
    if not a or not b:
        return None
    return ((b[0]-a[0])*10*YD, (b[1]-a[1])*10*YD)

out = []
for key, v in plays.items():
    rec = {'week': week, 'gameId': key[0], 'playId': key[1], 'cat': v['cat'], 'T': v['T'], 'snap': v['snap'],
           'tackle_time_from_snap_s': None if v['T'] is None or v['snap'] is None else round((v['T']-v['snap'])/10, 2),
           'first_contact': ';'.join(map(str, v['fc'])), 'oob_frame': v['oob'], 'tackleForALoss': v['tflr'],
           'passResult': v['passResult'], 'desc_tackled': int(bool(re.search(r'\btackled\b', v['desc'], re.I))),
           'desc_pushed_ob': int(bool(re.search(r'pushed ob|out of bounds', v['desc'], re.I))),
           'n_credited': len(v['credited']), 'credited_ids': ';'.join(v['credited']),
           'carrier_ids': ';'.join(v['carriers']), 'n_carriers': len(v['carriers'])}
    carrier = v['carriers'][0] if len(v['carriers']) == 1 else None
    rec['carrier_id'] = carrier or ''
    rec['carrier_status'] = 'single' if carrier else ('none' if not v['carriers'] else 'multiple')
    T = v['T']
    if T is not None and carrier and carrier in rows_at[key].get(T, {}):
        cx, cy, _ = rows_at[key][T][carrier]
        fb = ball[key].get(T)
        rec['football_to_carrier_yd'] = round(math.hypot(fb[0]-cx, fb[1]-cy), 2) if fb else None
        defs = {n: (x, y) for n, (x, y, c) in rows_at[key][T].items() if c != v['possessionTeam'] and n != carrier}
        dists = sorted(((math.hypot(x-cx, y-cy)*YD, n) for n, (x, y) in defs.items()))
        rec['n_defenders_tracked_at_T'] = len(defs)
        rec['nearest_def_id'] = dists[0][1] if dists else ''
        rec['nearest_def_m'] = round(dists[0][0], 3) if dists else None
        per = []
        for d in v['credited']:
            if d not in rows_at[key].get(T, {}):
                per.append({'id': d, 'status': 'missing_at_T'}); continue
            dx, dy, _ = rows_at[key][T][d]
            dist = math.hypot(dx-cx, dy-cy)*YD
            vd = vel(key, d, T); vc = vel(key, carrier, T)
            prev = rows_at[key].get(T-1, {})
            closing = None
            if d in prev and carrier in prev:
                pdist = math.hypot(prev[d][0]-prev[carrier][0], prev[d][1]-prev[carrier][1])*YD
                closing = round((pdist - dist) * 10, 3)  # m/s; positive = closing
            ang_def = None
            if vd and math.hypot(*vd) > 0.3:
                bx, by = cx-dx, cy-dy
                cosang = (vd[0]*bx*YD + vd[1]*by*YD) / (math.hypot(vd[0], vd[1]) * math.hypot(bx, by)*YD + 1e-9)
                ang_def = round(math.degrees(math.acos(max(-1, min(1, cosang)))), 1)
            rel = None
            if vc and math.hypot(*vc) > 0.5:
                ux, uy = vc
                ex, ey = dx-cx, dy-cy
                cosr = (ux*ex + uy*ey) / (math.hypot(ux, uy)*math.hypot(ex, ey) + 1e-9)
                rel = round(math.degrees(math.acos(max(-1, min(1, cosr)))), 1)  # 0 = defender ahead of carrier's motion
            per.append({'id': d, 'status': 'ok', 'dist_m': round(dist, 3), 'closing_mps': closing,
                        'def_heading_vs_to_carrier_deg': ang_def, 'defender_bearing_from_carrier_motion_deg': rel,
                        'credited_is_nearest': (dists[0][1] == d) if dists else None})
        rec['credited_detail'] = json.dumps(per)
    else:
        rec['credited_detail'] = ''
    if v['cat'] == 'C_label_only' and carrier:
        best = None
        for d in v['credited']:
            for fr, pos in rows_at[key].items():
                if d in pos and carrier in pos:
                    dd = math.hypot(pos[d][0]-pos[carrier][0], pos[d][1]-pos[carrier][1])*YD
                    if best is None or dd < best[0]:
                        best = (dd, d, fr)
        rec['label_only_min_dist_m'] = round(best[0], 3) if best else None
        rec['label_only_min_frame'] = best[2] if best else None
    out.append(rec)
fields = sorted({k for r in out for k in r})
with open(f'{OUT}/week{week}_plays_audit.csv', 'w', newline='', encoding='utf-8') as f:
    w = csv.DictWriter(f, fieldnames=fields)
    w.writeheader(); w.writerows(out)
print(f'week {week} wrote {len(out)} plays in {time.time()-t0:.0f}s', flush=True)
