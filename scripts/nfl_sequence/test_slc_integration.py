"""Runtime integration: one Week 8 game through the full SLC path, checking the stage order and the reconciled statistics.

Skipped when the database or the frozen snapshot is not present on this machine. The checks are on the record the engine returns,
so they test the path as it runs, not a unit in isolation.
"""
import collections
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
REPO = HERE.parents[1]
DB = '/root/legendarypicks/backend/data/picks.dev.db'
SNAPSHOT = REPO / 'docs/research/slc-week8-2026/snapshots/2026_08_CAR_GB.json'
ARTIFACT = REPO / 'docs/research/SLC-PLAYCALL-ARTIFACT-v1.json'
PASS_EVENTS = ('pass_complete', 'pass_incomplete', 'interception')
RUSH_EVENTS = ('run',)


@unittest.skipUnless(Path(DB).exists() and SNAPSHOT.exists(), 'database or frozen snapshot not present')
class Game(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import json
        import pregame_snapshot as ps
        import slc_engine as se
        snapshot = ps.load_frozen_snapshot(str(SNAPSHOT))
        ref, _excluded = se.load_reference(DB, snapshot, str(ARTIFACT), team_outcomes=True, formation=True,
                                           coverage=True)
        snapshot['model_reference']['observed_reference'] = ref.model_inputs
        cls.record, cls.decisions = se.play(1, ref, snapshot)
        cls.plays = [p for d in cls.record['drives'] for p in d['plays']]
        cls.engine = se
        cls.json = json

    def test_the_decisions_and_the_plays_are_the_same_sequence(self):
        # Official drives are only the committed prefix. A blocked game can also
        # retain raw plays from the unresolved drive and its unresolved decision.
        blocked = self.record.get('blocked_attempt') or {}
        partial_plays = blocked.get('plays_before_block') or []
        unresolved = blocked.get('unrepresented_decisions') or []
        self.assertEqual(
            len(self.decisions), len(self.plays) + len(partial_plays) + len(unresolved))
        self.assertEqual([d['event'] for d in self.decisions[:len(self.plays)]],
                         [p['event_type'] for p in self.plays])
        for decision, play in zip(self.decisions[len(self.plays):], partial_plays):
            self.assertTrue(
                self.engine._decision_resolves_to_event(decision, play['event_type']),
                f"blocked-attempt decision {decision.get('event')} does not resolve to {play['event_type']}",
            )
        self.assertEqual(self.decisions[len(self.plays) + len(partial_plays):], unresolved)

    def test_every_scrimmage_decision_names_a_formation_before_its_outcome(self):
        scrimmage = [d for d in self.decisions if d['intent'] != 'kick']
        self.assertTrue(scrimmage)
        self.assertTrue(all(d.get('formation') in ('SHOTGUN', 'UNDER CENTER', 'PISTOL') for d in scrimmage))
        self.assertTrue(all(d.get('formation_conditioned') for d in scrimmage))

    def test_every_dropback_names_a_known_coverage_before_its_outcome(self):
        dropbacks = [d for d in self.decisions if d['intent'] == 'dropback']
        self.assertTrue(dropbacks)
        self.assertTrue(all(d.get('coverage') not in (None, 'UNKNOWN') for d in dropbacks))
        self.assertTrue(all(d.get('coverage_conditioned') for d in dropbacks))
        self.assertTrue(all(d.get('coverage') is None for d in self.decisions if d['intent'] == 'run'))

    def test_a_pass_or_run_names_its_participants_before_the_outcome_and_the_play_carries_them(self):
        for decision, play in zip(self.decisions, self.plays):
            if play['event_type'] in PASS_EVENTS + RUSH_EVENTS:
                self.assertEqual(play['participants']['attribution'], 'pre_event_selection')
                self.assertEqual(decision['participants'].get('passer') or decision['participants'].get('rusher'),
                                 play['participants'].get('passer_id') or play['participants'].get('rusher_id'))

    def test_the_team_statistics_reconcile_with_the_plays(self):
        for side in ('A', 'B'):
            own = [p for p in self.plays if p['state_before']['offense_team'] == side]
            team = self.record['stats']['team'][side]
            self.assertEqual(team['pass_att'], sum(p['event_type'] in PASS_EVENTS for p in own), side)
            # A lost fumble by an attributed ball carrier remains a rushing attempt.
            expected_rush_att = sum(
                p['event_type'] == 'run'
                or (p['event_type'] == 'fumble_lost' and bool(p['participants'].get('rusher_id')))
                for p in own
            )
            self.assertEqual(team['rush_att'], expected_rush_att, side)

    def test_the_points_reconcile_with_the_drives(self):
        """Each side's points are the sum of its scoring drives, extra points included, and match the team statistics."""
        scored = collections.Counter()
        for drive in self.record['drives']:
            points = drive.get('points_scored_on_drive') or {}
            if points.get('points'):
                scored[points['team']] += points['points']
        for side in ('A', 'B'):
            self.assertEqual(scored[side], self.record['points'][side], side)
            self.assertEqual(self.record['stats']['team'][side]['points'], self.record['points'][side], side)

    def test_the_player_lines_add_up_to_the_team_lines(self):
        for side in ('A', 'B'):
            lines = [p for p in self.record['stats']['player'] if p.get('player_side') == side]
            team = self.record['stats']['team'][side]
            self.assertEqual(sum(p.get('passing', {}).get('att', 0) for p in lines), team['pass_att'], side)
            self.assertEqual(sum(p.get('rushing', {}).get('att', 0) for p in lines), team['rush_att'], side)


if __name__ == '__main__':
    unittest.main()
