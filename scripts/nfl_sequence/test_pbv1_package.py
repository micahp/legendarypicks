"""Equality tests for the SLC PBV1 sampler (pbv1_package.py) against the frozen PBV1 evaluation.

The frozen results (docs/research/pbv1-sampler-2026-11-02/outputs/pbv1_results.json) were written by pbv1_eval.py. The runtime
model is refitted from the exported training table with the same folds. Its sampler, B0 and B1 mean log-likelihoods, unsupported
counts and comparable-play counts must reproduce the frozen numbers. The frozen target name 'package' is the RB plus FB code,
stored in the table as package_comparable. The frozen 'package_rb' is the RB-only code, stored as package (the SLC code).
"""
import collections
import csv
import json
import math
import os
import unittest

import pbv1_package as pp

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
TABLE = os.path.join(ROOT, pp.TRAINING_TABLE)
MANIFEST = os.path.join(ROOT, 'docs', 'research', 'pbv1-package-integration-2026-11-02', 'pbv1_training_manifest.json')
RESULTS = os.path.join(ROOT, 'docs', 'research', 'pbv1-sampler-2026-11-02', 'outputs', 'pbv1_results.json')
FROZEN_COLUMN = {'package': 'package_comparable', 'package_rb': 'package'}
TEST_SEASON = {'dev_2023': 2023, 'dev_2024': 2024, 'retro_2025': 2025}
TOL = 1e-5  # the frozen values are rounded to five decimals, and a difference of two rounded values can reach 1e-5


def _rows():
    with open(TABLE, encoding='utf-8') as handle:
        return list(csv.DictReader(handle))


def _cell(row):
    return (row['family'], row['down'], row['distance'], int(row['red_zone']))


def replay(rows, column, test_season):
    """One fold's scores, as the frozen evaluation computes them: the sampler from pbv1_package, B0 and B1 from the same rows."""
    model = pp.load(TABLE, pp.TABLE_SHA256, test_season, target=column)
    marginal, cell = collections.Counter(), collections.defaultdict(collections.Counter)
    for row in rows:
        if int(row['season']) < test_season:
            marginal[row[column]] += 1
            cell[_cell(row)][row[column]] += 1
    total = sum(marginal.values())
    unsupported = collections.Counter()
    ll = collections.defaultdict(float)
    comparable = 0
    for row in rows:
        if int(row['season']) != test_season:
            continue
        key, package = _cell(row), row[column]
        dist = model.distribution(key)
        scores = {'sampler': dist.get(package) if dist else None}
        cc = cell.get(key)
        scores['b1'] = cc[package] / sum(cc.values()) if cc and cc.get(package) else None
        scores['b0'] = marginal[package] / total if marginal.get(package) else None
        for arm in ('sampler', 'b1'):
            if scores[arm] is None:
                unsupported[arm] += 1
        if all(scores[arm] is not None for arm in ('sampler', 'b0', 'b1')):
            comparable += 1
            for arm in ('sampler', 'b0', 'b1'):
                ll[arm] += math.log(scores[arm])
    return {'comparable': comparable, 'unsupported': unsupported, 'll': {arm: ll[arm] / comparable for arm in ll}}


class FrozenEvaluationEquality(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rows = _rows()
        with open(RESULTS, encoding='utf-8') as handle:
            cls.frozen = json.load(handle)['folds']

    def _check(self, target):
        checked = 0
        for fold in self.frozen:
            if fold['target'] != target or fold['K'] != pp.K:
                continue
            got = replay(self.rows, FROZEN_COLUMN[target], TEST_SEASON[fold['fold']])
            name = (target, fold['fold'])
            self.assertEqual(got['comparable'], fold['comparable_plays'], name)
            self.assertEqual(got['unsupported']['sampler'], fold['unsupported']['sampler']['count'], name)
            self.assertEqual(got['unsupported']['b1'], fold['unsupported']['b1']['count'], name)
            for arm in ('sampler', 'b0', 'b1'):
                self.assertLessEqual(abs(got['ll'][arm] - fold['mean_log_likelihood'][arm]), TOL, (name, arm))
            diff = got['ll']['sampler'] - got['ll']['b0']
            self.assertLessEqual(abs(diff - fold['sampler_minus_b0']['diff']), TOL, (name, 'sampler_minus_b0'))
            checked += 1
        return checked

    def test_comparable_target_reproduces_all_three_folds(self):
        self.assertEqual(self._check('package'), 3)

    def test_rb_only_target_reproduces_the_development_folds(self):
        self.assertEqual(self._check('package_rb'), 2)


class TableAndSupport(unittest.TestCase):
    def test_pinned_hash_matches_the_manifest(self):
        with open(MANIFEST, encoding='utf-8') as handle:
            manifest = json.load(handle)
        self.assertEqual(manifest['csv_sha256'], pp.TABLE_SHA256)
        self.assertEqual(manifest['rows'], 133262)

    def test_load_refuses_other_bytes(self):
        with self.assertRaises(ValueError):
            pp.load(TABLE, '0' * 64, 2025)

    def test_fit_excludes_the_game_season(self):
        self.assertEqual(pp.load(TABLE, pp.TABLE_SHA256, 2023).fitted_plays, 33592)  # 2022 only
        self.assertEqual(pp.load(TABLE, pp.TABLE_SHA256, 2026).fitted_plays, 133262)  # 2022 to 2025

    def test_draw_is_deterministic_and_stays_in_the_parent_support(self):
        model = pp.load(TABLE, pp.TABLE_SHA256, 2026)
        first = pp.Draws(model).draw('dropback', 1, 10, 50, 'snap:1:0:pbv1')
        again = pp.Draws(model).draw('dropback', 1, 10, 50, 'snap:1:0:pbv1')
        self.assertEqual(first, again)
        self.assertIn(first, model.distribution(('pass', '1', 'd10_14', 0)))

    def test_fallbacks_are_counted_by_reason(self):
        draws = pp.Draws(pp.load(TABLE, pp.TABLE_SHA256, 2026))
        self.assertIsNone(draws.draw('run', 1, 0, 50, 'x'))  # no distance bucket
        self.assertIsNone(draws.draw('run', 0, 10, 50, 'x'))  # down outside 1 to 4
        self.assertEqual(draws.usage['fallback_distance_outside_buckets'], 1)
        self.assertEqual(draws.usage['fallback_down_unknown'], 1)
        self.assertEqual(draws.usage['drawn'], 0)


if __name__ == '__main__':
    unittest.main()
