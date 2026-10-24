import csv, glob, json, collections
AUD = '/root/nfl-tracking-data/bdb2025/audit'; D = '/root/nfl-tracking-data/bdb2025/code-data'
sel = json.load(open(f'{AUD}/cohort_selection.json'))
want = {}
for label, w, g, p in sel['visual']:
    want[(g, p)] = {'split': 'exploratory_visual', 'label': label, 'week': w}
for w, g, p in sel['dev']:
    want.setdefault((g, p), {'split': 'development', 'label': '', 'week': w})
audit = {}
for f in glob.glob(f'{AUD}/week*_plays_audit.csv'):
    for r in csv.DictReader(open(f, newline='', encoding='utf-8')):
        if (r['gameId'], r['playId']) in want:
            audit[(r['gameId'], r['playId'])] = r
sel_weeks = sorted({v['week'] for v in want.values()})
frames = collections.defaultdict(lambda: collections.defaultdict(int))  # key -> frame -> rows
ball = collections.defaultdict(set); pdir = {}; teams = {}
for w in sel_weeks:
    with open(f'{D}/tracking_week_{w}.csv', newline='', encoding='utf-8') as f:
        for line in f:
            g, p, _ = line.split(',', 2)
            if (g, p) not in want: continue
            r = next(csv.reader([line.rstrip('\r\n')]))
            fr = int(r[4]); key = (g, p)
            if r[2] in ('', 'NA'):
                ball[key].add(fr)
            else:
                frames[key][fr] += 1
            pdir.setdefault(key, r[9])
rows_out = []
for key, meta in want.items():
    a = audit[key]
    fr = frames[key]
    lo, hi = min(fr), max(fr)
    span = hi - lo + 1
    full = sum(1 for f_, v in fr.items() if v == 22 and f_ in ball[key])
    contiguous = len(fr) == span
    snap = int(a['snap']) if a['snap'] else None
    T = int(a['T']) if a['T'] else None
    det = json.loads(a['credited_detail'] or '[]')
    ok = [d for d in det if d.get('status') == 'ok']
    mind = min((d['dist_m'] for d in ok), default=None)
    fbc = float(a['football_to_carrier_yd']) if a.get('football_to_carrier_yd') not in ('', None) else None
    reasons = []
    if a['cat'][0] == 'B': reasons.append('event_only_no_credit')
    if a['cat'][0] == 'C': reasons.append('no_tackle_event')
    if a['carrier_status'] != 'single': reasons.append('carrier_not_single')
    if a['cat'][0] == 'A' and a['carrier_status'] == 'single' and (not ok or len(ok) != len(det)): reasons.append('credited_not_tracked')
    if mind is not None and mind > 3: reasons.append('credited_gt3m')
    if fbc is not None and fbc > 2: reasons.append('football_carrier_gt2yd')
    if a['passResult'] == 'IN': reasons.append('incomplete_pass')
    if (key in [tuple(x) for x in json.load(open(f'{AUD}/qb_sack_plays.json'))]): reasons.append('sack_event')
    if not span or full / len(fr) < 0.999: reasons.append('incomplete_frames')
    conf = 'high' if not reasons else ('medium' if set(reasons) <= {'credited_gt3m', 'football_carrier_gt2yd'} else 'excluded')
    rows_out.append({
        'schema_version': 'bdb2025-observed-tackle-manifest/v1', 'dataset': 'nfl-big-data-bowl-2025-2022season-github-copy',
        'split': meta['split'], 'visual_label': meta['label'], 'week': a['week'], 'game_id': key[0], 'play_id': key[1],
        'snap_frame': snap, 'first_contact_frames': a['first_contact'], 'tackle_frame': T, 'oob_frame': a['oob_frame'],
        'first_tracked_frame': lo, 'terminal_frame': hi, 'n_frames': len(fr), 'frames_with_22_players_and_ball_share': round(full/len(fr), 4),
        'contiguous_frames': contiguous, 'play_direction': pdir.get(key, ''), 'coord_units': 'yards; x 0-120 field length, y 0-53.3 width',
        'carrier_id': a['carrier_id'], 'carrier_status': a['carrier_status'], 'credited_ids': a['credited_ids'],
        'credited_flag_types': '', 'n_credited': a['n_credited'],
        'credited_min_dist_m_at_tackle': round(mind, 3) if mind is not None else None,
        'nearest_def_id': a['nearest_def_id'], 'football_to_carrier_yd_at_tackle': round(fbc, 2) if fbc is not None else None,
        'pre_snap_input_cutoff': 'frames <= snap_frame', 'outcome_label_provenance': 'tackle/first_contact/out_of_bounds: tracking event column (broadcast to all rows at frame); credited tacklers: player_play.csv soloTackle/tackleAssist/assistedTackle; carrier: player_play.csv hadRushAttempt/hadPassReception (inferred, not a tracking field)',
        'identity_confidence': conf, 'exclusion_reasons': ';'.join(reasons), 'included': conf != 'excluded',
    })
# credited flag types per play
flag = {}
for r in csv.DictReader(open(f'{D}/player_play.csv', newline='', encoding='utf-8')):
    k = (r['gameId'], r['playId'])
    if k in want:
        t = 'solo' if r['soloTackle']=='1' else 'tackleAssist' if r['tackleAssist']=='1' else 'assistedTackle' if r['assistedTackle']=='1' else ''
        if t: flag.setdefault(k, []).append(f"{r['nflId']}:{t}")
for row in rows_out:
    row['credited_flag_types'] = ';'.join(flag.get((row['game_id'], row['play_id']), []))
fields = list(rows_out[0].keys())
with open('/tmp/claude-0/-root-lp-nfl-props/bff38fe9-f0e2-4f8c-abd6-b038f3ae0d5f/scratchpad/manifest_v1.csv', 'w', newline='', encoding='utf-8') as f:
    w = csv.DictWriter(f, fieldnames=fields); w.writeheader(); w.writerows(rows_out)
print('manifest rows', len(rows_out), collections.Counter(r['identity_confidence'] for r in rows_out), collections.Counter(r['split'] for r in rows_out))
print('complete frames share min', min(r['frames_with_22_players_and_ball_share'] for r in rows_out), 'contiguous all', all(r['contiguous_frames'] for r in rows_out))
print('terminal minus tackle (frames) median', sorted(r['terminal_frame']-r['tackle_frame'] for r in rows_out if r['tackle_frame'] is not None)[len(rows_out)//2])
print('exclusion counts', collections.Counter(x for r in rows_out for x in r['exclusion_reasons'].split(';') if x))
