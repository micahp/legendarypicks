#!/usr/bin/env python3
"""Write the type inventory of unmodelled transitions, from unmodelled-transitions-300.json and the survey summary.

Counts and printed rule headings come from the enumeration and the survey, not from typing. The treatment of each type (an
implemented transition with its tests, or a guard that fails loudly) is written here, and every test name is checked to exist.
Writes docs/evidence/e2-successor/UNMODELLED-TRANSITIONS-300-2026-10-24.md. Usage: python3 unmodelled_doc.py
"""
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))
import traceability as tb  # noqa: E402  (imports the test modules to resolve test names)

ROOT = HERE.parents[2]
SRC = ROOT / 'docs' / 'evidence' / 'e2-successor' / 'unmodelled-transitions-300.json'
SURVEY = ROOT / 'docs' / 'evidence' / 'e2-successor' / 'legality-survey-300-summary.json'
OUT = ROOT / 'docs' / 'evidence' / 'e2-successor' / 'UNMODELLED-TRANSITIONS-300-2026-10-24.md'

# treatment: 'guard' (not modelled; the record is guarded and never a complete game), 'blocked' (the game stops, blocker named),
# 'refused' (the engine cannot draw it; the validator refuses it), or 'implemented' (modelled, with tests).
INVENTORY = {
    'two_minute_warning': {
        'treatment': 'guard',
        'fails_loudly': 'the game is status regulation_end_guarded, complete_game is false, and validate_game refuses a complete '
                        'claim; the checker reports check_unmodelled',
        'tests': ['test_game_state.UnmodelledKinds.test_a_guarded_game_described_as_complete_is_refused',
                  'test_game_state.UnmodelledTransitions.test_a_two_minute_crossing_is_listed_in_the_record',
                  'test_legality.UnmodelledNegatives.test_the_two_minute_crossing_is_derived_from_the_plays_not_the_records_own_list'],
        'note': 'The clock is not stopped at 2:00; the sampled runoff is used as recorded.',
    },
    'penalty': {
        'treatment': 'blocked',
        'fails_loudly': 'the game is blocked as penalty_not_modelled and is never complete',
        'tests': ['test_game_state.UnmodelledTransitions.test_a_sampled_penalty_blocks_the_game_and_is_not_completed',
                  'test_legality.UnmodelledNegatives.test_a_penalty_transition_cannot_pass_as_a_legal_complete_game'],
        'note': 'The E1 pool excludes penalty rows by construction, so a penalty is drawn only if a row carries one.',
    },
    'timeout': {
        'treatment': 'guard',
        'fails_loudly': 'the game is guarded: complete_game is false, and the checker reports check_unmodelled',
        'tests': ['test_game_state.UnmodelledKinds.test_a_timeout_flag_is_an_unmodelled_stoppage',
                  'test_game_state.TimeoutCharges.test_flags_charge_at_most_three_per_half_and_reset_at_halftime',
                  'test_game_state.TimeoutTransition.test_the_count_is_written_once_in_state_after_and_only_for_the_charged_side'],
        'note': 'The count is implemented: a timeout is charged to a side that has one left. Its stoppage time is inside the observed '
                'runoff, so the clock effect is guarded.',
    },
    'overtime_block': {
        'treatment': 'blocked',
        'fails_loudly': 'a tied regulation game is blocked as overtime_not_modelled; validate_game refuses it described as complete',
        'tests': ['test_game_state.ScopedOut.test_a_tied_regulation_game_is_scoped_out_as_overtime',
                  'test_game_state.ScopeRefusals.test_a_tied_game_with_its_overtime_block_removed_is_refused'],
        'note': 'Overtime rows are excluded from the sampling pool (see overtime-rows-evaluation.json).',
    },
    'missed_field_goal_return': {
        'treatment': 'implemented with a guard',
        'fails_loudly': 'the awarded spot is implemented (Rule 11-4-2 (a) and (b)); the receivers\' touch exception (1) and (2) is '
                        'guarded: the game is guarded and the checker reports check_unmodelled',
        'tests': ['test_game_state.MissedFieldGoalBoundaries.test_one_yard_inside_the_receivers_20_gives_their_20',
                  'test_game_state.MissedFieldGoalBoundaries.test_one_yard_outside_the_receivers_20_gives_the_spot_of_the_kick',
                  'test_game_state.UnmodelledKinds.test_a_missed_field_goal_is_an_unmodelled_return',
                  'test_game_state.MissedFieldGoalReturn.test_the_return_exception_is_a_named_unsupported_rule_with_a_guard'],
        'note': 'The table records makes and misses, not touches, so the exception cannot be decided from the data.',
    },
    'onside_kick': {
        'treatment': 'refused',
        'fails_loudly': 'validate_game refuses any kickoff kind outside the engine vocabulary',
        'tests': ['test_game_state.UnmodelledKinds.test_an_onside_kickoff_kind_is_refused_because_it_is_not_modelled'],
        'note': 'Every kickoff is drawn from the observed kickoff pool, so no onside kick can be drawn.',
    },
    'exception_coin_toss': {
        'treatment': 'refused',
        'fails_loudly': 'explicit_exception_scenario raises NotImplementedError; every game is in normal mode',
        'tests': ['test_game_state.Ledger.test_exception_mode_is_not_implemented'],
        'note': 'The forfeited-privilege exception (Rule 4, Section 2, Article 2) is not drawn.',
    },
}


