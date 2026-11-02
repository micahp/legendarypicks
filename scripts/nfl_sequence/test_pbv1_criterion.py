"""PBV1 Milestone 2 gate, criterion (c), tested against the frozen results before any PBV1 integration.

Quoted (docs/research/PBV1-SAMPLER-SPEC-2026-11-02.md, section 9): "A sampler "passes" PBV1 Milestone 2 only if: (a) its
log-likelihood gain over B0 is positive with a 95% CI above zero on both development folds; (b) its unsupported-combination rate
is at or below the B1 rate on the same folds; and (c) the retrospective fold agrees in sign. Failure is reported as failure."

Intended property of (c): the sampler's advantage over the marginal package distribution must not be an artifact of the
development seasons it was checked on. The retrospective season is a later, separately scored season, so its gain must have the
sign the development folds show. (c) is a sign check. It is not a significance test on 2025.

Reading used: "agrees in sign" compares the retrospective gain with the development gains on the same comparison as (a), which is
B0. The spec does not name the comparison. The B1 reading is computed and reported, not used to claim (c) is met.

Verdicts are 'pass', 'fail' or 'not evaluated'. A missing retrospective fold is 'not evaluated', never a pass.
"""
import json
import os
import unittest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
RESULTS = os.path.join(ROOT, 'docs', 'research', 'pbv1-sampler-2026-11-02', 'outputs', 'pbv1_results.json')
DEV = ('dev_2023', 'dev_2024')
RETRO = 'retro_2025'
K_PRIMARY = 20


def _folds(results, target):
    return {f['fold']: f for f in results['folds'] if f['target'] == target and f['K'] == K_PRIMARY}


def _sign(x):
    return (x > 0) - (x < 0)


def parts(results, target, reading='B0'):
    """(a), (b), (c) for one target. (c) is None when the retrospective fold is absent from the frozen results."""
    folds = _folds(results, target)
    if not all(name in folds for name in DEV):
        raise ValueError(f'{target}: development folds missing from the frozen results')
    b0_gain = lambda f: f['sampler_minus_b0']  # (a) is defined over B0 under every reading
    a = all(b0_gain(folds[d])['diff'] > 0 and b0_gain(folds[d])['ci95'][0] > 0 for d in DEV)
    b = all(folds[d]['unsupported']['sampler']['rate'] <= folds[d]['unsupported']['b1']['rate'] for d in DEV)
    if RETRO not in folds:
        return {'a': a, 'b': b, 'c': None}
    gain = b0_gain if reading == 'B0' else (lambda f: f['sampler_minus_b1'])
    dev_signs = {_sign(gain(folds[d])['diff']) for d in DEV}
    c = len(dev_signs) == 1 and _sign(gain(folds[RETRO])['diff']) in dev_signs
    return {'a': a, 'b': b, 'c': c}


def verdict(results, target, reading='B0'):
    p = parts(results, target, reading)
    if not (p['a'] and p['b']):
        return 'fail'
    if p['c'] is None:
        return 'not evaluated'
    return 'pass' if p['c'] else 'fail'


class CriterionOnFrozenResults(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with open(RESULTS, encoding='utf-8') as handle:
            cls.results = json.load(handle)

    def test_primary_target_passes_with_criterion_c_read_as_b0(self):
        # The frozen target name 'package' is the RB plus FB code, the PBV1 primary target.
        self.assertEqual(verdict(self.results, 'package', 'B0'), 'pass')

    def test_primary_target_fails_if_criterion_c_is_read_as_b1(self):
        # Development gaps to B1 are negative (-0.00033, -0.00037); the retrospective gap is +0.00007. The signs disagree, so
        # the B1 reading does not support (c). The earlier report's claim that they agree in sign on B1 was incorrect.
        self.assertFalse(parts(self.results, 'package', 'B1')['c'])
        self.assertEqual(verdict(self.results, 'package', 'B1'), 'fail')

    def test_rb_only_slc_target_is_not_evaluated_on_criterion_c(self):
        # The SLC code 'package_rb' has development folds only. (a) and (b) hold, but no retrospective fold was frozen.
        p = parts(self.results, 'package_rb', 'B0')
        self.assertTrue(p['a'] and p['b'])
        self.assertIsNone(p['c'])
        self.assertEqual(verdict(self.results, 'package_rb', 'B0'), 'not evaluated')


if __name__ == '__main__':
    unittest.main()
