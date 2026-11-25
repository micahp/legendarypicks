import unittest

import ceg_contract as c
from event_expansion_stats import EventStatisticsError, play_deltas, try_deltas


P = c.ProvenanceV2('event-stats-test', '0', 'a' * 64)
STATE = {'offense': 'A', 'defense': 'B', 'down': 2, 'togo': 7, 'yl': 40}


def play(**updates):
    base = dict(contract=c.CONTRACT_V2_VERSION, call=c.PlayCallV2('dropback'),
                event='pass_complete', yards_gained=8, provenance=P,
                clock=c.ClockV2(5), air_yards=6, yards_after_catch=2,
                players=c.PlayerRolesV2(passer=c.PlayerRoleV2.named('qb1'),
                                        receiver=c.PlayerRoleV2.named('wr1')))
    base.update(updates)
    return c.GeneratedPlayV2(**base)


class EventExpansionStatisticsTests(unittest.TestCase):
    def test_interception_return_touchdown_reconciles_teams_and_players(self):
        possession = c.PossessionV2(
            'defense', 'interception', turnover_spot_yardline_100=40,
            dead_ball_yardline_100=100, return_yards=60,
            returner=c.PlayerRoleV2.named('db1'))
        record = play(event='interception', yards_gained=0, air_yards=None,
                      yards_after_catch=None, possession=possession,
                      scoring=c.ScoringV2('touchdown', 'defense'),
                      players=c.PlayerRolesV2(passer=c.PlayerRoleV2.named('qb1'),
                                              interceptor=c.PlayerRoleV2.named('db1'),
                                              returner=c.PlayerRoleV2.named('db1')))
        stats = play_deltas(record, STATE)
        self.assertEqual(stats['team']['A']['interceptions_thrown'], 1)
        self.assertEqual(stats['team']['B']['interceptions'], 1)
        self.assertEqual(stats['team']['B']['interception_return_yards'], 60)
        self.assertEqual(stats['team']['B']['return_touchdowns'], 1)
        self.assertEqual(stats['team']['B']['points_scored'], 6)
        self.assertEqual(stats['player']['db1']['stats']['interceptions'], 1)
        self.assertEqual(stats['player']['db1']['stats']['return_touchdowns'], 1)

    def test_spike_counts_as_a_pass_attempt_without_receiver_stats(self):
        record = play(call=c.PlayCallV2('spike'), event='spike', yards_gained=0,
                      air_yards=None, yards_after_catch=None,
                      players=c.PlayerRolesV2(passer=c.PlayerRoleV2.named('qb1')))
        stats = play_deltas(record, STATE)
        self.assertEqual(stats['team']['A']['pass_attempts'], 1)
        self.assertEqual(stats['player']['qb1']['stats']['pass_attempts'], 1)

    def test_sack_fumble_return_keeps_sack_fumble_recovery_and_return_credits(self):
        possession = c.PossessionV2(
            'defense', 'fumble_recovery', turnover_spot_yardline_100=45,
            recovery_spot_yardline_100=45, dead_ball_yardline_100=100,
            return_yards=55, recovered_by=c.PlayerRoleV2.named('de1'),
            returner=c.PlayerRoleV2.named('de1'), fumble_spot_yardline_100=45)
        record = play(event='sack', yards_gained=-5, air_yards=None,
                      yards_after_catch=None, fumble=True, possession=possession,
                      scoring=c.ScoringV2('touchdown', 'defense'),
                      players=c.PlayerRolesV2(passer=c.PlayerRoleV2.named('qb1'),
                                              sacker=c.PlayerRoleV2.named('de1'),
                                              fumbler=c.PlayerRoleV2.named('qb1'),
                                              recoverer=c.PlayerRoleV2.named('de1'),
                                              returner=c.PlayerRoleV2.named('de1')))
        stats = play_deltas(record, STATE)
        self.assertEqual(stats['team']['A']['sacks_taken'], 1)
        self.assertEqual(stats['team']['A']['fumbles_lost'], 1)
        self.assertEqual(stats['team']['B']['sacks'], 1)
        self.assertEqual(stats['team']['B']['fumble_recoveries'], 1)
        self.assertEqual(stats['team']['B']['fumble_return_yards'], 55)
        self.assertEqual(stats['player']['de1']['stats']['sacks'], 1)
        self.assertEqual(stats['player']['qb1']['stats']['fumbles_lost'], 1)

    def test_punt_muff_attributes_fumble_and_recovery_without_inventing_a_return(self):
        kick = c.KickV2('punt', 'A', 'B', 40, 45, 'muff',
                        possession_after='kicking_team', recovery_team='kicking_team',
                        recovery_yardline_100=50, dead_ball_yardline_100=50,
                        receiving_team_touched_beyond_line=True,
                        returner=c.PlayerRoleV2.named('pr1'),
                        recoverer=c.PlayerRoleV2.named('g1'),
                        fumble_spot_yardline_100=50)
        record = play(call=c.PlayCallV2('punt'), event='punt', yards_gained=None,
                      air_yards=None, yards_after_catch=None, kick=kick, fumble=True,
                      players=c.PlayerRolesV2(punter=c.PlayerRoleV2.named('p1')))
        stats = play_deltas(record, STATE)
        self.assertEqual(stats['team']['B']['fumbles_lost'], 1)
        self.assertEqual(stats['team']['A']['fumble_recoveries'], 1)
        self.assertNotIn('punt_returns', stats['team']['B'])
        self.assertEqual(stats['player']['pr1']['stats']['fumbles_lost'], 1)

    def test_unmodelled_roles_remain_unassigned_but_team_totals_close(self):
        possession = c.PossessionV2(
            'defense', 'interception', turnover_spot_yardline_100=40,
            dead_ball_yardline_100=45, return_yards=5,
            returner=c.PlayerRoleV2.unmodelled('returner'))
        record = play(event='interception', yards_gained=0, air_yards=None,
                      yards_after_catch=None, possession=possession,
                      players=c.PlayerRolesV2(passer=c.PlayerRoleV2.named('qb1'),
                                              interceptor=c.PlayerRoleV2.unmodelled('defender')))
        stats = play_deltas(record, STATE)
        self.assertNotIn('slot:defender', stats['player'])
        self.assertEqual(stats['unattributed']['B']['interceptions'], 1)
        self.assertEqual(stats['unattributed']['B']['interception_return_yards'], 5)

    def test_declined_penalty_is_not_charged_as_accepted_penalty_yards(self):
        penalty = c.PenaltyV2('live_ball', (c.PenaltyFoulV2('holding', 'offense', 10),),
                              'declined', provenance=P)
        stats = play_deltas(play(penalty=penalty), STATE)
        self.assertEqual(stats['team']['A']['penalties_declined'], 1)
        self.assertNotIn('penalties_accepted_yards', stats['team']['A'])

    def test_accepted_penalty_yards_reconcile_to_named_offender(self):
        penalty = c.PenaltyV2(
            'live_ball', (c.PenaltyFoulV2('offensive_holding', 'offense', 10,
                                          player=c.PlayerRoleV2.named('ol1')),),
            'accepted', provenance=P)
        near_goal = {**STATE, 'yl': 96}
        with self.assertRaisesRegex(EventStatisticsError,
                                    'accepted_penalty_requires_rules_enforcement_result'):
            play_deltas(play(penalty=penalty), near_goal)
        stats = play_deltas(play(penalty=penalty), near_goal,
                            penalty_enforcement={'accepted': True, 'yards': 2.0})
        self.assertEqual(stats['team']['A']['penalties_accepted_yards'], 2.0)
        self.assertEqual(stats['player']['ol1']['stats']['penalties_accepted_yards'], 2.0)

    def test_non_counting_accepted_penalty_keeps_penalty_stats_and_omits_play_stats(self):
        penalty = c.PenaltyV2(
            'live_ball', (c.PenaltyFoulV2('defensive_pass_interference', 'defense', 0,
                                          foul_spot=32,
                                          player=c.PlayerRoleV2.named('cb1')),),
            'accepted', automatic_first_down=True, provenance=P)
        record = play(event='pass_incomplete', yards_gained=0, air_yards=None,
                      yards_after_catch=None, penalty=penalty,
                      players=c.PlayerRolesV2(passer=c.PlayerRoleV2.named('qb1')))
        stats = play_deltas(record, STATE,
                            penalty_enforcement={'accepted': True, 'yards': 8,
                                                 'play_counts': False})
        self.assertEqual(stats['team']['B']['penalties_accepted'], 1)
        self.assertEqual(stats['team']['B']['penalties_accepted_yards'], 8)
        self.assertEqual(stats['player']['cb1']['stats']['penalties_accepted'], 1)
        self.assertNotIn('pass_attempts', stats['team'].get('A', {}))
        self.assertNotIn('targets', stats['team'].get('A', {}))
        self.assertNotIn('pass_attempts', stats['player'].get('qb1', {}).get('stats', {}))

    def test_non_counting_accepted_penalty_does_not_credit_a_cancelled_touchdown(self):
        penalty = c.PenaltyV2(
            'live_ball', (c.PenaltyFoulV2('defensive_pass_interference', 'defense', 0,
                                          foul_spot=8),),
            'accepted', automatic_first_down=True, provenance=P)
        record = play(yards_gained=40, air_yards=35, yards_after_catch=5,
                      scoring=c.ScoringV2('touchdown', 'offense'), penalty=penalty)
        stats = play_deltas(record, STATE,
                            penalty_enforcement={'accepted': True, 'yards': 32,
                                                 'play_counts': False})
        self.assertNotIn('touchdowns', stats['team'].get('A', {}))
        self.assertNotIn('points_scored', stats['team'].get('A', {}))
        self.assertNotIn('passing_touchdowns', stats['player'].get('qb1', {}).get('stats', {}))

    def test_try_defensive_return_is_two_points_for_the_returning_team(self):
        record = c.TryRecordV2(c.CONTRACT_V2_VERSION, 'two_point', 'A',
                               'defensive_return', 'B', P)
        self.assertEqual(try_deltas(record, 'A', 'B'), {
            'A': {'try_points': 0, 'points_scored': 0},
            'B': {'try_points': 2, 'points_scored': 2},
        })


if __name__ == '__main__':
    unittest.main()
