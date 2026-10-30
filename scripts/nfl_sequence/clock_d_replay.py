#!/usr/bin/env python3
"""Fixed-outcome replay: the research clock D against the E2 cell rule (A), quarter by quarter.

Each quarter keeps its observed play sequence: every play keeps its observed event and flags. Only the clock is generated.
At each play, a model draws its runoff from the clock state it has produced, and never from the observed clock.

For each quarter, the model's clock is compared with the observed last play of that quarter:
  accurate   the model ends the quarter at the observed last play;
  premature  the model ends it at an earlier play, so the observed plays after that point are lost;
  missed     the model still has clock at the observed last play.

D (clock_d.py) is fitted on the training window only. A_train is the E2 cell rule fitted on the same training window.
A_deployed is the E2 cell rule as shipped, which pools 2022-2025 and so includes the holdout season. It is in-sample for
the holdout and is labelled that way.

Usage: python3 clock_d_replay.py --window dev|holdout [--out-dir DIR]
"""
import argparse
import json
import random
from collections import Counter, defaultdict
from pathlib import Path

import clock_d as cd
import e1_drive as e1

REPLICATES = 20
SHORT_SECONDS = 15
TRAIN = (2022, 2022, 1, 5)  # season, season, first week, last week
DEV_GAMES = ('2022_05_CIN_BAL', '2022_09_GB_DET', '2022_05_MIA_NYJ', '2022_06_SF_ATL', '2022_07_TB_CAR',
             '2022_06_DAL_PHI')
WINDOWS = {'dev': (2022, 2022, 1, 18, DEV_GAMES), 'holdout': (2025, 2025, 1, 18, None)}


def quarter_plays(rows, flags, counts):
    """The observed plays of each (game, quarter), in order, with the E1 classification. A play is kept when it has an
    observed next row in the same quarter or is followed by the quarter's end marker; the marker is the boundary,
    not a play."""
    by_game = defaultdict(list)
    for r in rows:
        by_game[r['game_id']].append(r)
    quarters = defaultdict(list)
    for gid, seq in by_game.items():
        for i, row in enumerate(seq):
            if row['qtr'] not in (1, 2, 3, 4) or cd.is_marker(row):
                continue
            nxt = seq[i + 1] if i + 1 < len(seq) else None
            if nxt is None:
                continue
            ended = cd.ends_quarter(seq, i)
            if nxt['qtr'] != row['qtr'] and not ended:
                continue
            hit = e1.classify(row, nxt, counts)
            if hit is None:
                continue
            event, runoff, _ = hit
            qsr = cd.quarter_clock(row)
            oob = flags.get((gid, int(row['play_id'])), (0, 0))[0]
            terminal = 'touchdown' if row['touchdown'] == 1 else None
            quarters[(gid, row['qtr'])].append({
                'row': row, 'event': event, 'runoff': runoff, 'ended': ended, 'qsr': qsr, 'qtr': row['qtr'],
                'terminal': terminal, 'stop': cd.stop_class(event, oob, row['qtr'], qsr, terminal)})
    return quarters


def run_d(plays, model, seed):
    clock = cd.BoundaryClock(model, seed)
    c, n, draws = plays[0]['qsr'], len(plays), []
    for i, p in enumerate(plays):
        runoff, ended, refusal = clock.draw(p['row'], p['event'], p['terminal'], p['qtr'], c)
        if refusal:
            return {'refused': refusal}
        if i == n - 1:
            return {'outcome': 'accurate' if ended else 'missed', 'lost': 0,
                    'leftover': None if ended else c - runoff, 'draws': draws + ([(i, runoff)] if not ended else []),
                    'counts': clock.counts}
        if ended:
            return {'outcome': 'premature', 'lost': n - 1 - i, 'leftover': None, 'draws': draws, 'counts': clock.counts}
        draws.append((i, runoff))
        c -= runoff
    raise AssertionError('empty quarter')


