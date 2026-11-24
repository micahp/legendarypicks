import unittest

import ceg_contract as c


PROVENANCE = c.ProvenanceV2('slc-v2-event-expansion', '0', 'a' * 64,
                            ('historical_row',), ('play_outcome',), '2024_01_BUF_NYJ:7', 'b' * 64)
STATE = {'down': 2, 'togo': 7, 'yl': 40}


def play(**updates):
    base = dict(
        contract=c.CONTRACT_V2_VERSION,
        call=c.PlayCallV2('dropback'),
        event='pass_complete',
        yards_gained=8,
        provenance=PROVENANCE,
        clock=c.ClockV2(6.0),
        air_yards=6,
        yards_after_catch=2,
        players=c.PlayerRolesV2(passer=c.PlayerRoleV2.named('qb1'),
                                receiver=c.PlayerRoleV2.named('wr1')),
    )
    base.update(updates)
    return c.GeneratedPlayV2(**base)


class CegPlay2Contract(unittest.TestCase):
    def test_play1_api_remains_available(self):
        old_provenance = c.Provenance('ceg-arm-b', '0', 'c' * 64, (), ())
        old_call = c.PlayCall('dropback', {}, old_provenance)
        old_play = c.GeneratedPlay(
            c.CONTRACT_VERSION, old_call, 'pass_complete', 8, air_yards=6,
            yards_after_catch=2, receiver='wr1', clock=c.Clock(2.0, 4.0, 'running'),
            provenance=old_provenance)
        self.assertIsNone(c.validate(STATE, old_play))
        self.assertEqual(c.CONTRACT_VERSION, 'ceg-play-1')

    def test_source_row_identity_requires_a_paired_sha256(self):
        provenance = c.ProvenanceV2('v2', '1', 'a' * 64, source_row_id='row-1')
        with self.assertRaisesRegex(c.ContractViolationV2, 'source_row_and_hash_must_be_paired'):
            c.validate_v2(STATE, play(provenance=provenance))

    def test_total_clock_can_be_used_without_a_live_dead_split(self):
        self.assertIsNone(c.validate_v2(STATE, play(clock=c.ClockV2(9.0))))
        self.assertIsNone(c.validate_v2(STATE, play(clock=c.ClockV2(9.0, stop_class='running'))))
        with self.assertRaisesRegex(c.ContractViolationV2, 'clock_split_must_be_present_together'):
            c.validate_v2(STATE, play(clock=c.ClockV2(9.0, live_seconds=4.0)))

    def test_clock_split_must_reconcile_to_total(self):
        with self.assertRaisesRegex(c.ContractViolationV2, 'clock_split_does_not_match_total'):
            c.validate_v2(STATE, play(clock=c.ClockV2(9.0, 4.0, 4.0, 'running')))

    def test_optional_clock_is_validated_when_supplied(self):
        self.assertIsNone(c.validate_v2(STATE, play(clock=c.ClockV2(2.0)), require_clock=False))
        self.assertIsNone(c.validate_v2(STATE, play(clock=None), require_clock=False))
        with self.assertRaisesRegex(c.ContractViolationV2, 'clock_split_must_be_present_together'):
            c.validate_v2(STATE, play(clock=c.ClockV2(2.0, live_seconds=1.0)),
                          require_clock=False)

    def test_pre_snap_penalty_is_a_void_no_play_with_no_runoff(self):
        foul = c.PenaltyFoulV2('false_start', 'offense', 5)
        penalty = c.PenaltyV2('pre_snap', (foul,), 'accepted', play_void=True, provenance=PROVENANCE)
        record = play(call=None, event='no_play', yards_gained=None, air_yards=None,
                      yards_after_catch=None, clock=c.ClockV2(0), players=c.PlayerRolesV2(),
                      penalty=penalty, play_void=True)
        self.assertIsNone(c.validate_v2(STATE, record))
        with self.assertRaisesRegex(c.ContractViolationV2, 'clock_runoff_must_be_zero'):
            c.validate_v2(STATE, play(call=None, event='no_play', yards_gained=None,
                                      air_yards=None, yards_after_catch=None, clock=c.ClockV2(1),
                                      players=c.PlayerRolesV2(), penalty=penalty, play_void=True))

    def test_unknown_penalty_disposition_fails_closed(self):
        penalty = c.PenaltyV2('live_ball', (c.PenaltyFoulV2('holding', 'offense', 10),),
                              'unknown', provenance=PROVENANCE)
        with self.assertRaisesRegex(c.ContractViolationV2, 'unknown_penalty_disposition'):
            c.validate_v2(STATE, play(penalty=penalty))

    def test_offsetting_penalties_need_multiple_fouls(self):
        penalty = c.PenaltyV2('live_ball', (c.PenaltyFoulV2('holding', 'offense', 10),),
                              'offsetting', provenance=PROVENANCE)
        with self.assertRaisesRegex(c.ContractViolationV2, 'offsetting_penalty_needs_multiple_fouls'):
            c.validate_v2(STATE, play(penalty=penalty))

    def test_declined_live_penalty_preserves_the_play_result(self):
        penalty = c.PenaltyV2('live_ball', (c.PenaltyFoulV2('holding', 'defense', 10),),
                              'declined', provenance=PROVENANCE)
        self.assertIsNone(c.validate_v2(STATE, play(penalty=penalty)))

    def test_interception_return_touchdown_requires_return_possession_and_scorer(self):
        possession = c.PossessionV2(
            'defense', 'interception', turnover_spot_yardline_100=40,
            dead_ball_yardline_100=100, return_yards=60,
            returner=c.PlayerRoleV2.named('db1'))
        record = play(event='interception', yards_gained=0, air_yards=None,
                      yards_after_catch=None,
                      players=c.PlayerRolesV2(passer=c.PlayerRoleV2.named('qb1'),
                                              interceptor=c.PlayerRoleV2.named('db1'),
                                              returner=c.PlayerRoleV2.named('db1')),
                      possession=possession, scoring=c.ScoringV2('touchdown', 'defense'))
        self.assertIsNone(c.validate_v2(STATE, record))
        with self.assertRaisesRegex(c.ContractViolationV2, 'interception_requires_possession_facts'):
            c.validate_v2(STATE, play(event='interception', yards_gained=0,
                                      air_yards=None, yards_after_catch=None,
                                      players=record.players,
                                      scoring=c.ScoringV2('touchdown', 'defense')))

    def test_sack_fumble_retains_sack_identity_and_recovery_facts(self):
        possession = c.PossessionV2(
            'defense', 'fumble_recovery', turnover_spot_yardline_100=45,
            recovery_spot_yardline_100=45, dead_ball_yardline_100=100,
            return_yards=55, recovered_by=c.PlayerRoleV2.named('de1'),
            returner=c.PlayerRoleV2.named('de1'), fumble_spot_yardline_100=45)
        record = play(event='sack', yards_gained=-5, air_yards=None,
                      yards_after_catch=None, fumble=True,
                      players=c.PlayerRolesV2(passer=c.PlayerRoleV2.named('qb1'),
                                              sacker=c.PlayerRoleV2.named('de1'),
                                              fumbler=c.PlayerRoleV2.named('qb1'),
                                              recoverer=c.PlayerRoleV2.named('de1'),
                                              returner=c.PlayerRoleV2.named('de1')),
                      possession=possession, scoring=c.ScoringV2('touchdown', 'defense'))
        self.assertIsNone(c.validate_v2(STATE, record))

    def test_offense_recovering_its_fumble_in_own_end_zone_can_be_classified_as_safety(self):
        state = {'down': 1, 'togo': 5, 'yl': 95}
        possession = c.PossessionV2(
            'offense', 'fumble_recovery', turnover_spot_yardline_100=100,
            recovery_spot_yardline_100=100, dead_ball_yardline_100=100,
            recovered_by=c.PlayerRoleV2.named('rb1'), fumble_spot_yardline_100=100)
        record = play(call=c.PlayCallV2('designed_run'), event='run', yards_gained=-5,
                      air_yards=None, yards_after_catch=None, fumble=True,
                      players=c.PlayerRolesV2(rusher=c.PlayerRoleV2.named('rb1'),
                                              fumbler=c.PlayerRoleV2.named('rb1'),
                                              recoverer=c.PlayerRoleV2.named('rb1')),
                      possession=possession, scoring=c.ScoringV2('safety', 'defense'))
        self.assertEqual(c.validate_v2(state, record), 'own_goal_line')

    def test_unmodelled_player_slots_never_receive_stats(self):
        role = c.PlayerRoleV2.unmodelled('punt_returner')
        self.assertIsNone(role.stat_player_id)
        self.assertEqual(c.PlayerRolesV2(returner=role).statistical_ids(), {})

    def test_punt_return_touchdown_uses_kicking_team_frame(self):
        kick = c.KickV2('punt', 'A', 'B', 40, 45, 'return',
                        possession_after='receiving_team', return_start_yardline_100=80,
                        dead_ball_yardline_100=100, return_yards=20,
                        returner=c.PlayerRoleV2.named('pr1'))
        record = play(call=c.PlayCallV2('punt'), event='punt', yards_gained=None,
                      air_yards=None, yards_after_catch=None, kick=kick,
                      players=c.PlayerRolesV2(punter=c.PlayerRoleV2.named('p1'),
                                              returner=c.PlayerRoleV2.named('pr1')),
                      scoring=c.ScoringV2('touchdown', 'receiving_team'))
        self.assertIsNone(c.validate_v2(None, record))
        mismatched = c.KickV2('punt', 'A', 'B', 40, 45, 'return',
                              possession_after='kicking_team', return_start_yardline_100=80,
                              dead_ball_yardline_100=100, return_yards=20,
                              returner=c.PlayerRoleV2.named('pr1'))
        with self.assertRaisesRegex(c.ContractViolationV2, 'kick_return_touchdown_team_or_result_mismatch'):
            c.validate_v2(None, play(call=c.PlayCallV2('punt'), event='punt', yards_gained=None,
                                     air_yards=None, yards_after_catch=None, kick=mismatched,
                                     players=c.PlayerRolesV2(punter=c.PlayerRoleV2.unmodelled('punter')),
                                     scoring=c.ScoringV2('touchdown', 'receiving_team')))
        wrong_scorer = c.KickV2('punt', 'A', 'B', 40, 45, 'return',
                                possession_after='receiving_team',
                                return_start_yardline_100=80,
                                dead_ball_yardline_100=100, return_yards=20,
                                returner=c.PlayerRoleV2.named('pr1'))
        with self.assertRaisesRegex(c.ContractViolationV2,
                                    'kick_return_touchdown_team_or_result_mismatch'):
            c.validate_v2(None, play(call=c.PlayCallV2('punt'), event='punt', yards_gained=None,
                                     air_yards=None, yards_after_catch=None, kick=wrong_scorer,
                                     players=c.PlayerRolesV2(punter=c.PlayerRoleV2.unmodelled('punter')),
                                     scoring=c.ScoringV2('touchdown', 'kicking_team')))

    def test_muff_records_recovery_team_spot_and_next_possession(self):
        kick = c.KickV2('punt', 'A', 'B', 40, 45, 'muff',
                        possession_after='kicking_team', recovery_team='kicking_team',
                        recovery_yardline_100=45, dead_ball_yardline_100=45,
                        receiving_team_touched_beyond_line=True,
                        returner=c.PlayerRoleV2.unmodelled('punt_fumbler'),
                        recoverer=c.PlayerRoleV2.named('g1'), fumble_spot_yardline_100=45)
        record = play(call=c.PlayCallV2('punt'), event='punt', yards_gained=None,
                      air_yards=None, yards_after_catch=None, kick=kick, fumble=True,
                      players=c.PlayerRolesV2(punter=c.PlayerRoleV2.unmodelled('punter')))
        self.assertIsNone(c.validate_v2(None, record))
        with self.assertRaisesRegex(c.ContractViolationV2, 'muff_needs_recovery_team'):
            c.validate_v2(None, play(call=c.PlayCallV2('punt'), event='punt', yards_gained=None,
                                     air_yards=None, yards_after_catch=None,
                                     kick=c.KickV2('punt', 'A', 'B', 40, 45, 'muff',
                                                   possession_after='kicking_team',
                                                   dead_ball_yardline_100=45,
                                                   fumble_spot_yardline_100=45)))
        advancing_muff = c.KickV2(
            'punt', 'A', 'B', 40, 45, 'muff', possession_after='receiving_team',
            recovery_team='receiving_team', recovery_yardline_100=45,
            dead_ball_yardline_100=47, return_yards=2,
            returner=c.PlayerRoleV2.unmodelled('punt_fumbler'),
            recoverer=c.PlayerRoleV2.unmodelled('punt_recoverer'),
            fumble_spot_yardline_100=45)
        with self.assertRaisesRegex(c.ContractViolationV2,
                                    'muff_return_yardage_attribution_unsupported'):
            c.validate_v2(None, play(call=c.PlayCallV2('punt'), event='punt', yards_gained=None,
                                     air_yards=None, yards_after_catch=None,
                                     kick=advancing_muff, fumble=True))

    def test_blocked_kick_with_explicit_recovery_is_valid(self):
        kick = c.KickV2('punt', 'A', 'B', 40, 45, 'blocked',
                        possession_after='receiving_team', recovery_team='receiving_team',
                        recovery_yardline_100=42, dead_ball_yardline_100=42,
                        recoverer=c.PlayerRoleV2.unmodelled('kick_recoverer'))
        record = play(call=c.PlayCallV2('punt'), event='punt', yards_gained=None,
                      air_yards=None, yards_after_catch=None, kick=kick,
                      players=c.PlayerRolesV2(punter=c.PlayerRoleV2.unmodelled('punter')))
        self.assertIsNone(c.validate_v2(None, record))
        with self.assertRaisesRegex(c.ContractViolationV2,
                                    'blocked_return_touchdown_attribution_unsupported'):
            c.validate_v2(None, play(call=c.PlayCallV2('punt'), event='punt', yards_gained=None,
                                     air_yards=None, yards_after_catch=None, kick=kick,
                                     players=c.PlayerRolesV2(punter=c.PlayerRoleV2.unmodelled('punter')),
                                     scoring=c.ScoringV2('touchdown', 'receiving_team')))

    def test_negative_return_yards_are_valid_when_spots_agree(self):
        possession = c.PossessionV2(
            'defense', 'interception', turnover_spot_yardline_100=40,
            dead_ball_yardline_100=35, return_yards=-5,
            returner=c.PlayerRoleV2.named('db1'))
        record = play(event='interception', yards_gained=0, air_yards=None,
                      yards_after_catch=None, players=c.PlayerRolesV2(
                          passer=c.PlayerRoleV2.named('qb1'),
                          interceptor=c.PlayerRoleV2.named('db1')),
                      possession=possession)
        self.assertIsNone(c.validate_v2(STATE, record))

    def test_interception_touchback_requires_explicit_restart_spot(self):
        possession = c.PossessionV2(
            'defense', 'interception', turnover_spot_yardline_100=0,
            dead_ball_yardline_100=0, return_yards=0,
            returner=c.PlayerRoleV2.unmodelled('interceptor'), touchback=True,
            next_yardline_100=20)
        record = play(event='interception', yards_gained=0, air_yards=None,
                      yards_after_catch=None, possession=possession,
                      players=c.PlayerRolesV2(passer=c.PlayerRoleV2.named('qb1'),
                                              interceptor=c.PlayerRoleV2.unmodelled('interceptor')))
        self.assertIsNone(c.validate_v2(STATE, record))
        invalid = c.PossessionV2(
            'defense', 'interception', turnover_spot_yardline_100=0,
            dead_ball_yardline_100=0, return_yards=0,
            returner=c.PlayerRoleV2.unmodelled('interceptor'), touchback=True)
        with self.assertRaisesRegex(c.ContractViolationV2,
                                    'defensive_touchback_needs_end_zone_dead_ball_and_restart_facts'):
            c.validate_v2(STATE, play(event='interception', yards_gained=0, air_yards=None,
                                      yards_after_catch=None, possession=invalid,
                                      players=record.players))

    def test_offense_retained_fumble_records_fumble_and_recovery_spots(self):
        possession = c.PossessionV2(
            'offense', 'kept', recovery_spot_yardline_100=43,
            dead_ball_yardline_100=43, recovered_by=c.PlayerRoleV2.named('rb1'),
            fumble_spot_yardline_100=45)
        record = play(call=c.PlayCallV2('designed_run'), event='run', yards_gained=3,
                      air_yards=None, yards_after_catch=None, fumble=True,
                      players=c.PlayerRolesV2(rusher=c.PlayerRoleV2.named('rb1'),
                                              fumbler=c.PlayerRoleV2.named('rb1'),
                                              recoverer=c.PlayerRoleV2.named('rb1')),
                      possession=possession)
        self.assertIsNone(c.validate_v2(STATE, record))

    def test_designed_run_requires_rusher_role(self):
        with self.assertRaisesRegex(c.ContractViolationV2, 'designed_run_rusher_role_required'):
            c.validate_v2(STATE, play(call=c.PlayCallV2('designed_run'), event='run',
                                      players=c.PlayerRolesV2()))

    def test_punt_kicking_team_recovery_is_classified_as_muff(self):
        kick = c.KickV2('punt', 'A', 'B', 40, 45, 'kicking_team_recovery',
                        possession_after='kicking_team', recovery_team='kicking_team',
                        recovery_yardline_100=45, dead_ball_yardline_100=45)
        with self.assertRaisesRegex(c.ContractViolationV2,
                                    'kicking_team_recovery_only_supported_for_kickoffs'):
            c.validate_v2(None, play(call=c.PlayCallV2('punt'), event='punt', yards_gained=None,
                                     air_yards=None, yards_after_catch=None, kick=kick))

    def test_kick_safety_has_named_unsupported_classification(self):
        kick = c.KickV2('punt', 'A', 'B', 40, 45, 'return',
                        possession_after='receiving_team', return_start_yardline_100=5,
                        dead_ball_yardline_100=0, return_yards=-5)
        with self.assertRaisesRegex(c.ContractViolationV2, 'kick_safety_unsupported'):
            c.validate_v2(None, play(call=c.PlayCallV2('punt'), event='punt', yards_gained=None,
                                     air_yards=None, yards_after_catch=None, kick=kick,
                                     scoring=c.ScoringV2('safety', 'kicking_team')))

    def test_made_field_goal_requires_a_scoring_fact(self):
        kick = c.KickV2('field_goal', 'A', 'B', 80, 37, 'made')
        base = play(call=c.PlayCallV2('field_goal'), event='field_goal_attempt',
                    yards_gained=None, air_yards=None, yards_after_catch=None, kick=kick,
                    players=c.PlayerRolesV2(kicker=c.PlayerRoleV2.unmodelled('kicker')))
        with self.assertRaisesRegex(c.ContractViolationV2, 'made_field_goal_requires_matching'):
            c.validate_v2(None, base)
        self.assertIsNone(c.validate_v2(None, play(call=c.PlayCallV2('field_goal'),
                                                  event='field_goal_attempt', yards_gained=None,
                                                  air_yards=None, yards_after_catch=None, kick=kick,
                                                  players=c.PlayerRolesV2(kicker=c.PlayerRoleV2.unmodelled('kicker')),
                                                  scoring=c.ScoringV2('field_goal', 'kicking_team'))))


if __name__ == '__main__':
    unittest.main()
