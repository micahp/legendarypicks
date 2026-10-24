#!/usr/bin/env python3
"""Rule traceability matrix for the successor engine. Each rule the engine cites is mapped to the reducer transition that
implements it, to positive and adversarial tests, and to the rulebook text it was checked against.

Every build checks what it writes: each transition must resolve to a function, each code citation must occur in its file,
and each test id must name a test method. A row without a positive or an adversarial test is written as a GAP, not dropped.
A rule with no rulebook text on the box is marked "not verified", and its code citation is said to be unverified.

Writes docs/evidence/e2-successor/RULE-TRACEABILITY-MATRIX-2026-10-24.{md,json}. Usage: python3 traceability.py
"""
import importlib
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
OUT = ROOT / 'docs' / 'evidence' / 'e2-successor'
KICK_JSON = OUT / 'kick-distance-offset.json'

RULEBOOK = {
    'title': '2026 NFL Rulebook (ops-2026-NFL-Rulebook-FINAL.pdf)',
    'page': 'https://operations.nfl.com/rules-officiating/2026-nfl-rulebook',
    'pdf': 'https://static.www.nfl.com/image/upload/fl_attachment/league/tqivdkzt9mu6wdgsh1ku.pdf',
    'sha256': '144cec5bffd2725bb703a26523f5ccf0b16c59c2fe5c13f6e671f4bddaa87c55',
    'pages': 91,
    'extraction': 'pdftotext -layout; the extracted text is not committed',
    'retrieved': '2026-10-24',
}
LP_REFERENCE = 'docs/rules/NFL-2026-GAME-STATE-RULES.md on origin/dev (LP engineering reference, not the official rulebook)'

NOT_VERIFIED = 'not verified: no rulebook text read; code citation not verified against rulebook text'
GAME = 'game_state.py'
E1 = 'e1_drive.py'

