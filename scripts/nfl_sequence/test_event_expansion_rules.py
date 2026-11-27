import unittest

import ceg_contract as c
import ceg_contract_v3 as c3
from event_expansion import EventExpansionSwitches
from event_expansion_rules import (apply_field_goal_play, apply_kickoff_play, apply_punt_play, apply_v3_play,
                                   apply_scrimmage_play, UnsupportedEventTransition)


P = c.ProvenanceV2('event-expansion-test', '0', 'a' * 64, ('forced_state',), ('draw-1',))
S = {'offense': 'A', 'defense': 'B', 'down': 2, 'togo': 7, 'yl': 40}


def record(**kw):
    base = dict(
        contract=c.CONTRACT_V2_VERSION,
        call=c.PlayCallV2('designed_run'),
        event='run',
        yards_gained=4,
        provenance=P,
        clock=c.ClockV2(6),
        players=c.PlayerRolesV2(rusher=c.PlayerRoleV2.named('rb1')),
    )
    base.update(kw)
    return c.GeneratedPlayV2(**base)


class EventExpansionRulesTests(unittest.TestCase):
    def test_defense_recovery_of_blocked_field_goal_changes_possession_not_turnover_stat(self):
        recovery = c3.FieldSpotV3(50, 'receiving_team')
        dead = c3.FieldSpotV3(45, 'receiving_team')
        recoverer = c.PlayerRoleV2.named('recoverer')
        blocked = c3.BlockedFieldGoalReturnV3(
            recovery_team='receiving_team', recovery_spot=recovery,
            recoverer=recoverer, post_block_returner=recoverer,
            return_yards=5, dead_ball_spot=dead, possession_after='receiving_team')
        kick = c3.KickV3('field_goal', 'A', 'B', c3.FieldSpotV3(40, 'kicking_team'), 57,
                         'blocked', possession_after='receiving_team',
                         recovery_team='receiving_team', recovery_spot=recovery,
                         blocked_field_goal_return=blocked)
        play = c3.GeneratedPlayV3(
            contract=c3.CONTRACT_V3_VERSION, call=c.PlayCallV2('field_goal'),
            event='field_goal_attempt', yards_gained=None, provenance=P,
            clock=c.ClockV2(4), kick=kick,
            players=c.PlayerRolesV2(kicker=c.PlayerRoleV2.named('kicker')))
        applied = apply_v3_play({**S, 'down': 4}, play)
        self.assertEqual(applied.terminal, 'turnover')
        self.assertEqual(applied.state_after, {'offense': 'B', 'defense': 'A',
                                               'down': 1, 'togo': 10, 'yl': 45})
        self.assertTrue(applied.flags['possession_change'])
        self.assertFalse(applied.flags.get('turnover', False))
        self.assertTrue(applied.flags['field_goal_attempt'])

    def test_ceg_play_3_downed_and_fair_catch_punts_are_distinct_nonreturns(self):
        provenance = P
        dead = c3.FieldSpotV3(30, 'receiving_team')
        for result, catcher in (('downed', None), ('fair_catch', c.PlayerRoleV2.named('pc'))):
            kick = c3.KickV3('punt', 'A', 'B', c3.FieldSpotV3(40, 'kicking_team'), 45,
                             result, possession_after='receiving_team', dead_ball_spot=dead,
                             fair_catcher=catcher)
            play = c3.GeneratedPlayV3(
                contract=c3.CONTRACT_V3_VERSION, call=c.PlayCallV2('punt'), event='punt',
                yards_gained=None, provenance=provenance, clock=c.ClockV2(5), kick=kick,
                players=c.PlayerRolesV2(punter=c.PlayerRoleV2.named('punter')))
            applied = apply_v3_play(S, play)
            self.assertEqual(applied.state_after, {'offense': 'B', 'defense': 'A',
                                                   'down': 1, 'togo': 10, 'yl': 30})
            self.assertFalse(applied.flags['punt_return'])
            self.assertEqual(applied.flags['fair_catch'], result == 'fair_catch')

    def test_ceg_play_3_muff_attributes_the_recovery_and_post_recovery_returner(self):
        muffing = c.PlayerRoleV2.named('muffing-player')
        recoverer = c.PlayerRoleV2.named('recoverer')
        runner = c.PlayerRoleV2.named('post-recovery-runner')
        recovery, dead = c3.FieldSpotV3(70, 'kicking_team'), c3.FieldSpotV3(75, 'kicking_team')
        facts = c3.KickReturnV3('receiving_team', c.PlayerRoleV2.none(), None, dead, 5,
                                muffing, recoverer, runner, recovery, c3.FieldSpotV3(70, 'kicking_team'))
        kick = c3.KickV3('punt', 'A', 'B', c3.FieldSpotV3(40, 'kicking_team'), 45, 'muff',
                         possession_after='receiving_team', dead_ball_spot=dead,
                         recovery_team='receiving_team', recovery_spot=recovery,
                         recoverer=recoverer, return_facts=facts)
        play = c3.GeneratedPlayV3(
            contract=c3.CONTRACT_V3_VERSION, call=c.PlayCallV2('punt'), event='punt',
            yards_gained=None, fumble=True, provenance=P, clock=c.ClockV2(5), kick=kick,
            players=c.PlayerRolesV2(punter=c.PlayerRoleV2.named('punter')))
        applied = apply_v3_play(S, play)
        self.assertEqual(applied.state_after['offense'], 'B')
        self.assertEqual(applied.flags['return_yards'], 5)
        self.assertEqual(applied.flags['fumbler_id'], 'muffing-player')
        self.assertEqual(applied.flags['recoverer_id'], 'recoverer')
        self.assertEqual(applied.flags['returner_id'], 'post-recovery-runner')
        self.assertFalse(applied.flags['punt_return'])

    def test_ceg_play_3_muffed_kick_touchback_uses_restart_spot_and_keeps_fumble(self):
        recovery = c3.FieldSpotV3(1, 'kicking_team')
        dead = c3.FieldSpotV3(0, 'kicking_team')
        recoverer = c.PlayerRoleV2.named('recoverer')
        return_facts = c3.KickReturnV3(
            'receiving_team', c.PlayerRoleV2.none(), None, dead, -1,
            c.PlayerRoleV2.named('muffing-player'), recoverer,
            c.PlayerRoleV2.named('post-recovery-runner'), recovery,
            c3.FieldSpotV3(1, 'kicking_team'))
        kick = c3.KickV3(
            'kickoff', 'A', 'B', c3.FieldSpotV3(65, 'kicking_team'), 35, 'muff',
            possession_after='receiving_team', dead_ball_spot=dead,
            receiving_restart_spot=c3.FieldSpotV3(65, 'receiving_team'),
            recovery_team='receiving_team', recovery_spot=recovery,
            recoverer=recoverer, return_facts=return_facts)
        play = c3.GeneratedPlayV3(
            contract=c3.CONTRACT_V3_VERSION, call=c.PlayCallV2('kickoff'), event='kickoff',
            yards_gained=None, fumble=True, provenance=P, clock=c.ClockV2(0), kick=kick,
            players=c.PlayerRolesV2(kicker=c.PlayerRoleV2.named('kicker')))
        applied = apply_v3_play(
            {'offense': 'A', 'defense': 'B', 'down': 1, 'togo': 10, 'yl': 65}, play)
        self.assertEqual(applied.state_after, {
            'offense': 'B', 'defense': 'A', 'down': 1, 'togo': 10, 'yl': 65})
        self.assertTrue(applied.flags['touchback'])
        self.assertTrue(applied.flags['fumble'])
        self.assertEqual(applied.flags['fumble_return_yards'], -1)

    def test_ceg_play_3_kickoff_oob_applies_typed_restart_choice(self):
        oob = c3.KickoffOutOfBoundsV3(
            'kicking_team_out_of_bounds', 'at_distance_from_kick',
            c3.FieldSpotV3(60, 'kicking_team'), c3.FieldSpotV3(60, 'receiving_team'),
            distance_yards=25)
        kick = c3.KickV3('kickoff', 'A', 'B', c3.FieldSpotV3(65, 'kicking_team'), 35,
                         'out_of_bounds', possession_after='receiving_team',
                         dead_ball_spot=c3.FieldSpotV3(60, 'kicking_team'),
                         out_of_bounds_spot=c3.FieldSpotV3(60, 'kicking_team'), kickoff_oob=oob)
        play = c3.GeneratedPlayV3(
            contract=c3.CONTRACT_V3_VERSION, call=c.PlayCallV2('kickoff'), event='kickoff',
            yards_gained=None, provenance=P, clock=c.ClockV2(5), kick=kick,
            players=c.PlayerRolesV2(kicker=c.PlayerRoleV2.named('kicker')))
        applied = apply_v3_play({'offense': 'A', 'defense': 'B', 'down': 1, 'togo': 10, 'yl': 65}, play)
        self.assertEqual(applied.state_after['offense'], 'B')
        self.assertEqual(applied.state_after['yl'], 60)
        self.assertEqual(applied.flags['kickoff_out_of_bounds_enforcement']['choice'],
                         'at_distance_from_kick')

    def test_ceg_play_3_punt_return_safety_names_scorer_and_pending_free_kick(self):
        safety = c3.KickSafetyV3(
            scoring_team='kicking_team', possessing_team='receiving_team',
            safety_dead_ball_spot=c3.FieldSpotV3(100, 'receiving_team'),
            free_kick_team='receiving_team', free_kick_spot=c3.FieldSpotV3(80, 'receiving_team'),
            free_kick_spot_basis='own_20', receiving_team='kicking_team', restart_status='pending')
        returner = c.PlayerRoleV2.named('returner')
        return_facts = c3.KickReturnV3(
            'receiving_team', returner, c3.FieldSpotV3(95, 'receiving_team'),
            c3.FieldSpotV3(100, 'receiving_team'), -5,
            c.PlayerRoleV2.none(), c.PlayerRoleV2.none(), c.PlayerRoleV2.none(),
            scoring_kind='safety', scoring_team='kicking_team')
        kick = c3.KickV3(
            'punt', 'A', 'B', c3.FieldSpotV3(40, 'kicking_team'), 45, 'return',
            possession_after='receiving_team', dead_ball_spot=c3.FieldSpotV3(0, 'kicking_team'),
            return_facts=return_facts, safety=safety)
        play = c3.GeneratedPlayV3(
            contract=c3.CONTRACT_V3_VERSION, call=c.PlayCallV2('punt'), event='punt',
            yards_gained=None, provenance=P, clock=c.ClockV2(5),
            scoring=c.ScoringV2('safety', 'kicking_team'), kick=kick,
            players=c.PlayerRolesV2(punter=c.PlayerRoleV2.named('punter'), returner=returner))
        applied = apply_v3_play(S, play)
        self.assertEqual((applied.terminal, applied.scoring_team), ('safety', 'A'))
        self.assertTrue(applied.flags['safety'])

    def test_existing_run_transition_uses_the_frozen_reducer(self):
        result = apply_scrimmage_play(S, record())
        self.assertEqual(result.state_after,
                         {'offense': 'A', 'defense': 'B', 'down': 3, 'togo': 3, 'yl': 36})
        self.assertIsNone(result.terminal)

    def test_interception_return_is_independently_switchable(self):
        possession = c.PossessionV2(
            'defense', 'interception', turnover_spot_yardline_100=40,
            dead_ball_yardline_100=50, return_yards=10,
            returner=c.PlayerRoleV2.named('db1'))
        interception = record(
            call=c.PlayCallV2('dropback'), event='interception', yards_gained=0,
            air_yards=None, yards_after_catch=None, possession=possession,
            players=c.PlayerRolesV2(passer=c.PlayerRoleV2.named('qb1'),
                                    interceptor=c.PlayerRoleV2.named('db1'),
                                    returner=c.PlayerRoleV2.named('db1')))
        with self.assertRaisesRegex(UnsupportedEventTransition, 'event_switch_disabled:interception_returns'):
            apply_scrimmage_play(S, interception, EventExpansionSwitches.from_enabled(()))
        enabled = EventExpansionSwitches.from_enabled(('interception_returns',))
        result = apply_scrimmage_play(S, interception, enabled)
        self.assertEqual(result.state_after,
                         {'offense': 'B', 'defense': 'A', 'down': 1, 'togo': 10, 'yl': 50})
        self.assertEqual(result.flags['return_yards'], 10)

    def test_pick_six_is_a_defensive_touchdown_terminal(self):
        possession = c.PossessionV2(
            'defense', 'interception', turnover_spot_yardline_100=40,
            dead_ball_yardline_100=100, return_yards=60,
            returner=c.PlayerRoleV2.named('db1'))
        interception = record(
            call=c.PlayCallV2('dropback'), event='interception', yards_gained=0,
            air_yards=None, yards_after_catch=None, possession=possession,
            scoring=c.ScoringV2('touchdown', 'defense'),
            players=c.PlayerRolesV2(passer=c.PlayerRoleV2.named('qb1'),
                                    interceptor=c.PlayerRoleV2.named('db1'),
                                    returner=c.PlayerRoleV2.named('db1')))
        switches = EventExpansionSwitches.from_enabled(('interception_returns',))
        result = apply_scrimmage_play(S, interception, switches)
        self.assertEqual((result.terminal, result.scoring_team), ('touchdown', 'B'))
        self.assertTrue(result.flags['turnover'])

    def test_defensive_return_into_its_own_end_zone_is_a_safety_for_offense(self):
        state = {'offense': 'A', 'defense': 'B', 'down': 1, 'togo': 10, 'yl': 10}
        possession = c.PossessionV2(
            'defense', 'interception', turnover_spot_yardline_100=10,
            dead_ball_yardline_100=0, return_yards=-10,
            returner=c.PlayerRoleV2.named('db1'))
        interception = record(
            call=c.PlayCallV2('dropback'), event='interception', yards_gained=0,
            air_yards=None, yards_after_catch=None, possession=possession,
            scoring=c.ScoringV2('safety', 'offense'),
            players=c.PlayerRolesV2(passer=c.PlayerRoleV2.named('qb1'),
                                    interceptor=c.PlayerRoleV2.named('db1'),
                                    returner=c.PlayerRoleV2.named('db1')))
        result = apply_scrimmage_play(
            state, interception, EventExpansionSwitches.from_enabled(('interception_returns',)))
        self.assertEqual((result.terminal, result.scoring_team), ('safety', 'A'))

    def test_interception_touchback_is_a_distinct_turnover_terminal(self):
        possession = c.PossessionV2(
            'defense', 'interception', turnover_spot_yardline_100=0,
            dead_ball_yardline_100=0, return_yards=0,
            returner=c.PlayerRoleV2.unmodelled('interceptor'),
            touchback=True, next_yardline_100=20)
        interception = record(
            call=c.PlayCallV2('dropback'), event='interception', yards_gained=0,
            air_yards=None, yards_after_catch=None, possession=possession,
            players=c.PlayerRolesV2(passer=c.PlayerRoleV2.named('qb1'),
                                    interceptor=c.PlayerRoleV2.unmodelled('interceptor')))
        with self.assertRaisesRegex(UnsupportedEventTransition,
                                    'event_switch_disabled:turnover_terminal_events'):
            apply_scrimmage_play(S, interception,
                                 EventExpansionSwitches.from_enabled(('interception_returns',)))
        result = apply_scrimmage_play(
            S, interception,
            EventExpansionSwitches.from_enabled(('turnover_terminal_events',)))
        self.assertEqual(result.terminal, 'turnover')
        self.assertEqual(result.state_after,
                         {'offense': 'B', 'defense': 'A', 'down': 1, 'togo': 10, 'yl': 20})
        self.assertTrue(result.flags['touchback'])

    def test_sack_fumble_return_preserves_sack_and_requires_goal_line_switch(self):
        possession = c.PossessionV2(
            'defense', 'fumble_recovery', turnover_spot_yardline_100=45,
            recovery_spot_yardline_100=45, dead_ball_yardline_100=100,
            return_yards=55, returner=c.PlayerRoleV2.named('de1'),
            recovered_by=c.PlayerRoleV2.named('de1'), fumble_spot_yardline_100=45)
        sack = record(
            call=c.PlayCallV2('dropback'), event='sack', yards_gained=-5,
            air_yards=None, yards_after_catch=None, fumble=True, possession=possession,
            scoring=c.ScoringV2('touchdown', 'defense'),
            players=c.PlayerRolesV2(passer=c.PlayerRoleV2.named('qb1'),
                                    sacker=c.PlayerRoleV2.named('de1'),
                                    fumbler=c.PlayerRoleV2.named('qb1'),
                                    recoverer=c.PlayerRoleV2.named('de1'),
                                    returner=c.PlayerRoleV2.named('de1')))
        switches = EventExpansionSwitches.from_enabled(
            ('sack_fumble_transitions', 'own_end_zone_recovery'))
        result = apply_scrimmage_play(S, sack, switches)
        self.assertEqual((result.terminal, result.scoring_team), ('touchdown', 'B'))
        self.assertTrue(result.flags['sack'])
        self.assertTrue(result.flags['fumble'])

    def test_retained_fumble_turnover_on_downs_uses_receiving_field_frame(self):
        state = {**S, 'down': 4}
        possession = c.PossessionV2(
            'offense', 'kept', recovery_spot_yardline_100=38,
            dead_ball_yardline_100=36, recovered_by=c.PlayerRoleV2.named('rb1'),
            fumble_spot_yardline_100=38)
        play = record(yards_gained=2, fumble=True, possession=possession,
                      players=c.PlayerRolesV2(rusher=c.PlayerRoleV2.named('rb1'),
                                              fumbler=c.PlayerRoleV2.named('rb1'),
                                              recoverer=c.PlayerRoleV2.named('rb1')))
        applied = apply_scrimmage_play(state, play)
        self.assertEqual(applied.terminal, 'turnover_on_downs')
        self.assertEqual(applied.state_after['yl'], 64)
        self.assertEqual(applied.state_after['offense'], 'B')
        self.assertEqual(applied.flags['fumble_recovery_team'], 'A')

    def test_offense_recovery_of_own_end_zone_fumble_is_a_safety(self):
        state = {'offense': 'A', 'defense': 'B', 'down': 1, 'togo': 5, 'yl': 95}
        possession = c.PossessionV2(
            'offense', 'fumble_recovery', turnover_spot_yardline_100=100,
            recovery_spot_yardline_100=100, dead_ball_yardline_100=100,
            recovered_by=c.PlayerRoleV2.named('rb1'), fumble_spot_yardline_100=100)
        run = record(yards_gained=-5, fumble=True, possession=possession,
                     scoring=c.ScoringV2('safety', 'defense'),
                     players=c.PlayerRolesV2(rusher=c.PlayerRoleV2.named('rb1'),
                                             fumbler=c.PlayerRoleV2.named('rb1'),
                                             recoverer=c.PlayerRoleV2.named('rb1')))
        switches = EventExpansionSwitches.from_enabled(('fumble_returns', 'own_end_zone_recovery'))
        result = apply_scrimmage_play(state, run, switches)
        self.assertEqual((result.terminal, result.scoring_team), ('safety', 'B'))

    def test_pre_snap_false_start_enforces_before_a_snap(self):
        foul = c.PenaltyFoulV2('false_start', 'offense', 5)
        penalty = c.PenaltyV2('pre_snap', (foul,), 'accepted', play_void=True, provenance=P)
        no_play = record(call=None, event='no_play', yards_gained=None, air_yards=None,
                         yards_after_catch=None, clock=c.ClockV2(0), players=c.PlayerRolesV2(),
                         penalty=penalty, play_void=True)
        switches = EventExpansionSwitches.from_enabled(('pre_snap_penalties',))
        result = apply_scrimmage_play(S, no_play, switches)
        self.assertEqual(result.state_after,
                         {'offense': 'A', 'defense': 'B', 'down': 2, 'togo': 12, 'yl': 45})
        self.assertFalse(result.flags['snap_occurred'])

    def test_declined_live_penalty_keeps_the_play_transition(self):
        penalty = c.PenaltyV2(
            'live_ball', (c.PenaltyFoulV2('offensive_holding', 'offense', 10),),
            'declined', provenance=P)
        completion = record(call=c.PlayCallV2('dropback'), event='pass_complete',
                            yards_gained=8, air_yards=6, yards_after_catch=2,
                            players=c.PlayerRolesV2(passer=c.PlayerRoleV2.named('qb1'),
                                                    receiver=c.PlayerRoleV2.named('wr1')),
                            penalty=penalty)
        result = apply_scrimmage_play(
            S, completion, EventExpansionSwitches.from_enabled(('live_ball_penalties',)))
        self.assertEqual(result.state_after['down'], 1)
        self.assertFalse(result.penalty_enforcement['accepted'])
        self.assertTrue(result.penalty_enforcement['play_counts'])

    def test_accepted_dpi_erases_a_fourth_down_turnover_and_awards_first_down(self):
        state = {**S, 'down': 4, 'togo': 4}
        penalty = c.PenaltyV2(
            'live_ball', (c.PenaltyFoulV2('defensive_pass_interference', 'defense', 0,
                                          foul_spot=32),),
            'accepted', automatic_first_down=True, provenance=P)
        incomplete = record(call=c.PlayCallV2('dropback'), event='pass_incomplete',
                            yards_gained=0, penalty=penalty,
                            players=c.PlayerRolesV2(passer=c.PlayerRoleV2.named('qb1')))
        result = apply_scrimmage_play(state, incomplete, EventExpansionSwitches())
        self.assertIsNone(result.terminal)
        self.assertEqual(result.state_after, {'offense': 'A', 'defense': 'B', 'down': 1, 'togo': 10, 'yl': 32})
        self.assertFalse(result.flags['turnover'])
        self.assertFalse(result.flags['turnover_on_downs'])
        self.assertFalse(result.flags['touchdown'])
        self.assertFalse(result.penalty_enforcement['play_counts'])

    def test_accepted_dpi_cancels_interception_return_and_keeps_offensive_possession(self):
        possession = c.PossessionV2(
            'defense', 'interception', turnover_spot_yardline_100=30,
            dead_ball_yardline_100=40, return_yards=10,
            returner=c.PlayerRoleV2.named('db1'))
        penalty = c.PenaltyV2(
            'live_ball', (c.PenaltyFoulV2('defensive_pass_interference', 'defense', 0,
                                          foul_spot=32),),
            'accepted', automatic_first_down=True, provenance=P)
        interception = record(
            call=c.PlayCallV2('dropback'), event='interception', yards_gained=0,
            air_yards=None, yards_after_catch=None, possession=possession, penalty=penalty,
            players=c.PlayerRolesV2(passer=c.PlayerRoleV2.named('qb1'),
                                    interceptor=c.PlayerRoleV2.named('db1'),
                                    returner=c.PlayerRoleV2.named('db1')))
        result = apply_scrimmage_play(S, interception, EventExpansionSwitches())
        self.assertIsNone(result.terminal)
        self.assertEqual(result.state_after,
                         {'offense': 'A', 'defense': 'B', 'down': 1, 'togo': 10, 'yl': 32})
        self.assertIsNone(result.scoring_team)
        self.assertFalse(result.flags['turnover'])
        self.assertFalse(result.flags['interception'])
        self.assertNotIn('return_yards', result.flags)
        self.assertNotIn('return_team', result.flags)

    def test_accepted_penalty_cancels_touchdown_and_declined_penalty_keeps_it(self):
        accepted = c.PenaltyV2(
            'live_ball', (c.PenaltyFoulV2('defensive_pass_interference', 'defense', 0,
                                          foul_spot=8),),
            'accepted', automatic_first_down=True, provenance=P)
        touchdown = record(call=c.PlayCallV2('dropback'), event='pass_complete',
                           yards_gained=40, air_yards=35, yards_after_catch=5,
                           scoring=c.ScoringV2('touchdown', 'offense'), penalty=accepted,
                           players=c.PlayerRolesV2(passer=c.PlayerRoleV2.named('qb1'),
                                                   receiver=c.PlayerRoleV2.named('wr1')))
        result = apply_scrimmage_play(S, touchdown, EventExpansionSwitches())
        self.assertIsNone(result.terminal)
        self.assertIsNone(result.scoring_team)
        self.assertEqual(result.state_after['yl'], 8)
        self.assertFalse(result.flags['touchdown'])
        self.assertFalse(result.penalty_enforcement['play_counts'])

        declined = c.PenaltyV2('live_ball', accepted.fouls, 'declined', provenance=P)
        touchdown = record(call=c.PlayCallV2('dropback'), event='pass_complete',
                           yards_gained=40, air_yards=35, yards_after_catch=5,
                           scoring=c.ScoringV2('touchdown', 'offense'), penalty=declined,
                           players=c.PlayerRolesV2(passer=c.PlayerRoleV2.named('qb1'),
                                                   receiver=c.PlayerRoleV2.named('wr1')))
        result = apply_scrimmage_play(S, touchdown, EventExpansionSwitches())
        self.assertEqual((result.terminal, result.scoring_team), ('touchdown', 'A'))
        self.assertTrue(result.flags['touchdown'])
        self.assertTrue(result.penalty_enforcement['play_counts'])

    def test_penalty_source_yards_must_be_nominal_not_enforced_yards(self):
        penalty = c.PenaltyV2(
            'live_ball', (c.PenaltyFoulV2('Offensive Holding', 'offense', 5),),
            'accepted', provenance=P)
        call = record(penalty=penalty)
        with self.assertRaisesRegex(UnsupportedEventTransition,
                                    'penalty_nominal_yards_disagree_with_rule:offense:'):
            apply_scrimmage_play(S, call,
                                 EventExpansionSwitches.from_enabled(('live_ball_penalties',)))

    def test_dpi_is_enabled_by_default_and_enforces_its_foul_spot_with_nominal_zero(self):
        penalty = c.PenaltyV2(
            'live_ball', (c.PenaltyFoulV2(
                'defensive_pass_interference', 'defense', 0, foul_spot=0),),
            'accepted', automatic_first_down=True, provenance=P)
        incomplete = record(
            call=c.PlayCallV2('dropback'), event='pass_incomplete', yards_gained=0,
            penalty=penalty,
            players=c.PlayerRolesV2(passer=c.PlayerRoleV2.named('qb1')))
        result = apply_scrimmage_play(S, incomplete, EventExpansionSwitches())
        self.assertEqual(result.state_after,
                         {'offense': 'A', 'defense': 'B', 'down': 1, 'togo': 1, 'yl': 1.0})
        self.assertTrue(result.penalty_enforcement['accepted'])
        self.assertEqual(result.penalty_enforcement['yards'], 39.0)
        self.assertTrue(result.flags['penalty'])
        self.assertTrue(result.flags['automatic_first_down'])

    def test_pre_snap_penalty_returns_a_no_snap_replay_transition(self):
        penalty = c.PenaltyV2(
            'pre_snap', (c.PenaltyFoulV2('false_start', 'offense', 5),),
            'accepted', provenance=P, play_void=True)
        no_play = c.GeneratedPlayV2(
            c.CONTRACT_V2_VERSION, None, 'no_play', None, P,
            c.ClockV2(0, 0, 0, 'stopped'), penalty=penalty, play_void=True)
        result = apply_scrimmage_play(S, no_play, EventExpansionSwitches())
        self.assertEqual(result.state_after['down'], S['down'])
        self.assertEqual(result.state_after['yl'], 45.0)
        self.assertIsNone(result.terminal)
        self.assertTrue(result.flags['no_play'])
        self.assertTrue(result.flags['penalty'])

    def test_offsetting_live_ball_penalties_replay_the_down_without_counting_play(self):
        penalty = c.PenaltyV2(
            'live_ball', (c.PenaltyFoulV2('offensive_holding', 'offense', 10),
                          c.PenaltyFoulV2('defensive_holding', 'defense', 5)),
            'offsetting', provenance=P)
        call = record(penalty=penalty)
        result = apply_scrimmage_play(
            S, call, EventExpansionSwitches.from_enabled(('live_ball_penalties',)))
        self.assertEqual(result.state_after, S)
        self.assertIsNone(result.terminal)
        self.assertFalse(result.penalty_enforcement['accepted'])
        self.assertTrue(result.penalty_enforcement['offsetting'])
        self.assertFalse(result.penalty_enforcement['play_counts'])
        self.assertTrue(result.flags['penalty'])

    def test_offsetting_penalties_with_turnover_fail_closed_without_foul_order(self):
        possession = c.PossessionV2(
            'defense', 'interception', turnover_spot_yardline_100=40,
            dead_ball_yardline_100=50, return_yards=10,
            returner=c.PlayerRoleV2.named('db1'))
        penalty = c.PenaltyV2(
            'live_ball', (c.PenaltyFoulV2('offensive_holding', 'offense', 10),
                          c.PenaltyFoulV2('defensive_holding', 'defense', 5)),
            'offsetting', provenance=P)
        interception = record(call=c.PlayCallV2('dropback'), event='interception',
                              yards_gained=0, air_yards=None, yards_after_catch=None,
                              possession=possession, penalty=penalty,
                              players=c.PlayerRolesV2(passer=c.PlayerRoleV2.named('qb1'),
                                                      interceptor=c.PlayerRoleV2.named('db1'),
                                                      returner=c.PlayerRoleV2.named('db1')))
        with self.assertRaisesRegex(UnsupportedEventTransition,
                                    'offsetting_penalty_turnover_sequence_needs_foul_order'):
            apply_scrimmage_play(S, interception, EventExpansionSwitches())

    def test_multiple_accepted_fouls_fail_closed_until_shared_contract_supports_selection(self):
        penalty = c.PenaltyV2(
            'live_ball', (c.PenaltyFoulV2('defensive_holding', 'defense', 5),
                          c.PenaltyFoulV2('offensive_holding', 'offense', 10)),
            'accepted', automatic_first_down=True, provenance=P)
        call = record(call=c.PlayCallV2('dropback'), event='pass_incomplete',
                      yards_gained=0, air_yards=None, yards_after_catch=None, penalty=penalty,
                      players=c.PlayerRolesV2(passer=c.PlayerRoleV2.named('qb1')))
        with self.assertRaisesRegex(ValueError, 'multiple_fouls_need_offsetting_or_named_rules_support'):
            apply_scrimmage_play(S, call, EventExpansionSwitches())

    def test_accepted_offensive_foul_in_own_end_zone_is_a_safety(self):
        state = {'offense': 'A', 'defense': 'B', 'down': 2, 'togo': 7, 'yl': 99}
        penalty = c.PenaltyV2(
            'live_ball', (c.PenaltyFoulV2('offensive_holding', 'offense', 10,
                                          foul_spot=100),),
            'accepted', provenance=P)
        call = record(call=c.PlayCallV2('designed_run'), yards_gained=0,
                      penalty=penalty)
        result = apply_scrimmage_play(
            state, call, EventExpansionSwitches.from_enabled(('live_ball_penalties',)))
        self.assertEqual((result.terminal, result.scoring_team), ('safety', 'B'))
        self.assertIsNone(result.state_after)
        self.assertTrue(result.flags['safety'])
        self.assertFalse(result.flags['touchdown'])

    def test_punt_return_touchdown_uses_explicit_return_endpoint(self):
        kick = c.KickV2('punt', 'A', 'B', 40, 45, 'return',
                        possession_after='receiving_team', return_start_yardline_100=20,
                        dead_ball_yardline_100=100, return_yards=80,
                        returner=c.PlayerRoleV2.named('pr1'))
        punt = record(call=c.PlayCallV2('punt'), event='punt', yards_gained=None,
                      air_yards=None, yards_after_catch=None, kick=kick,
                      scoring=c.ScoringV2('touchdown', 'receiving_team'),
                      players=c.PlayerRolesV2(punter=c.PlayerRoleV2.named('p1'),
                                              returner=c.PlayerRoleV2.named('pr1')))
        result = apply_punt_play(S, punt, EventExpansionSwitches.from_enabled(('punt_return_events',)))
        self.assertEqual((result.terminal, result.scoring_team), ('touchdown', 'B'))

    def test_punt_return_safety_fails_closed_until_shared_contract_supports_it(self):
        kick = c.KickV2('punt', 'A', 'B', 40, 45, 'return',
                        possession_after='receiving_team', return_start_yardline_100=5,
                        dead_ball_yardline_100=0, return_yards=-5,
                        returner=c.PlayerRoleV2.named('pr1'))
        punt = record(call=c.PlayCallV2('punt'), event='punt', yards_gained=None,
                      air_yards=None, yards_after_catch=None, kick=kick,
                      scoring=c.ScoringV2('safety', 'kicking_team'),
                      players=c.PlayerRolesV2(punter=c.PlayerRoleV2.named('p1'),
                                              returner=c.PlayerRoleV2.named('pr1')))
        with self.assertRaisesRegex(c.ContractViolationV2, 'kick_safety_unsupported'):
            apply_punt_play(S, punt, EventExpansionSwitches())

    def test_punt_touchback_requires_the_punt_event_switch(self):
        kick = c.KickV2('punt', 'A', 'B', 40, 45, 'touchback',
                        possession_after='receiving_team', dead_ball_yardline_100=20)
        punt = record(call=c.PlayCallV2('punt'), event='punt', yards_gained=None,
                      air_yards=None, yards_after_catch=None, kick=kick,
                      players=c.PlayerRolesV2(punter=c.PlayerRoleV2.named('p1')))
        with self.assertRaisesRegex(UnsupportedEventTransition,
                                    'event_switch_disabled:punt_return_events'):
            apply_punt_play(S, punt, EventExpansionSwitches.from_enabled(()))
        result = apply_punt_play(
            S, punt, EventExpansionSwitches.from_enabled(('punt_return_events',)))
        self.assertEqual((result.state_after['offense'], result.state_after['yl']), ('B', 80))

    def test_kneel_requires_its_switch_and_uses_a_rusher(self):
        kneel = record(call=c.PlayCallV2('kneel'), event='kneel', yards_gained=-1,
                       players=c.PlayerRolesV2(rusher=c.PlayerRoleV2.named('qb1')))
        with self.assertRaisesRegex(UnsupportedEventTransition,
                                    'event_switch_disabled:kneel_events'):
            apply_scrimmage_play(S, kneel, EventExpansionSwitches.from_enabled(()))
        result = apply_scrimmage_play(
            S, kneel, EventExpansionSwitches.from_enabled(('kneel_events',)))
        self.assertEqual(result.state_after['down'], 3)
        self.assertEqual(result.state_after['yl'], 41)

    def test_spike_requires_its_switch_and_is_marked_in_result(self):
        spike = record(call=c.PlayCallV2('spike'), event='spike', yards_gained=0,
                       players=c.PlayerRolesV2(passer=c.PlayerRoleV2.named('qb1')))
        with self.assertRaisesRegex(UnsupportedEventTransition,
                                    'event_switch_disabled:spike_events'):
            apply_scrimmage_play(S, spike, EventExpansionSwitches.from_enabled(()))
        result = apply_scrimmage_play(
            S, spike, EventExpansionSwitches.from_enabled(('spike_events',)))
        self.assertTrue(result.flags['spike'])
        self.assertEqual(result.state_after['down'], 3)

    def test_punt_return_uses_kicking_frame_then_converts_to_receiving_frame(self):
        kick = c.KickV2('punt', 'A', 'B', 40, 45, 'return',
                        possession_after='receiving_team', return_start_yardline_100=20,
                        dead_ball_yardline_100=15, return_yards=-5,
                        returner=c.PlayerRoleV2.named('pr1'))
        punt = record(call=c.PlayCallV2('punt'), event='punt', yards_gained=None,
                      air_yards=None, yards_after_catch=None, kick=kick,
                      players=c.PlayerRolesV2(punter=c.PlayerRoleV2.unmodelled('punter'),
                                              returner=c.PlayerRoleV2.named('pr1')))
        result = apply_punt_play(S, punt, EventExpansionSwitches.from_enabled(('punt_return_events',)))
        self.assertEqual((result.state_after['offense'], result.state_after['yl']), ('B', 85))
        self.assertEqual(result.flags['return_yards'], -5)

    def test_negative_punt_return_must_match_dead_ball_spot(self):
        kick = c.KickV2('punt', 'A', 'B', 40, 45, 'return',
                        possession_after='receiving_team', return_start_yardline_100=20,
                        dead_ball_yardline_100=16, return_yards=-5,
                        returner=c.PlayerRoleV2.named('pr1'))
        punt = record(call=c.PlayCallV2('punt'), event='punt', yards_gained=None,
                      air_yards=None, yards_after_catch=None, kick=kick,
                      players=c.PlayerRolesV2(punter=c.PlayerRoleV2.unmodelled('punter'),
                                              returner=c.PlayerRoleV2.named('pr1')))
        with self.assertRaisesRegex(UnsupportedEventTransition,
                                    'punt_return_yards_disagree_with_dead_ball_spot'):
            apply_punt_play(S, punt, EventExpansionSwitches.from_enabled(('punt_return_events',)))

    def test_muffed_punt_recovered_by_receiver_starts_at_dead_ball_spot(self):
        kick = c.KickV2('punt', 'A', 'B', 40, 45, 'muff',
                        possession_after='receiving_team', recovery_team='receiving_team',
                        recovery_yardline_100=25, dead_ball_yardline_100=25,
                        return_yards=0, recoverer=c.PlayerRoleV2.unmodelled('punt_recoverer'),
                        returner=c.PlayerRoleV2.unmodelled('punt_fumbler'),
                        fumble_spot_yardline_100=75)
        punt = record(call=c.PlayCallV2('punt'), event='punt', yards_gained=None,
                      air_yards=None, yards_after_catch=None, kick=kick, fumble=True,
                      players=c.PlayerRolesV2(punter=c.PlayerRoleV2.unmodelled('punter'),
                                              returner=c.PlayerRoleV2.unmodelled('punt_fumbler'),
                                              fumbler=c.PlayerRoleV2.unmodelled('punt_fumbler')))
        result = apply_punt_play(S, punt, EventExpansionSwitches.from_enabled(('punt_return_events',)))
        self.assertEqual((result.state_after['offense'], result.state_after['yl']), ('B', 75))

    def test_muffed_punt_recovered_by_kickers_requires_touch_and_keeps_possession(self):
        kick = c.KickV2('punt', 'A', 'B', 40, 45, 'muff',
                        possession_after='kicking_team', recovery_team='kicking_team',
                        recovery_yardline_100=30, dead_ball_yardline_100=30, return_yards=0,
                        receiving_team_touched_beyond_line=True,
                        returner=c.PlayerRoleV2.unmodelled('punt_fumbler'),
                        recoverer=c.PlayerRoleV2.unmodelled('punt_recoverer'),
                        fumble_spot_yardline_100=50)
        punt = record(call=c.PlayCallV2('punt'), event='punt', yards_gained=None,
                      air_yards=None, yards_after_catch=None, kick=kick, fumble=True,
                      players=c.PlayerRolesV2(punter=c.PlayerRoleV2.unmodelled('punter'),
                                              fumbler=c.PlayerRoleV2.unmodelled('punt_fumbler')))
        result = apply_punt_play(S, punt, EventExpansionSwitches.from_enabled(('punt_return_events',)))
        self.assertEqual((result.state_after['offense'], result.state_after['yl']), ('A', 30))
        self.assertTrue(result.flags['possession_retained'])

    def test_field_goal_attempt_adapter_reports_made_and_missed_results(self):
        common = dict(call=c.PlayCallV2('field_goal'), event='field_goal_attempt',
                      yards_gained=None, air_yards=None, yards_after_catch=None,
                      players=c.PlayerRolesV2(kicker=c.PlayerRoleV2.named('k1')))
        made = record(**{**common,
                         'kick': c.KickV2('field_goal', 'A', 'B', 47, 64, 'made'),
                         'scoring': c.ScoringV2('field_goal', 'kicking_team')})
        result = apply_field_goal_play(S, made, EventExpansionSwitches())
        self.assertEqual((result.terminal, result.scoring_team), ('field_goal_attempt', 'A'))
        self.assertEqual(result.flags['field_goal_result'], 'made')
        missed = record(**{**common,
                           'kick': c.KickV2('field_goal', 'A', 'B', 47, 64, 'missed',
                                            possession_after='receiving_team')})
        result = apply_field_goal_play(S, missed, EventExpansionSwitches())
        self.assertIsNone(result.scoring_team)
        self.assertEqual(result.flags['field_goal_result'], 'missed')

    def test_kickoff_touchback_and_return_touchdown_use_kicking_team_frame(self):
        state = {**S, 'offense': 'A', 'defense': 'B', 'yl': 65}
        touchback = record(
            call=c.PlayCallV2('kickoff'), event='kickoff', yards_gained=None,
            air_yards=None, yards_after_catch=None,
            kick=c.KickV2('kickoff', 'A', 'B', 65, 65, 'touchback',
                          possession_after='receiving_team', dead_ball_yardline_100=35))
        result = apply_kickoff_play(state, touchback, EventExpansionSwitches())
        self.assertEqual((result.state_after['offense'], result.state_after['yl']), ('B', 65))
        returned = record(
            call=c.PlayCallV2('kickoff'), event='kickoff', yards_gained=None,
            air_yards=None, yards_after_catch=None,
            kick=c.KickV2('kickoff', 'A', 'B', 65, 65, 'return',
                          possession_after='receiving_team', return_start_yardline_100=20,
                          dead_ball_yardline_100=100, return_yards=80,
                          returner=c.PlayerRoleV2.named('kr1')),
            players=c.PlayerRolesV2(returner=c.PlayerRoleV2.named('kr1')),
            scoring=c.ScoringV2('touchdown', 'receiving_team'))
        result = apply_kickoff_play(state, returned, EventExpansionSwitches())
        self.assertEqual((result.terminal, result.scoring_team), ('touchdown', 'B'))

    def test_kickoff_return_safety_fails_closed_until_shared_contract_supports_it(self):
        state = {**S, 'offense': 'A', 'defense': 'B', 'yl': 65}
        returned = record(
            call=c.PlayCallV2('kickoff'), event='kickoff', yards_gained=None,
            air_yards=None, yards_after_catch=None,
            kick=c.KickV2('kickoff', 'A', 'B', 65, 65, 'return',
                          possession_after='receiving_team', return_start_yardline_100=5,
                          dead_ball_yardline_100=0, return_yards=-5,
                          returner=c.PlayerRoleV2.named('kr1')),
            players=c.PlayerRolesV2(returner=c.PlayerRoleV2.named('kr1')),
            scoring=c.ScoringV2('safety', 'kicking_team'))
        with self.assertRaisesRegex(c.ContractViolationV2, 'kick_safety_unsupported'):
            apply_kickoff_play(state, returned, EventExpansionSwitches())

    def test_punt_nonreturns_keep_distinct_event_class_and_no_return_stats(self):
        state = {**S, 'offense': 'A', 'defense': 'B', 'yl': 40}
        cases = ('downed', 'out_of_bounds', 'fair_catch')
        for result_name in cases:
            with self.subTest(result=result_name):
                kick = c.KickV2(
                    'punt', 'A', 'B', 40, 50, result_name,
                    possession_after='receiving_team',
                    dead_ball_yardline_100=30,
                    return_start_yardline_100=(30 if result_name == 'fair_catch' else None),
                    returner=(c.PlayerRoleV2.named('catcher') if result_name == 'fair_catch'
                              else c.PlayerRoleV2.none()))
                play = record(call=c.PlayCallV2('punt'), event='punt', yards_gained=None,
                              air_yards=None, yards_after_catch=None, kick=kick,
                              players=c.PlayerRolesV2(punter=c.PlayerRoleV2.unmodelled('punter'),
                                                      returner=kick.returner))
                with self.assertRaisesRegex(UnsupportedEventTransition,
                                            'punt_result_requires_ceg_play_2_extension:' + result_name):
                    apply_punt_play(state, play, EventExpansionSwitches())

    def test_kickoff_out_of_bounds_fails_closed_without_shared_contract_fields(self):
        state = {**S, 'offense': 'A', 'defense': 'B', 'yl': 65}
        play = record(
            call=c.PlayCallV2('kickoff'), event='kickoff', yards_gained=None,
            air_yards=None, yards_after_catch=None,
            kick=c.KickV2('kickoff', 'A', 'B', 65, 65, 'out_of_bounds',
                          possession_after='receiving_team', dead_ball_yardline_100=40,
                          out_of_bounds=True))
        with self.assertRaisesRegex(UnsupportedEventTransition,
                                    'kickoff_out_of_bounds_requires_ceg_play_2_extension'):
            apply_kickoff_play(state, play, EventExpansionSwitches())

    def test_kickoff_onside_recovery_retains_kicking_team_possession(self):
        state = {**S, 'offense': 'A', 'defense': 'B', 'yl': 65}
        onside = record(
            call=c.PlayCallV2('kickoff'), event='kickoff', yards_gained=None,
            air_yards=None, yards_after_catch=None,
            kick=c.KickV2('kickoff', 'A', 'B', 65, 10, 'onside_recovery',
                          possession_after='kicking_team', recovery_team='kicking_team',
                          recovery_yardline_100=55,
                          recoverer=c.PlayerRoleV2.named('k1')))
        result = apply_kickoff_play(state, onside, EventExpansionSwitches())
        self.assertEqual((result.state_after['offense'], result.state_after['yl']), ('A', 55))

    def test_untouched_onside_recovery_before_ten_yards_is_rejected(self):
        state = {**S, 'offense': 'A', 'defense': 'B', 'yl': 65}
        onside = record(
            call=c.PlayCallV2('kickoff'), event='kickoff', yards_gained=None,
            air_yards=None, yards_after_catch=None,
            kick=c.KickV2('kickoff', 'A', 'B', 65, 5, 'onside_recovery',
                          possession_after='kicking_team', recovery_team='kicking_team',
                          recovery_yardline_100=60,
                          receiving_team_touched_beyond_line=False,
                          recoverer=c.PlayerRoleV2.named('k1')))
        with self.assertRaisesRegex(UnsupportedEventTransition,
                                    'onside_recovery_before_ten_yards_without_receiving_touch'):
            apply_kickoff_play(state, onside, EventExpansionSwitches())

    def test_receiving_touch_allows_onside_recovery_before_ten_yards(self):
        state = {**S, 'offense': 'A', 'defense': 'B', 'yl': 65}
        onside = record(
            call=c.PlayCallV2('kickoff'), event='kickoff', yards_gained=None,
            air_yards=None, yards_after_catch=None,
            kick=c.KickV2('kickoff', 'A', 'B', 65, 5, 'onside_recovery',
                          possession_after='kicking_team', recovery_team='kicking_team',
                          recovery_yardline_100=60,
                          receiving_team_touched_beyond_line=True,
                          recoverer=c.PlayerRoleV2.named('k1')))
        result = apply_kickoff_play(state, onside, EventExpansionSwitches())
        self.assertEqual((result.state_after['offense'], result.state_after['yl']), ('A', 60))


if __name__ == '__main__':
    unittest.main()
