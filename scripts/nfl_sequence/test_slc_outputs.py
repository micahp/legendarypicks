import copy
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import slc_outputs as outputs  # noqa: E402
import game_stats  # noqa: E402


def roster_player(gsis_id, name, team, position):
    return {'gsis_id': gsis_id, 'player_id': int(gsis_id[-1]), 'player_name': name,
            'team': team, 'pos_abb': position, 'pos_rank': 1, 'starter': True,
            'roster_eligible': True}


SNAPSHOT = {
    'as_of': '2026-10-09T10:00:00Z',
    'snapshot_sha256': 'e' * 64,
    'schedule': {'game_id': '2026_05_AAA_BBB', 'home_team': 'AAA', 'away_team': 'BBB'},
    'rosters': {
        'home': {'team': 'AAA', 'players': [roster_player('GA1', 'Home QB', 'AAA', 'QB'),
                                            roster_player('GA2', 'Home WR', 'AAA', 'WR'),
                                            roster_player('GA3', 'Home RB', 'AAA', 'RB')]},
        'away': {'team': 'BBB', 'players': [roster_player('GB1', 'Away QB', 'BBB', 'QB'),
                                            roster_player('GB2', 'Away WR', 'BBB', 'WR')]},
    },
}
PROFILE = {'profile': 'v1_full_stack', 'model_id': 'SLC_v1_full_stack', 'configuration_hash': 'f' * 64,
           'evaluation_class': 'retrospective_archive_reconstruction', 'prospective': False,
           'enabled_layers': {'score_clock_playcalling': True, 'dirichlet_player_target_carry_shares': True}}


def game_record(home_points=24, away_points=17):
    return {
        'valid_full_game': True, 'complete_game': True, 'status': 'complete', 'points': {'A': home_points, 'B': away_points},
        'drives': [
            {'offense_team': 'A', 'terminal': 'touchdown', 'field_goal_made': None,
             'plays': [{'state_before': {'yardline_100': 12}}]},
            {'offense_team': 'B', 'terminal': 'punt', 'field_goal_made': None,
             'plays': [{'state_before': {'yardline_100': 40}}]},
        ],
        'stats': {
            'player_attribution': 'pre_event_selection',
            'team': {
                'A': {'points': home_points, 'touchdowns': 1, 'offensive_touchdowns': 1,
                      'observed_overtime_touchdowns': 0, 'drives': 1,
                      'possession_seconds': 1300, 'drive_window_seconds': 1300,
                      'plays': 1, 'rush_att': 0, 'rush_yds': 0,
                      'pass_att': 1, 'pass_comp': 1, 'pass_yds': 10, 'interceptions': 0,
                      'pass_tgt': 1, 'sacks_taken': 0, 'sack_yds': 0, 'punts': 0,
                      'fg_att': 0, 'fg_made': 0, 'turnovers': 0, 'fumbles_lost': 0,
                      'turnovers_on_downs': 0},
                'B': {'points': away_points, 'touchdowns': 0, 'offensive_touchdowns': 0,
                      'observed_overtime_touchdowns': 0, 'drives': 1,
                      'possession_seconds': 1200, 'drive_window_seconds': 1200,
                      'plays': 0, 'rush_att': 0, 'rush_yds': 0,
                      'pass_att': 0, 'pass_comp': 0, 'pass_yds': 0, 'interceptions': 0,
                      'pass_tgt': 0, 'sacks_taken': 0, 'sack_yds': 0, 'punts': 1,
                      'fg_att': 0, 'fg_made': 0, 'turnovers': 0, 'fumbles_lost': 0,
                      'turnovers_on_downs': 0},
            },
            'player': [
                {'player_id': 'GA1', 'player_name': 'Home QB', 'player_team': 'AAA', 'player_position': 'QB',
                 'player_side': 'A', 'attribution': 'pre_event_selection',
                 'passing': {'att': 1, 'comp': 1, 'yds': 10, 'td': 1, 'int': 0, 'sacked': 0, 'sack_yds': 0}},
                {'player_id': 'GA2', 'player_name': 'Home WR', 'player_team': 'AAA', 'player_position': 'WR',
                 'player_side': 'A', 'attribution': 'pre_event_selection',
                 'receiving': {'tgt': 1, 'rec': 1, 'yds': 10, 'td': 1}},
            ],
        },
    }