# Each row: the rule, its rulebook article and status, the reducer transition, the code citations (file, snippet), and the tests.
ROWS = [
    dict(id='R01', rule='Toss winner chooses receive or defer. Normal mode refuses kick and goal-to-defend as first choice.',
         rulebook=dict(article='4-2-2 Article 2', status='verified',
                       quote='"Unless the winner of the toss defers his choice to the second half, he must choose one of two privileges"'),
         lp_reference='Rules file, STRICT DEFAULT SIMULATION POLICY (LP policy, not rulebook text: the rulebook permits kick and goal choices)',
         transition='game_state:CoinTossLedger.__init__',
         citations=[(GAME, 'only receive or defer')],
         positive=['test_game_state.Ledger.test_receive_path_gives_one_kickoff_per_team',
                   'test_game_state.Ledger.test_defer_path_gives_one_kickoff_per_team'],
         adversarial=['test_game_state.Ledger.test_normal_mode_refuses_kick_and_defend_goal',
                      'test_game_state.Ledger.test_exception_mode_is_not_implemented'],
         status='policy', note='The engine restricts the rulebook\'s permitted choices to LP normal-mode policy.'),
    dict(id='R02', rule='The pregame toss loser has first choice for the second half, unless the winner deferred.',
         rulebook=dict(article='4-2-2 Article 2', status='verified',
                       quote='"the captain who lost the pregame toss is to have the first choice ... unless the winner of the pregame toss deferred"'),
         lp_reference='Rules file section 1',
         transition='game_state:CoinTossLedger.__init__',
         citations=[(GAME, 'self.first_chooser = loser if self.deferred else winner')],
         positive=['test_game_state.Ledger.test_second_half_first_choice_follows_the_deferral'],
         adversarial=['test_game_state.Validators.test_recorded_kickoffs_must_match_the_ledger',
                      'test_game_state.TossSymmetry.test_a_ledger_that_disagrees_with_the_kickoffs_is_rejected'],
         status='modelled', note=''),
    dict(id='R03', rule='A kickoff starts each half. Normal mode: exactly two half-start kickoffs, one by each team.',
         rulebook=dict(article='4-2-1 Article 1', status='verified', quote='"Both teams must be on the field to kick off ... for the start of each half"'),
         lp_reference='Rules file, STRICT DEFAULT SIMULATION POLICY and section 3',
         transition='game_state:_Game._half_start',
         citations=[(GAME, 'Halftime: the first half is over')],
         positive=['test_game_state.HalfStart.test_halftime_ends_the_first_half_and_the_second_half_kickoff_is_generated',
                   'test_game_state.TossSymmetry.test_every_winner_and_choice_gives_the_matrix_kickoffs'],
         adversarial=['test_game_state.Validators.test_same_team_kicking_twice_is_a_hard_failure',
                      'test_game_state.RulesMatrix.test_the_same_team_kicking_both_half_openers_is_a_failure'],
         status='modelled', note='The validator is game_state:validate_half_start.'),
    dict(id='R04', rule='Teams change goals after Q1 and Q3. Possession, down, spot and line to gain persist: no kickoff, no drive end.',
         rulebook=dict(article='4-2-3 Article 3', status='verified',
                       quote='"At the end of the first and third periods, the teams must change goals. Team possession, the number of the succeeding down ... remain the same."'),
         lp_reference='Rules file section 2',
         transition='game_state:_Game._new_quarter',
         citations=[(GAME, 'a quarter change inside a drive: the drive goes on'), (E1, 'FLIP_AFTER = (1, 3)')],
         positive=['test_e1_transitions.QuarterTransitions.test_q1_expiry_continues_the_series_without_a_kickoff',
                   'test_game_state.Clock.test_a_punt_that_expires_q1_keeps_the_receiving_team_and_its_spot'],
         adversarial=['test_e1_transitions.QuarterTransitions.test_no_drive_terminates_at_q1_or_q3_expiry'],
         status='modelled', note='The flip itself is e1_drive:flips_between; game_state carries the orientation.'),
    dict(id='R05', rule='The second-quarter expiry is the halftime: the first half ends, with no turnover on downs.',
         rulebook=dict(article='4-1-3 Article 3', status='verified',
                       quote='"Between the second and third periods, there shall be an intermission of 13 minutes."'),
         lp_reference='Rules file section 3',
         transition='game_state:quarter_end_kind',
         citations=[(GAME, "return 'halftime'"), (GAME, 'def quarter_end_kind')],
         positive=['test_e1_transitions.QuarterTransitions.test_q2_expiry_is_halftime_and_not_a_turnover_on_downs',
                   'test_game_state.HalfStart.test_halftime_ends_the_first_half_and_the_second_half_kickoff_is_generated'],
         adversarial=['test_game_state.Clock.test_a_score_that_expires_the_half_is_followed_by_the_second_half_kickoff_only'],
         status='modelled', note='The rulebook text for "the first-half drive does not cross halftime" is not read.'),
    dict(id='R06', rule='Four 15-minute periods. The fourth-quarter expiry ends regulation.',
         rulebook=dict(article='4-1-1 Article 1', status='verified', quote='"divided into four periods of 15 minutes each"'),
         lp_reference='Rules file section 7 (clock row)',
         transition='game_state:quarter_end_kind',
         citations=[(GAME, "return 'regulation_end'")],
         positive=['test_e1_transitions.QuarterTransitions.test_q4_expiry_is_regulation_end'],
         adversarial=['test_game_state.ScopedOut.test_a_tied_regulation_game_is_scoped_out_as_overtime'],
         status='modelled', note=''),
    dict(id='R07', rule='A regulation tie goes to overtime, a 10-minute extra period. The engine blocks the game as overtime_not_modelled.',
         rulebook=dict(article='Overtime procedures, Section 1, Article 3 (rule number not printed in the extraction)', status='verified',
                       quote='"an extra period of 10 minutes shall commence"'),
         lp_reference='Rules file section 7 (overtime row, Rule 16)',
         transition='game_state:scope_out_reasons',
         citations=[(GAME, 'overtime_not_modelled')],
         positive=['test_game_state.ScopedOut.test_a_tied_regulation_game_is_scoped_out_as_overtime'],
         adversarial=[],
         status='guard', note='GAP: no test that validate_game refuses a tied record marked complete. The guard is the block itself.'),
    dict(id='R08', rule='Touchdown is 6 points. The try after it is 1 point (kick) or 2 points (conversion). Scoring team kicks off.',
         rulebook=dict(article='Rule 11, Section 1, Article 2 (TYPES OF SCORING PLAYS)', status='verified',
                       quote='"(a) Touchdown: 6 points" and "(d) Try after touchdown: 1 point (field goal or safety) or 2 points (touchdown)"'),
         lp_reference='Rules file section 7 (scoring row)',
         transition='game_state:_try_after_touchdown',
         citations=[(GAME, 'def _try_after_touchdown'), (GAME, 'def try_record')],
         positive=['test_game_state.Scoring.test_a_touchdown_takes_its_try_then_the_scoring_team_kicks_off',
                   'test_game_state.Scoring.test_a_two_point_try_scores_eight_when_it_is_chosen_and_made'],
         adversarial=['test_game_state.Scoring.test_a_missed_extra_point_scores_six',
                      'test_game_state.TryPublisherField.test_an_epa_style_success_flag_in_a_try_is_rejected'],
         status='modelled', note=''),
    dict(id='R09', rule='A field goal is worth 3 points.',
         rulebook=dict(article='Rule 11, Section 1, Article 2', status='verified', quote='"(b) Field goal: 3 points"'),
         lp_reference='Rules file section 7 (scoring row)',
         transition='game_state:_Game._drive_body',
         citations=[(GAME, "elif terminal == 'field_goal_attempt':")],
         positive=['test_game_state.TryPublisherField.test_a_made_field_goal_scores_three_and_the_kicker_kicks_off'],
         adversarial=['test_game_state.Validators.test_a_touchdown_whose_points_disagree_with_its_try_is_refused',
                      'test_game_state.RulesMatrix.test_a_points_total_that_disagrees_with_the_drives_is_a_failure'],
         status='modelled', note='The validator refuses points that disagree with the drives; the adversarial test for a field goal is the points-total check.'),
    dict(id='R10', rule='A safety is worth 2 points.',
         rulebook=dict(article='Rule 11, Section 1, Article 2', status='verified', quote='"(c) Safety: 2 points"'),
         lp_reference='Rules file section 7 (scoring row)',
         transition='game_state:_Game._drive_body',
         citations=[(GAME, 'SAFETY_POINTS = 2')],
         positive=[],
         adversarial=[],
         status='modelled', note='GAP: the safety is a terminal in E1 (e1_drive) and a constant in game_state; no test covers a game-level safety.'),
    dict(id='R11', rule='A missed field goal: the receiving team takes the ball at the spot of the kick, or at its own 20 when the kick spot is inside its 20.',
         rulebook=dict(article='11-4-2 Article 2 (a) and (b)', status='verified',
                       quote='"(a) If the spot of the kick was inside the receivers\' 20-yard line, it is the receivers\' ball at the 20-yard line; or (b) ... at the spot of the kick."'),
         lp_reference='Rules file section 4 and the review note cited by the engine',
         transition='game_state:missed_field_goal_spot',
         citations=[(GAME, 'Review note, Rule 11-4-2'), ('rules_matrix.py', 'Rule 11-4-2'), (GAME, 'def missed_field_goal_spot')],
         positive=['test_game_state.MissedFieldGoalSpot.test_the_spot_of_the_kick_when_it_is_outside_the_receivers_20',
                   'test_game_state.MissedFieldGoalSpot.test_the_receivers_own_20_when_the_kick_spot_is_inside_its_20'],
         adversarial=['test_game_state.MissedFieldGoalSpot.test_the_matrix_rejects_the_snap_based_value_for_a_kick_from_the_21',
                      'test_game_state.MissedFieldGoalSpot.test_the_matrix_rejects_a_next_drive_at_the_kick_spot_inside_the_20'],
         status='modelled',
         note='The engine docstring says the rulebook text is not in the repository; the text is now verified. Not modelled: '
              '11-4-2 exceptions (1) and (2), where the receivers touch the ball beyond the line of scrimmage.'),
    dict(id='R12', rule='The holder and kicker stand seven or more yards behind the line of scrimmage. The engine places the kick at the snap yardline plus HOLDER_OFFSET.',
         rulebook=dict(article='Section 17 KICKS, Article 7(b)', status='verified',
                       quote='"a potential holder and potential kicker seven or more yards behind the neutral zone"'),
         lp_reference='Rules file section 7 (kick-spot row)',
         transition='game_state:kick_spot_yardline_100',
         citations=[(GAME, 'HOLDER_OFFSET = 7'), (GAME, 'def kick_spot_yardline_100')],
         positive=['test_game_state.MissedFieldGoalSpot.test_the_engine_snap_and_kick_spot_differ_and_the_receiver_starts_at_the_kick_spot_rule'],
         adversarial=['test_game_state.MissedFieldGoalSpot.test_the_20_exception_applies_to_the_kick_spot_not_the_snap'],
         status='modelled',
         note='DISAGREEMENT, one place. The rule minimum is 7. The engine implies kick_distance = yardline_100 + 17 (holder 7 + end line 10, '
              'Rule 3, Section 11, Article 2). The publisher kick_distance is yardline_100 + 18 on most field-goal rows (see the '
              'kick_distance_offset block below). The engine keeps 7, and the publisher offset is kept as the reference.'),
    dict(id='R13', rule='A made field goal runs off at most five seconds of game clock.',
         rulebook=dict(article='11-4-2 Field Goal Attempt Notes (5)', status='verified',
                       quote='"For a successful field goal ... the maximum amount of time that can run off the game clock is five seconds."'),
         lp_reference='Rules file section 7 (clock row)',
         transition='game_state:_Game._charge_made_kick',
         citations=[(GAME, 'def _charge_made_kick'), (GAME, 'KICK_DURATION_SECONDS = 5'),
                    ('rules_matrix.py', 'Field goal made: the kick takes at most five seconds of clock')],
         positive=['test_game_state.FiveSecondKick.test_a_made_kick_with_a_long_observed_runoff_is_charged_five_seconds',
                   'test_game_state.FiveSecondKick.test_the_kickoff_after_a_made_kick_starts_from_the_charged_clock'],
         adversarial=['test_game_state.FiveSecondKick.test_the_matrix_rejects_a_made_kick_charged_over_five_seconds',
                      'test_game_state.FiveSecondKick.test_a_missed_kick_keeps_its_observed_runoff'],
         status='modelled',
         note='The rule\'s cap also covers unsuccessful kicks that do not land in the field of play; the engine applies the cap to made kicks '
              'only. A missed kick keeps its observed runoff, pinned by the adversarial test.'),
    dict(id='R14', rule='Three charged team timeouts per half. The count resets at halftime.',
         rulebook=dict(article='4-5-1 Item 1', status='verified',
                       quote='"A team is allowed three charged team timeouts during each half"'),
         lp_reference='Rules file section 7 (timeouts row)',
         transition='game_state:_Game._apply_timeouts',
         citations=[(GAME, 'def _apply_timeouts'), (GAME, 'no timeout is drawn')],
         positive=['test_game_state.TimeoutCharges.test_flags_charge_at_most_three_per_half_and_reset_at_halftime',
                   'test_game_state.TimeoutTransition.test_a_timeout_changes_the_counts_and_nothing_on_the_clock'],
         adversarial=['test_game_state.Guards.test_a_record_without_the_timeout_guard_is_rejected',
                      'test_game_state.TimeoutTransition.test_the_count_is_written_once_in_state_after_and_only_for_the_charged_side'],
         status='guard',
         note='Timeouts are charged from flags only; no timeout is drawn from the table, so the count is observed, not sampled.'),
    dict(id='R15', rule='The two-minute warning: the referee signals it, and the clock stops, at 2:00 in the second and fourth quarters.',
         rulebook=dict(article='4-4 (item h); definition Rule 3, Section 41', status='verified',
                       quote='"when the Referee signals the two-minute warning for a half"'),
         lp_reference='Rules file section 5 (two_minute_warning substate)',
         transition='game_state:unmodelled_transitions',
         citations=[(GAME, 'no two-minute stoppage is modelled')],
         positive=['test_game_state.UnmodelledTransitions.test_a_two_minute_crossing_is_listed_in_the_record',
                   'test_game_state.Guards.test_every_unmodelled_rule_carries_a_guard_and_is_never_pass'],
         adversarial=['test_legality.UnmodelledNegatives.test_the_two_minute_crossing_is_derived_from_the_plays_not_the_records_own_list',
                      'test_legality.ScopeGuard.test_the_successor_seed_one_is_not_a_legal_complete_game_because_of_the_two_minute_crossing'],
         status='guard', note='Not modelled: the warning stoppage. The sampled runoff is not checked for it.'),
    dict(id='R16', rule='Penalties and their enforcement.',
         rulebook=dict(article='Rule 14 (per LP reference); article text not read', status='not verified', quote=''),
         lp_reference='Rules file section 7 (overtime/penalty row)',
         transition='game_state:_Game._drive_body',
         citations=[(GAME, 'penalty_not_modelled')],
         positive=['test_game_state.UnmodelledTransitions.test_a_sampled_penalty_blocks_the_game_and_is_not_completed'],
         adversarial=['test_legality.UnmodelledNegatives.test_a_penalty_transition_cannot_pass_as_a_legal_complete_game'],
         status='guard', note='Penalty plays are excluded from the E1 pool by construction (e1_drive build_pool). ' + NOT_VERIFIED + '.'),
    dict(id='R17', rule='Turnover on downs: the other team takes over at the same dead-ball spot, field position complemented.',
         rulebook=dict(article='not read', status='not verified', quote=''),
         lp_reference='Rules file section 4 (coordinate invariant)',
         transition='e1_drive:classify',
         citations=[(E1, 'def classify')],
         positive=['test_e1_transitions.Reducer.test_turnover_on_downs_complements_field_position'],
         adversarial=['test_e1_transitions.Reducer.test_unknown_event_is_refused'],
         status='modelled', note=NOT_VERIFIED + '.'),
    dict(id='R18', rule='Punt: the receiving team takes the ball at the spot of the punt\'s receipt.',
         rulebook=dict(article='not read', status='not verified', quote=''),
         lp_reference='Rules file section 5 (terminal vocabulary)',
         transition='e1_drive:classify',
         citations=[(E1, 'def classify')],
         positive=['test_e1_transitions.Reducer.test_punt_gives_the_receiving_spot'],
         adversarial=['test_e1_transitions.Reducer.test_field_goal_attempt_has_no_result_and_no_next_spot'],
         status='modelled', note=NOT_VERIFIED + '.'),
    dict(id='R19', rule='The restart after a score or a quarter-end score: kickoff timing and the next quarter.',
         rulebook=dict(article='not read', status='not verified', quote=''),
         lp_reference='Rules file section 5 (provisional clock rules)',
         transition='game_state:_Game._new_quarter',
         citations=[(GAME, 'PRACTICE_SOURCE'), (GAME, "PENDING_2026 = 'pending_2026_rulebook'")],
         positive=['test_game_state.ProvisionalIsNeverPass.test_a_score_that_expires_q1_marks_its_rows_provisional'],
         adversarial=['test_game_state.Clock.test_a_touchdown_on_the_last_play_of_q1_kicks_off_to_open_q2'],
         status='provisional', note='PROVISIONAL: practice-sourced and marked so in the record. ' + NOT_VERIFIED + '.'),
    dict(id='R20', rule='Direction convention: the offense attacks x=100 or x=0. los = 100 - yardline_100 for dir +1.',
         rulebook=dict(article='none: LP representation convention', status='not applicable', quote=''),
         lp_reference='Rules file section 4',
         transition='game_state:CoinTossLedger.attacks_x100',
         citations=[(GAME, 'def attacks_x100')],
         positive=['test_game_state.Ledger.test_second_half_first_choice_follows_the_deferral'],
         adversarial=[],
         status='representation', note='GAP: no test isolates attacks_x100 directly. A representation convention, not a rulebook article.'),
]


