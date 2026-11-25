"""Verify each ablation arm through the run-time instrumentation (spec amendment 2, verification 2).

For every arm: each switched-off mechanism must show zero applications; the chooser evidence a removed choice must
erase must be zero; and every other mechanism must still run, at a rate within a tolerance of the control's.
Usage: python3 verify_arms.py OUT_DIR
"""
import glob
import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import ablation_hook as h  # noqa: E402

EVIDENCE_ZERO = {  # mechanism switched off -> chooser evidence that must then be zero
    'label_generation': ['labels_drawn', 'playbook_used'],
    'formation_choice': ['formation_drawn'],
    'coverage_choice': ['coverage_drawn'],
    'qb_target_role_selection': ['qb_target_role_drawn'],
    'qb_scramble_probability': ['qb_scramble_probability_source:qb_team_model'],
    'playbook_label_priors': ['playbook_used'],
    'dirichlet_player_shares': ['participant_share_model:dirichlet_multinomial'],
    'score_clock_playcalling': ['call_policy_source:score_clock_logistic_artifact'],
}
# mechanisms whose activity legitimately depends on another switched-off one (not an unrelated mechanism)
DEPENDS = {
    'label_generation': {'label_outcome_lift', 'label_row_filter', 'label_conditional_pass_model'},
    'formation_choice': {'formation_outcome_lift', 'formation_row_filter'},
    'coverage_choice': {'coverage_outcome_lift', 'coverage_row_filter'},
    'qb_target_role_selection': {'qb_target_role_row_filter'},
}


def totals(arm_dir):
    m, e, n = Counter(), Counter(), 0
    for f in glob.glob(str(arm_dir / 'stats.*.jsonl')):
        for line in open(f):
            r = json.loads(line)
            n += r['decisions']
            m.update(r['mechanisms_applied'])
            e.update(r['evidence'])
    return m, e, n


def main(out):
    out = Path(out)
    cm, ce, cn = totals(out / 'A00_control')
    rows = []
    for arm, spec in h.ARMS.items():
        if spec is None or not (out / arm).exists():
            continue
        m, e, n = totals(out / arm)
        problems = []
        if n == 0:
            problems.append('no decisions recorded')
        off = set(spec['off'])
        for mech in off:
            if m.get(mech, 0):
                problems.append(f'{mech} still applied {m[mech]}x')
            for key in EVIDENCE_ZERO.get(mech, []):
                if e.get(key, 0):
                    problems.append(f'{key} = {e[key]} (should be 0)')
        dependent = set().union(*(DEPENDS.get(x, set()) for x in off)) if off else set()
        for mech, base in cm.items():
            if mech in off or mech in dependent or not base or not cn or not n:
                continue
            if mech.startswith(('streak_', 'team_streak', 'league_streak')) and spec['attrs'].get('current_streak') == {}:
                continue
            ratio = (m.get(mech, 0) / n) / (base / cn)
            if ratio < 0.5:
                problems.append(f'unrelated {mech} fell to {ratio:.2f} of the control rate')
        rows.append({'arm': arm, 'decisions': n, 'off': sorted(off), 'attrs': sorted(spec['attrs']),
                     'ok': not problems, 'problems': problems})
    for r in rows:
        print(('PASS ' if r['ok'] else 'FAIL ') + r['arm'], r['decisions'], '; '.join(r['problems']))
    (out / 'verification.json').write_text(json.dumps(rows, indent=1) + '\n')
    return 0 if all(r['ok'] for r in rows) else 1


if __name__ == '__main__':
    raise SystemExit(main(sys.argv[1]))