class BoxscoreSerialization(unittest.TestCase):
    def test_integrity_labels_and_lineup_check(self):
        outcome = {'complete_game': True, 'valid_full_game': False,
                   'playcall': {'lineup': {'AAA': {'player_snaps': {'GA2': 0}}}}}
        box = outputs.build_boxscore(1, outcome, game_record(), SNAPSHOT, PROFILE)
        self.assertEqual(box['status'], 'complete_unverified')
        self.assertEqual(box['teams'][0]['stats']['possession_seconds'], 1300)
        self.assertEqual(box['teams'][0]['stats']['drive_window_seconds'], 1300)
        self.assertIn('player_stats_exceed_snaps', box['reconciliation']['teams'][0]['mismatches'])
        self.assertEqual(box['teams'][0]['stats']['drive_terminals'], {'touchdown': 1})
        self.assertIn('throwaways', box['field_semantics']['targets'])

    def test_invalid_qb_rank_rejected(self):
        roster = copy.deepcopy(SNAPSHOT['rosters']['home'])
        roster['players'][0]['pos_rank'] = 'unknown'
        with self.assertRaisesRegex(ValueError, 'invalid QB depth rank'):
            outputs._depth_chart_qb1(roster)

    def test_missing_touchdown_scorer_rejected(self):
        drive = {'offense_team': 'A', 'quarter_start': 1, 'clock_start': 900,
                 'end_quarter': 1, 'end_clock': 890, 'plays': [],
                 'terminal': 'touchdown', 'field_goal_made': None}
        with self.assertRaisesRegex(ValueError, 'touchdown_scored_by'):
            game_stats.team_stats([drive], {})

    def test_red_zone_missed_kick_is_not_made(self):
        drive = {'offense_team': 'A', 'terminal': 'field_goal', 'field_goal_made': False,
                 'plays': [{'state_before': {'yardline_100': 15}}]}
        zone = outputs._red_zone_diagnostics({'drives': [drive]})['A']
        self.assertEqual(zone['red_zone_field_goal_attempts'], 1)
        self.assertEqual(zone['red_zone_field_goals'], 0)
        self.assertEqual(zone['red_zone_field_goals_made'], 0)

    def test_invalid_clock_is_unknown(self):
        self.assertIsNone(outputs._play_period_seconds(
            {'state_before': {'quarter': 1, 'clock_seconds': 'bad'},
             'state_after': {'quarter': 1, 'clock_seconds': 10}}, 'Q1'))
        self.assertIsNone(outputs._period_time(1, 901))

    def test_clock_and_score_components(self):
        drive = {'offense_team': 'A', 'quarter_start': 1, 'clock_start': 900,
                 'end_quarter': 1, 'end_clock': 890, 'plays': [],
                 'terminal': 'touchdown', 'touchdown_scored_by': 'B',
                 'field_goal_made': None,
                 'points_scored_on_drive': {'team': 'B', 'points': 8, 'try': {'kind': 'two', 'made': True}}}
        stats = game_stats.team_stats([drive], {'A': 0, 'B': 8})
        self.assertEqual(stats['A']['drive_terminal_touchdown'], 1)
        self.assertEqual(stats['B']['touchdown_points'], 6)
        self.assertEqual(stats['B']['try_points'], 2)
        self.assertEqual(stats['B']['score_ledger_points'], 8)
        self.assertEqual(outputs._period_time(5, 600), 3600)
        self.assertEqual(outputs._period_time(5, 0), 4200)

    def test_quarter_invalid_end_period_and_clock_marks_incomplete(self):
        drive = {'offense_team': 'A', 'quarter_start': 1, 'clock_start': 900,
                 'end_quarter': 'bad', 'end_clock': 0, 'terminal': 'punt', 'field_goal_made': None,
                 'plays': [{'event_type': 'punt', 'participants': {},
                    'outcome': {'yards_gained': 0, 'turnover': False, 'punt': True, 'touchdown': False},
                    'state_before': {'quarter': 1, 'clock_seconds': 30},
                    'state_after': {'quarter': 1, 'clock_seconds': 'bad'}}]}
        quarter = outputs._quarter_by_quarter({'points': {'A': 0, 'B': 0}, 'drives': [drive]}, SNAPSHOT)
        self.assertFalse(quarter['complete'])
        self.assertFalse(quarter['play_stats_complete_by_period']['Q1'])
        self.assertIsNone(quarter['team_stats']['AAA']['Q1']['recorded_play_clock_seconds'])

    def test_missing_role_yardage_is_counted(self):
        play = {'event_type': 'run', 'participants': {'rusher_id': 'GA3'},
                'outcome': {'yards_gained': 4, 'touchdown': False, 'turnover': False},
                'state_before': {'yardline_100': 50}}
        drive = {'offense_team': 'A', 'quarter_start': 1, 'clock_start': 900,
                 'end_quarter': 1, 'end_clock': 890, 'plays': [play],
                 'terminal': 'punt', 'field_goal_made': None}
        stats = game_stats.compute([drive], {'A': 0, 'B': 0})
        self.assertEqual(stats['player_yardage_fallbacks']['rushing_yards'], 1)
        self.assertEqual(stats['player'][0]['rushing']['yds'], 4)
        play['participants']['sampled_play_context'] = {'rushing_yards': 3}
        stats = game_stats.compute([drive], {'A': 0, 'B': 0})
        self.assertEqual(stats['player_yardage_fallbacks']['rushing_yards'], 0)
        self.assertEqual(stats['player'][0]['rushing']['yds'], 3)

    def test_score_components_are_unknown_when_ledger_is_incomplete(self):
        record = game_record()
        record['stats']['player_yardage_fallbacks'] = {}
        record['stats']['team']['A']['score_ledger_points'] = 7
        record['stats']['team']['A']['other_score_points'] = 0
        box = outputs.build_boxscore(1, {'complete_game': True}, record, SNAPSHOT, PROFILE)
        home = box['teams'][0]['stats']
        self.assertEqual(home['score_ledger_points'], 7)
        self.assertIsNone(home['other_score_points'])
        self.assertIn('including field goals', box['field_semantics']['other_score_points'])
        self.assertIn('score_ledger_points', box['reconciliation']['teams'][0]['mismatches'])
        del record['stats']['team']['A']['score_ledger_points']
        box = outputs.build_boxscore(1, {'complete_game': True}, record, SNAPSHOT, PROFILE)
        self.assertIsNone(box['teams'][0]['stats']['score_ledger_points'])
        self.assertIn('score_components_unavailable', box['reconciliation']['teams'][0]['mismatches'])

    def test_raw_clock_semantics_and_player_distribution_attribution(self):
        stats = game_stats.compute([], {'A': 0, 'B': 0})
        self.assertIn('kickoffs', stats['team_stat_semantics']['possession_seconds'])
        box = outputs.build_boxscore(1, {'valid_full_game': True}, game_record(), SNAPSHOT, PROFILE)
        summary = outputs.aggregate_boxscores([box])
        player = next(p for p in summary['players'] if p['stable_player_id'] == 'GA1')
        self.assertEqual(player['attribution_modes'], ['pre_event_selection'])
        self.assertEqual(set(player['statistics']), {f'{category}.{field}'
                         for category, fields in outputs.PLAYER_FIELDS.items() for field in fields})
        self.assertIn('allocations', player['attribution_note'])

    def test_regular_punt_is_counted_even_when_punt_attempt_flag_is_false(self):
        drive = {
            'offense_team': 'A', 'quarter_start': 1, 'clock_start': 600,
            'end_quarter': 1, 'end_clock': 570, 'terminal': 'punt',
            'field_goal_made': None,
            'plays': [{
                'event_type': 'punt',
                'outcome': {'yards_gained': None, 'turnover': False, 'punt': True,
                            'punt_attempt': False, 'field_goal_attempt': False},
                'participants': {},
            }],
        }

        stats = game_stats.team_stats([drive], {'A': 0, 'B': 0})

        self.assertEqual(stats['A'].get('punts', 0), 1)

    def test_starter_metadata_uses_available_qb_depth_rank_and_preserves_unknown_roles(self):
        snapshot = copy.deepcopy(SNAPSHOT)
        for side in ('home', 'away'):
            for player in snapshot['rosters'][side]['players']:
                player.pop('starter', None)
        backup = roster_player('GA4', 'Home Backup QB', 'AAA', 'QB')
        backup.update({'pos_rank': 2})
        backup.pop('starter')
        snapshot['rosters']['home']['players'].append(backup)

        indexed = outputs._roster_index(snapshot)
        self.assertIs(indexed['GA1']['starter'], True)
        self.assertEqual(indexed['GA1']['starter_basis'], 'depth_chart_rank_and_availability')
        self.assertIs(indexed['GA4']['starter'], False)
        self.assertIsNone(indexed['GA2']['starter'])
        self.assertEqual(indexed['GA2']['starter_basis'], 'unknown')

        snapshot['rosters']['home']['injury_report'] = {
            'available': True, 'players': [{'gsis_id': 'GA1', 'report_status': 'Out'}]}
        indexed = outputs._roster_index(snapshot)
        self.assertIs(indexed['GA1']['starter'], False)
        self.assertIs(indexed['GA4']['starter'], True)

    def test_full_stack_record_is_versioned_reconciled_and_includes_rostered_zeros(self):
        outcome = {'seed': 1, 'status': 'complete', 'valid_full_game': True,
                   'complete_game': True, 'tied_at_regulation_end': False}
        box = outputs.build_boxscore(1, outcome, game_record(), SNAPSHOT, PROFILE,
                                     {'classification': 'retrospective_archive_reconstruction', 'prospective': False})
        self.assertEqual(box['schema'], outputs.BOX_SCHEMA)
        self.assertEqual(box['status'], 'valid_complete')
        self.assertEqual(box['reconciliation']['status'], 'passed')
        self.assertEqual(box['evaluation_class'], 'retrospective_archive_reconstruction')
        self.assertFalse(box['prospective'])
        zero = next(player for player in box['players'] if player['stable_player_id'] == 'GA3')
        self.assertEqual(zero['rushing'], {'att': 0, 'yds': 0, 'td': 0})
        self.assertEqual(zero['receiving']['tgt'], 0)
        self.assertEqual(len(box['players']), 5)
        self.assertIn('quarter_by_quarter', box)

    def test_v2_output_contract_rejects_valid_game_without_play_metrics(self):
        v2_profile = dict(PROFILE, output_contract={'require_play_metrics': True})
        box = outputs.build_boxscore(
            1, {'seed': 1, 'status': 'complete', 'valid_full_game': True},
            game_record(), SNAPSHOT, v2_profile)
        self.assertEqual(box['reconciliation']['status'], 'failed')
        self.assertTrue(box['reconciliation']['strict'])
        mismatches = box['reconciliation']['teams'][0]['mismatches']
        self.assertIn('clock_reconciliation', mismatches)
        self.assertIn('down_play_count', mismatches)

    def test_quarter_boxscore_attributes_cross_period_drive_stats_and_points(self):
        def play(event, quarter, yards, *, touchdown=False, rusher=None, passer=None, receiver=None):
            participants = {
                'rusher_id': rusher, 'rusher_name': 'Home RB' if rusher else None,
                'rusher_position': 'RB' if rusher else None, 'rusher_team': 'AAA' if rusher else None,
                'rusher_side': 'A' if rusher else None,
                'passer_id': passer, 'passer_name': 'Home QB' if passer else None,
                'passer_position': 'QB' if passer else None, 'passer_team': 'AAA' if passer else None,
                'passer_side': 'A' if passer else None,
                'receiver_id': receiver, 'receiver_name': 'Home WR' if receiver else None,
                'receiver_position': 'WR' if receiver else None, 'receiver_team': 'AAA' if receiver else None,
                'receiver_side': 'A' if receiver else None,
                'attribution': 'pre_event_selection', 'sampled_play_context': {},
            }
            return {
                'event_type': event,
                'state_before': {'quarter': quarter, 'clock_seconds': 30, 'yardline_100': 10},
                'state_after': {'quarter': quarter, 'clock_seconds': 25, 'yardline_100': 10 - yards},
                'outcome': {'yards_gained': yards, 'touchdown': touchdown, 'safety': False,
                            'turnover': False, 'punt': False},
                'participants': participants,
            }

        record = {
            'points': {'A': 7, 'B': 0},
            'drives': [{
                'index': 1, 'offense_team': 'A', 'quarter_start': 1, 'clock_start': 40,
                'end_quarter': 2, 'end_clock': 20, 'terminal': 'touchdown',
                'touchdown_scored_by': 'A', 'field_goal_made': None,
                'points_scored_on_drive': {'team': 'A', 'points': 7, 'try': {'kind': 'kick', 'made': True}},
                'plays': [play('run', 1, 5, rusher='GA3'),
                          play('pass_complete', 2, 5, touchdown=True, passer='GA1', receiver='GA2')],
            }],
        }

        quarterly = outputs._quarter_by_quarter(record, SNAPSHOT)

        self.assertEqual(quarterly['schema'], 'lp-nfl-slc-quarter-boxscore-3')
        self.assertTrue(quarterly['complete'])
        self.assertEqual(quarterly['points_by_team']['AAA']['Q2'], 7)
        self.assertEqual(quarterly['points_by_team']['AAA']['Q1'], 0)
        self.assertEqual(quarterly['team_stats']['AAA']['Q1']['rush_attempts'], 1)
        self.assertEqual(quarterly['team_stats']['AAA']['Q1']['rushing_yards'], 5)
        self.assertEqual(quarterly['team_stats']['AAA']['Q1']['possession_seconds'], 5)
        self.assertEqual(quarterly['team_stats']['AAA']['Q1']['drive_window_seconds'], 40)
        self.assertEqual(quarterly['team_stats']['AAA']['Q1']['recorded_play_clock_seconds'], 5)
        self.assertEqual(quarterly['team_stats']['AAA']['Q2']['completions'], 1)
        self.assertEqual(quarterly['drive_summary_count_semantics']['plays'],
                         'recorded_play_events_including_punts_and_field_goal_attempts')
        self.assertEqual(quarterly['drive_summary_count_semantics']['team_stats.plays'],
                         'scrimmage_snaps_excluding_special_teams')
        self.assertEqual(quarterly['player_stats']['Q1'][0]['stable_player_id'], 'GA3')
        self.assertEqual(quarterly['player_stats']['Q2'][0]['stable_player_id'], 'GA1')
        drive = quarterly['drive_summaries'][0]
        self.assertEqual((drive['start_period'], drive['end_period'], drive['scoring_period']), ('Q1', 'Q2', 'Q2'))
        self.assertEqual(quarterly['drive_summary_by_team_and_period']['AAA']['Q1']['drives_started'], 1)
        self.assertEqual(quarterly['drive_summary_by_team_and_period']['AAA']['Q2']['drives_ended'], 1)

    def test_no_play_overtime_score_is_assigned_to_ot_team_boxscore(self):
        record = {
            'points': {'A': 6, 'B': 0},
            'drives': [{
                'index': 1, 'offense_team': 'A', 'quarter_start': 5, 'clock_start': 600,
                'end_quarter': 5, 'end_clock': 600, 'plays': [], 'terminal': 'touchdown',
                'touchdown_scored_by': 'A', 'observed_overtime_drive': {'outcome': 'touchdown'},
                'points_scored_on_drive': {'team': 'A', 'points': 6, 'try': None},
            }],
        }

        quarterly = outputs._quarter_by_quarter(record, SNAPSHOT)

        self.assertFalse(quarterly['complete'])
        self.assertTrue(quarterly['scoring_complete'])
        self.assertTrue(quarterly['play_stats_complete_by_period']['Q4'])
        self.assertFalse(quarterly['play_stats_complete_by_period']['OT'])
        self.assertEqual(quarterly['play_stats_incomplete_reasons']['OT'],
                         ['observed_overtime_drive_has_no_play_sequence'])
        self.assertEqual(quarterly['points_by_team']['AAA']['OT'], 6)
        self.assertEqual(quarterly['team_stats']['AAA']['OT']['touchdowns'], 1)
        self.assertEqual(quarterly['team_stats']['AAA']['OT']['offensive_touchdowns'], 1)
        self.assertEqual(quarterly['team_stats']['AAA']['OT']['observed_overtime_touchdowns'], 1)
        self.assertEqual(quarterly['drive_summaries'][0]['play_sequence_status'], 'not_modeled')

    def test_cross_period_drive_event_counts_include_kicks_without_double_counting(self):
        def play(event, quarter, yards, *, punt=False):
            return {
                'event_type': event,
                'state_before': {'quarter': quarter, 'clock_seconds': 100, 'yardline_100': 40},
                'state_after': {'quarter': quarter, 'clock_seconds': 95, 'yardline_100': 40 - yards},
                'outcome': {'yards_gained': yards, 'touchdown': False, 'safety': False,
                            'turnover': False, 'punt': punt, 'punt_attempt': False,
                            'field_goal_attempt': False},
                'participants': {'rusher_id': None},
            }

        record = {
            'points': {'A': 0, 'B': 0},
            'drives': [{
                'index': 1, 'offense_team': 'A', 'quarter_start': 1, 'clock_start': 100,
                'end_quarter': 2, 'end_clock': 95, 'terminal': 'punt', 'field_goal_made': None,
                'plays': [play('run', 1, 4), play('punt', 2, 0, punt=True)],
            }],
        }

        quarterly = outputs._quarter_by_quarter(record, SNAPSHOT)
        period_drive_plays = quarterly['drive_summary_by_team_and_period']['AAA']
        scrimmage_plays = quarterly['team_stats']['AAA']

        self.assertEqual(len(quarterly['drive_summaries']), 1)
        self.assertEqual(quarterly['drive_summaries'][0]['start_period'], 'Q1')
        self.assertEqual(quarterly['drive_summaries'][0]['end_period'], 'Q2')
        self.assertEqual(period_drive_plays['Q1']['plays'] + period_drive_plays['Q2']['plays'], 2)
        self.assertEqual(scrimmage_plays['Q1']['plays'], 1)
        self.assertEqual(scrimmage_plays['Q2']['plays'], 0)
        self.assertEqual(scrimmage_plays['Q2']['punts'], 1)

    def test_s0_comparison_boxscores_also_zero_fill_and_enforce_frozen_roster_identity(self):
        s0_profile = dict(PROFILE, profile='s0', model_id='S0', enabled_layers={})
        box = outputs.build_boxscore(1, {'valid_full_game': True}, game_record(), SNAPSHOT, s0_profile)
        self.assertEqual(len(box['players']), 5)
        self.assertEqual(box['reconciliation']['status'], 'passed')
        record = game_record()
        record['stats']['player'][0]['player_id'] = 'GZZ'
        with self.assertRaisesRegex(ValueError, 'not present on the frozen roster'):
            outputs.build_boxscore(1, {'valid_full_game': True}, record, SNAPSHOT, s0_profile)

    def test_player_not_on_frozen_roster_is_rejected_for_slc(self):
        record = game_record()
        record['stats']['player'][0]['player_id'] = 'GZZ'
        with self.assertRaisesRegex(ValueError, 'not present on the frozen roster'):
            outputs.build_boxscore(1, {'valid_full_game': True}, record, SNAPSHOT, PROFILE)

    def test_team_and_player_mismatch_is_reported_and_never_marked_reconciled(self):
        record = game_record()
        record['stats']['team']['A']['pass_yds'] = 11
        box = outputs.build_boxscore(1, {'valid_full_game': True}, record, SNAPSHOT, PROFILE)
        self.assertEqual(box['reconciliation']['status'], 'failed')
        self.assertIn('passing_yards', box['reconciliation']['teams'][0]['mismatches'])

    def test_passing_td_credit_is_not_counted_as_a_second_team_touchdown(self):
        record = game_record(31, 17)
        team = record['stats']['team']['A']
        team.update({'touchdowns': 3, 'offensive_touchdowns': 3, 'pass_att': 2,
                     'pass_comp': 2, 'pass_yds': 20, 'pass_tgt': 2,
                     'rush_att': 1, 'rush_yds': 5})
        quarterback, receiver = record['stats']['player']
        quarterback['passing'].update({'att': 2, 'comp': 2, 'yds': 20, 'td': 2})
        receiver['receiving'].update({'tgt': 2, 'rec': 2, 'yds': 20, 'td': 2})
        record['stats']['player'].append({
            'player_id': 'GA3', 'player_name': 'Home RB', 'player_team': 'AAA',
            'player_position': 'RB', 'player_side': 'A', 'attribution': 'pre_event_selection',
            'rushing': {'att': 1, 'yds': 5, 'td': 1},
        })

        box = outputs.build_boxscore(1, {'valid_full_game': True}, record, SNAPSHOT, PROFILE)

        self.assertEqual(box['reconciliation']['status'], 'passed')
        home = next(row for row in box['reconciliation']['teams'] if row['side'] == 'A')
        self.assertNotIn('offensive_touchdowns', home['mismatches'])

    def test_observed_no_play_overtime_touchdown_is_explicitly_unassigned(self):
        record = game_record()
        record['stats']['team']['A']['offensive_touchdowns'] = 2
        record['stats']['team']['A']['observed_overtime_touchdowns'] = 1
        box = outputs.build_boxscore(7, {'valid_full_game': True}, record, SNAPSHOT, PROFILE)
        self.assertEqual(box['status'], 'valid_complete')
        self.assertEqual(box['teams'][0]['stats']['offensive_touchdowns'], 2)
        self.assertEqual(box['teams'][0]['stats']['observed_overtime_touchdowns'], 1)
        self.assertEqual(box['reconciliation']['status'], 'passed')

        record['stats']['team']['A']['observed_overtime_touchdowns'] = 0
        invalid = outputs.build_boxscore(8, {'valid_full_game': True}, record, SNAPSHOT, PROFILE)
        self.assertEqual(invalid['reconciliation']['status'], 'failed')
        mismatch = invalid['reconciliation']['teams'][0]['mismatches']['offensive_touchdowns']
        self.assertEqual(mismatch['unassigned_observed_overtime'], 0)
        self.assertEqual(mismatch['reconciled_team_total'], 2)

    def test_duplicate_players_and_conflicting_roster_identities_fail(self):
        record = game_record()
        record['stats']['player'].append(dict(record['stats']['player'][0]))
        with self.assertRaisesRegex(ValueError, 'duplicate player box-score identity'):
            outputs.build_boxscore(1, {'valid_full_game': True}, record, SNAPSHOT, PROFILE)