def resolve(dotted, module_name):
    mod = importlib.import_module(module_name)
    obj = mod
    for part in dotted.split('.'):
        obj = getattr(obj, part)
    return obj


def check_test_id(tid):
    """test_<module>.<Class>.<method>: the module is imported and the method must be a unittest test on that class."""
    module_name, cls_name, method = tid.split('.')
    cls = getattr(importlib.import_module(module_name), cls_name)
    return issubclass(cls, unittest.TestCase) and callable(getattr(cls, method, None)) and method.startswith('test_')


def find_citation(file_name, snippet):
    """Line numbers where the snippet occurs in a cited engine file. Every cited file lives in scripts/nfl_sequence."""
    lines = (NFL / file_name).read_text().splitlines()
    hits = [i + 1 for i, line in enumerate(lines) if snippet in line]
    return {'file': file_name, 'snippet': snippet, 'lines': hits}


def build_checks():
    problems, resolved = [], {'transitions': 0, 'tests': 0, 'citations': 0}
    for row in ROWS:
        module_name, dotted = row['transition'].split(':')
        try:
            resolve(dotted, module_name)
            resolved['transitions'] += 1
        except AttributeError as err:
            problems.append(f"{row['id']}: transition {row['transition']} does not resolve ({err})")
        for tid in row['positive'] + row['adversarial']:
            try:
                if check_test_id(tid):
                    resolved['tests'] += 1
                else:
                    problems.append(f"{row['id']}: {tid} is not a test method")
            except (AttributeError, ImportError, ValueError) as err:
                problems.append(f"{row['id']}: {tid} does not resolve ({err})")
        for file_rel, snippet in row['citations']:
            found = find_citation(file_rel, snippet)
            if not found['lines']:
                problems.append(f"{row['id']}: citation {snippet!r} not found in {found['file']}")
            else:
                resolved['citations'] += 1
            row.setdefault('located', []).append(found)
        row['gaps'] = []
        if not row['positive']:
            row['gaps'].append('GAP: no positive test')
        if not row['adversarial']:
            row['gaps'].append('GAP: no adversarial test')
    return problems, resolved


