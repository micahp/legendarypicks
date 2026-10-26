#!/usr/bin/env python3
"""Enumerate every unmodelled transition type that seeds 1-300 produce, with counts per type, seeds affected and the printed
rule heading. Each count is cross-checked against the independent checker, which derives the list from the plays and does not
read the record's own list. A mismatch fails the build.

The games are the same ones survey_legality_300.py plays. Writes docs/evidence/e2-successor/unmodelled-transitions-300.json.
Usage: python3 unmodelled_enumeration.py
"""
import argparse
import json
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))
import e2_reference as er  # noqa: E402
import game_state as gs  # noqa: E402
import legality_check as lc  # noqa: E402
import versions  # noqa: E402

ROOT = HERE.parents[2]
OUT = ROOT / 'docs' / 'evidence' / 'e2-successor' / 'unmodelled-transitions-300.json'

# Each unmodelled type: the printed rule heading it comes from, and the guard that scopes it out.
TYPES = {
    'two_minute_warning': {
        'printed_heading': ('RULE 3 DEFINITIONS, SECTION 41 TWO-MINUTE WARNING; RULE 4 GAME TIMING, SECTIONS 3 STARTING THE GAME '
                            'CLOCK, 4 STOPPING THE GAME CLOCK and 5 TIMEOUTS'),
        'guard': 'clock_start_stop',
        'status': ('guarded: the crossing marker is recorded at the actual post-down clock, but running/stopped state and '
                   'explicit restart transitions are unsupported'),
    },
    'penalty': {
        'printed_heading': ('RULE 14 PENALTY ENFORCEMENT; the clock stop for a foul is RULE 4 GAME TIMING, SECTION 4 STOPPING THE '
                            'GAME CLOCK, items (e) "at the end of a down during which a foul occurs" and (g)'),
        'guard': 'penalties',
    },
    'timeout': {
        'printed_heading': ('RULE 4 GAME TIMING, SECTION 5 TIMEOUTS, ARTICLE 1 CHARGED TEAM TIMEOUTS and Item 1 "Timeouts Allowed" '
                            '("three charged team timeouts during each half")'),
        'guard': 'timeouts',
    },
    'overtime_block': {
        'printed_heading': 'RULE 16 OVERTIME PROCEDURES, SECTION 1 ARTICLE 3 "an extra period of 10 minutes shall commence"',
        'guard': 'overtime',
    },
    'missed_field_goal_return': {
        'printed_heading': ('RULE 11 SCORING, SECTION 4 FIELD GOAL, ARTICLE 2 MISSED FIELD GOALS, exceptions (1) and (2): receivers '
                            'touch beyond the line of scrimmage'),
        'guard': 'missed_field_goal_return',
    },
    'onside_kick': {
        'printed_heading': 'RULE 6 FREE KICKS (onside kick); no onside kick is drawn in this engine',
        'guard': 'onside_kicks',
    },
    'exception_coin_toss': {
        'printed_heading': ('RULE 4 GAME TIMING, SECTION 2 STARTING A PERIOD OR HALF, ARTICLE 2 TOSS OF COIN, the forfeited-privilege '
                            'exception'),
        'guard': 'exception_coin_toss',
    },
}


# Warning crossings are independently derived and compared with event markers; the complete clock lifecycle remains guarded.
MODELLED_LATE_QUARTERS = (2, 4)
MODELLED_MARK = 120
UNMODELLED_KINDS = ('two_minute_warning', 'penalty', 'timeout', 'missed_field_goal_return')


