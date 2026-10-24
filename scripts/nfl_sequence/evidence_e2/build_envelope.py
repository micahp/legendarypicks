#!/usr/bin/env python3
"""Wrap an E2 game record in the gridiron.lp-full-game-payload 1.0.0 envelope, the way the frozen envelope wraps the frozen
record: the record is passed through unaltered, and the source block pins the producer branch, commit and engine file hashes.

Refuses to run while the producer files have uncommitted changes, so the envelope never pins code it does not describe.
Usage: python3 build_envelope.py <record.json> <out.json>
"""
import hashlib
import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(HERE.parent))
import versions  # noqa: E402

PRODUCER_FILES = versions.RULE_FILES  # the same scoped set that defines rules_version


def git(*args):
    return subprocess.run(['git', '-C', str(ROOT), *args], check=True, capture_output=True, text=True).stdout.strip()


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    record_path, out_path = Path(sys.argv[1]), Path(sys.argv[2])
    if git('status', '--porcelain', '--', *PRODUCER_FILES):
        raise SystemExit('producer files have uncommitted changes; commit them before building the envelope')
    raw = json.loads(record_path.read_text())
    envelope = {
        'contract': {'name': 'gridiron.lp-full-game-payload', 'version': '1.0.0'},
        'source': {
            'repository': 'micahp/legendarypicks',
            'branch': git('rev-parse', '--abbrev-ref', 'HEAD'),
            'base_commit': git('rev-parse', 'HEAD'),
            'producer_worktree_dirty': False,
            'producer_file_sha256': {f: sha256(ROOT / f) for f in PRODUCER_FILES},
            'data_source': {'table': 'nfl_pbp', 'seasons': [2022, 2025], 'week_max': 18, 'as_of': 'unknown',
                            'selection': 'retrospective empirical sampling'},
        },
        'record': raw.get('record', raw),
    }
    out_path.write_text(json.dumps(envelope, indent=1) + '\n')
    print(f"wrote {out_path}: base_commit {envelope['source']['base_commit'][:12]}, "
          f"{len(envelope['record']['drives'])} drives")


if __name__ == '__main__':
    main()
