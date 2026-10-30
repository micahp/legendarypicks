import copy
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import slc_outputs as outputs  # noqa: E402


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
                      'possession_seconds': 1300, 'plays': 1, 'rush_att': 0, 'rush_yds': 0,
                      'pass_att': 1, 'pass_comp': 1, 'pass_yds': 10, 'interceptions': 0,
                      'pass_tgt': 1, 'sacks_taken': 0, 'sack_yds': 0, 'punts': 0,
                      'fg_att': 0, 'fg_made': 0, 'turnovers': 0, 'fumbles_lost': 0,
                      'turnovers_on_downs': 0},
                'B': {'points': away_points, 'touchdowns': 0, 'offensive_touchdowns': 0,
                      'observed_overtime_touchdowns': 0, 'drives': 1,
                      'possession_seconds': 1200, 'plays': 0, 'rush_att': 0, 'rush_yds': 0,
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


if __name__ == '__main__':
    unittest.main()