# Negative fixtures for each guarded transition family and the clock. Each row names the guard it proves, and every test name is
# checked to resolve before the document is written.
NEGATIVE_FIXTURES = [
    ('clock (no clamp)', 'a negative clock is refused, so no clamp can hide one', 
     'test_game_state.KickoffClock.test_a_negative_clock_is_refused_so_no_clamp_can_hide_one'),
    ('clock (no clamp)', 'a kickoff longer than the clock expires the quarter; the overrun is recorded, not clamped',
     'test_game_state.KickoffClock.test_a_kickoff_longer_than_the_clock_expires_the_quarter_and_records_the_overrun'),
    ('clock', 'a clock that rises inside a quarter is refused by the checker',
     'test_legality.NegativeFixtures.test_a_clock_that_rises_inside_a_quarter'),
    ('clock', 'a quarter that falls is refused by the checker', 'test_legality.NegativeFixtures.test_a_quarter_that_falls'),
    ('clock', 'a complete game that does not end at zero is refused by the checker',
     'test_legality.NegativeFixtures.test_a_complete_game_that_does_not_end_at_zero'),
    ('clock', 'a clock that rises inside a quarter fails the rules matrix',
     'test_game_state.RulesMatrix.test_a_clock_that_rises_inside_a_quarter_is_a_failure'),
    ('two-minute warning', 'a crossing removed from the record is still derived from the plays and refuses the complete claim',
     'test_legality.UnmodelledNegatives.test_the_two_minute_crossing_is_derived_from_the_plays_not_the_records_own_list'),
    ('two-minute warning', 'the seed-1 record is not a legal complete game because of its two-minute crossing',
     'test_legality.ScopeGuard.test_the_successor_seed_one_is_not_a_legal_complete_game_because_of_the_two_minute_crossing'),
    ('two-minute warning', 'a guarded game relabelled complete_regulation is refused by validate_game',
     'test_game_state.UnmodelledKinds.test_a_guarded_game_described_as_complete_is_refused'),
    ('two-minute warning', 'a guarded game with its complete flag set is refused by validate_game',
     'test_game_state.UnmodelledKinds.test_a_guarded_game_with_its_complete_flag_set_is_refused'),
    ('penalty', 'a sampled penalty blocks the game and it is never complete',
     'test_game_state.UnmodelledTransitions.test_a_sampled_penalty_blocks_the_game_and_is_not_completed'),
    ('penalty', 'a penalty transition cannot pass as a legal complete game (checker)',
     'test_legality.UnmodelledNegatives.test_a_penalty_transition_cannot_pass_as_a_legal_complete_game'),
    ('timeout', 'a timeout stoppage cannot pass as a legal complete game (checker)',
     'test_legality.UnmodelledKindNegatives.test_a_timeout_stoppage_cannot_pass_as_a_legal_complete_game'),
    ('missed field goal return', 'a missed-field-goal return cannot pass as a legal complete game (checker)',
     'test_legality.UnmodelledKindNegatives.test_a_missed_field_goal_return_cannot_pass_as_a_legal_complete_game'),
    ('onside kick', 'an onside kickoff kind is refused by validate_game',
     'test_game_state.UnmodelledKinds.test_an_onside_kickoff_kind_is_refused_because_it_is_not_modelled'),
]


