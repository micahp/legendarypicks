"""The PBV1 personnel hook in pre_event.choose (research flag, off by default).

With the flag off the choice is the formation layer's, as before. With the flag on, only the personnel label changes, the draw
uses its own substream (the ':pbv1' seed suffix), and a play that cannot be drawn keeps the formation layer's personnel.
"""
import os
import unittest
from unittest.mock import patch

import pbv1_package as pp
import pre_event as pe
from test_pre_event import SNAPSHOT

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
TABLE = os.path.join(ROOT, pp.TRAINING_TABLE)
STATE = {'down': 1, 'togo': 10, 'yl': 50, 'quarter': 1, 'clock': 900, 'score_diff': 0}


class Recorder:
    """A stand-in draw that records the seed text it was given and returns a fixed package."""

    def __init__(self, package):
        self.package = package
        self.seen = []

    def draw(self, intent, down, togo, yardline_100, seed_text):
        self.seen.append(seed_text)
        return self.package


def _choose(pbv1=None, seed=7, index=0, intent='dropback'):
    with patch('formation_layer.choose', return_value=('SHOTGUN', '11')):
        return pe.choose(SNAPSHOT, 'home', intent, seed=seed, index=index, formation_priors={}, state=STATE, pbv1=pbv1)


def _without_personnel(chosen):
    return {k: v for k, v in chosen.items() if k != 'personnel'}


class PersonnelHook(unittest.TestCase):
    def test_flag_off_keeps_the_formation_personnel(self):
        self.assertEqual(_choose()['personnel'], '11')

    def test_flag_on_changes_only_the_personnel_label(self):
        off, rec = _choose(), Recorder('12')
        on = _choose(pbv1=rec)
        self.assertEqual(on['personnel'], '12')
        self.assertEqual(on['formation'], 'SHOTGUN')
        self.assertEqual(_without_personnel(on), _without_personnel(off))
        self.assertEqual(rec.seen, [f"{SNAPSHOT['snapshot_sha256']}:7:0:pbv1"])

    def test_a_package_that_cannot_be_drawn_keeps_the_formation_personnel(self):
        self.assertEqual(_choose(pbv1=Recorder(None))['personnel'], '11')

    def test_a_kick_is_not_drawn(self):
        self.assertIsNone(pe.choose(SNAPSHOT, 'home', 'kick', seed=7, index=0, state=STATE, pbv1=Recorder('12')))


class RealModelDraw(unittest.TestCase):
    def test_real_draw_changes_only_personnel_and_stays_in_support(self):
        model = pp.load(TABLE, pp.TABLE_SHA256, 2026)  # fitted on 2022 to 2025 only
        draws = pp.Draws(model)
        off, on = _choose(), _choose(pbv1=draws)
        self.assertEqual(_without_personnel(on), _without_personnel(off))
        self.assertIn(on['personnel'], model.distribution(('pass', '1', 'd10_14', 0)))
        self.assertEqual(draws.usage['drawn'], 1)

    def test_real_pbv1_package_controls_lineup_and_player_eligibility(self):
        import participation_field as pf
        from test_participation_field_hook import FIELD, SNAPSHOT as REAL_ROSTERS

        model = pp.load(TABLE, pp.TABLE_SHA256, 2026)
        draws = pp.Draws(model)
        chooser = pe.chooser(REAL_ROSTERS, 19, seed_root='b' * 64, field=FIELD, pbv1=draws)
        states = [dict(STATE, down=1 + i % 3, togo=(i % 4) + 1, yl=40) for i in range(30)]
        decisions = [chooser('run' if i % 2 else 'dropback', 'A', state) for i, state in enumerate(states)]
        self.assertEqual(draws.usage['drawn'], len(decisions))
        self.assertGreater(len({d['lineup']['group'] for d in decisions}), 1)
        for decision in decisions:
            lineup = decision['lineup']
            self.assertEqual(decision['personnel'], lineup['group'])
            for role in ('rusher', 'receiver'):
                player = decision.get(role)
                if player is not None and player['pos_abb'] in pf.SKILL:
                    self.assertIn(player['gsis_id'], lineup['on_field'])


class PersonnelFirst(unittest.TestCase):
    """With personnel first, prepare() draws the PBV1 package before the call, from the pooled cell; the lineup takes it as
    its grouping, and the call is drawn given it. pick() keeps it and does not draw PBV1 again."""

    def setUp(self):
        import formation_layer
        from test_formation_layer import personnel_first_table
        from test_participation_field_hook import FIELD, SNAPSHOT as REAL_ROSTERS
        self.fl, self.table, self.field, self.snapshot = formation_layer, personnel_first_table(), FIELD, REAL_ROSTERS
        self.model = pp.load(TABLE, pp.TABLE_SHA256, 2026)

    def _game(self, p_dropback, recorder=None):
        draws = recorder or pp.Draws(self.model)
        chooser = pe.chooser(self.snapshot, 19, seed_root='b' * 64, field=self.field, pbv1=draws,
                             formation_priors=self.table)
        out = []
        for i in range(30):
            state = dict(STATE, down=1 + i % 3, togo=(i % 4) + 1, yl=40)
            prepared = chooser.prepare('A', state, p_dropback)
            out.append((state, prepared, chooser('dropback', 'A', state, prepared=prepared)))
        return draws, out

    def test_the_package_does_not_see_the_call(self):
        _, low = self._game(0.1)
        _, high = self._game(0.9)
        self.assertEqual([p['pbv1_package'] for _, p, _ in low], [p['pbv1_package'] for _, p, _ in high])

    def test_the_package_is_the_lineup_grouping_and_is_drawn_once_per_play(self):
        draws, plays = self._game(0.5)
        self.assertEqual(draws.usage['drawn'], len(plays))
        for state, prepared, chosen in plays:
            self.assertEqual(chosen['lineup']['group'], prepared['pbv1_package'])
            self.assertEqual(chosen['personnel'], prepared['pbv1_package'])
            self.assertIn(prepared['pbv1_package'], self.model.distribution(
                (pp.POOLED, str(state['down']), pp.distance_bucket(state['togo']), 0)))

    def test_the_call_is_drawn_given_the_package(self):
        _, plays = self._game(0.5)
        for state, prepared, _ in plays:
            self.assertAlmostEqual(prepared['p_dropback'], self.fl.dropback_given(
                self.table, 0.5, state, prepared['personnel'], prepared['formation'], self.snapshot['rosters']['home']['team']))

    def test_the_prepare_draw_has_no_call(self):
        seen = []

        class Recording(pp.Draws):
            def draw(self, intent, *args):
                seen.append(intent)
                return super().draw(intent, *args)
        self._game(0.5, Recording(self.model))
        self.assertEqual(set(seen), {None})

    def test_pbv1_without_the_call_tables_is_refused(self):
        chooser = pe.chooser(self.snapshot, 19, seed_root='b' * 64, field=self.field, pbv1=pp.Draws(self.model))
        with self.assertRaises(ValueError):
            chooser.prepare('A', STATE, 0.5)


if __name__ == '__main__':
    unittest.main()