def run_a(plays, pool, seed):
    rng = random.Random(seed)
    c, n, draws, refused = plays[0]['qsr'], len(plays), [], 0
    for i, p in enumerate(plays):
        row = p['row']
        cell = pool.get((row['down'], e1.e0.ydstogo_bucket(row['ydstogo']), e1.e0.yardline_bucket(row['yardline_100'])),
                        [])
        runoffs = [x[2] for x in cell if x[0] == p['event']]
        if not runoffs:
            return {'refused': 'no A cell for this play'}
        runoff = rng.choice(runoffs)
        ended = c - runoff <= 0  # the E2 rule clamps the clock at zero
        if i == n - 1:
            return {'outcome': 'accurate' if ended else 'missed', 'lost': 0,
                    'leftover': None if ended else c - runoff, 'draws': draws + ([(i, runoff)] if not ended else []),
                    'counts': {}}
        if ended:
            return {'outcome': 'premature', 'lost': n - 1 - i, 'leftover': None, 'draws': draws, 'counts': {}}
        draws.append((i, runoff))
        c -= runoff
    raise AssertionError('empty quarter')


def w1(a, b):
    a, b = sorted(a), sorted(b)
    grid = [i / 100 for i in range(1, 100)]
    q = lambda s, p: s[min(len(s) - 1, int(p * (len(s) - 1)))]
    return sum(abs(q(a, p) - q(b, p)) for p in grid) / len(grid)


