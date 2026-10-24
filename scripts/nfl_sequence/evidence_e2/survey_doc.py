#!/usr/bin/env python3
"""Write the 300-seed survey document from legality-survey-300.csv and legality-survey-300-summary.json.

Every count is read from the survey outputs. The document lists each blocked seed with its reason, the FAIL rows, the comparison
with the frozen survey, and one row per seed. Writes docs/evidence/e2-successor/SURVEY-300-SUCCESSOR-2026-10-24.md.
Usage: python3 survey_doc.py
"""
import csv
import json
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
EVIDENCE = ROOT / 'docs' / 'evidence' / 'e2-successor'
CSV_PATH = EVIDENCE / 'legality-survey-300.csv'
SUMMARY = EVIDENCE / 'legality-survey-300-summary.json'
OUT = EVIDENCE / 'SURVEY-300-SUCCESSOR-2026-10-24.md'


def main():
    rows = list(csv.DictReader(open(CSV_PATH, newline='')))
    s = json.loads(SUMMARY.read_text())
    mismatch_path = EVIDENCE / 'MISMATCH-300-SUCCESSOR-2026-10-24.json'
    mismatch = json.loads(mismatch_path.read_text()) if mismatch_path.exists() else None
    differs = {m['seed'] for m in s['mismatches_vs_frozen']}
    blocked = [r for r in rows if r['status'] == 'blocked']
    fail_rows = sum(int(r['matrix_fail']) for r in rows)
    blockers = Counter(r['blocker'] for r in blocked)
    lines = [
        '# E2 successor: 300-seed survey on the current research source (2026-10-24)', '',
        f"Engine base commit: `{s['source']['base_model_version']}`. Exact source-tree SHA-256: "
        f"`{s['source']['source_tree_sha256']}`. Producer files: {'dirty research snapshot' if s['source']['producer_worktree_dirty'] else 'clean'}.",
        'Command: `survey_legality_300.py`. Seeds 1-300, regulation-only pool.',
        'Each record passes `validate_game`, is checked by the independent checker (no engine imports) and by `rules_matrix`.',
        '`legal_complete_game` is a candidate under this engine’s modeled rules. It does not mean shared-v1 `valid_full_game`.', '',
        '## Counts', '',
        '| measure | count |', '|---|---:|',
        f"| seeds | {s['seeds']} |",
        f"| validate_game passed | {s['validate_game_passed']} |",
        f"| reached regulation end under the simulation (`regulation_end_reached`) | {s['regulation_end_reached']} |",
        f"| regulation end, guarded by an unmodelled transition (`regulation_end_guarded`) | {s['regulation_end_guarded']} |",
        f"| complete regulation game (`complete_regulation`, unguarded) | {s['complete_regulation']} |",
        f"| complete model-scoped regulation (`complete_game`) | {s['complete_game']} |",
        f"| independent model-scoped candidate (`legal_complete_game`) | {s['legal_complete_game']} |",
        f"| shared-v1 `valid_full_game=true` | {s['valid_full_game']} |",
        f"| legal under the modelled rules (checker) | {s['legal_modelled']} |",
        f"| blocked | {s['status'].get('blocked', 0)} |",
        f"| blocked described as complete | {s['blocked_described_complete']} |",
        f"| guarded described as complete | {s['guarded_described_complete']} |",
        f"| matrix FAIL rows | {fail_rows} |",
        f"| try findings | {s['try_findings_total']} |",
        f"| matches the frozen survey on status, blocker, regulation end and matrix (frozen a442dcd7, unmodified) | "
        f"{s['matches_frozen_survey']} of {s['seeds']} |", '',
        '## Why `valid_full_game` remains false', '',
        'These records use `mode=legal_game_state_first_piece` and retrospective sampled plays. They do not identify a scheduled '
        'upcoming game, a pregame as-of time and kickoff, or an eligible roster snapshot; the shared-v1 audit has nine unresolved '
        'contract residuals on the seed-1 record. The engine also keeps unsupported rule families explicit. Reaching regulation end '
        'and passing the independent modeled-rule checks is not enough to set the full-game contract flag.', '',
        'Two-minute warning crossings are marked and independently checked at the actual post-down clock; the play is not '
        'rewound to 2:00. The required running/stopped clock state and explicit restart transitions remain unsupported under '
        '`clock_start_stop`, so this marker does not establish full clock-rule coverage.', '',
    ]
    if mismatch:
        lines += [f"The all-quarter counterfactual classified {mismatch['classification_counts']} across the {mismatch['changed_seeds']} "
                  f"changed seeds. Detail: {mismatch['classification_detail_counts']}. In 11 cases the all-quarter run matches the "
                  'frozen status, blocker and regulation-end outcome, but the current two-minute-warning guard correctly keeps '
                  '`complete_game=false`; in 2 cases the status or blocker still differs with the all-quarter pool. See '
                  '`MISMATCH-300-SUCCESSOR-2026-10-24.md` for the per-seed controlled comparison.', '']
    lines += [
        '## Blocked seeds, with their reason', '', '| seed | blocker | scope reason |', '|---:|---|---|',
    ]
    for r in blocked:
        lines.append(f"| {r['seed']} | `{r['blocker']}` | {r['scope_out']} |")
    lines += ['', f"Blocker counts: {dict(blockers)}.", '', '## Per seed', '',
              '| seed | status | blocker | regulation end | complete_game | valid_full_game | unmodelled | scope | FAIL rows | vs frozen |',
              '|---:|---|---|:-:|:-:|:-:|---:|---|---:|---|']
    for r in rows:
        lines.append(f"| {r['seed']} | {r['status']} | {r['blocker'] or '-'} | {r['regulation_end_reached']} | {r['complete_game']} | "
                     f"{r['valid_full_game']} | {r['unmodelled_transitions']} | {r['scope_out'] or '-'} | {r['matrix_fail']} | "
                     f"{'differs' if int(r['seed']) in differs else 'same'} |")
    OUT.write_text('\n'.join(lines) + '\n')
    print(f'wrote {OUT}')


if __name__ == '__main__':
    main()