def main():
    data = json.loads(SRC.read_text())
    summary = json.loads(SURVEY.read_text())
    counts = {t['type']: t for t in data['types']}
    for name, spec in INVENTORY.items():
        for test in spec['tests']:
            if not tb.check_test_id(test):
                raise SystemExit(f'{name}: test {test} does not resolve')
    for guard, claim, test in NEGATIVE_FIXTURES:
        if not tb.check_test_id(test):
            raise SystemExit(f'negative fixture {test} does not resolve')
    lines = [
        '# E2 successor: unmodelled transitions, type inventory (300 seeds, 2026-10-24)', '',
        'Every unmodelled transition type that the 300 seeds produce or can produce, with its count across the seeds, the printed '
        '2026 rulebook heading it falls under, and its treatment: an implemented transition with tests, a guard, a block, or a '
        'refusal. Each treatment fails loudly. A game that contains an unmodelled transition is never described as a complete game.',
        '', f"Engine commit `{data['source']['engine_commit']}`. Games: seeds 1-300. Cross-check: {data['source']['crosscheck']}.",
        '', '## Inventory', '',
        '| type | count | seeds | printed rule heading | treatment | how it fails | tests |',
        '|---|---:|---:|---|---|---|---|',
    ]
    for name, spec in INVENTORY.items():
        c = counts[name]
        tests = '<br>'.join(f'`{t}`' for t in spec['tests'])
        lines.append(f"| `{name}` | {c['count']} | {c['seeds_affected']} | {c['printed_heading']} | {spec['treatment']} | "
                     f"{spec['fails_loudly']} | {tests} |")
    lines += ['', '`lineups` is a labelling guard, not a transition: participants are labelled sampled_observed_play.', '',
              '## Counts by quarter', '',
              f"Two-minute crossings by quarter: {', '.join(f'{k}: {v}' for k, v in data['two_minute_warning_by_quarter'].items())}.",
              f"Seeds with at least one unmodelled transition: {data['seeds_with_any_unmodelled_transition']} of 300.", '',
              '## Notes per type', '']
    for name, spec in INVENTORY.items():
        lines.append(f"- `{name}`: {spec['note']}")
    lines += ['', '## Negative fixtures for the guards', '',
              'Each row is a test that fails if the guard stops refusing the claim. Test names are checked to resolve on every build.', '',
              '| guard family | what the fixture proves | test |', '|---|---|---|']
    for guard, claim, test in NEGATIVE_FIXTURES:
        lines.append(f'| {guard} | {claim} | `{test}` |')
    lines += ['', '## Shared-v1 residuals', '',
              'Nine residuals are guarded: `shared-v1-residuals.json` lists each with its guard test. Seven come from the LP check '
              '(`V-mode`, `V-unresolved-game_id`, `V-unresolved-scheduled_kickoff_utc`, `V-unresolved-as_of_utc`, '
              '`V-unresolved-snapshot_hash`, `V-unresolved-roster_snapshot_id`, `V-duration-seconds`). Two come from Gridiron only '
              '(`V-teams-unresolved`, `V-valid-full-game`). Gridiron\'s combined as-of and kickoff line maps onto the two LP time '
              'IDs, so it is not counted twice.', '']
    lines += ['', '## Survey outcome', '',
              f"Seeds 300. Validated by validate_game: {summary['validate_game_passed']}. Blocked: {summary['status'].get('blocked', 0)}, "
              f"with a named reason each. Regulation end under the simulation: {summary['regulation_end_reached']}, of which guarded: "
              f"{summary['regulation_end_guarded']}. Complete games: {summary['complete_game']}. Guarded seeds described as complete: "
              f"{summary['guarded_described_complete']}. Blocked seeds described as complete: {summary['blocked_described_complete']}. "
              f"Legal complete games: {summary['legal_complete_game']}.", '',
              'The claim the survey supports is consistency under the modelled rules. It is not a claim that any sampled game is a '
              'complete legal game.']
    OUT.write_text('\n'.join(lines) + '\n')
    print(f'wrote {OUT}')


if __name__ == '__main__':
    main()
