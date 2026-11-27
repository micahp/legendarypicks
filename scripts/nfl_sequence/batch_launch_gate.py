"""Bounded fail-closed batch launch helpers; no engine or database dependency."""
from concurrent.futures import ThreadPoolExecutor, as_completed
from itertools import islice


def run_stage(jobs, worker, on_result, concurrency):
    """Run bounded waves. Drain in-flight jobs; never start another wave after failure.

    on_result(job, result, error) must return True only for accepted jobs.
    """
    if type(concurrency) is not int or concurrency < 1:
        raise ValueError('concurrency must be a positive integer')
    pending = iter(jobs)
    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        while True:
            wave = list(islice(pending, concurrency))
            if not wave:
                return True
            accepted = True
            futures = {pool.submit(worker, job): job for job in wave}
            for future in as_completed(futures):
                try:
                    result, error = future.result(), None
                except Exception as exc:
                    result, error = None, exc
                if not on_result(futures[future], result, error):
                    accepted = False
            if not accepted:
                return False


def require_full_seed_census(rows, start, count):
    """Require exactly the planned seeds, each legal and complete; never trust aggregate counts."""
    if (not isinstance(rows, list) or len(rows) != count
            or any(not isinstance(row, dict) or type(row.get('seed')) is not int for row in rows)
            or {row['seed'] for row in rows} != set(range(start, start + count))):
        raise ValueError('SEED_CENSUS_MISMATCH')
    for row in rows:
        if (row.get('valid_full_game') is not True or row.get('complete_game') is not True
                or row.get('score_scope') != 'valid_final'
                or any(type(row.get(k)) is not int or row[k] < 0 for k in ('home_points', 'away_points'))):
            raise ValueError(f"INVALID_SEED seed={row['seed']} status={row.get('status')} "
                             f"blocker={row.get('blocker')} error={row.get('error')}")
    return count
