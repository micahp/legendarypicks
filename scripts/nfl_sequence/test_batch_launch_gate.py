import unittest
from batch_launch_gate import run_stage, require_full_seed_census


def row(seed):
    return {'seed': seed, 'valid_full_game': True, 'complete_game': True,
            'score_scope': 'valid_final', 'home_points': 21, 'away_points': 17}


class BatchGateTests(unittest.TestCase):
    def test_failed_smoke_prevents_next_wave(self):
        attempted = []
        def worker(job):
            attempted.append(job)
            return job != 0
        self.assertFalse(run_stage(range(1000), worker, lambda j, r, e: e is None and r, 1))
        self.assertEqual(attempted, [0])

    def test_parallel_failure_never_starts_later_wave(self):
        attempted = []
        def worker(job):
            attempted.append(job)
            if job == 1:
                raise ValueError('invalid')
            return True
        self.assertFalse(run_stage(range(1000), worker, lambda j, r, e: e is None and r, 3))
        self.assertEqual(sorted(attempted), [0, 1, 2])

    def test_success_drains_all_jobs(self):
        accepted = []
        self.assertTrue(run_stage(range(7), lambda j: j, lambda j, r, e: not accepted.append(r) and e is None, 3))
        self.assertEqual(sorted(accepted), list(range(7)))

    def test_census_rejects_missing_duplicate_invalid_and_nonfinal(self):
        self.assertEqual(require_full_seed_census([row(10), row(11)], 10, 2), 2)
        for rows in ([row(10)], [row(10), row(10)], [row(10), {**row(11), 'valid_full_game': False}],
                     [row(10), {**row(11), 'score_scope': 'partial'}]):
            with self.subTest(rows=rows), self.assertRaises(ValueError):
                require_full_seed_census(rows, 10, 2)


if __name__ == '__main__':
    unittest.main()
