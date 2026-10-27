#!/usr/bin/env python3
"""Confirm the toss winner and the winner's choice each sample both sides across seeds 1-300, and pin the counts.

The toss is drawn from the seed before any play starts, so one drive per game (max_drives=1) reads the same ledger as a full
game. The pinned counts are the earlier measurement on the same seeds. If the draw order changes, this check fails loudly.

Writes docs/evidence/e2-successor/toss-sampling-300.json. Exits 1 when a side is never sampled or a count differs from the pin.
Usage: python3 toss_sampling_check.py
"""
import json
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))  # the engine (nfl_sequence)
import e2_reference as er  # noqa: E402
import game_state as gs  # noqa: E402

OUT = HERE.parents[2] / 'docs' / 'evidence' / 'e2-successor' / 'toss-sampling-300.json'
PINNED = {
    'winner': {'A': 153, 'B': 147},
    'choice': {'receive': 155, 'defer': 145},
    'winner_choice': {'A-receive': 83, 'A-defer': 70, 'B-receive': 72, 'B-defer': 75},
}


def main():
    ref, _ = er.load()
    seen = Counter()
    for seed in range(1, 301):
        ledger = gs.play_game(seed, ref, max_drives=1)['ledger']
        seen[('winner', ledger['winner'])] += 1
        seen[('choice', ledger['winner_choice'])] += 1
        seen[('winner_choice', f"{ledger['winner']}-{ledger['winner_choice']}")] += 1

    counts = {kind: {k: seen[(kind, k)] for k in PINNED[kind]} for kind in PINNED}
    checks = {
        'both_winners_sampled': all(v > 0 for v in counts['winner'].values()),
        'both_choices_sampled': all(v > 0 for v in counts['choice'].values()),
        'counts_match_pin': counts == PINNED,
    }
    summary = {'seeds': 300, 'max_drives': 1, 'counts': counts, 'pinned': PINNED, 'checks': checks,
               'passed': all(checks.values())}
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(summary, indent=1, sort_keys=True) + '\n')
    print(json.dumps(summary, indent=1, sort_keys=True))
    if not summary['passed']:
        sys.exit(1)


if __name__ == '__main__':
    main()
