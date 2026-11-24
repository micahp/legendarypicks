#!/usr/bin/env python3
"""Week 11 rerun: seed completion per model, the failure breakdown, and matched-seed copies. Read-only on the runs.

Inputs:
  --runs   RUNS/<game_id>/<model>.json  portable runtime output (summary.outcomes, player_boxscores_by_seed)

Completion: a seed is completed when its outcome has valid_full_game true (regulation or overtime). Every other seed is a
failure, classified by its blocker, or by status simulation_error with the engine error text.

Matched seeds: for each game, the seeds that every model completed. --matched-out writes a copy of every run with
valid_full_game set false on the other seeds, so build_report.py, props_compare.py and grade.py read only matched seeds
without any change. The original files are not touched.

Usage: python3 matched_seeds.py --runs DIR --out-dir DIR [--matched-out DIR]
"""
from __future__ import annotations

import argparse
import collections
import glob
import json
import os
import re
from pathlib import Path

MODELS = ('v1', 'v1.5', 'v1.6', 'v2', 'pbv1', 'pbv1-off')
CELL = re.compile(r"^(?P<family>[a-z_]+):\((?P<down>\d+), '(?P<distance>[^']+)', '(?P<field>[^']+)'\)$")


def failure(o):
    """(class, family, detail) for a seed that did not complete."""
    if o['status'] == 'simulation_error':
        text = o.get('error') or ''
        return 'engine_error', text.split(';')[0].split(': ', 1)[-1][:120], None
    blocker = o.get('blocker') or o['status']
    m = CELL.match(blocker)
    if m:
        return 'unsupported_cell', m['family'], {'down': int(m['down']), 'distance': m['distance'], 'field': m['field']}
    return 'unsupported_cell', blocker.split(':')[0], {'detail': blocker}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--runs', required=True)
    ap.add_argument('--out-dir', required=True)
    ap.add_argument('--matched-out')
    args = ap.parse_args(argv)

    attempted, completed = collections.Counter(), collections.Counter()
    by_class = collections.defaultdict(collections.Counter)
    by_family = collections.defaultdict(collections.Counter)
    cells, errors, games_hit = [], [], collections.defaultdict(set)
    matched = {}
    for game_dir in sorted(glob.glob(os.path.join(args.runs, '2026_11_*'))):
        game = os.path.basename(game_dir)
        data = {m: json.loads(Path(game_dir, f'{m}.json').read_text()) for m in MODELS}
        valid = {}
        for m, d in data.items():
            valid[m] = {o['seed'] for o in d['summary']['outcomes'] if o['valid_full_game']}
            for o in d['summary']['outcomes']:
                attempted[m] += 1
                if o['valid_full_game']:
                    completed[m] += 1
                    continue
                cls, family, detail = failure(o)
                by_class[m][cls] += 1
                by_family[m][family] += 1
                games_hit[m].add(game)
                row = {'model': m, 'game_id': game, 'seed': o['seed'], 'class': cls, 'family': family}
                (errors if cls == 'engine_error' else cells).append(dict(row, **(detail or {}), error=o.get('error')))
        common = set.intersection(*valid.values())
        matched[game] = {'common_seeds': len(common), 'requested': len(data['v1']['summary']['outcomes'])}
        if args.matched_out:
            os.makedirs(os.path.join(args.matched_out, game), exist_ok=True)
            for m, d in data.items():
                for o in d['summary']['outcomes']:
                    o['valid_full_game'] = o['valid_full_game'] and o['seed'] in common
                Path(args.matched_out, game, f'{m}.json').write_text(json.dumps(d))

    out = {
        'completion': {m: {'attempted': attempted[m], 'completed': completed[m],
                           'completion_pct': round(100 * completed[m] / attempted[m], 2),
                           'failures': attempted[m] - completed[m], 'games_with_a_failure': len(games_hit[m]),
                           'by_class': dict(by_class[m]), 'by_family': dict(by_family[m])} for m in MODELS},
        'unsupported_cell_failures': cells, 'engine_error_failures': errors, 'matched_seeds_by_game': matched,
        'matched_seeds_total': sum(v['common_seeds'] for v in matched.values()),
    }
    Path(args.out_dir, 'seed_completion.json').write_text(json.dumps(out, indent=1, sort_keys=True, default=str) + '\n')
    for m in MODELS:
        c = out['completion'][m]
        print(f"{m}: {c['completed']}/{c['attempted']} ({c['completion_pct']}%) failures {c['failures']} {c['by_class']}")
    print('matched seeds', out['matched_seeds_total'], {g: v['common_seeds'] for g, v in matched.items()})
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
