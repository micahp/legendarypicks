#!/usr/bin/env python3
"""Wrap an E2 research record in the gridiron.lp-full-game-payload 1.0.0 envelope.

The record must carry research_source with hashes matching the current tree. This allows an explicitly identified dirty research
snapshot without claiming that it is a clean release. Usage: python3 build_envelope.py <record.json> <out.json>
"""
import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(HERE.parent))
import versions  # noqa: E402

def git(*args):
    return subprocess.run(['git', '-C', str(ROOT), *args], check=True, capture_output=True, text=True).stdout.strip()


def main():
    record_path, out_path = Path(sys.argv[1]), Path(sys.argv[2])
    raw = json.loads(record_path.read_text())
    source = versions.source_snapshot()
    record_source = raw.get('research_source')
    if not record_source or record_source != source:
        raise SystemExit('record research_source does not match the current engine and producer files')
    envelope = {
        'contract': {'name': 'gridiron.lp-full-game-payload', 'version': '1.0.0'},
        'source': {
            'repository': 'micahp/legendarypicks',
            'branch': git('rev-parse', '--abbrev-ref', 'HEAD'),
            'base_commit': git('rev-parse', 'HEAD'),
            'producer_worktree_dirty': source['producer_worktree_dirty'],
            'source_tree_sha256': source['source_tree_sha256'],
            'source_file_sha256': source['source_file_sha256'],
            'producer_file_sha256': source['producer_file_sha256'],
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
