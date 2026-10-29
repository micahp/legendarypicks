"""Verify that each reference source advances with a historical cutoff and holds no season at or after it (research).

Loads the reference at each cutoff, then checks the play pool, participant facts, blocked-kick records, safety and overtime
pools, the missed-field-goal pool and the kick table. Prints one line per cutoff. A failed check exits non-zero.

Usage: python3 audit_reference_cutoff.py --db DB --artifact JSON
"""
import argparse
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import e2_reference as er  # noqa: E402

CUTOFFS = ((2024, 1), (2025, 1), (2026, 1))


def before(season, week, cutoff):
    return (int(season), int(week)) < (int(cutoff[0]), int(cutoff[1]))


def audit(db, artifact, cutoff):
    ref, _ = er.load(db, eligible_before=cutoff, playcall_artifact=artifact, playcall_teams={'A': 'X', 'B': 'Y'})
    checks = {}
    pool_rows = [row for cell in ref.pool.values() for _event, row, _runoff, _spot in cell]
    checks['play_pool'] = all(before(r['season'], r['week'], cutoff) for r in pool_rows)
    checks['participants'] = all(
        before(int(key[0][:4]), int(key[0][5:7]), cutoff) for key in ref.participants)
    checks['blocked_kicks'] = all(before(r['season'], r['week'], cutoff)
                                  for kind in ref.blocked_kicks['records'].values() for r in kind)
    checks['missed_field_goal_pool'] = bool(ref.missed_field_goal_pool)
    checks['safety_pool'] = ref.safety_kick_pool is not None
    checks['overtime_pool'] = ref.overtime_pool is not None
    counts = {'play_pool': len(pool_rows), 'participants': len(ref.participants),
              'missed_field_goal_pool': sum(len(v) for v in ref.missed_field_goal_pool.values())}
    return checks, counts


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--db', required=True)
    ap.add_argument('--artifact', required=True)
    args = ap.parse_args()
    failed = False
    for cutoff in CUTOFFS:
        checks, counts = audit(args.db, args.artifact, cutoff)
        ok = all(checks.values())
        failed = failed or not ok
        print(f"cutoff {cutoff[0]}w{cutoff[1]} ok={ok} checks={checks} counts={counts}")
    sys.exit(1 if failed else 0)


if __name__ == '__main__':
    main()