class DistributionAggregation(unittest.TestCase):
    def test_pre_final_roster_snapshot_remains_in_valid_game_count(self):
        before = dict(SNAPSHOT, roster_finalization_timing={
            'status': 'before_roster_finalization', 'before_roster_finalization': True,
        })
        box = outputs.build_boxscore(1, {'valid_full_game': True}, game_record(), before, PROFILE)
        summary = outputs.aggregate_boxscores([box], requested_games=1)
        self.assertEqual(summary['valid_complete_games'], 1)
        self.assertEqual(summary['valid_complete_games_by_roster_finalization_timing'][
            'before_roster_finalization'], 1)

    def test_aggregate_uses_valid_unique_seeds_and_reports_player_zeroes(self):
        first = outputs.build_boxscore(1, {'valid_full_game': True}, game_record(24, 17), SNAPSHOT, PROFILE)
        second = outputs.build_boxscore(2, {'valid_full_game': True}, game_record(20, 10), SNAPSHOT, PROFILE)
        invalid = outputs.build_boxscore(3, {'valid_full_game': False, 'tied_at_regulation_end': True},
                                         game_record(7, 7), SNAPSHOT, PROFILE)
        duplicate = dict(second)
        duplicate['teams'] = [dict(line, stats=dict(line['stats'], points=30 if line['side'] == 'A' else 0))
                              for line in second['teams']]
        summary = outputs.aggregate_boxscores([first, second, invalid, duplicate], requested_games=3)
        self.assertEqual(summary['valid_complete_games'], 2)
        self.assertEqual(summary['duplicate_ledger_rows'], 1)
        self.assertEqual(summary['winner_probability']['home'], 1.0)
        home = next(row for row in summary['teams']['AAA'].values())
        self.assertEqual(home['sample_count'], 2)
        qb = next(row for row in summary['players'] if row['stable_player_id'] == 'GA1')
        self.assertEqual(qb['statistics']['passing.att']['sample_count'], 2)
        self.assertEqual(qb['statistics']['passing.att']['mean'], 1.0)
        rb = next(row for row in summary['players'] if row['stable_player_id'] == 'GA3')
        self.assertEqual(rb['statistics']['rushing.att']['probability_zero'], 1.0)

    def test_final_overtime_tie_is_aggregated_but_regulation_tie_is_not(self):
        regulation_tie = outputs.build_boxscore(
            1, {'valid_full_game': False, 'tied_at_regulation_end': True, 'status': 'blocked'},
            game_record(17, 17), SNAPSHOT, PROFILE)
        final_overtime_tie = outputs.build_boxscore(
            2, {'valid_full_game': True, 'tied_at_regulation_end': True, 'status': 'complete_overtime'},
            game_record(17, 17), SNAPSHOT, PROFILE)
        decisive = outputs.build_boxscore(
            3, {'valid_full_game': True, 'tied_at_regulation_end': False, 'status': 'complete_regulation'},
            game_record(24, 17), SNAPSHOT, PROFILE)
        boxes = [regulation_tie, final_overtime_tie, decisive]
        frozen_before_aggregation = copy.deepcopy(boxes)

        summary = outputs.aggregate_boxscores(boxes, requested_games=3)

        self.assertEqual(boxes, frozen_before_aggregation)
        self.assertEqual(summary['valid_complete_games'], 2)
        self.assertEqual(summary['status_counts']['regulation_tie'], 1)
        self.assertEqual(summary['winner_probability'], {'home': 0.5, 'away': 0.0, 'tie': 0.5})
        total_points = summary['game']['total_points']
        self.assertEqual(total_points['sample_count'], 2)
        self.assertEqual(total_points['histogram'], {'34': 1, '41': 1})
        decisive_games = [box for box in boxes if box['status'] == 'valid_complete'
                          and box['teams'][0]['stats']['points'] != box['teams'][1]['stats']['points']]
        self.assertEqual(len(decisive_games), 1)
        self.assertEqual(summary['coverage'], 2 / 3)

    def test_distribution_summary_has_stable_quantiles_and_exact_histogram(self):
        stat = outputs._distribution([0, 0, 10, 20])
        self.assertEqual(stat['sample_count'], 4)
        self.assertEqual(stat['mean'], 7.5)
        self.assertEqual(stat['probability_zero'], 0.5)
        self.assertEqual(stat['histogram'], {'0': 2, '10': 1, '20': 1})
        self.assertEqual(stat['quantiles']['p50'], 5)