def summarise(name, results, quarters):
    """results: model -> list of per-quarter dicts (one per replicate); quarters: the observed plays of each quarter."""
    out = {}
    tally = Counter(r.get('outcome', r.get('refused', 'refused')) for rs in results.values() for r in rs)
    for m, rs in results.items():
        oc = Counter(r.get('outcome', 'refused') for r in rs)
        n_q = len(rs)
        premature = [r['lost'] for r in rs if r.get('outcome') == 'premature']
        missed = [r['leftover'] for r in rs if r.get('outcome') == 'missed']
        out[m] = {
            'quarter_replicates': n_q,
            'accurate': oc.get('accurate', 0), 'premature': oc.get('premature', 0), 'missed': oc.get('missed', 0),
            'refused': oc.get('refused', 0),
            'premature_share': round(oc.get('premature', 0) / n_q, 4) if n_q else None,
            'missed_share': round(oc.get('missed', 0) / n_q, 4) if n_q else None,
            'plays_lost_per_premature_quarter': round(sum(premature) / len(premature), 2) if premature else None,
            'median_leftover_when_missed_s': sorted(missed)[len(missed) // 2] if missed else None,
        }
    out['_tally'] = dict(tally)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--window', choices=sorted(WINDOWS), required=True)
    ap.add_argument('--out-dir', default=str(Path(__file__).resolve().parents[2] / 'docs' / 'research' / 'e3'))
    args = ap.parse_args()
    season_from, season_to, week_from, week_to, only = WINDOWS[args.window]

    flags = cd.load_flags()
    train_rows = [r for r in cd.load_window(e1.DEFAULT_DB, *TRAIN) if r['game_id'] not in DEV_GAMES]
    model = cd.fit(train_rows, flags)
    a_train, _ = e1.build_pool(train_rows)
    eval_rows = cd.load_window(e1.DEFAULT_DB, season_from, season_to, week_from, week_to)
    if only is not None:
        eval_rows = [r for r in eval_rows if r['game_id'] in only]
    counts = Counter()
    quarters = quarter_plays(eval_rows, flags, counts)
    a_deployed = None
    if args.window == 'holdout':
        a_deployed, _ = e1.build_pool(e1.load(e1.DEFAULT_DB))

    results = defaultdict(list)
    observed_pairs = defaultdict(list)  # event -> observed runoffs of plays that were not the quarter's end
    draws_by_event = defaultdict(lambda: defaultdict(list))
    stop_obs = defaultdict(lambda: [0, 0])
    stop_model = defaultdict(lambda: defaultdict(lambda: [0, 0]))
    calib = defaultdict(lambda: [0, 0, 0.0])  # (stop, bucket) -> plays, observed quarter ends, expected quarter ends
    last_not_ended = 0
    for qi, (key, plays) in enumerate(sorted(quarters.items())):
        boundary = plays[-1]['ended']  # the boundary test needs the observed last play to be a quarter end
        if not boundary:
            last_not_ended += 1
        for p in plays:
            bucket = cd.qsr_bucket(p['qsr'])
            cell = calib[(p['stop'], bucket)]
            cell[0] += 1
            cell[1] += int(p['ended'])
            p_end, _ = model.p_end(p['event'], p['stop'], bucket)
            if p_end is None:
                counts['calibration: thin hazard cell'] += 1
            else:
                cell[2] += p_end
            if not p['ended']:
                observed_pairs[p['event']].append(p['runoff'])
                stop_obs[p['stop']][0] += int(p['runoff'] <= SHORT_SECONDS)
                stop_obs[p['stop']][1] += 1
        for rep in range(REPLICATES):
            seed = rep * 100003 + qi
            d = run_d(plays, model, seed)
            a = run_a(plays, a_train, seed)
            for name, res in (('D', d), ('A_train', a)) + ((('A_deployed', run_a(plays, a_deployed, seed)),)
                                                        if a_deployed is not None else ()):
                if boundary:
                    results[name].append(res if 'refused' not in res else {'refused': res['refused']})
                if 'draws' in res:
                    for i, runoff in res['draws']:
                        p = plays[i]
                        draws_by_event[name][p['event']].append(runoff)
                        stop_model[name][p['stop']][0] += int(runoff <= SHORT_SECONDS)
                        stop_model[name][p['stop']][1] += 1
            if 'counts' in d:
                counts.update({f'D: {k}': v for k, v in d['counts'].items()})

    out = {
        'window': args.window, 'train': {'seasons': [TRAIN[0], TRAIN[1]], 'weeks': [TRAIN[2], TRAIN[3]],
                                         'excludes': list(DEV_GAMES), 'plays_fitted': sum(
                                             v for k, v in model.fit_counts.items() if k.startswith('plays fitted'))},
        'eval': {'seasons': [season_from, season_to], 'weeks': [week_from, week_to],
                 'games': len({r['game_id'] for r in eval_rows}), 'quarters': len(quarters),
                 'quarters_with_boundary_test': len(quarters) - last_not_ended,
                 'quarters_excluded_from_boundary_test': last_not_ended},
        'replicates': REPLICATES, 'short_seconds': SHORT_SECONDS,
        'quarter_end': summarise(args.window, results, quarters),
        'runoff_w1_seconds_by_event': {
            name: {e: {'n_observed': len(observed_pairs[e]), 'n_draws': len(draws_by_event[name][e]),
                       'w1': round(w1(draws_by_event[name][e], observed_pairs[e]), 2)}
                   for e in sorted(observed_pairs) if observed_pairs[e] and draws_by_event[name][e]}
            for name in draws_by_event},
        'short_share_by_stop_class': {
            stop: {'observed': round(v[0] / v[1], 3) if v[1] else None, 'n_observed': v[1],
                   **{name: round(stop_model[name][stop][0] / stop_model[name][stop][1], 3)
                      for name in stop_model if stop_model[name][stop][1]}}
            for stop, v in sorted(stop_obs.items())},
        'hazard_calibration': {
            f'{stop}|{bucket}': {'plays': v[0], 'observed_quarter_ends': v[1], 'expected_quarter_ends': round(v[2], 1)}
            for (stop, bucket), v in sorted(calib.items())},
        'counts': dict(counts),
    }
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f'clock-d-replay-{args.window}.json'
    path.write_text(json.dumps(out, indent=1, sort_keys=True) + '\n')
    print(json.dumps(out, indent=1, sort_keys=True))


if __name__ == '__main__':
    main()
