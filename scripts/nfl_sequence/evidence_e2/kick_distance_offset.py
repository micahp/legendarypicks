#!/usr/bin/env python3
"""Measure the publisher's kick_distance against the engine's kick-spot transform, on the field-goal rows of the kick table.

The engine puts the holder HOLDER_OFFSET yards behind the line of scrimmage (game_state.kick_spot_yardline_100). The kick
then runs from that spot to the end line, which the rulebook puts ENDZONE_DEPTH yards beyond the goal line (Rule 3, Section
11, Article 2: "The end line is 10 yards from the goal line"). So the engine implies
kick_distance = yardline_100 + HOLDER_OFFSET + ENDZONE_DEPTH, that is yardline_100 + 17.

Reads docs/fixtures/e2/kick_results_2022_2025.csv (read only). Writes docs/evidence/e2-successor/kick-distance-offset.json.
Usage: python3 kick_distance_offset.py
"""
import csv
import hashlib
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
import game_state as gs  # noqa: E402

ROOT = HERE.parents[2]
TABLE = ROOT / 'docs' / 'fixtures' / 'e2' / 'kick_results_2022_2025.csv'
OUT = ROOT / 'docs' / 'evidence' / 'e2-successor' / 'kick-distance-offset.json'
ENDZONE_DEPTH = 10  # yards from the goal line to the end line; rulebook Rule 3, Section 11, Article 2


def main():
    engine_offset = gs.HOLDER_OFFSET + ENDZONE_DEPTH
    rows = list(csv.DictReader(open(TABLE, newline='')))
    fg = [r for r in rows if r['play_type'] == 'field_goal']
    both = [r for r in fg if r['kick_distance'] not in ('', 'NA') and r['yardline_100'] not in ('', 'NA')]
    diff = [(r, int(round(float(r['kick_distance']) - float(r['yardline_100'])))) for r in both]

    counts = Counter(d for _, d in diff)
    by_season, by_result = defaultdict(Counter), defaultdict(Counter)
    for r, d in diff:
        by_season[r['season']][d] += 1
        by_result[r['field_goal_result'] or 'blank'][d] += 1
    n = len(diff)
    modal = counts.most_common(1)[0][0]
    outliers = [{'game_id': r['game_id'], 'play_id': r['play_id'], 'offset': d}
                for r, d in diff if d not in (engine_offset, engine_offset + 1, engine_offset + 2)]
    result = {
        'source': {'file': 'docs/fixtures/e2/kick_results_2022_2025.csv',
                   'sha256': hashlib.sha256(TABLE.read_bytes()).hexdigest()},
        'engine': {'holder_offset': gs.HOLDER_OFFSET, 'endzone_depth': ENDZONE_DEPTH, 'implied_kick_distance_offset': engine_offset},
        'rule_minimum_holder_offset': 7,  # rulebook, Section 17 KICKS, Article 7(b): holder and kicker "seven or more yards"
        'field_goal_rows': len(fg),
        'field_goal_rows_with_both_fields': n,
        'field_goal_rows_missing_a_field': len(fg) - n,
        'offset_counts': {str(k): v for k, v in sorted(counts.items())},
        'share_at_engine_offset': round(counts[engine_offset] / n, 4),
        'share_at_modal_offset': round(counts[modal] / n, 4),
        'modal_offset': modal,
        'holder_offset_implied_by_modal': modal - ENDZONE_DEPTH,
        'by_season': {s: dict(sorted(c.items())) for s, c in sorted(by_season.items())},
        'by_field_goal_result': {k: dict(sorted(c.items())) for k, c in sorted(by_result.items())},
        'outliers_outside_17_to_19': outliers,
        'reading': ('The engine offset is not the publisher convention. At the modal offset the publisher implies a holder '
                    'modal_offset - ENDZONE_DEPTH yards behind the line of scrimmage, which the rule allows (7 or more). '
                    'The data cannot say whether the gap is the holder spot or the publisher yardline convention.'),
        'source_engine_difference': {
            'engine': f'holder {gs.HOLDER_OFFSET} + end line {ENDZONE_DEPTH} = +{engine_offset}; kept, not changed',
            'publisher_modal': f'+{modal} on {counts[modal]} of {n} field-goal rows ({counts[modal] / n:.1%})',
            'difference_yards': modal - engine_offset,
            'rule': ('The holder and kicker stand seven or more yards behind the line of scrimmage. The printed 2026 rulebook '
                     'states this at Rule 3, Section 17 (KICKS), Article 7(b). The citation "Rule 1-6-2" was given in review and '
                     'was not used: Rule 1 of the printed rulebook ends at Section 5 and has no Section 6.'),
            'reasoning': ('Seven is the rule minimum, so the engine value is legal. The publisher offset of +' + str(modal) +
                          ' is the publisher\'s own measurement convention: its yardline_100 or its kick_distance definition, '
                          'not a rule. The data cannot tell the two apart, so the engine does not adopt the publisher '
                          'convention.'),
            'decision': ('Engine stays at +17. The frozen survey, the frozen fixtures and the engine are not changed for this '
                         'difference. It is recorded here and nowhere else.'),
            'consequence': ('A missed field goal is awarded at the spot of the kick. On the engine convention the receivers start '
                            'one yard closer to their own goal line than on the publisher convention (93 - snap against 92 - snap). '
                            'Made-field-goal rates are keyed on the snap yardline and are not affected.'),
        },
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(result, indent=1, sort_keys=True) + '\n')
    print(json.dumps({k: result[k] for k in ('field_goal_rows_with_both_fields', 'offset_counts',
                                              'share_at_engine_offset', 'share_at_modal_offset', 'modal_offset')},
                     indent=1, sort_keys=True))


if __name__ == '__main__':
    main()
