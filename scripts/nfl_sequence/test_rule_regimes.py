import hashlib
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import rule_regimes as rr  # noqa: E402


class RegistryBoundaries(unittest.TestCase):
    """Regime boundaries from the rule-history registry: the engine must see the rules that applied in the target season."""

    @classmethod
    def setUpClass(cls):
        cls.registry, cls.sha = rr.load_registry()

    def test_the_manifest_checksum_is_the_file_checksum(self):
        raw = rr.REGISTRY.read_bytes()
        self.assertEqual(self.sha, hashlib.sha256(raw).hexdigest())
        self.assertEqual(len(self.sha), 64)

    def test_kickoff_rules_change_at_the_registered_seasons(self):
        ids = lambda s: rr.active_rules(self.registry, s, 'REG', 'kickoff')
        self.assertIn('2016-KO-TB25', ids(2022))
        self.assertNotIn('2024-DYNAMIC-KO', ids(2022))
        self.assertIn('2023-FAIR-CATCH25', ids(2023))
        self.assertNotIn('2023-FAIR-CATCH25', ids(2024))
        self.assertIn('2024-DYNAMIC-KO', ids(2024))
        self.assertNotIn('2016-KO-TB25', ids(2024))
        self.assertIn('2025-KO-PERM-TB35', ids(2025))
        self.assertIn('2026-KO-50-TB', ids(2026))
        self.assertNotIn('2026-KO-50-TB', ids(2025))

    def test_each_season_from_2022_to_2026_has_its_own_kickoff_regime(self):
        keys = {s: rr.regime_key(self.registry, s, 'REG', 'kickoff') for s in range(2022, 2027)}
        self.assertEqual(len(set(keys.values())), len(keys), keys)

    def test_kickoff_samples_pool_only_seasons_with_the_same_rules(self):
        seasons = range(2022, 2027)
        same = lambda t: rr.seasons_with_same_rules(self.registry, t, seasons, 'REG', 'kickoff')
        self.assertEqual(same(2022), [2022])
        self.assertEqual(same(2023), [2023])
        self.assertEqual(same(2024), [2024])
        self.assertEqual(same(2025), [2025])
        self.assertEqual(same(2026), [2026])
        self.assertEqual(rr.seasons_with_same_rules(self.registry, 2019, seasons, 'REG', 'kickoff'), [2022])
        self.assertEqual(rr.seasons_with_same_rules(self.registry, 2027, seasons, 'REG', 'kickoff'), [2026])  # open-ended rules
        self.assertEqual(rr.seasons_with_same_rules(self.registry, 2010, seasons, 'REG', 'kickoff'), [])

    def test_overtime_rule_changes_at_the_registered_seasons(self):
        ids = lambda s, t='REG': rr.active_rules(self.registry, s, t, 'overtime')
        self.assertIn('2017-REG-OT-10', ids(2024))
        self.assertNotIn('2025-REG-OT-BOTH', ids(2024))
        self.assertIn('2025-REG-OT-BOTH', ids(2025))
        self.assertIn('2025-REG-OT-BOTH', ids(2026))
        self.assertIn('2022-POST-OT-BOTH', ids(2022, 'POST'))
        self.assertNotIn('2022-POST-OT-BOTH', ids(2022, 'REG'))

    def test_postseason_rules_are_not_applied_to_the_regular_season(self):
        self.assertNotIn('2022-POST-OT-BOTH', rr.active_rules(self.registry, 2023, 'REG', 'overtime'))
        self.assertNotIn('2021-PRESEASON-OT-REMOVED', rr.active_rules(self.registry, 2021, 'REG', 'overtime'))

    def test_unknown_domains_and_seasons_have_no_rules(self):
        self.assertEqual(rr.active_rules(self.registry, 2026, 'REG', 'no-such-domain'), [])
        self.assertEqual(rr.active_rules(self.registry, 1990, 'REG', 'kickoff'), [])


if __name__ == '__main__':
    unittest.main()
