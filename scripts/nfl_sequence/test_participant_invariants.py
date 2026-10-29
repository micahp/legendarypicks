"""A pass has a rostered passer and a rostered receiver, and they are different players. A run names a rusher and nobody else.

Roles are not fixed by position. The starting QB is the default passer, but a non-QB sometimes throws (a trick play) and a QB
sometimes catches. The trick rates are parameters, so these tests can set them to 0 or 1 and check each behaviour exactly.
"""
import random
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import pre_event as pe  # noqa: E402
import slc_playcall as slc  # noqa: E402
from test_pre_event import SNAPSHOT, FakeReference  # noqa: E402
from test_slc_playcall import STATE, blank_artifact, cell  # noqa: E402

NO_TRICKS = {'trick_passer_rate': 0.0, 'qb_receiver_rate': 0.0}
ALWAYS_TRICK = {'trick_passer_rate': 1.0, 'qb_receiver_rate': 1.0}


def rostered(team_side, gsis):
    return any(p['gsis_id'] == gsis for p in SNAPSHOT['rosters'][team_side]['players'])


class Roles(unittest.TestCase):
    def test_every_dropback_names_a_rostered_passer_and_a_different_rostered_receiver(self):
        for seed in range(1, 201):
            chosen = pe.choose(SNAPSHOT, 'home', 'dropback', seed=seed, index=0)
            self.assertTrue(rostered('home', chosen['passer']['gsis_id']), seed)
            self.assertTrue(rostered('home', chosen['receiver']['gsis_id']), seed)
            self.assertNotEqual(chosen['passer']['gsis_id'], chosen['receiver']['gsis_id'], seed)

    def test_with_no_trick_plays_the_starting_qb_throws_and_a_skill_player_catches(self):
        for seed in range(1, 201):
            chosen = pe.choose(SNAPSHOT, 'home', 'dropback', seed=seed, index=0, **NO_TRICKS)
            self.assertEqual(chosen['passer']['gsis_id'], 'AQB1', seed)
            self.assertIn(chosen['receiver']['pos_abb'], {'WR', 'TE', 'RB'}, seed)

    def test_a_run_names_a_rusher_and_no_passer_or_target(self):
        for seed in range(1, 51):
            chosen = pe.choose(SNAPSHOT, 'home', 'run', seed=seed, index=0)
            self.assertIn('rusher', chosen, seed)
            self.assertNotIn('passer', chosen, seed)
            self.assertNotIn('receiver', chosen, seed)

    def test_a_team_without_a_starting_qb_gets_no_target_at_all(self):
        players = [p for p in SNAPSHOT['rosters']['home']['players'] if p['gsis_id'] != 'AQB1']
        broken = {**SNAPSHOT, 'rosters': {**SNAPSHOT['rosters'], 'home': {**SNAPSHOT['rosters']['home'], 'players': players}}}
        with self.assertRaises(ValueError):
            pe.choose(broken, 'home', 'dropback', seed=7, index=0)


class TrickPlays(unittest.TestCase):
    """The rare non-QB throw and QB catch are drawn from their rates, and the passer never receives his own throw."""

    def test_a_drawn_trick_passer_is_a_rostered_skill_player_who_is_not_the_starting_qb(self):
        for seed in range(1, 51):
            chosen = pe.choose(SNAPSHOT, 'home', 'dropback', seed=seed, index=0, trick_passer_rate=1.0, qb_receiver_rate=0.0)
            self.assertIn(chosen['passer']['pos_abb'], {'RB', 'WR', 'TE'}, seed)
            self.assertTrue(rostered('home', chosen['passer']['gsis_id']), seed)

    def test_the_trick_passer_does_not_also_receive(self):
        for seed in range(1, 51):
            chosen = pe.choose(SNAPSHOT, 'home', 'dropback', seed=seed, index=0, **ALWAYS_TRICK)
            self.assertNotEqual(chosen['passer']['gsis_id'], chosen['receiver']['gsis_id'], seed)

    def test_a_drawn_qb_catch_is_a_rostered_backup_quarterback_throwing_to_the_starter(self):
        for seed in range(1, 51):
            chosen = pe.choose(SNAPSHOT, 'home', 'dropback', seed=seed, index=0, trick_passer_rate=0.0, qb_receiver_rate=1.0)
            self.assertEqual(chosen['passer']['gsis_id'], 'AQB1', seed)
            self.assertEqual(chosen['receiver']['gsis_id'], 'AQB2', seed)

    def test_the_default_trick_rates_are_the_measured_rates(self):
        self.assertAlmostEqual(pe.TRICK_PASSER_RATE, 63 / 35293, places=6)
        self.assertAlmostEqual(pe.QB_RECEIVER_RATE, 17 / 33802, places=6)


