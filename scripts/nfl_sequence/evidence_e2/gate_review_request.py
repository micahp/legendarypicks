#!/usr/bin/env python3
"""Write the E2 successor gate review request as a repository file, so it can be pasted when the gate opens.

Every count is read from the survey, the residual file and the drive-index totals, and both test suites are run here to record
their counts. Nothing is posted: the request is a file. Writes docs/evidence/e2-successor/GATE-REVIEW-REQUEST-E2-SUCCESSOR.md.
Usage: python3 gate_review_request.py [--head SHA]
"""
import argparse
import hashlib
import io
import json
import subprocess
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
NFL = HERE.parent
sys.path.insert(0, str(NFL))
sys.path.insert(0, str(HERE))
ROOT = HERE.parents[2]
EV = ROOT / 'docs' / 'evidence' / 'e2-successor'
OUT = EV / 'GATE-REVIEW-REQUEST-E2-SUCCESSOR.md'
ENGINE_SHA = '75962ffe5fca9eddee9b49ff377031c5075e2c16'
PREVIOUS_HEAD = '04a3752d95e62a0364cd8c80d5f003f76fb03beb'


def run_suite(directory, pattern):
    loader = unittest.TestLoader()
    suite = loader.discover(str(directory), pattern=pattern)
    result = unittest.TextTestRunner(stream=io.StringIO(), verbosity=0).run(suite)
    return {'run': result.testsRun, 'failures': len(result.failures), 'errors': len(result.errors),
            'ok': result.wasSuccessful()}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--head', default='(the commit that adds this file; see git log)')
    args = ap.parse_args()
    s = json.loads((EV / 'legality-survey-300-summary.json').read_text())
    residuals = json.loads((EV / 'shared-v1-residuals.json').read_text())
    engine = run_suite(NFL, 'test_*.py')
    evidence = run_suite(HERE, 'test_*.py')
    artifacts = sorted(p.name for p in EV.iterdir() if p.is_file() and p.name != OUT.name)
    e3 = sorted(str(p.relative_to(ROOT)) for p in (ROOT / 'docs' / 'evidence' / 'e3').rglob('*') if p.is_file())
    lines = [
        '# E2 successor: gate review request', '',
        '**Phase:** E2 successor, regulation-only sequence engine. Gate review of the scoped research milestone.', '',
        f'**Engine commit:** `{ENGINE_SHA}`. **Previous evidence head:** `{PREVIOUS_HEAD}`. **Head that adds this file:** {args.head}.',
        'The head is the commit that adds this file. A file cannot name its own commit.', '',
        '**Branch:** `feat/nfl-sequence-e2-successor-2026-10-24`. Frozen E2 reference `a442dcd7` is untouched.',
        '`valid_full_game` is false for every record.', '',
        '## Scope', '',
        'Regulation only. The sampling pool excludes overtime (1,214 rows in 2022-2025). Two-minute warning, penalties, timeouts,',
        'onside kicks, overtime and the exception coin toss are unmodelled and guarded. No guarded or blocked game is described as a',
        'complete game. The claim is consistency under the modelled rules, not a complete legal NFL game.', '',
        '## Tests', '',
        f"- Engine suite (`scripts/nfl_sequence`): {engine['run']} run, {engine['failures']} failures, {engine['errors']} errors. "
        f"{'OK' if engine['ok'] else 'NOT OK'}.",
        f"- Evidence suite (`scripts/nfl_sequence/evidence_e2`): {evidence['run']} run, {evidence['failures']} failures, "
        f"{evidence['errors']} errors. {'OK' if evidence['ok'] else 'NOT OK'}.", '',
        '## 300-seed survey (engine ' + ENGINE_SHA[:8] + ')', '',
        f"- Validated by validate_game: {s['validate_game_passed']} of {s['seeds']}.",
        f"- Reached regulation end under the simulation: {s['regulation_end_reached']}, all guarded (`regulation_end_guarded`).",
        f"- Complete games: {s['complete_game']}. Legal complete games: {s['legal_complete_game']}.",
        f"- Legal under the modelled rules: {s['legal_modelled']} of {s['seeds']}.",
        f"- Blocked: {s['status'].get('blocked', 0)}, each with a named reason ({s['scope_out_seeds']['overtime']} overtime, "
        f"{s['scope_out_seeds']['rare kick outcome']} rare kick outcome).",
        f"- Blocked, guarded or tied described as complete: {s['blocked_described_complete']}, {s['guarded_described_complete']}.",
        f"- Matrix FAIL rows: {s['matrix_fail_rows']}. Try findings: {s['try_findings_total']}.",
        f"- Drive index (blocker 3): {s['drive_index_mismatch_drives']} drives and {s['drive_index_mismatch_states']} play states "
        f"carry a wrong index, of {s['drive_index_states_checked']} play states checked on 300 seeds.",
        f"- Matches the frozen survey on {s['matches_frozen_survey']} of {s['seeds']} seeds.", '',
        '## Blocker status', '',
        '| blocker | status | where |', '|---|---|---|',
        '| 1 try rates from publisher fields | closed | `try-rates-publisher-vs-success.json`, `measure_kick_outcomes.py` |',
        '| 2 missed field goal, Rule 11-4-2 | award closed; touch exception guarded | matrix R11, `MissedFieldGoalBoundaries` |',
        '| 3 drive_index | closed on the successor corpus; the archived fixture still carries the 23 findings by design | '
        '`drive_index_check.py`, `test_drive_index_corpus.py`, survey summary |',
        '| 4 toss sampling | closed | `toss-sampling-300.json` |',
        '| 5 penalties and two-minute warning | guarded, not modelled, negative fixtures listed | `UNMODELLED-TRANSITIONS-300-2026-10-24.md` |',
        '| 6 overtime and rare kick outcomes | scoped out; never complete | survey scope counts, R07, R21 |',
        '| 7 shared-v1 residuals | documented, nine, each guarded; not conformant | `shared-v1-residuals.json`, mapping below |', '',
        '## Shared-v1 mapping, reviewer ten to our nine', '',
        'The reviewer\'s list of ten is not in the repository. The handoff (`HANDOFF-E2-REVIEW-2026-10-24.md` section 3) says it was never '
        'located. The mapping below uses the three sources that can be reproduced: the LP check, Gridiron\'s record-level audit, and '
        'Gridiron\'s v1 document audit. It shows every item that the three report, and how each collapses to one of our nine.', '',
        '| our residual | LP check id | Gridiron text | guard test |', '|---|---|---|---|',
    ]
    for r in residuals['residuals']:
        lp_id = r['id'] if r['source'] == 'shared_v1.check_document' else '-'
        lines.append(f"| `{r['id']}` | {lp_id} | {r['gridiron_text']} | `{r['guard_test']}` |")
    lines += [
        '', 'Collapsing rules, stated so the arithmetic can be checked:', '',
        '1. The Gridiron time line, "missing or invalid top-level as_of_utc before scheduled_kickoff_utc", names two fields. It maps to '
        '`V-unresolved-as_of_utc` and `V-unresolved-scheduled_kickoff_utc`, which the LP check reports separately. It is one '
        'coalesced claim about two fields, counted once in our nine.',
        '2. `missing stable game_id`, `mode is not pregame_full_game` and `missing eligible roster snapshot` each map to one LP id.',
        '3. `missing model_version` and `missing rules_version` were in Gridiron\'s record-level audit before the stamp commit '
        '(`bd5f3383`). Both are closed by the stamps, so they are not among the nine.',
        '4. `V-unresolved-snapshot_hash` and `V-duration-seconds` are reported by the LP check only.',
        '5. `missing real home/away team identities` and `record.valid_full_game is not true` are reported by Gridiron only.',
        '', f"Count: the three sources report {len(residuals['residuals'])} distinct residuals after the stamp commit. Before the stamp commit, "
        'the union was eleven, and two of them are closed by the stamps. If the reviewer\'s ten counts the time pair as two items '
        'plus the combined line, the difference is the coalescing in rule 1. The reviewer\'s list is needed to confirm each item.', '',
        '## Artifacts', '', 'In `docs/evidence/e2-successor/`:', ''] + [f'- `{a}`' for a in artifacts] + [
        '', 'In `docs/evidence/e3/`:', ''] + [f'- `{a}`' for a in e3] + [
        '', '## Open defects', '',
        '1. **Blocker 3, the archived fixture.** `docs/fixtures/e2/regression/lp-e2-game-seed1-5fcaa6bc.json` carries the 23 drives and '
        '280 play states. It is kept unmodified by design, and a test asserts its counts.',
        '2. **E1 standalone output.** `e1_drive.simulate` writes `drive_index` 1 on every play. The game engine overwrites it. A consumer '
        'that reads raw E1 states must not treat them as game indices.',
        '3. **Shared-v1 residuals.** Nine remain. Each is guarded, none is fixed, and the contract is unchanged.',
        '4. **Two-minute warning and penalties.** Guarded, not modelled. Timeout stoppage time is inside the observed runoff.',
        '5. **Missed field goal touch exception.** Rule 11-4-2 (1) and (2) are not modelled. The table records makes and misses, not touches.',
        '6. **Kickoff clock.** Uncapped observed runoff, a documented deviation. The five-second cap is printed for field goals only.',
        '7. **Overtime and rare kick outcomes.** 11 and 1 seeds blocked. Overtime is excluded from the sampling pool.',
        '8. **Coverage gaps.** R10 (safety game-level test) and R20 (attacks_x100 direct test) are pinned gaps.',
        '9. **Gridiron viewer.** The viewer refuses guarded records by design (`requireCompleteRegulation`). Validation-only accepts them.',
        '10. **Stale text.** The engine docstring says the rulebook is not in the repository, and that is now false.',
        '11. **E3 is out of this gate.** The E3 clock baseline and tracking coverage are separate artifacts, reported separately.', '',
        '## The three asks', '',
        'These are the decisions this request needs. The request did not list them, so they are stated here as the reviewer\'s asks.',
        '',
        '1. Accept or reject the guarded status as the correct treatment of a regulation end with an unmodelled transition. Under it,',
        '   `complete_regulation` is false for every seed, and `regulation_end_reached` carries the simulation fact.',
        '2. Supply the reviewer\'s list of ten shared-v1 violations, so the mapping above can be completed line by line.',
        '3. Decide the two modelling questions: whether the kickoff clock stays uncapped as a documented deviation, and whether the',
        '   missed field goal touch exception is modelled or scoped out.',
        '', 'Rule 1 of the printed rulebook ends at Section 5. The citation "Rule 1-6-2" was given in review; it appears in this package only as a note that it was not used.', '',
    ]
    OUT.write_text('\n'.join(lines) + '\n')
    print(f'wrote {OUT}; engine {engine}; evidence {evidence}')


if __name__ == '__main__':
    main()
