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
        self.assertEqual(self.registry['schema'], 'lp-nfl-rule-regime-registry-2')
        ids = lambda s: rr.active_rules(self.registry, s, 'REG', 'kickoff')
        self.assertIn('NFL-2011-01', ids(2011))
        self.assertNotIn('NFL-2011-01', ids(2010))
        self.assertIn('NFL-2018-04', ids(2022))  # 25-yard touchback made permanent in 2018
        self.assertNotIn('NFL-2018-04', ids(2024))  # replaced by the 2024 dynamic kickoff
        self.assertNotIn('NFL-2016-05', ids(2022))  # one-year trial ended in 2017
        self.assertIn('NFL-2016-05', ids(2017))
        self.assertIn('NFL-2017-02', ids(2017))
        self.assertNotIn('NFL-2017-02', ids(2018))
        self.assertIn('NFL-2018-02', ids(2018))
        self.assertNotIn('NFL-2018-02', ids(2019))
        self.assertIn('NFL-2019-01', ids(2019))
        self.assertNotIn('NFL-2019-01', ids(2024))  # 2018-23 formation replaced by dynamic kickoff
        self.assertIn('NFL-2021-02', ids(2021))
        self.assertNotIn('NFL-2021-02', ids(2022))
        self.assertIn('NFL-2022-01', ids(2022))
        self.assertIn('NFL-2023-06', ids(2023))
        self.assertNotIn('NFL-2023-06', ids(2024))  # explicitly a one-year rule
        self.assertIn('NFL-2024-01', ids(2024))
        self.assertNotIn('NFL-2024-01', ids(2023))
        self.assertNotIn('NFL-2024-01', ids(2025))  # 2025 permanent version supersedes the trial
        self.assertIn('NFL-2025-01', ids(2025))
        self.assertNotIn('NFL-2025-01', ids(2024))
        self.assertIn('NFL-2025-03', ids(2025))  # touchback-to-35 is a separate change
        self.assertIn('NFL-2026-01', ids(2026))
        self.assertNotIn('NFL-2026-01', ids(2025))
        self.assertIn('NFL-2026-02', ids(2026))  # kick from midfield spot change
        self.assertNotIn('NFL-2026-02', ids(2025))

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
        self.assertEqual(rr.seasons_with_same_rules(self.registry, 2019, seasons, 'REG', 'kickoff'), [])
        self.assertEqual(
            set(rr.regime_key(self.registry, 2022, 'REG', 'kickoff'))
            - set(rr.regime_key(self.registry, 2019, 'REG', 'kickoff')),
            {'NFL-2022-01'},
        )
        self.assertEqual(rr.seasons_with_same_rules(self.registry, 2027, seasons, 'REG', 'kickoff'), [2026])  # open-ended rules
        self.assertEqual(rr.seasons_with_same_rules(self.registry, 2010, seasons, 'REG', 'kickoff'), [])

    def test_overtime_rule_changes_at_the_registered_seasons(self):
        ids = lambda s, t='REG': rr.active_rules(self.registry, s, t, 'overtime')
        self.assertNotIn('NFL-2017-09', ids(2016))
        self.assertIn('NFL-2017-09', ids(2017))
        self.assertIn('NFL-2017-09', ids(2024))
        self.assertNotIn('NFL-2025-06', ids(2024))
        self.assertIn('NFL-2025-06', ids(2025))
        self.assertIn('NFL-2025-06', ids(2026))
        self.assertIn('NFL-2022-02', ids(2022, 'POST'))
        self.assertNotIn('NFL-2022-02', ids(2021, 'POST'))
        self.assertNotIn('NFL-2022-02', ids(2022, 'REG'))

    def test_each_contract_boundary_switches_its_rule_on_one_side_only(self):
        """The adopted rule ID first appears in the season and phase listed by its source."""
        def assert_start(rule_id, first_season, domain, season_type='REG'):
            self.assertNotIn(rule_id, rr.active_rules(self.registry, first_season - 1, season_type, domain))
            self.assertIn(rule_id, rr.active_rules(self.registry, first_season, season_type, domain))

        assert_start('NFL-2017-09', 2017, 'overtime')  # ten-minute regular-season OT
        assert_start('NFL-2015-01', 2015, 'extra_point')  # 15-yard PAT trial
        assert_start('NFL-2015-02', 2015, 'try_scoring')  # defensive return trial
        assert_start('NFL-2016-04', 2016, 'extra_point')  # PAT spot and defensive return made permanent
        assert_start('NFL-2016-08', 2016, 'disqualification')  # one-year automatic-ejection trial
        assert_start('NFL-2016-05', 2016, 'kickoff')  # touchback-to-25 trial
        assert_start('NFL-2017-02', 2017, 'kickoff')  # touchback extension
        assert_start('NFL-2018-01', 2018, 'extra_point')  # walk-off try no longer required
        assert_start('NFL-2018-02', 2018, 'kickoff')  # one-year kickoff test
        assert_start('NFL-2019-08', 2019, 'replay')  # one-year PI review authority
        assert_start('NFL-2021-02', 2021, 'kickoff')  # setup-zone maximum trial
        assert_start('NFL-2022-02', 2022, 'overtime', 'POST')  # postseason both-teams-possession rule
        assert_start('NFL-2023-06', 2023, 'kickoff')  # one-year fair-catch rule
        assert_start('NFL-2024-01', 2024, 'kickoff')  # dynamic-kickoff trial
        assert_start('NFL-2025-01', 2025, 'kickoff')  # dynamic kickoff made permanent
        assert_start('NFL-2026-02', 2026, 'kickoff')  # midfield kick dead-ball spot

        # Temporary provisions stop at their sourced trial year; successor rows carry the later rule.
        for rule_id, domain, last_season in [
            ('NFL-2015-01', 'extra_point', 2015),
            ('NFL-2015-02', 'try_scoring', 2015),
            ('NFL-2016-05', 'kickoff', 2017),
            ('NFL-2016-08', 'disqualification', 2016),
            ('NFL-2017-02', 'kickoff', 2017),
            ('NFL-2018-02', 'kickoff', 2018),
            ('NFL-2019-08', 'replay', 2019),
            ('NFL-2021-02', 'kickoff', 2021),
            ('NFL-2023-06', 'kickoff', 2023),
            ('NFL-2024-01', 'kickoff', 2024),
        ]:
            self.assertIn(rule_id, rr.active_rules(self.registry, last_season, 'REG', domain))
            self.assertNotIn(rule_id, rr.active_rules(self.registry, last_season + 1, 'REG', domain))

    def test_expired_and_contingent_records_are_not_active_rules(self):
        replay_2019 = rr.active_rules(self.registry, 2019, 'REG', 'replay')
        replay_2020 = rr.active_rules(self.registry, 2020, 'REG', 'replay')
        self.assertIn('NFL-2019-08', replay_2019)
        self.assertNotIn('NFL-2019-08', replay_2020)  # one-year PI review authority expired
        self.assertNotIn('NFL-2020-07', replay_2020)  # expiry record, not an active rule
        self.assertNotIn('NFL-2026-05', rr.active_rules(self.registry, 2026, 'REG', 'replay'))

    def test_overtime_rules_active_in_2026_by_open_ended_fallback(self):
        self.assertEqual(
            set(rr.active_rules(self.registry, 2026, 'REG', 'overtime')),
            {'NFL-2012-01', 'NFL-2017-09', 'NFL-2018-08', 'NFL-2025-06'},
        )
        self.assertEqual(
            set(rr.active_rules(self.registry, 2026, 'POST', 'overtime')),
            {'NFL-2010-01', 'NFL-2018-08', 'NFL-2022-02'},
        )
        self.assertEqual(
            set(rr.active_rules(self.registry, 2026, 'PRE', 'overtime')),
            {'NFL-2017-09', 'NFL-2021-07'},
        )

    def test_legacy_registry_fields_and_explicit_end_seasons_remain_supported(self):
        legacy = {'changes': [{
            'id': 'legacy-rule', 'domain': 'kickoff', 'effective_from_season': 2020,
            'effective_through_season': 2021, 'applies_to': ['REG'],
        }]}
        self.assertEqual(rr.active_rules(legacy, 2020, 'REG', 'kickoff'), ['legacy-rule'])
        self.assertEqual(rr.active_rules(legacy, 2022, 'REG', 'kickoff'), [])

        expanded = {'changes': [{
            'id': 'trial-rule', 'domain': 'kickoff', 'effective_from_season': 2020,
            'trial_until': 2021, 'season_types': ['REG'],
        }]}
        self.assertEqual(rr.active_rules(expanded, 2021, 'REG', 'kickoff'), ['trial-rule'])
        self.assertEqual(rr.active_rules(expanded, 2022, 'REG', 'kickoff'), [])

    def test_missing_end_season_uses_the_documented_open_ended_fallback(self):
        ids = rr.active_rules(self.registry, 2026, 'REG', 'overtime')
        self.assertIn('NFL-2017-09', ids)

    def test_postseason_rules_are_not_applied_to_the_regular_season(self):
        self.assertNotIn('NFL-2022-02', rr.active_rules(self.registry, 2023, 'REG', 'overtime'))
        self.assertNotIn('NFL-2021-07', rr.active_rules(self.registry, 2021, 'REG', 'overtime'))

    def test_unknown_domains_and_seasons_have_no_rules(self):
        self.assertEqual(rr.active_rules(self.registry, 2026, 'REG', 'no-such-domain'), [])
        self.assertEqual(rr.active_rules(self.registry, 1990, 'REG', 'kickoff'), [])


if __name__ == '__main__':
    unittest.main()