class Credit(unittest.TestCase):
    """The engine credits the chosen players to the outcome. A pass event with no passer chosen is a broken selection."""

    def _play(self, event, pre):
        facts = {'play_type': 'pass', 'posteam': 'AAA'}
        ref = FakeReference({('g', 1): facts}, None)
        play = {'event_type': event, 'sequence': 9,
                'outcome': {'sampled_from': {'game_id': 'g', 'play_id': 1}, 'pre_event': pre}}
        return ref, play

    def test_a_completion_with_a_target_but_no_passer_fails_closed(self):
        receiver = SNAPSHOT['rosters']['home']['players'][3]
        ref, play = self._play('pass_complete', {'side': 'home', 'team': 'AAA', 'receiver': receiver})
        with self.assertRaises(ValueError):
            ref.participants_for(play, offense_team='A', snapshot=SNAPSHOT, seed=7)

    def test_an_incompletion_with_a_target_but_no_passer_fails_closed(self):
        receiver = SNAPSHOT['rosters']['home']['players'][3]
        ref, play = self._play('pass_incomplete', {'side': 'home', 'team': 'AAA', 'receiver': receiver})
        with self.assertRaises(ValueError):
            ref.participants_for(play, offense_team='A', snapshot=SNAPSHOT, seed=7)

    def test_a_sack_with_no_passer_fails_closed(self):
        ref, play = self._play('sack', {'side': 'home', 'team': 'AAA'})
        with self.assertRaises(ValueError):
            ref.participants_for(play, offense_team='A', snapshot=SNAPSHOT, seed=7)

    def test_a_pass_with_a_rusher_only_choice_fails_closed(self):
        rusher = SNAPSHOT['rosters']['home']['players'][2]
        ref, play = self._play('pass_complete', {'side': 'home', 'team': 'AAA', 'rusher': rusher})
        with self.assertRaises(ValueError):
            ref.participants_for(play, offense_team='A', snapshot=SNAPSHOT, seed=7)


class DecisionRecord(unittest.TestCase):
    """What the sampler writes down for each play: a dropback record names a passer and a different target, a run names a rusher."""

    def test_every_recorded_dropback_has_a_passer_and_a_target_and_every_run_has_a_rusher(self):
        sampler = slc.PlayCallSampler(slc.PlayCallLayer(blank_artifact(0.0)), side_teams={'A': 'AAA', 'B': 'BBB'})
        pool = cell([('run', 'run'), ('pass_complete', 'pass'), ('pass_incomplete', 'pass')])
        seen = {'dropback': 0, 'run': 0}
        for seed in range(1, 101):
            sampler.participant_chooser = pe.chooser(SNAPSHOT, seed=seed)
            sampler.sample(random.Random(seed), pool, 'A', 'B', state=dict(STATE))
            record = sampler.decisions[-1]
            participants = record['participants']
            if record['intent'] == 'dropback':
                seen['dropback'] += 1
                self.assertIn('passer', participants, seed)
                self.assertIn('receiver', participants, seed)
                self.assertNotEqual(participants['passer'], participants['receiver'], seed)
            else:
                seen['run'] += 1
                self.assertIn('rusher', participants, seed)
                self.assertNotIn('passer', participants, seed)
                self.assertNotIn('receiver', participants, seed)
        self.assertGreater(seen['dropback'], 0)
        self.assertGreater(seen['run'], 0)


class WithDecisionLabels(unittest.TestCase):
    """The decision labels pick the target's role and the outcome. With no trick plays, the starting QB still throws."""

    def test_a_drawn_target_role_keeps_the_starting_qb_as_passer(self):
        from test_decision_layer import CELL, table_forcing
        for role in ('TE', 'WR', 'RB', 'Other'):
            table = table_forcing({'A': role}, CELL)
            for seed in range(1, 41):
                chosen = pe.choose(SNAPSHOT, 'home', 'dropback', seed=seed, index=0, state=STATE,
                                   player_shares={'receive': {}, 'carry': {}}, decision_table=table, **NO_TRICKS)
                self.assertEqual(chosen['passer']['gsis_id'], 'AQB1', (role, seed))
                self.assertIn(chosen['receiver']['pos_abb'], {'WR', 'TE', 'RB'}, (role, seed))

    def test_the_decision_record_of_a_labelled_dropback_names_a_passer_and_a_different_target(self):
        from test_decision_layer import CELL, table_forcing
        table = table_forcing({'A': 'TE', 'E': 'left'}, CELL)
        pool = cell([('run', 'run'), ('pass_complete', 'pass'), ('pass_incomplete', 'pass')])
        sampler = slc.PlayCallSampler(slc.PlayCallLayer(blank_artifact(30.0)), side_teams={'A': 'AAA', 'B': 'BBB'})
        sampler.decision_table = table
        sampler.decision_outcomes = True
        for seed in range(1, 41):
            sampler.participant_chooser = pe.chooser(SNAPSHOT, seed=seed, decision_table=table)
            sampler.sample(random.Random(seed), pool, 'A', 'B', state=dict(STATE))
            record = sampler.decisions[-1]
            if record['intent'] == 'dropback':
                self.assertIn('passer', record['participants'], seed)
                self.assertIn('receiver', record['participants'], seed)
                self.assertNotEqual(record['participants']['passer'], record['participants']['receiver'], seed)


if __name__ == '__main__':
    unittest.main()