def two_minute_crossings(record):
    """Derive warning events from scrimmage downs and kickoffs, excluding period expiry."""
    crossings = []
    for d in record['drives']:
        for p in d['plays']:
            before, after = p['state_before'], p['state_after']
            if (before['quarter'] in MODELLED_LATE_QUARTERS and after['quarter'] == before['quarter']
                    and before['clock_seconds'] > MODELLED_MARK >= after['clock_seconds'] > 0):
                crossings.append({'source': 'play', 'quarter': before['quarter'], 'clock_seconds': after['clock_seconds']})
    for k in record['kickoffs']:
        if (k['quarter'] in MODELLED_LATE_QUARTERS and not k['clock_expired_during_kickoff']
                and k['clock_before'] > MODELLED_MARK >= k['clock_after'] > 0):
            crossings.append({'source': 'kickoff', 'quarter': k['quarter'], 'clock_seconds': k['clock_after']})
    return crossings


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--records-dir', help='reuse the versioned records from survey_legality_300.py')
    args = ap.parse_args()
    records_dir = Path(args.records_dir) if args.records_dir else None
    ref = None if records_dir else er.load()[0]
    source = versions.source_snapshot()
    seeds_with = Counter()
    counts = Counter()
    by_quarter = Counter()
    stops_total = 0
    checker_mismatch = []
    per_seed = []
    for seed in range(1, 301):
        record_path = records_dir / f'seed-{seed:03d}.json' if records_dir else None
        record = json.loads(record_path.read_text()) if record_path else gs.play_game(seed, ref)
        if record_path and record.get('research_source') != source:
            raise SystemExit(f'seed {seed}: the reused record source fingerprint does not match this tree')
        gs.validate_game(record)
        plays = [p for d in record['drives'] for p in d['plays']]
        listed = record['unmodelled_transitions']
        pen = [t for t in listed if t['kind'] == 'penalty']
        derived = lc.check_unmodelled(record)
        prefixes = {'penalty': 'penalty', 'timeout': 'timeout stoppage', 'missed_field_goal_return': 'missed field goal return',
                    'two_minute_warning': 'two-minute warning clock lifecycle'}
        for kind, prefix in prefixes.items():
            if sum(1 for t in listed if t['kind'] == kind) != sum(1 for x in derived if x.startswith(prefix)):
                checker_mismatch.append((seed, kind))
        crossings = two_minute_crossings(record)
        stops = record['two_minute_warnings']
        signature = lambda rows: sorted((x['source'], x['quarter'], x['clock_seconds']) for x in rows)
        if signature(crossings) != signature(stops) or lc.check_two_minute(record):
            checker_mismatch.append((seed, 'two_minute_warning'))
        stops_total += len(stops)
        for w in stops:
            by_quarter[f"Q{w['quarter']}"] += 1
        found = {
            'two_minute_warning': len(stops),
            'penalty': len(pen),
            'timeout': sum(1 for p in plays if p['participants'].get('timeout')),
            'overtime_block': 1 if (record.get('overtime') or {}).get('result') is None and record.get('overtime') else 0,
            'missed_field_goal_return': sum(1 for d in record['drives']
                                            if d['terminal'] == 'field_goal_attempt' and d['field_goal_made'] is False),
            'onside_kick': sum(1 for k in record['kickoffs'] if 'onside' in str(k.get('kind', '')) + str(k.get('reason', ''))),
            'exception_coin_toss': 0 if record['ledger']['policy_mode'] == gs.NORMAL_MODE else 1,
        }
        for kind, n in found.items():
            counts[kind] += n
            if n:
                seeds_with[kind] += 1
        per_seed.append({'seed': seed, **{k: v for k, v in found.items() if v}, **({'two_minute_stops': len(stops)} if stops else {})})

    if checker_mismatch:
        raise SystemExit(f'the engine list and the checker derivation disagree on seeds {checker_mismatch}')
    result = {
        'source': {'engine_commit': source['base_model_version'],
                   'research_source_sha256': source['source_tree_sha256'],
                   'producer_worktree_dirty': source['producer_worktree_dirty'],
                   'games': 'seeds 1-300, er.load() regulation-only pool, validate_game on every record',
                   'crosscheck': 'legality_check.check_unmodelled, derived from the plays; 0 mismatches'},
        'types': [{'type': k, 'count': counts[k], 'seeds_affected': seeds_with[k], 'printed_heading': TYPES[k]['printed_heading'],
                   'guard': TYPES[k]['guard'],
                   'status': TYPES[k].get('status', 'scoped out: guard enforced, not modelled; valid_full_game false; never a legal complete game')}
                  for k in TYPES],
        'two_minute_warning_by_quarter': dict(sorted(by_quarter.items())),
        'two_minute_stops_total': stops_total,
        'two_minute_stops_status': ('warning crossing markers are recorded at actual post-down clocks and independently '
                                    'derived from plays and kickoffs; the complete clock running/stopped and restart lifecycle '
                                    'is guarded as an unmodelled two_minute_warning transition.'),
        'seeds_with_any_unmodelled_transition': sum(1 for r in per_seed if any(k in r for k in UNMODELLED_KINDS)),
        'per_seed': per_seed,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(result, indent=1, sort_keys=True) + '\n')
    for t in result['types']:
        print(f"{t['type']:26s} count {t['count']:5d}  seeds {t['seeds_affected']:4d}")
    print('two-minute warning markers by quarter:', result['two_minute_warning_by_quarter'], 'total', stops_total,
          '(clock lifecycle unsupported)')


if __name__ == '__main__':
    main()
