"""The faster manifest and fingerprint hashing must give the same bytes as the code it replaced."""
import json
import math
import os
import pickle
import sys
import tempfile
import unittest
from collections import Counter, defaultdict
from collections.abc import Mapping
from pathlib import Path
from unittest import mock

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import fit_cache  # noqa: E402
import slc_engine as se  # noqa: E402


def frozen_stable_model_value(value):
    """slc_engine._stable_model_value as of 5425ce28, before the fast paths."""
    if isinstance(value, Mapping):
        entries = [(frozen_stable_model_value(key), frozen_stable_model_value(item)) for key, item in value.items()]
        entries.sort(key=lambda pair: json.dumps(pair[0], sort_keys=True, default=str))
        return {'__mapping__': entries}
    if isinstance(value, (tuple, list)):
        return [frozen_stable_model_value(item) for item in value]
    if isinstance(value, (set, frozenset)):
        entries = [frozen_stable_model_value(item) for item in value]
        return sorted(entries, key=lambda item: json.dumps(item, sort_keys=True, default=str))
    if hasattr(value, 'tolist'):
        return frozen_stable_model_value(value.tolist())
    if hasattr(value, 'item'):
        try:
            return value.item()
        except (TypeError, ValueError):
            pass
    if hasattr(value, '__dict__'):
        return frozen_stable_model_value(vars(value))
    return value


def frozen_model_hash(value):
    import hashlib
    encoded = json.dumps(frozen_stable_model_value(value), sort_keys=True, separators=(',', ':'), default=str).encode()
    return hashlib.sha256(encoded).hexdigest()


class Thing:
    def __init__(self):
        self.b = {'z': 1, 'a': (2, 3)}
        self.a = [np.float64(0.5), np.int64(7)]


AWKWARD = {
    'ab': 1, 'ab!': 2, 'ab"': 3, 'a\\b': 4, 'é': 5, 'e': 6, '\x01': 7, '': 8, '日本': 9,
    ('PHI', 'WR'): {'n': 3}, ('PHI',): [1, 2.5, None, True, False], 10: 'ten', 2: 'two', -1: 'neg', 1.5: 'float key',
    True: 'bool key', None: 'none key',
    'floats': [0.1, 1e-300, float('inf'), -float('inf'), 1.0, -0.0],
    'numpy': {'arr': np.array([[1, 2], [3, 4]]), 'scalar': np.float32(1.25), 'int': np.int32(-3), 'bool': np.bool_(True),
              'str': np.str_('np string')},
    'sets': {frozenset({'b', 'a', 'ab!', 'ab'}), frozenset({3, 1, 2})},
    'set_of_tuples': {(1, 'a'), (0, 'b'), ('x', 2)},
    'counter': Counter({'run': 5, 'pass': 7}),
    'defaultdict': defaultdict(Counter, {'qb': Counter({'sack': 1})}),
    'object': Thing(),
}


class StableModelValue(unittest.TestCase):
    def test_the_hash_is_unchanged_on_awkward_values(self):
        self.assertEqual(se._model_hash(AWKWARD), frozen_model_hash(AWKWARD))

    def test_the_stable_value_is_unchanged_on_awkward_values(self):
        self.assertEqual(json.dumps(se._stable_model_value(AWKWARD), sort_keys=True, default=str),
                         json.dumps(frozen_stable_model_value(AWKWARD), sort_keys=True, default=str))

    def test_a_value_walked_once_hashes_like_the_value(self):
        table = {'cells': {(1, 2): Counter({'a': 2})}, 'n': np.int64(4)}
        walked = se._Stable(se._stable_model_value(table))
        self.assertEqual(se._model_hash(walked), frozen_model_hash(table))
        self.assertEqual(se._model_hash({'model': walked, 'enabled': True}),
                         frozen_model_hash({'model': table, 'enabled': True}))

    def test_nan_still_hashes_like_before(self):
        self.assertEqual(se._model_hash({'x': math.nan}), frozen_model_hash({'x': math.nan}))


class FingerprintEncoder(unittest.TestCase):
    def test_the_shared_encoder_gives_json_dumps_bytes(self):
        import e2_reference as er
        for value in (AWKWARD['floats'], {'b': 1, 'a': {'é': [None, True]}}, ['play-cell', ('run', 1, 2)], 'é"\\'):
            self.assertEqual(er._FINGERPRINT_ENCODER.encode(value),
                             json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False))


