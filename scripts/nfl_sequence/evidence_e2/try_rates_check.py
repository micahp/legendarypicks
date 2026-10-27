#!/usr/bin/env python3
"""Cross-tabulate the publisher's extra-point and two-point result fields against the EPA-positive `success` flag, over the
kick window (2022-2025, weeks <= 18). The engine's rates come from the publisher fields. This shows what a success-based rate
would have printed, and how far it is from the publisher rate. Read-only: the kick table and the dev database.

Writes docs/evidence/e2-successor/try-rates-publisher-vs-success.json. Usage: python3 try_rates_check.py
"""
import csv
import hashlib
import json
import sqlite3
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
import measure_kick_outcomes as mk  # noqa: E402

ROOT = HERE.parents[2]
OUT = ROOT / 'docs' / 'evidence' / 'e2-successor' / 'try-rates-publisher-vs-success.json'


def key(game_id, play_id):
    return (game_id, str(int(float(play_id))))


def main():
    table = mk.KICK_RESULTS
    con = sqlite3.connect(f'file:{mk.DEFAULT_DB}?mode=ro', uri=True)
    db = {}
    for g, p, s, tp, pt in con.execute(
            f"SELECT game_id, play_id, success, two_point_attempt, play_type FROM nfl_pbp WHERE {mk.WINDOW} "
            f"AND (play_type = 'extra_point' OR two_point_attempt = 1)"):
        db[key(g, p)] = s
    con.close()

    ep, tp = Counter(), Counter()
    with open(table, newline='') as f:
        for r in csv.DictReader(f):
            if r['play_type'] == 'extra_point':
                ep[(r['extra_point_result'] or 'missing', str(db.get(key(r['game_id'], r['play_id']), 'no row')))] += 1
            if r['two_point_attempt'] in ('1', '1.0'):
                tp[(r['two_point_conv_result'] or 'missing', str(db.get(key(r['game_id'], r['play_id']), 'no row')))] += 1

    def rates(counts, good, bad):
        n = sum(v for (pub, _), v in counts.items() if pub in (good, bad))
        g = sum(v for (pub, _), v in counts.items() if pub == good)
        return g, n - g

    ep_pub_g, ep_pub_f = rates(ep, 'good', 'failed')
    ep_like_s1 = sum(v for (pub, s), v in ep.items() if pub in ('good', 'failed') and s == '1.0')
    ep_like_s0 = sum(v for (pub, s), v in ep.items() if pub in ('good', 'failed') and s == '0.0')
    ep_all_s1 = sum(v for (_, s), v in ep.items() if s == '1.0')
    ep_all_s0 = sum(v for (_, s), v in ep.items() if s == '0.0')
    tp_pub_s, tp_pub_f = rates(tp, 'success', 'failure')
    tp_like_s1 = sum(v for (pub, s), v in tp.items() if pub in ('success', 'failure') and s == '1.0')
    tp_like_s0 = sum(v for (pub, s), v in tp.items() if pub in ('success', 'failure') and s == '0.0')

    result = {
        'source': {'table': 'docs/fixtures/e2/kick_results_2022_2025.csv',
                   'sha256': hashlib.sha256(table.read_bytes()).hexdigest(),
                   'database': 'backend/data/picks.dev.db (read-only)', 'window': mk.WINDOW},
        'extra_point': {
            'publisher_good': ep_pub_g, 'publisher_failed': ep_pub_f,
            'publisher_rate': round(ep_pub_g / (ep_pub_g + ep_pub_f), 4),
            'success_rate_on_the_same_rows': round(ep_like_s1 / (ep_like_s1 + ep_like_s0), 4),
            'success_rate_all_rows_naive': round(ep_all_s1 / (ep_all_s1 + ep_all_s0), 4),
            'success_flag_on_publisher_failed_rows': {
                'success_1': sum(v for (pub, s), v in ep.items() if pub == 'failed' and s == '1.0'),
                'success_0': sum(v for (pub, s), v in ep.items() if pub == 'failed' and s == '0.0')},
            'cross_tab': {f'{pub} x success {s}': v for (pub, s), v in sorted(ep.items())},
        },
        'two_point': {
            'publisher_success': tp_pub_s, 'publisher_failure': tp_pub_f,
            'publisher_rate': round(tp_pub_s / (tp_pub_s + tp_pub_f), 4),
            'success_rate_on_the_same_rows': round(tp_like_s1 / (tp_like_s1 + tp_like_s0), 4),
            'cross_tab': {f'{pub} x success {s}': v for (pub, s), v in sorted(tp.items())},
        },
        'reading': ('The success flag is EPA-positive and is not a make result, so no rate is built on it. In this window it happens '
                    'to agree with the publisher on every good and failed extra point and on every two-point try. It does not agree '
                    'on blocked extra points, which it records as misses, and on rows with no result. A success-based rate would '
                    'therefore differ from the publisher rate by the blocked rows. The engine reads only the publisher fields '
                    '(measure_kick_outcomes.load_try_results), and the tool prints no success-based rate '
                    '(test_kick_results.test_the_tool_contains_no_rate_built_on_the_success_flag).'),
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(result, indent=1, sort_keys=True) + '\n')
    print(json.dumps({'extra_point': {k: result['extra_point'][k] for k in ('publisher_rate', 'success_rate_on_the_same_rows',
                                                                              'success_rate_all_rows_naive')},
                      'two_point': {k: result['two_point'][k] for k in ('publisher_rate', 'success_rate_on_the_same_rows')}},
                     indent=1))


if __name__ == '__main__':
    main()