def lp_reference_blob():
    out = subprocess.run(['git', '-C', str(ROOT), 'rev-parse', 'origin/dev:docs/rules/NFL-2026-GAME-STATE-RULES.md'],
                         capture_output=True, text=True)
    commit = subprocess.run(['git', '-C', str(ROOT), 'rev-parse', 'origin/dev'], capture_output=True, text=True).stdout.strip()
    return {'origin_dev_head': commit, 'blob': out.stdout.strip() or 'not found'}


def render_md(problems, resolved, kick):
    gaps = [(r['id'], g) for r in ROWS for g in r['gaps']]
    lines = [
        '# E2 successor: rule traceability matrix (2026-10-24)', '',
        f'Engine: successor branch. Generator: `scripts/nfl_sequence/evidence_e2/traceability.py`. Rows: {len(ROWS)}.', '',
        '## Rulebook source', '',
        f"- {RULEBOOK['title']}: {RULEBOOK['pdf']}",
        f"- Page: {RULEBOOK['page']}",
        f"- SHA-256 of the PDF: `{RULEBOOK['sha256']}`, {RULEBOOK['pages']} pages, retrieved {RULEBOOK['retrieved']}.",
        f"- Extraction: {RULEBOOK['extraction']}.",
        f"- LP reference: {LP_REFERENCE}. Blob: `{lp_reference_blob()['blob']}` at origin/dev `{lp_reference_blob()['origin_dev_head'][:12]}`.",
        '- Status values: **verified** (article text read in the PDF, quote given); **not verified** (no rulebook text read, code '
        'citation only); **not applicable** (LP representation); **policy** (LP restriction the rulebook does not impose).',
        '', '## Checks on this build', '',
        f"- Transitions resolved: {resolved['transitions']} of {len(ROWS)}. Test methods resolved: {resolved['tests']}. "
        f"Code citations found: {resolved['citations']}.",
        f"- Problems: {len(problems)}" + (': ' + '; '.join(problems) if problems else '.'),
        f"- Gaps (rows missing a positive or an adversarial test): {len(gaps)}.", '',
        '## Matrix', '',
        '| id | rule | rulebook article and status | reducer transition | positive tests | adversarial tests | status | note |',
        '|---|---|---|---|---|---|---|---|',
    ]
    for r in ROWS:
        rb = f"{r['rulebook']['article']}: {r['rulebook']['status']}"
        pos = '<br>'.join(f'`{t}`' for t in r['positive']) or '**GAP**'
        adv = '<br>'.join(f'`{t}`' for t in r['adversarial']) or '**GAP**'
        note = (r['note'] + (' ' + ' '.join(r['gaps']) if r['gaps'] else '')).strip()
        lines.append(f"| {r['id']} | {r['rule']} | {rb} | `{r['transition']}` | {pos} | {adv} | {r['status']} | {note} |")
    lines += ['', '## Kick distance (R12, the one place this disagreement is written)', '',
              f"Publisher `kick_distance - yardline_100` on {kick['field_goal_rows_with_both_fields']} field-goal rows "
              f"(`kick-distance-offset.json`, source sha `{kick['source']['sha256'][:12]}`):", '',
              '| offset | rows | share |', '|---:|---:|---:|']
    for k, v in kick['offset_counts'].items():
        lines.append(f"| {k} | {v} | {v / kick['field_goal_rows_with_both_fields']:.1%} |")
    lines += ['', f"The engine implies +{kick['engine']['implied_kick_distance_offset']} (holder {kick['engine']['holder_offset']} + end line "
              f"{kick['engine']['endzone_depth']}). It matches {kick['share_at_engine_offset']:.1%} of rows. The modal offset "
              f"+{kick['modal_offset']} implies a holder {kick['holder_offset_implied_by_modal']} yards back, which the rule allows. "
              'The engine keeps 7 and documents this here; the publisher offset is kept as the reference.', '',
              '## Gaps', ''] + ([f'- {rid}: {g}' for rid, g in gaps] or ['- none']) + ['']
    return '\n'.join(lines)


def main():
    problems, resolved = build_checks()
    kick = json.loads(KICK_JSON.read_text())
    out = {'rulebook': RULEBOOK, 'lp_reference': {'path': LP_REFERENCE, **lp_reference_blob()},
           'checks': {'problems': problems, 'resolved': resolved}, 'rows': ROWS,
           'kick_distance': {'file': 'kick-distance-offset.json', 'offset_counts': kick['offset_counts'],
                             'share_at_engine_offset': kick['share_at_engine_offset'],
                             'modal_offset': kick['modal_offset']}}
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / 'RULE-TRACEABILITY-MATRIX-2026-10-24.json').write_text(json.dumps(out, indent=1, sort_keys=True, default=str) + '\n')
    (OUT / 'RULE-TRACEABILITY-MATRIX-2026-10-24.md').write_text(render_md(problems, resolved, kick))
    print(f"rows {len(ROWS)}, transitions {resolved['transitions']}, tests {resolved['tests']}, "
          f"citations {resolved['citations']}, problems {len(problems)}")
    if problems:
        for p in problems:
            print('PROBLEM', p)
        raise SystemExit(1)


if __name__ == '__main__':
    main()
