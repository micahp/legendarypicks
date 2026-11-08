"""Observed sack rate by situation cell for ablation A (restore_sack_mass). Writes docs/research/slc-scoring-realism-ablation-A/obs_sack_cells.json.

Query: nfl_pbp, seasons 2022-2025, weeks 1-18, quarters 1-4, play_type 'pass', down 1-4, ydstogo not null, yardline_100 1-99.
Cell: e0_single_play.pool_key(down, ydstogo, yardline_100). Sack rate = sacks / dropbacks, where a dropback is any such row.
Shrinkage: cells with fewer than 100 dropbacks get obs = (sacks + 100 * pooled) / (dropbacks + 100), pooled = all sacks / all dropbacks.
"""
import hashlib
import json
import sqlite3
import sys
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import e0_single_play as e0  # noqa: E402

DB = '/root/legendarypicks/backend/data/picks.dev.db'
OUT = HERE.parents[1] / 'docs/research/slc-scoring-realism-ablation-A/obs_sack_cells.json'
QUERY = """select down, ydstogo, yardline_100, sack, complete_pass, interception from nfl_pbp
where season between 2022 and 2025 and week between 1 and 18 and qtr between 1 and 4 and play_type='pass'
and down between 1 and 4 and ydstogo is not null and yardline_100 between 1 and 99"""
PSEUDO = 100


def main():
    conn = sqlite3.connect(f'file:{DB}?mode=ro', uri=True)
    dropbacks, sacks, incomplete = defaultdict(int), defaultdict(int), defaultdict(int)
    for down, togo, yl, sack, comp, intercept in conn.execute(QUERY):
        cell = str(e0.pool_key(int(down), int(togo), int(yl)))
        dropbacks[cell] += 1
        if sack == 1:
            sacks[cell] += 1
        elif not comp and not intercept:
            incomplete[cell] += 1
    total_n, total_sacks = sum(dropbacks.values()), sum(sacks.values())
    pooled = total_sacks / total_n
    cells = {}
    for cell in sorted(dropbacks):
        n, s = dropbacks[cell], sacks[cell]
        obs = (s + PSEUDO * pooled) / (n + PSEUDO) if n < PSEUDO else s / n
        cells[cell] = {'dropbacks': n, 'sacks': s, 'incomplete': incomplete[cell],
                       'obs_sack_rate': obs, 'shrunk': n < PSEUDO}
    doc = {'query': QUERY, 'database': DB, 'pseudo_count': PSEUDO, 'pooled_sack_rate': pooled,
           'pooled_dropbacks': total_n, 'pooled_sacks': total_sacks, 'cells': cells}
    OUT.write_text(json.dumps(doc, indent=1, sort_keys=True) + '\n', encoding='utf-8')
    print('cells', len(cells), 'dropbacks', total_n, 'sacks', total_sacks, 'pooled %.6f' % pooled)
    print('cells under 100 dropbacks', sum(1 for c in cells.values() if c['shrunk']))
    print('sha256', hashlib.sha256(OUT.read_bytes()).hexdigest(), OUT)


if __name__ == '__main__':
    main()
