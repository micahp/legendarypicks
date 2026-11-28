import unittest
from dataclasses import replace

import ceg_contract as v2
import ceg_contract_v3 as c


PROVENANCE = v2.ProvenanceV2('v3-special-teams-test', '1', 'a' * 64,
                            ('authored_contract_fixture',), ('kick_outcome',))


def punt_record(kick, **updates):
    record = dict(
        contract=c.CONTRACT_V3_VERSION,
        call=v2.PlayCallV2('punt'),
        event='punt',
        yards_gained=None,
        provenance=PROVENANCE,
        clock=v2.ClockV2(5),
        kick=kick,
        players=v2.PlayerRolesV2(punter=v2.PlayerRoleV2.named('punter')),
    )
    record.update(updates)
    return c.GeneratedPlayV3(**record)


def kickoff_record(kick, **updates):
    record = dict(
        contract=c.CONTRACT_V3_VERSION,
        call=v2.PlayCallV2('kickoff'),
        event='kickoff',
        yards_gained=None,
        provenance=PROVENANCE,
        clock=v2.ClockV2(5),
        kick=kick,
        players=v2.PlayerRolesV2(kicker=v2.PlayerRoleV2.named('kicker')),
    )
    record.update(updates)
    return c.GeneratedPlayV3(**record)


