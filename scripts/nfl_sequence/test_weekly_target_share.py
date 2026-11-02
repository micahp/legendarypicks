"""Equality test: the SLC runtime P2 estimate reproduces the frozen C2 forecasts for every 2025 player-game.

The frozen manifest (docs/research/slc-v2-p2-usage-2026-11-02/outputs/p2_forecast_manifest_target_share_retro2025.csv) was written
by p2_eval.py --retro under the M6 freeze, with the frozen lagged availability rule. Rows whose prior is the player's own prior-season
mean do not depend on the position source, so they must match exactly. Rows whose prior is the position-group mean depend on the
position source: the frozen run used the gridiron players file and the runtime uses the database players table. Any disagreement
of position group is counted and printed, not hidden.
"""
import csv
import datetime as dt
import os
import unittest

import team_pass_share as tp
import weekly_target_share as wts

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
DB = '/root/legendarypicks/backend/data/picks.dev.db'
MANIFEST = os.path.join(ROOT, 'docs', 'research', 'slc-v2-p2-usage-2026-11-02', 'outputs',
                        'p2_forecast_manifest_target_share_retro2025.csv')


class FrozenTargetShareEquality(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rows_logs = wts.logs(DB, (2024, 2025))
        cls.table = wts.Table(cls.rows_logs, wts.positions(DB), 2025)
        sched = tp.schedule(DB, (2024, 2025))
        cls.kickoff_of = {g: v[0] for g, v in sched.items() if v[0] is not None}
        with open(MANIFEST, encoding='utf-8') as handle:
            cls.manifest = list(csv.DictReader(handle))

    def test_player_prior_rows_match_exactly(self):
        mismatches, checked = [], 0
        for row in self.manifest:
            if row['prior_source'] != 'player_prior':
                continue
            cutoff = dt.datetime.fromisoformat(row['cutoff_utc']).replace(tzinfo=None)
            got = self.table.estimate(row['gsis'], wts.usable_before_cutoff(self.kickoff_of, cutoff))
            checked += 1
            if got is None or round(got['estimate'], 5) != float(row['estimate']) \
                    or round(got['prior'], 5) != float(row['prior_value']) or got['games_used'] != int(row['games_used']):
                mismatches.append((row['game_id'], row['gsis'], got, row['estimate']))
        self.assertGreater(checked, 1000)
        self.assertEqual(mismatches[:5], [], f'{len(mismatches)} of {checked} player-prior rows differ')

    def test_position_group_agreement_is_reported(self):
        agree = sum(1 for row in self.manifest if self.table.group(row['gsis']) == row['position_group'])
        disagree = [(row['gsis'], row['position_group'], self.table.group(row['gsis']))
                    for row in self.manifest if self.table.group(row['gsis']) != row['position_group']]
        print(f'\nposition group: {agree} rows agree, {len(disagree)} disagree (sample {disagree[:3]})')
        self.assertGreater(agree, len(self.manifest) * 0.9)


if __name__ == '__main__':
    unittest.main()
