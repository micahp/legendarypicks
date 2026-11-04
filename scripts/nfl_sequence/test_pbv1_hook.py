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


if __name__ == '__main__':
    unittest.main()
