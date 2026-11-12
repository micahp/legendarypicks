import unittest
import itertools
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from pass_label_outcomes import OUTCOMES, PassLabelOutcomeModel


class PassLabelOutcomeModelTest(unittest.TestCase):
    def test_fit_returns_normalized_pass_only_probabilities(self):
        pool = {(1, '3-5', '30-49'): []}
        events = ('pass_complete', 'pass_incomplete', 'interception', 'fumble_lost')
        for i in range(400):
            event = events[i % len(events)]
            labels = ({'A': 'WR', 'D': 'deep', 'E': 'left'} if event == 'pass_complete'
                      else {'A': 'RB', 'D': 'short', 'E': 'middle'})
            row = {'season': 2024, 'labels': labels, 'penalty': 0}
            pool[(1, '3-5', '30-49')].append((event, row, 0.0, 50))

        model = PassLabelOutcomeModel.fit(pool)
        probabilities = model.probabilities((1, '3-5', '30-49'),
                                             {'A': 'WR', 'D': 'deep', 'E': 'left'})
        self.assertEqual(tuple(probabilities), OUTCOMES)
        self.assertAlmostEqual(sum(probabilities.values()), 1.0)
        self.assertNotIn('sack', probabilities)
        self.assertGreater(probabilities['pass_complete'], probabilities['pass_incomplete'])
        self.assertEqual(model.manifest['fit_seasons'], [2024])

        prior = {'A': {'WR': 0.5, 'RB': 0.5}, 'D': {'deep': 0.5, 'short': 0.5},
                 'E': {'left': 0.5, 'middle': 0.5}}
        base = model.base_probabilities((1, '3-5', '30-49'))
        for event in OUTCOMES:
            average = 0.0
            for a, d, e in itertools.product(prior['A'], prior['D'], prior['E']):
                labels = {'A': a, 'D': d, 'E': e}
                average += (1 / 8) * base[event] * model.ratio(
                    (1, '3-5', '30-49'), labels, event,
                    label_prior=prior, calibration_key=('AAA', '1|short|other'))
            self.assertAlmostEqual(average, base[event], places=8)

    def test_rushing_and_scramble_fumbles_do_not_contaminate_pass_outcome_baselines(self):
        cell = (1, '3-5', '30-49')
        pass_rows = []
        for i in range(240):
            event = OUTCOMES[i % len(OUTCOMES)]
            labels = {'A': 'WR' if i % 3 else 'RB',
                      'D': 'short' if i % 2 else 'deep',
                      'E': 'left' if i % 2 else 'middle'}
            pass_rows.append((event, {'season': 2024, 'penalty': 0,
                                      'play_type': 'pass', 'qb_scramble': 0,
                                      'labels': labels}, 0, None))
        added_rushing_fumbles = []
        for i in range(80):
            added_rushing_fumbles.append((
                'fumble_lost', {'season': 2024, 'penalty': 0,
                                'play_type': 'run', 'qb_scramble': int(i % 2 == 0),
                                'labels': {'A': 'RB', 'D': 'short', 'E': 'left'}},
                0, None))
        control = PassLabelOutcomeModel.fit({cell: pass_rows})
        candidate = PassLabelOutcomeModel.fit({cell: pass_rows + added_rushing_fumbles})
        self.assertEqual(candidate.manifest['excluded_nonpass_fumbles'], 80)
        self.assertEqual(candidate.manifest['rows'], control.manifest['rows'])
        self.assertEqual(candidate.base_probabilities(cell), control.base_probabilities(cell))
        labels = {'A': 'WR', 'D': 'short', 'E': 'left'}
        for event in OUTCOMES:
            self.assertAlmostEqual(candidate.probabilities(cell, labels)[event],
                                   control.probabilities(cell, labels)[event], places=12)

    def test_unknown_context_falls_back_to_global_distribution(self):
        pool = {(1, '3-5', '30-49'): []}
        for i, event in enumerate(OUTCOMES * 30):
            pool[(1, '3-5', '30-49')].append((event, {
                'season': 2024,
                'labels': {'A': 'WR' if i % 2 else 'RB', 'D': 'short', 'E': 'left'},
                'penalty': 0,
            }, 0.0, 50))
        model = PassLabelOutcomeModel.fit(pool)
        self.assertEqual(model.base_probabilities((4, '10+', '80-99')),
                         dict(zip(OUTCOMES, model.global_base)))

    def test_penalty_unknown_and_tagged_rows_do_not_enter_fit(self):
        pool = {(1, '3-5', '30-49'): []}
        for i in range(120):
            penalty = 0 if i < 110 else (None if i < 115 else 1)
            pool[(1, '3-5', '30-49')].append((OUTCOMES[i % len(OUTCOMES)], {
                'season': 2024, 'labels': {'A': 'WR', 'D': 'short', 'E': 'left'}, 'penalty': penalty,
            }, 0.0, 50))
        model = PassLabelOutcomeModel.fit(pool)
        self.assertEqual(model.manifest['rows'], 110)
        self.assertEqual(model.manifest['penalty_eligibility'], {
            'known_clean': 110, 'penalty_tagged': 5, 'unknown': 5, 'other': 0,
        })


if __name__ == '__main__':
    unittest.main()
