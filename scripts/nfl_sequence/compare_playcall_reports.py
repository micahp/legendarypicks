"""Compare a regenerated play-call evaluation report with the committed one (research).

Run-time fields (stage_seconds, seconds_total, fits, lbfgs_iterations) differ between runs and are not compared. Every other value
must match: integers and strings exactly, floats within 1e-9. Each difference is printed. The exit status is 1 if any value differs.

Usage: python3 compare_playcall_reports.py COMMITTED.json REGENERATED.json
"""
import json
import sys

RUN_TIME_FIELDS = {'stage_seconds', 'seconds_total', 'fits', 'lbfgs_iterations'}
TOLERANCE = 1e-9


def is_number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def walk(committed, regenerated, path, diffs):
    if isinstance(committed, dict) and isinstance(regenerated, dict):
        for key in sorted(set(committed) | set(regenerated)):
            if not path and key in RUN_TIME_FIELDS:
                continue
            if key not in committed or key not in regenerated:
                diffs.append((path + [key], 'present on one side only'))
                continue
            walk(committed[key], regenerated[key], path + [key], diffs)
    elif isinstance(committed, list) and isinstance(regenerated, list):
        if len(committed) != len(regenerated):
            diffs.append((path, f'length {len(committed)} vs {len(regenerated)}'))
            return
        for index, (a, b) in enumerate(zip(committed, regenerated)):
            walk(a, b, path + [index], diffs)
    elif is_number(committed) and is_number(regenerated):
        if abs(committed - regenerated) > TOLERANCE:
            diffs.append((path, f'{committed} vs {regenerated}'))
    elif committed != regenerated:
        diffs.append((path, f'{committed!r} vs {regenerated!r}'))


def main():
    committed = json.load(open(sys.argv[1]))
    regenerated = json.load(open(sys.argv[2]))
    diffs = []
    walk(committed, regenerated, [], diffs)
    compared = 'every value except run-time fields'
    if not diffs:
        print(f'match: {compared}')
        return 0
    for path, message in diffs:
        print('/'.join(str(p) for p in path), message)
    print(f'{len(diffs)} difference(s) in {compared}')
    return 1


if __name__ == '__main__':
    sys.exit(main())
