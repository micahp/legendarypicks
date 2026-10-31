import json
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import seed_selection  # noqa: E402


class SeedSelectionTests(unittest.TestCase):
    def test_loads_unique_nonnegative_seed_ids_in_deterministic_order(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'seeds.json'
            path.write_text(json.dumps({'seeds': [344, 196, 9]}), encoding='utf-8')
            selection = seed_selection.load_seed_selection(path)

        self.assertEqual(selection.seeds, (9, 196, 344))
        self.assertEqual(selection.seed_start, 9)
        self.assertEqual(selection.seed_end_inclusive, 344)
        self.assertEqual(len(selection.sha256), 64)

    def test_rejects_empty_duplicate_negative_or_non_integer_seed_lists(self):
        invalid = ([], [2, 2], [-1], [True], [1.0], ['3'])
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'seeds.json'
            for seeds in invalid:
                with self.subTest(seeds=seeds):
                    path.write_text(json.dumps({'seeds': seeds}), encoding='utf-8')
                    with self.assertRaises(ValueError):
                        seed_selection.load_seed_selection(path)

    def test_rejects_a_seed_file_with_an_unrecognized_shape(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'seeds.json'
            path.write_text(json.dumps({'seed_ids': [1, 2]}), encoding='utf-8')
            with self.assertRaises(ValueError):
                seed_selection.load_seed_selection(path)


if __name__ == '__main__':
    unittest.main()