class CegPlay3SpecialTeams(unittest.TestCase):
    def test_contract_has_named_successor_without_changing_v2(self):
        self.assertEqual(c.CONTRACT_V3_VERSION, 'ceg-play-3')
        self.assertEqual(v2.CONTRACT_V2_VERSION, 'ceg-play-2')

    def test_muff_records_three_distinct_roles_and_recovery_to_dead_ball_yards(self):
        receiving = v2.PlayerRoleV2.named('returner-a')
        recovering = v2.PlayerRoleV2.named('gunner-b')
        advancing = v2.PlayerRoleV2.named('returner-c')
        recovery = c.FieldSpotV3(70, 'kicking_team')
        dead = c.FieldSpotV3(75, 'kicking_team')
        facts = c.KickReturnV3(
            'receiving_team', v2.PlayerRoleV2.none(), None, dead, 5,
            receiving, recovering, advancing, recovery,
            c.FieldSpotV3(70, 'kicking_team'))
        kick = c.KickV3(
            'punt', 'A', 'B', c.FieldSpotV3(40, 'kicking_team'), 45, 'muff',
            possession_after='receiving_team', dead_ball_spot=dead,
            recovery_team='receiving_team', recovery_spot=recovery,
            recoverer=recovering, return_facts=facts)
        self.assertIsNone(c.validate_v3(None, punt_record(kick, fumble=True)))
        self.assertIsNot(facts.muffing_returner, facts.recoverer)
        self.assertIsNot(facts.recoverer, facts.post_recovery_returner)

    def test_muff_yards_must_reconcile_in_returning_team_frame(self):
        recovery = c.FieldSpotV3(70, 'kicking_team')
        dead = c.FieldSpotV3(75, 'kicking_team')
        recovering = v2.PlayerRoleV2.named('recoverer')
        facts = c.KickReturnV3(
            'receiving_team', v2.PlayerRoleV2.none(), None, dead, 4,
            v2.PlayerRoleV2.named('muffing-player'), recovering,
            v2.PlayerRoleV2.named('advancer'), recovery,
            c.FieldSpotV3(70, 'kicking_team'))
        kick = c.KickV3('punt', 'A', 'B', c.FieldSpotV3(40, 'kicking_team'), 45,
                        'muff', possession_after='receiving_team', dead_ball_spot=dead,
                        recovery_team='receiving_team', recovery_spot=recovery,
                        recoverer=recovering, return_facts=facts)
        with self.assertRaisesRegex(c.ContractViolationV3,
                                    'kick_return_yards_disagree_with_framed_spots'):
            c.validate_v3(None, punt_record(kick, fumble=True))

    def test_muff_recovery_touchdown_uses_post_recovery_returner(self):
        recovery = c.FieldSpotV3(95, 'kicking_team')
        dead = c.FieldSpotV3(0, 'receiving_team')
        recoverer = v2.PlayerRoleV2.named('recoverer')
        advancer = v2.PlayerRoleV2.named('touchdown-returner')
        facts = c.KickReturnV3(
            'receiving_team', v2.PlayerRoleV2.none(), None, dead, 5,
            v2.PlayerRoleV2.named('muffing-player'), recoverer, advancer,
            recovery, c.FieldSpotV3(95, 'kicking_team'), 'touchdown', 'receiving_team')
        kick = c.KickV3('punt', 'A', 'B', c.FieldSpotV3(40, 'kicking_team'), 45,
                        'muff', possession_after='receiving_team',
                        dead_ball_spot=c.FieldSpotV3(100, 'kicking_team'),
                        recovery_team='receiving_team', recovery_spot=recovery,
                        recoverer=recoverer, return_facts=facts)
        record = punt_record(kick, fumble=True,
                             scoring=v2.ScoringV2('touchdown', 'receiving_team'))
        self.assertIsNone(c.validate_v3(None, record))

    def test_punt_fair_catch_and_downed_are_typed_outcomes(self):
        dead = c.FieldSpotV3(30, 'receiving_team')
        fair = c.KickV3('punt', 'A', 'B', c.FieldSpotV3(40, 'kicking_team'), 45,
                        'fair_catch', possession_after='receiving_team',
                        dead_ball_spot=dead, fair_catcher=v2.PlayerRoleV2.named('pc'))
        self.assertIsNone(c.validate_v3(None, punt_record(fair)))
        downed = c.KickV3('punt', 'A', 'B', c.FieldSpotV3(40, 'kicking_team'), 45,
                          'downed', possession_after='receiving_team', dead_ball_spot=dead)
        self.assertIsNone(c.validate_v3(None, punt_record(downed)))
        missing_catcher = c.KickV3('punt', 'A', 'B', c.FieldSpotV3(40, 'kicking_team'), 45,
                                   'fair_catch', possession_after='receiving_team',
                                   dead_ball_spot=dead)
        with self.assertRaisesRegex(c.ContractViolationV3,
                                    'fair_catcher_role_required_or_unmodelled_slot'):
            c.validate_v3(None, punt_record(missing_catcher))

    def test_kickoff_oob_records_choice_enforcement_and_restart_frame(self):
        # Kicking-team 35 is receiving-team 35; the 25-yard option is receiving-team 60.
        oob = c.KickoffOutOfBoundsV3(
            'kicking_team_out_of_bounds', 'at_distance_from_kick',
            c.FieldSpotV3(60, 'kicking_team'), c.FieldSpotV3(60, 'receiving_team'),
            distance_yards=25)
        kick = c.KickV3('kickoff', 'A', 'B', c.FieldSpotV3(65, 'kicking_team'), 35,
                        'out_of_bounds', possession_after='receiving_team',
                        dead_ball_spot=c.FieldSpotV3(60, 'kicking_team'),
                        out_of_bounds_spot=c.FieldSpotV3(60, 'kicking_team'),
                        kickoff_oob=oob)
        self.assertIsNone(c.validate_v3(None, kickoff_record(kick)))

    def test_short_kickoff_landing_records_rule_choice_and_actual_landing_spot(self):
        landing = c.FieldSpotV3(50, 'receiving_team')
        resolution = c.KickoffOutOfBoundsV3(
            'short_of_landing_zone', 'at_short_landing_spot', None, landing,
            landing_spot=landing)
        kick = c.KickV3(
            'kickoff', 'A', 'B', c.FieldSpotV3(65, 'kicking_team'), 35,
            'short_of_landing_zone', possession_after='receiving_team',
            dead_ball_spot=landing, kickoff_oob=resolution)
        self.assertIsNone(c.validate_v3(None, kickoff_record(kick)))

    def test_safety_kick_oob_uses_30_yard_option(self):
        # Safety kick from the free-kicking team's own 20 to receiving team's 50.
        oob = c.KickoffOutOfBoundsV3(
            'kicking_team_out_of_bounds', 'at_distance_from_kick',
            c.FieldSpotV3(45, 'kicking_team'), c.FieldSpotV3(50, 'receiving_team'),
            distance_yards=30)
        kick = c.KickV3('safety_kick', 'A', 'B', c.FieldSpotV3(80, 'kicking_team'), 35,
                        'out_of_bounds', possession_after='receiving_team',
                        dead_ball_spot=c.FieldSpotV3(45, 'kicking_team'),
                        out_of_bounds_spot=c.FieldSpotV3(45, 'kicking_team'),
                        kickoff_oob=oob)
        self.assertIsNone(c.validate_v3(None, kickoff_record(kick)))
        wrong_distance = c.KickoffOutOfBoundsV3(
            'kicking_team_out_of_bounds', 'at_distance_from_kick',
            c.FieldSpotV3(45, 'kicking_team'), c.FieldSpotV3(45, 'receiving_team'),
            distance_yards=25)
        with self.assertRaisesRegex(c.ContractViolationV3, 'kickoff_oob_distance_option_mismatch'):
            c.validate_v3(None, kickoff_record(
                c.KickV3('safety_kick', 'A', 'B', c.FieldSpotV3(80, 'kicking_team'), 35,
                         'out_of_bounds', possession_after='receiving_team',
                         dead_ball_spot=c.FieldSpotV3(45, 'kicking_team'),
                         out_of_bounds_spot=c.FieldSpotV3(45, 'kicking_team'),
                         kickoff_oob=wrong_distance)))

    def test_safety_records_possessing_side_scorer_free_kick_and_pending_restart(self):
        safety = c.KickSafetyV3(
            scoring_team='kicking_team', possessing_team='receiving_team',
            safety_dead_ball_spot=c.FieldSpotV3(100, 'receiving_team'),
            free_kick_team='receiving_team', free_kick_spot=c.FieldSpotV3(80, 'receiving_team'),
            free_kick_spot_basis='own_20', receiving_team='kicking_team',
            restart_status='pending')
        returner = v2.PlayerRoleV2.named('returner')
        facts = c.KickReturnV3(
            'receiving_team', returner, c.FieldSpotV3(95, 'receiving_team'),
            c.FieldSpotV3(100, 'receiving_team'), -5,
            v2.PlayerRoleV2.none(), v2.PlayerRoleV2.none(), v2.PlayerRoleV2.none(),
            scoring_kind='safety', scoring_team='kicking_team')
        kick = c.KickV3('punt', 'A', 'B', c.FieldSpotV3(40, 'kicking_team'), 45,
                        'return', possession_after='receiving_team',
                        dead_ball_spot=c.FieldSpotV3(0, 'kicking_team'),
                        return_facts=facts, safety=safety)
        record = punt_record(kick, scoring=v2.ScoringV2('safety', 'kicking_team'))
        self.assertIsNone(c.validate_v3(None, record))
        with self.assertRaisesRegex(c.ContractViolationV3,
                                    'kick_safety_dead_ball_frame_must_name_possessing_team'):
            bad_safety = c.KickSafetyV3(
                'kicking_team', 'receiving_team', c.FieldSpotV3(100, 'kicking_team'),
                'receiving_team', c.FieldSpotV3(80, 'receiving_team'), 'own_20',
                'kicking_team', 'pending')
            c.validate_v3(None, punt_record(
                c.KickV3('punt', 'A', 'B', c.FieldSpotV3(40, 'kicking_team'), 45,
                         'return', possession_after='receiving_team',
                         dead_ball_spot=c.FieldSpotV3(0, 'kicking_team'),
                         return_facts=facts, safety=bad_safety),
                scoring=v2.ScoringV2('safety', 'kicking_team')))

    def test_blocked_field_goal_return_and_touchdown_are_attributed(self):
        recovery = c.FieldSpotV3(50, 'receiving_team')
        dead = c.FieldSpotV3(0, 'receiving_team')
        blocked = c.BlockedFieldGoalReturnV3(
            recovery_team='receiving_team', recovery_spot=recovery,
            recoverer=v2.PlayerRoleV2.named('recoverer'),
            post_block_returner=v2.PlayerRoleV2.named('returner'),
            return_yards=50, dead_ball_spot=dead, possession_after='receiving_team',
            scoring_kind='touchdown', scoring_team='receiving_team')
        kick = c.KickV3('field_goal', 'A', 'B', c.FieldSpotV3(80, 'kicking_team'), 37,
                        'blocked', possession_after='receiving_team',
                        recovery_team='receiving_team', recovery_spot=recovery,
                        blocked_field_goal_return=blocked)
        record = c.GeneratedPlayV3(
            contract=c.CONTRACT_V3_VERSION, call=v2.PlayCallV2('field_goal'),
            event='field_goal_attempt', yards_gained=None, provenance=PROVENANCE,
            clock=v2.ClockV2(4), kick=kick,
            players=v2.PlayerRolesV2(kicker=v2.PlayerRoleV2.named('kicker')),
            scoring=v2.ScoringV2('touchdown', 'receiving_team'))
        self.assertIsNone(c.validate_v3(None, record))
        bad = c.BlockedFieldGoalReturnV3(
            'receiving_team', recovery, v2.PlayerRoleV2.named('recoverer'),
            v2.PlayerRoleV2.named('returner'), 50, dead, 'receiving_team',
            'touchdown', 'kicking_team')
        with self.assertRaisesRegex(c.ContractViolationV3,
                                    'blocked_field_goal_touchdown_team_or_spot_mismatch'):
            c.validate_v3(None, c.GeneratedPlayV3(
                contract=c.CONTRACT_V3_VERSION, call=v2.PlayCallV2('field_goal'),
                event='field_goal_attempt', yards_gained=None, provenance=PROVENANCE,
                clock=v2.ClockV2(4),
                kick=c.KickV3('field_goal', 'A', 'B', c.FieldSpotV3(80, 'kicking_team'), 37,
                              'blocked', possession_after='receiving_team',
                              recovery_team='receiving_team', recovery_spot=recovery,
                              blocked_field_goal_return=bad),
                players=v2.PlayerRolesV2(kicker=v2.PlayerRoleV2.named('kicker')),
                scoring=v2.ScoringV2('touchdown', 'receiving_team')))

    def test_touchback_needs_explicit_receiving_restart_spot(self):
        kick = c.KickV3('kickoff', 'A', 'B', c.FieldSpotV3(65, 'kicking_team'), 35,
                        'touchback', possession_after='receiving_team',
                        dead_ball_spot=c.FieldSpotV3(0, 'receiving_team'))
        with self.assertRaisesRegex(c.ContractViolationV3,
                                    'touchback_needs_receiving_possession_dead_ball_and_restart_spots'):
            c.validate_v3(None, kickoff_record(kick))

    def test_interception_return_fumble_recovery_chain_is_ordered_and_attributed(self):
        interceptor = v2.PlayerRoleV2.named('db-interceptor')
        initial_returner = v2.PlayerRoleV2.named('db-returner')
        fumbler = v2.PlayerRoleV2.named('db-fumbler')
        recoverer = v2.PlayerRoleV2.named('wr-recoverer')
        post_returner = v2.PlayerRoleV2.named('wr-advancer')
        chain = c.ScrimmageTurnoverChainV3(
            initial_turnover='interception', initial_possession_team='defense',
            turnover_spot=c.FieldSpotV3(40, 'offense'),
            initial_returner=initial_returner, initial_return_yards=15,
            fumbler=fumbler, fumble_spot=c.FieldSpotV3(55, 'offense'),
            recoverer=recoverer, recovery_team='offense',
            recovery_spot=c.FieldSpotV3(54, 'offense'),
            post_recovery_returner=post_returner, post_recovery_return_yards=44,
            dead_ball_spot=c.FieldSpotV3(10, 'offense'), final_possession_team='offense',
            interceptor=interceptor)
        possession = v2.PossessionV2(
            team='offense', how='fumble_recovery', turnover_spot_yardline_100=55,
            recovery_spot_yardline_100=54, dead_ball_yardline_100=10,
            return_yards=44, returner=post_returner, recovered_by=recoverer,
            fumble_spot_yardline_100=55)
        record = c.GeneratedPlayV3(
            contract=c.CONTRACT_V3_VERSION, call=v2.PlayCallV2('dropback'),
            event='interception', yards_gained=0, provenance=PROVENANCE,
            clock=v2.ClockV2(6), fumble=True, possession=possession,
            players=v2.PlayerRolesV2(
                passer=v2.PlayerRoleV2.named('qb'), interceptor=interceptor,
                fumbler=fumbler, recoverer=recoverer, returner=post_returner),
            turnover_chain=chain)
        self.assertIsNone(c.validate_v3({'down': 2, 'togo': 7, 'yl': 40}, record))

    def test_goal_line_interception_touchback_uses_existing_v2_representation(self):
        possession = v2.PossessionV2(
            team='defense', how='interception', turnover_spot_yardline_100=0,
            dead_ball_yardline_100=0, return_yards=0,
            returner=v2.PlayerRoleV2.unmodelled('interceptor'), touchback=True,
            next_yardline_100=20)
        record = v2.GeneratedPlayV2(
            contract=v2.CONTRACT_V2_VERSION, call=v2.PlayCallV2('dropback'),
            event='interception', yards_gained=0, provenance=PROVENANCE,
            clock=v2.ClockV2(5), possession=possession,
            players=v2.PlayerRolesV2(passer=v2.PlayerRoleV2.named('qb'),
                                     interceptor=v2.PlayerRoleV2.unmodelled('interceptor')))
        self.assertIsNone(v2.validate_v2({'down': 2, 'togo': 7, 'yl': 1}, record))

    def test_interception_return_fumble_chain_rejects_lost_spot_or_wrong_recoverer(self):
        interceptor = v2.PlayerRoleV2.named('db-interceptor')
        fumbler = v2.PlayerRoleV2.named('db-fumbler')
        recoverer = v2.PlayerRoleV2.named('wr-recoverer')
        post_returner = v2.PlayerRoleV2.named('wr-advancer')
        chain = c.ScrimmageTurnoverChainV3(
            'interception', 'defense', c.FieldSpotV3(40, 'offense'),
            v2.PlayerRoleV2.named('db-returner'), 15, fumbler,
            c.FieldSpotV3(55, 'offense'), recoverer, 'offense',
            c.FieldSpotV3(54, 'offense'), post_returner, 44,
            c.FieldSpotV3(10, 'offense'), 'offense', interceptor)
        possession = v2.PossessionV2(
            'offense', 'fumble_recovery', turnover_spot_yardline_100=55,
            recovery_spot_yardline_100=54, dead_ball_yardline_100=10,
            return_yards=44, returner=post_returner, recovered_by=recoverer,
            fumble_spot_yardline_100=55)
        record = c.GeneratedPlayV3(
            contract=c.CONTRACT_V3_VERSION, call=v2.PlayCallV2('dropback'),
            event='interception', yards_gained=0, provenance=PROVENANCE,
            clock=v2.ClockV2(6), fumble=True, possession=possession,
            players=v2.PlayerRolesV2(passer=v2.PlayerRoleV2.named('qb'),
                                     interceptor=interceptor, fumbler=fumbler,
                                     recoverer=recoverer, returner=post_returner),
            turnover_chain=chain)
        bad_spot = c.GeneratedPlayV3(
            **{**record.__dict__, 'turnover_chain': replace(chain, initial_return_yards=14)})
        with self.assertRaisesRegex(c.ContractViolationV3,
                                    'turnover_chain_initial_return_yards_disagree_with_spots'):
            c.validate_v3({'down': 2, 'togo': 7, 'yl': 40}, bad_spot)
        bad_possession = c.GeneratedPlayV3(
            **{**record.__dict__, 'possession': replace(possession, team='defense')})
        with self.assertRaisesRegex(c.ContractViolationV3,
                                    'turnover_chain_possession_fact_mismatch'):
            c.validate_v3({'down': 2, 'togo': 7, 'yl': 40}, bad_possession)


if __name__ == '__main__':
    unittest.main()