class RosterEligibilityIsNotAssumed(unittest.TestCase):
    """A snapshot that never carried roster_eligible reports unknown, so the legality guard cannot be satisfied by default."""

    def test_a_missing_field_is_unknown_not_eligible(self):
        snapshot = copy.deepcopy(SNAPSHOT)
        for side in ('home', 'away'):
            for player in snapshot['rosters'][side]['players']:
                player.pop('roster_eligible')
        index = outputs._roster_index(snapshot)
        self.assertTrue(index)
        self.assertTrue(all(entry['roster_eligible'] is None for entry in index.values()))

    def test_an_explicit_false_is_kept_as_false(self):
        snapshot = copy.deepcopy(SNAPSHOT)
        snapshot['rosters']['home']['players'][1]['roster_eligible'] = False
        index = outputs._roster_index(snapshot)
        self.assertIs(index['GA2']['roster_eligible'], False)


class ClockReconciliation(unittest.TestCase):
    """Possession plus kickoff runoff must account for every elapsed game-clock second, or the game says so."""

    RECORDS = Path(__file__).resolve().parents[2] / 'docs/research/slc-sunday-rerun-2026-11-08/refusals-reproduced/refused-records'

    def record(self, name):
        import gzip
        import json
        return json.load(gzip.open(self.RECORDS / f'{name}.json.gz', 'rt'))

    def test_a_regulation_game_reconciles_to_the_clock_exactly(self):
        result = game_stats.clock_reconciliation(self.record('2026_09_HOU_LAC-seed9'))
        self.assertEqual(result['status'], 'reconciled')
        self.assertEqual(result['unassigned_seconds'], 0)
        self.assertEqual(result['elapsed_game_clock_seconds'], 3600)

    def test_a_game_with_a_gap_is_reported_unreconciled_not_forced(self):
        record = self.record('2026_09_LV_SF-seed23')
        self.assertEqual(game_stats.clock_reconciliation(record)['status'], 'reconciled')
        record['kickoffs'][1]['clock_after'] = 300  # the 313-second kickoff now charges 13 seconds the drives do not account for
        result = game_stats.clock_reconciliation(record)
        self.assertEqual(result['status'], 'unreconciled')
        self.assertFalse(result['regulation_only'])
        self.assertNotEqual(result['unassigned_seconds'], 0)

    def test_overtime_is_a_600_second_period_after_regulation(self):
        self.assertEqual(game_stats._elapsed(5, 600), 3600)
        self.assertEqual(game_stats._elapsed(5, 0), 4200)

    def test_a_record_without_clock_fields_says_what_is_missing(self):
        result = game_stats.clock_reconciliation({'drives': [{'offense_team': 'A'}]})
        self.assertEqual(result['status'], 'unavailable')
        self.assertIn('quarter_start', result['reason'])


