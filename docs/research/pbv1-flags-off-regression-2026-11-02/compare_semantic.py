"""Compare the per-seed semantic records of two batch ledgers (<name>.seeds.jsonl), ignoring provenance fields.

Provenance is whatever identifies the code, artifacts or reference rather than the game: code and artifact hashes,
the reference fingerprint, the resealed snapshot hash and the RNG manifest. Everything else is a semantic record.
Usage: compare_semantic.py <base.seeds.jsonl> <new.seeds.jsonl>
Prints the count of differing seeds, and each differing field path grouped by its last key.
"""
import collections
import json
import sys

PROVENANCE = {'snapshot_sha256', 'observed_reference_sha256', 'reference_sha256', 'integration_code_sha256',
              'source_commit', 'producer_file_sha256', 'rng_protocol', 'layer_artifact_sha256', 'model_artifact_sha256',
              'implementation_sha256', 'input_provenance', 'playcall_artifact_sha256', 'artifact_sha256'}


def load(path):
    with open(path, encoding='utf-8') as handle:
        lines = [json.loads(line) for line in handle if line.strip()]
    rows = {row['seed']: row for row in lines[1:]}
    return lines[0].get('header', {}), rows


def strip(value):
    if isinstance(value, dict):
        return {k: strip(v) for k, v in value.items() if k not in PROVENANCE}
    if isinstance(value, list):
        return [strip(v) for v in value]
    return value


def diff(a, b, path=''):
    if isinstance(a, dict) and isinstance(b, dict):
        out = []
        for key in sorted(set(a) | set(b)):
            if key not in a or key not in b:
                out.append((f'{path}/{key}', 'only in one side'))
            else:
                out.extend(diff(a[key], b[key], f'{path}/{key}'))
        return out
    if isinstance(a, list) and isinstance(b, list):
        if len(a) != len(b):
            return [(f'{path}', f'length {len(a)} vs {len(b)}')]
        out = []
        for i, (x, y) in enumerate(zip(a, b)):
            out.extend(diff(x, y, f'{path}[{i}]'))
        return out
    return [] if a == b else [(path, f'{a!r} vs {b!r}')]


def main():
    base_header, base = load(sys.argv[1])
    new_header, new = load(sys.argv[2])
    if sorted(base) != sorted(new):
        print(f'seed sets differ: {sorted(base)} vs {sorted(new)}')
    differing, by_key = 0, collections.Counter()
    samples = []
    for seed in sorted(set(base) & set(new)):
        found = diff(strip(base[seed]), strip(new[seed]))
        if found:
            differing += 1
            for path, _ in found:
                by_key[path.rsplit('/', 1)[-1].split('[')[0]] += 1
            samples.extend((seed, p, v) for p, v in found[:3])
    print(f'seeds compared: {len(set(base) & set(new))}; seeds with semantic differences: {differing}')
    for key, count in by_key.most_common(20):
        print(f'  {count:6d}  {key}')
    for seed, path, value in samples[:12]:
        print(f'  seed {seed}: {path}: {value}')


if __name__ == '__main__':
    main()
