#!/usr/bin/env python3
"""Play seed 1 and write the versioned research record, including an exact hash of the producing source tree.

The source fingerprint permits reproducible research output from an uncommitted tree. It does not relax the clean-tree
requirement of versions.stamp() for release records. Usage: python3 make_seed1_record.py [--out PATH]
"""
import argparse
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
import e2_reference as er  # noqa: E402
import game_state as gs  # noqa: E402
import versions  # noqa: E402

DEFAULT_OUT = HERE.parents[2] / 'docs' / 'evidence' / 'e2-successor' / 'seed1-game-successor.json'


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--out', default=str(DEFAULT_OUT))
    args = ap.parse_args()
    ref, _ = er.load()
    record = versions.research_stamp(gs.play_game(1, ref))
    Path(args.out).write_text(json.dumps(record, indent=1, sort_keys=True) + '\n')
    print(f"wrote {args.out}: model base {record['model_version'][:12]}, source {record['research_source']['source_tree_sha256'][:12]}, "
          f"status {record['status']}, points {record['points']}")


if __name__ == '__main__':
    main()