class FitCache(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.code = Path(self.dir.name) / 'fit_code.py'
        self.code.write_text('VERSION = 1\n')
        self.calls = []

    def fit(self, inputs):
        def compute():
            self.calls.append(inputs)
            return {'phi': sum(inputs['counts']), 'inputs': inputs}
        with mock.patch.dict(os.environ, {'SLC_FIT_CACHE_DIR': self.dir.name}):
            return fit_cache.memo('test.fit', inputs, compute, code_files=(self.code,))

    def test_off_computes_every_time(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            for _ in range(2):
                fit_cache.memo('test.fit', {'counts': [1]}, lambda: self.calls.append(1), code_files=(self.code,))
        self.assertEqual(len(self.calls), 2)

    def test_the_same_input_is_computed_once_and_returned_equal(self):
        first = self.fit({'counts': [1, 2]})
        second = self.fit({'counts': [1, 2]})
        self.assertEqual(first, second)
        self.assertEqual(len(self.calls), 1)

    def test_a_changed_value_type_or_order_is_a_new_fit(self):
        self.fit({'counts': [1, 2]})
        self.fit({'counts': [2, 1]})
        self.fit({'counts': [1.0, 2]})
        self.fit({'counts': [1, 2], 'cutoff': 2026})
        self.fit({'cutoff': 2026, 'counts': [1, 2]})
        self.assertEqual(len(self.calls), 5)

    def test_a_code_change_is_a_new_fit(self):
        self.fit({'counts': [1]})
        self.code.write_text('VERSION = 2\n')
        self.fit({'counts': [1]})
        self.assertEqual(len(self.calls), 2)

    def test_an_unreadable_entry_is_rebuilt(self):
        self.fit({'counts': [3]})
        for path in Path(self.dir.name).glob('test.fit-*.pkl'):
            path.write_bytes(b'not a pickle')
        self.assertEqual(self.fit({'counts': [3]})['phi'], 3)
        self.assertEqual(len(self.calls), 2)
        with next(Path(self.dir.name).glob('test.fit-*.pkl')).open('rb') as source:
            self.assertEqual(pickle.load(source)['result']['phi'], 3)

    def test_inputs_whose_repr_does_not_identify_them_are_refused(self):
        with self.assertRaises(TypeError):
            self.fit({'counts': defaultdict(lambda: 0)})
        with self.assertRaises(TypeError):
            self.fit({'counts': Counter({'a': 1})})

    def test_no_temp_file_is_left_behind(self):
        self.fit({'counts': [4]})
        self.assertEqual(list(Path(self.dir.name).glob('*.tmp')), [])

    def test_a_reader_never_sees_a_partial_entry_while_workers_rewrite_it(self):
        import multiprocessing
        context = multiprocessing.get_context('spawn')
        workers = [context.Process(target=_rewrite_entry, args=(self.dir.name, str(self.code), 15)) for _ in range(4)]
        for worker in workers:
            worker.start()
        reads = 0
        while any(worker.is_alive() for worker in workers) or reads == 0:
            for path in Path(self.dir.name).glob('test.big-*.pkl'):
                try:
                    source = path.open('rb')
                except FileNotFoundError:  # a worker removed it between the listing and the open; nothing was read
                    continue
                with source:
                    self.assertEqual(len(pickle.load(source)['result']), 200_000)  # a partial file would not unpickle
                reads += 1
        for worker in workers:
            worker.join()
            self.assertEqual(worker.exitcode, 0)
        self.assertGreater(reads, 0)
        self.assertEqual(list(Path(self.dir.name).glob('*.tmp')), [])


def _rewrite_entry(cache_dir, code, times):
    """A worker that recomputes and rewrites one large entry (its stored file is removed first, so each call writes)."""
    os.environ['SLC_FIT_CACHE_DIR'] = cache_dir
    for _ in range(times):
        for path in Path(cache_dir).glob('test.big-*.pkl'):
            try:
                path.unlink()
            except FileNotFoundError:
                pass
        fit_cache.memo('test.big', {'n': 200_000}, lambda: list(range(200_000)), code_files=(code,))


if __name__ == '__main__':
    unittest.main()
