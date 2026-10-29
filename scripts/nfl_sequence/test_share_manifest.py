"""The share-model manifest: it must name the exact model version, the source season and cutoff, the fitted concentrations, and the
eligibility rule. Written before share_distributions.manifest() exists.
"""
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import share_distributions as sd  # noqa: E402


def fitted_table():
    return {'phi': {'receive': 24.4, 'carry': 7.5}, 'base': {'receive': {}, 'carry': {}},
            'fit': {'receive': {'phi': 24.4, 'phi_interval': [22.8, 26.2], 'beta_binomial_phi': 24.8, 'team_games': 544},
                    'carry': {'phi': 7.5, 'phi_interval': [6.9, 8.1], 'beta_binomial_phi': 7.4, 'team_games': 544}},
            'season': 2025, 'model': sd.MODEL_VERSION}


class Manifest(unittest.TestCase):
    def test_the_manifest_names_the_model_version_and_the_source_season_and_cutoff(self):
        m = sd.manifest(fitted_table(), cutoff=2026, git_commit='abc123')
        self.assertEqual(m['model_version'], 'dirichlet-multinomial-mle-v2')
        self.assertEqual(m['source_season'], 2025)
        self.assertEqual(m['cutoff_season'], 2026)
        self.assertEqual(m['git_commit'], 'abc123')

    def test_the_manifest_carries_each_role_concentration_and_its_interval(self):
        m = sd.manifest(fitted_table(), cutoff=2026, git_commit='abc123')
        self.assertEqual(m['concentration']['receive']['phi'], 24.4)
        self.assertEqual(m['concentration']['carry']['phi_interval'], [6.9, 8.1])

    def test_the_manifest_states_the_eligibility_rule(self):
        m = sd.manifest(fitted_table(), cutoff=2026, git_commit='abc123')
        self.assertIn('Out', m['eligibility_rule'])
        self.assertIn('Doubtful', m['eligibility_rule'])
        self.assertIn('Questionable', m['eligibility_rule'])

    def test_a_manifest_refuses_a_table_fitted_on_another_season(self):
        table = fitted_table()
        table['season'] = 2024
        with self.assertRaises(ValueError):
            sd.manifest(table, cutoff=2026, git_commit='abc123')


if __name__ == '__main__':
    unittest.main()
