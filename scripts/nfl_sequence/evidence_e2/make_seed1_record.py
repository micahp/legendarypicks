#!/usr/bin/env python3
"""Play seed 1 of the successor engine and write its record with the two version stamps (versions.py).

Refuses to run while the producing files have uncommitted changes. Usage: python3 make_seed1_record.py [--out PATH]
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
    record = versions.stamp(gs.play_game(1, ref))
    Path(args.out).write_text(json.dumps(record, indent=1, sort_keys=True) + '\n')
    print(f"wrote {args.out}: model {record['model_version'][:12]}, rules {record['rules_version'][:12]}, "
          f"status {record['status']}, points {record['points']}")


if __name__ == '__main__':
    main()