class PlayerSnaps(unittest.TestCase):
    """A snap count is given only where the model counts one. Unmodeled players get None, never zero."""

    TEAM_STATS = {'A': {'plays': 61}, 'B': {'plays': 58}}
    LINEUP = {'CIN': {'player_snaps': {'SKILL1': 44}}}

    def line(self, **fields):
        base = {'side': 'A', 'team': 'CIN', 'stable_player_id': 'X', 'position': 'QB', 'starter': True}
        base.update(fields)
        return base

    def test_the_starting_qb_is_on_the_field_for_every_team_scrimmage_play(self):
        self.assertEqual(outputs._with_snaps(self.line(), self.TEAM_STATS, self.LINEUP)['snaps'], 61)

    def test_a_backup_qb_has_no_snap_count_because_replacement_is_not_modeled(self):
        self.assertIsNone(outputs._with_snaps(self.line(starter=False), self.TEAM_STATS, self.LINEUP)['snaps'])

    def test_a_skill_player_takes_his_lineup_count_and_zero_when_absent_from_the_lineup(self):
        wr = self.line(position='WR', stable_player_id='SKILL1', starter=False)
        self.assertEqual(outputs._with_snaps(wr, self.TEAM_STATS, self.LINEUP)['snaps'], 44)
        absent = self.line(position='WR', stable_player_id='SKILL2', starter=False)
        self.assertEqual(outputs._with_snaps(absent, self.TEAM_STATS, self.LINEUP)['snaps'], 0)

    def test_linemen_and_defenders_have_no_snap_count(self):
        ol = self.line(position='OL', stable_player_id='OL1', starter=True)
        self.assertIsNone(outputs._with_snaps(ol, self.TEAM_STATS, self.LINEUP)['snaps'])

    def test_skill_players_have_no_count_when_the_lineup_model_did_not_run(self):
        wr = self.line(position='WR', stable_player_id='SKILL1', starter=False)
        self.assertIsNone(outputs._with_snaps(wr, self.TEAM_STATS, {})['snaps'])


