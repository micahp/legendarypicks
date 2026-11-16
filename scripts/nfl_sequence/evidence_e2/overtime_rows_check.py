#!/usr/bin/env python3
"""The 1,214 overtime rows of the 2022-2025 window: excluded from the successor's sampling pool, and evaluated separately.

The successor is regulation only. The reference (e2_reference.load, regulation_only=True) must draw no entry from quarter 5 or
later, in either the play pool or the kickoff pool. This script (1) counts such entries and requires zero; (2) confirms the
exclusion count against the database; (3) reports the overtime rows' outcome mix separately, for information. The overtime rows
are never drawn from, so this evaluation does not feed any simulated game.

Writes docs/evidence/e2-successor/overtime-rows-evaluation.json. Usage: python3 overtime_rows_check.py
"""
import json
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
import e1_drive as e1  # noqa: E402
import e2_reference as er  # noqa: E402

ROOT = HERE.parents[2]
OUT = ROOT / 'docs' / 'evidence' / 'e2-successor' / 'overtime-rows-evaluation.json'


def quarter_of(row):
    return None if row is None or row.get('qtr') in (None, '') else int(row['qtr'])


def main():
    reference, excluded_kickoffs = er.load()
    in_play_pool = Counter()
    for entries in reference.pool.values():
        for entry in entries:
            if quarter_of(entry[1]) is not None and quarter_of(entry[1]) >= 5:
                in_play_pool[entry[0]] += 1
    in_kickoff_pool = sum(1 for k in reference.kickoff_pool if k.get('qtr') is not None and int(k['qtr']) >= 5)
    if in_play_pool or in_kickoff_pool:
        raise SystemExit(f'overtime entries reached the regulation-only pool: plays {dict(in_play_pool)}, kickoffs {in_kickoff_pool}')

    rows = e1.load(e1.DEFAULT_DB)
    unrestricted_pool, _ = e1.build_pool(rows, regulation_only=False)
    unrestricted_ot = sum(1 for entries in unrestricted_pool.values() for e in entries
                          if e[1] and e[1].get('qtr') not in (None, '') and int(e[1]['qtr']) >= 5)
    window = [r for r in rows if r['season'] is not None and 2022 <= int(r['season']) <= 2025 and r['week'] is not None
              and int(r['week']) <= 18]
    overtime = [r for r in window if quarter_of(r) is not None and quarter_of(r) >= 5]
    mix = Counter(r['play_type'] or 'none' for r in overtime)
    result = {
        'source': {'database': 'backend/data/picks.dev.db (read-only)', 'window': '2022-2025, weeks <= 18',
                   'engine_reference': 'e2_reference.load(regulation_only=True)'},
        'overtime_rows_in_window': len(overtime),
        'overtime_rows_in_regulation_only_play_pool': 0,
        'overtime_rows_in_regulation_only_kickoff_pool': 0,
        'pool_scope_reported_by_reference': reference.pool_scope,
        'excluded_kickoffs_reported_by_loader': excluded_kickoffs if isinstance(excluded_kickoffs, int) else len(excluded_kickoffs),
        'separate_evaluation': {
            'play_type_mix': dict(sorted(mix.items())),
            'touchdowns': sum(1 for r in overtime if r.get('touchdown') in (1, 1.0)),
            'interceptions': sum(1 for r in overtime if r.get('interception') in (1, 1.0)),
            'fumbles_lost': sum(1 for r in overtime if r.get('fumble_lost') in (1, 1.0)),
            'used_for_sampling': False,
        },
        'e1_unrestricted_pool_overtime_entries': unrestricted_ot,
        'reading': ('These rows are reported for information only. The successor is regulation only, so no simulated game draws '
                    'from them. The E1 standalone pool (e1_drive.build_pool with regulation_only=False) still carries them, and that '
                    'behaviour is unchanged: the frozen E1 fixtures depend on it.'),
    }
    if len(overtime) != result['pool_scope_reported_by_reference']['overtime_rows_excluded_from_pool']:
        raise SystemExit(f"overtime rows in the database ({len(overtime)}) disagree with the reference's exclusion count "
                         f"({result['pool_scope_reported_by_reference']['overtime_rows_excluded_from_pool']})")
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(result, indent=1, sort_keys=True, default=str) + '\n')
    print(json.dumps({k: result[k] for k in ('overtime_rows_in_window', 'overtime_rows_in_regulation_only_play_pool',
                                              'overtime_rows_in_regulation_only_kickoff_pool')}, indent=1))


if __name__ == '__main__':
    main()
