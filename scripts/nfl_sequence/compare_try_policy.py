"""Identical-seed comparison: the unconditional two-point share against the context-conditioned try policy.

Each seed runs twice through the same observed reference: once with the published share (try_policy None), once with the
TryPolicy fit on the 2022-2025 situation fixture. Both arms are read the same way: each try's situation is rebuilt from the drive
log, and the candidate's recorded situation must agree with it. Seeds 1-300 are the seeds the E2 survey already used. Reads the
dev database read-only. Usage: python3 compare_try_policy.py [--games 300] [--structure margin_period_opening] [--k 25]
"""
import argparse
import copy
import statistics
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import e2_reference as er  # noqa: E402
import game_state as gs  # noqa: E402
import rules_matrix as rm  # noqa: E402
import try_policy as tp  # noqa: E402

MARGIN_BUCKETS = [('down 14 or more', -99, -14), ('down 9-13', -13, -9), ('down 5-8', -8, -5), ('down 1-4', -4, -1),
                  ('tied', 0, 0), ('up 1-4', 1, 4), ('up 5-8', 5, 8), ('up 9 or more', 9, 99)]
PERIODS = ['H1', 'Q3', 'Q4_gt5', 'Q4_le5']
KEYS = ('margin', 'quarter', 'clock', 'opening_drive', 'first_td')


def tries_of(record):
    """Each try in a record with its situation, rebuilt from the drive log. The margin is read before the touchdown's points."""
    points, offense, out, seen_td = Counter(), Counter(), [], False
    for d in record['drives']:
        offense[d['offense_team']] += 1
        scorer = d.get('touchdown_scored_by')
        if scorer:
            opponent = 'B' if scorer == 'A' else 'A'
            # an observed overtime drive has no plays; its situation is read from where the drive ends
            last = d['plays'][-1]['state_after'] if d['plays'] else {'quarter': d['end_quarter'], 'clock_seconds': d['end_clock']}
            situation = {'margin': points[scorer] + gs.TD_POINTS - points[opponent], 'quarter': last['quarter'],
                         'clock': last['clock_seconds'], 'opening_drive': scorer == d['offense_team'] and offense[scorer] == 1,
                         'first_td': not seen_td}
            seen_td = True
        scored = d['points_scored_on_drive']
        if scored:
            points[scored['team']] += scored['points']
        if scorer and scored and scored['try']:
            out.append({**situation, 'kind': scored['try']['kind'], 'made': scored['try']['made'],
                        'recorded': d.get('try_policy')})
    return out


def winner(record):
    a, b = record['points']['A'], record['points']['B']
    return 'A' if a > b else 'B' if b > a else 'tie'


def bucket_of(margin):
    return next(label for label, lo, hi in MARGIN_BUCKETS if lo <= margin <= hi)


def arm_report(name, records):
    tries = [t for r in records for t in tries_of(r)]
    two = [t for t in tries if t['kind'] == 'two_point']
    xp = [t for t in tries if t['kind'] == 'extra_point']
    status, blocker = Counter(r['status'] for r in records), Counter(r['blocker'] or '-' for r in records)
    print(f'== {name}: {len(records)} games')
    print(f'  status {dict(status)}')
    print(f'  blocker {dict(blocker)}')
    print(f'  complete_regulation {sum(r["complete_regulation"] for r in records)}, '
          f'valid_full_game {sum(r["valid_full_game"] for r in records)}, '
          f'rules-matrix FAIL rows {sum(1 for r in records for c in rm.check(r) if c["status"] == "FAIL")}')
    print(f'  tries {len(tries)}: two-point {len(two)} ({100 * len(two) / max(len(tries), 1):.1f}%), '
          f'two-point made {sum(t["made"] for t in two)}, extra point made {sum(t["made"] for t in xp)}/{len(xp)}')
    for label, group in (('opening drive', lambda t: t['opening_drive']), ('first TD', lambda t: t['first_td'])):
        yes = [t for t in tries if group(t)]
        print(f'  {label}: two-point {sum(t["kind"] == "two_point" for t in yes)}/{len(yes)}')
    predicted = [t['recorded']['p_two'] for t in tries if t.get('recorded')]
    if predicted:
        print(f'  mean predicted two-point probability {statistics.mean(predicted):.4f} over {len(predicted)} tries, '
              f'realized {len(two) / len(tries):.4f}')
    print('  by period: ' + '; '.join(
        f'{p} {sum(t["kind"] == "two_point" for t in tries if tp.period_of(t["quarter"], t["clock"]) == p)}'
        f'/{sum(1 for t in tries if tp.period_of(t["quarter"], t["clock"]) == p)}' for p in PERIODS))
    print('  by margin: ' + '; '.join(
        f'{label} {sum(t["kind"] == "two_point" for t in tries if bucket_of(t["margin"]) == label)}'
        f'/{sum(1 for t in tries if bucket_of(t["margin"]) == label)}' for label, _, _ in MARGIN_BUCKETS))
    points = [sum(r['points'].values()) for r in records]
    margins = [abs(r['points']['A'] - r['points']['B']) for r in records]
    print(f'  points per game {statistics.mean(points):.2f}, mean absolute margin {statistics.mean(margins):.2f}')
    return tries


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--games', type=int, default=300)
    ap.add_argument('--structure', default=tp.CANDIDATE)
    ap.add_argument('--k', type=int, default=tp.K)
    args = ap.parse_args()
    policy = tp.TryPolicy.from_fixture(structure=args.structure, k=args.k)
    print('policy', policy.describe())
    ref, _ = er.load()
    candidate_ref = copy.copy(ref)
    candidate_ref.try_policy = policy
    base, cand, paired_points, paired_margin, winner_changed, mismatches = [], [], [], [], 0, 0
    for seed in range(1, args.games + 1):
        a = gs.play_game(seed, ref)
        b = gs.play_game(seed, candidate_ref)
        gs.validate_game(a)
        gs.validate_game(b)
        base.append(a)
        cand.append(b)
        for t in tries_of(b):
            recorded = t['recorded']
            if recorded is None or any(recorded[k] != t[k] for k in KEYS):
                mismatches += 1
        pa, pb = sum(a['points'].values()), sum(b['points'].values())
        paired_points.append(pb - pa)
        paired_margin.append(abs(b['points']['A'] - b['points']['B']) - abs(a['points']['A'] - a['points']['B']))
        winner_changed += winner(a) != winner(b)
    arm_report('unconditional (published share)', base)
    arm_report(f'candidate {args.structure} K={args.k}', cand)
    n = len(paired_points)
    sd = statistics.stdev(paired_points)
    print(f'paired per-seed total points, candidate minus base: mean {statistics.mean(paired_points):+.3f} '
          f'(95% CI {statistics.mean(paired_points) - 1.96 * sd / n ** 0.5:+.3f} to '
          f'{statistics.mean(paired_points) + 1.96 * sd / n ** 0.5:+.3f}); '
          f'mean absolute-margin change {statistics.mean(paired_margin):+.3f}; '
          f'winner changed in {winner_changed}/{n} seeds')
    print(f'candidate situation records that disagree with the rebuilt situation: {mismatches}')


if __name__ == '__main__':
    main()