class DownAndClockAccounting(unittest.TestCase):
    @staticmethod
    def play(event, down, to_go, yards, after_down, after_team='A', penalty=None):
        before_clock = 900 - (down * 10)
        return {
            'event_type': event,
            'state_before': {'offense_team': 'A', 'quarter': 1, 'clock_seconds': before_clock,
                             'down': down, 'yards_to_go': to_go, 'yardline_100': 50},
            'state_after': {'offense_team': after_team, 'quarter': 1, 'clock_seconds': before_clock - 10,
                            'down': after_down, 'yards_to_go': 10},
            'outcome': {'yards_gained': yards, 'touchdown': False, 'safety': False,
                        'turnover': False, 'punt': False, 'penalty': penalty},
            'participants': {'rusher_id': 'RB1'} if event == 'run' else
                           {'passer_id': 'QB1', 'receiver_id': 'WR1'},
        }

    def test_first_downs_and_third_fourth_down_rates_come_from_the_state_transition(self):
        plays = [
            self.play('run', 1, 10, 10, 1),
            self.play('pass_complete', 1, 10, 4, 2),
            self.play('pass_complete', 2, 6, 6, 1),
            self.play('run', 3, 2, 2, 1),
            self.play('run', 4, 1, 0, 1, after_team='B'),
        ]
        drive = {'offense_team': 'A', 'quarter_start': 1, 'clock_start': 900,
                 'end_quarter': 1, 'end_clock': 800, 'terminal': 'turnover_on_downs',
                 'field_goal_made': None,
                 'plays': plays}

        stats = game_stats.team_stats([drive], {'A': 0, 'B': 0})['A']

        self.assertEqual(stats['first_downs'], 3)
        self.assertEqual(stats['first_downs_run'], 2)
        self.assertEqual(stats['first_downs_pass'], 1)
        self.assertEqual(stats['down_3_attempts'], 1)
        self.assertEqual(stats['down_3_conversions'], 1)
        self.assertEqual(stats['down_4_attempts'], 1)
        self.assertEqual(stats['down_4_conversions'], 0)
        self.assertEqual(stats['third_down_conversion_rate'], 1.0)
        self.assertEqual(stats['fourth_down_conversion_rate'], 0.0)

    def test_third_and_fourth_down_offensive_touchdowns_convert_without_earning_a_first_down(self):
        third_down_td = self.play('run', 3, 1, 1, 1)
        third_down_td['state_before']['yardline_100'] = 1
        third_down_td['outcome'].update(touchdown=True, scoring_team='A')
        fourth_down_td = self.play('run', 4, 1, 1, 1)
        fourth_down_td['state_before']['yardline_100'] = 1
        fourth_down_td['outcome'].update(touchdown=True, scoring_team='A')

        def touchdown_drive(play, quarter_start=1):
            clock = play['state_before']['clock_seconds']
            return {'offense_team': 'A', 'quarter_start': quarter_start, 'clock_start': clock,
                    'end_quarter': quarter_start, 'end_clock': clock - 10, 'terminal': 'touchdown',
                    'touchdown_scored_by': 'A', 'field_goal_made': None,
                    'points_scored_on_drive': {'team': 'A', 'points': 7}, 'plays': [play]}

        stats = game_stats.team_stats(
            [touchdown_drive(third_down_td), touchdown_drive(fourth_down_td)], {'A': 14, 'B': 0})['A']
        self.assertEqual(stats['first_downs'], 0)
        self.assertEqual(stats['down_3_conversions'], 1)
        self.assertEqual(stats['down_4_conversions'], 1)
        self.assertEqual(stats['down_3_successful_plays'], 1)
        self.assertEqual(stats['down_4_successful_plays'], 1)
        self.assertIsNone(game_stats.first_down_result(third_down_td))
        self.assertIsNone(game_stats.first_down_result(fourth_down_td))

    def test_defensive_touchdown_and_turnover_on_downs_are_not_offensive_conversions(self):
        interception = self.play('interception', 3, 8, 0, 1, after_team='B')
        interception['outcome'].update(turnover=True, touchdown=True, scoring_team='B')
        turnover_on_downs = self.play('run', 4, 2, 0, 1, after_team='B')
        turnover_on_downs['outcome'].update(turnover=True, turnover_on_downs=True)
        drives = [
            {'offense_team': 'A', 'quarter_start': 1, 'clock_start': 870,
             'end_quarter': 1, 'end_clock': 860, 'terminal': 'touchdown',
             'touchdown_scored_by': 'B', 'field_goal_made': None,
             'points_scored_on_drive': {'team': 'B', 'points': 6}, 'plays': [interception]},
            {'offense_team': 'A', 'quarter_start': 1, 'clock_start': 860,
             'end_quarter': 1, 'end_clock': 850, 'terminal': 'turnover_on_downs',
             'touchdown_scored_by': None, 'field_goal_made': None,
             'points_scored_on_drive': {'team': None, 'points': 0}, 'plays': [turnover_on_downs]},
        ]

        stats = game_stats.team_stats(drives, {'A': 0, 'B': 6})['A']
        self.assertEqual(stats['down_3_attempts'], 1)
        self.assertEqual(stats['down_3_conversions'], 0)
        self.assertEqual(stats['down_4_attempts'], 1)
        self.assertEqual(stats['down_4_conversions'], 0)
        self.assertFalse(game_stats._is_successful_play(interception))

    def test_touchdown_conversion_flags_keep_first_down_source_empty(self):
        play = self.play('run', 3, 1, 1, 1)
        play['outcome'].update(touchdown=True, scoring_team='A')
        row = outputs.play_rows({'drives': [{'index': 1, 'plays': [play]}]})[0]
        self.assertTrue(row['third_down_attempt'])
        self.assertTrue(row['third_down_conversion'])
        self.assertIsNone(row['first_down_source'])


    def test_penalty_only_first_down_does_not_count_as_a_down_conversion(self):
        play = self.play('pass_incomplete', 3, 10, 0, 1, penalty={'accepted': True})
        self.assertEqual(game_stats.first_down_result(play), 'penalty')
        self.assertFalse(game_stats.down_conversion(play))
        stats = game_stats.team_stats([{
            'offense_team': 'A', 'quarter_start': 1, 'clock_start': 870,
            'end_quarter': 1, 'end_clock': 860, 'terminal': 'field_goal_missed',
            'field_goal_made': None, 'plays': [play],
        }], {'A': 0, 'B': 0})['A']
        self.assertEqual(stats['first_downs'], 1)
        self.assertEqual(stats['first_downs_penalty'], 1)
        self.assertEqual(stats['down_3_attempts'], 0)
        self.assertEqual(stats['down_3_conversions'], 0)

    def test_scrimmage_conversion_and_separate_penalty_first_down_both_count(self):
        play = self.play('run', 3, 2, 2, 1, penalty={
            'accepted': True, 'scrimmage_play_counted': True, 'scrimmage_first_down': True,
        })
        self.assertEqual(game_stats.first_down_results(play), ['run', 'penalty'])
        self.assertTrue(game_stats.down_conversion(play))
        stats = game_stats.team_stats([{
            'offense_team': 'A', 'quarter_start': 1, 'clock_start': 870,
            'end_quarter': 1, 'end_clock': 860, 'terminal': 'field_goal_missed',
            'field_goal_made': None, 'plays': [play],
        }], {'A': 0, 'B': 0})['A']
        self.assertEqual(stats['first_downs'], 2)
        self.assertEqual(stats['first_downs_run'], 1)
        self.assertEqual(stats['first_downs_penalty'], 1)
        self.assertEqual(stats['down_3_attempts'], 1)
        self.assertEqual(stats['down_3_conversions'], 1)

    def test_realism_export_excludes_penalty_only_down_attempt(self):
        play = self.play('pass_incomplete', 3, 10, 0, 1, penalty={'accepted': True})
        row = outputs.play_rows({'drives': [{'index': 1, 'plays': [play]}]})[0]
        self.assertFalse(row['third_down_attempt'])
        self.assertFalse(row['third_down_conversion'])
        self.assertEqual(row['first_down_sources'], ['penalty'])

    def test_realism_play_row_exports_post_play_state_and_conversion(self):
        play = self.play('run', 3, 2, 2, 1)
        row = outputs.play_rows({'drives': [{'index': 1, 'plays': [play]}]})[0]
        self.assertEqual(row['state_after']['down'], 1)
        self.assertTrue(row['third_down_attempt'])
        self.assertTrue(row['third_down_conversion'])
        self.assertEqual(row['first_down_source'], 'run')


if __name__ == '__main__':
    unittest.main()
