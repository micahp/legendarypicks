"""Export the PBV1 training table exactly as the PBV1 evaluation loaded it (SLC integration, research flag only).

Same population and filters as docs/research/pbv1-sampler-2026-11-02/pbv1_eval.py load_plays: regular-season scrimmage plays of
run or pass family, seasons 2022 to 2025, with every cell field known. The table is the frozen input of the SLC package sampler
(scripts/nfl_sequence/pbv1_package.py). Writes pbv1_training_plays.csv and pbv1_training_manifest.json next to this file. The
manifest records the SHA-256 of the CSV, the row counts by season, the exclusion counts and the gridiron source hashes.

Read only from the gridiron repo's raw files. Run from the repository root:
    python3 docs/research/pbv1-package-integration-2026-11-02/export_training.py
"""
import collections
import csv
import hashlib
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
GRID = os.path.abspath(os.path.join(HERE, '..', '..', '..', '..', 'gridiron-playbooks-research'))
if not os.path.isdir(os.path.join(GRID, 'pipeline')):
    GRID = '/root/gridiron-playbooks-research'
sys.path.insert(0, os.path.join(GRID, 'pipeline'))
import hpv1_build as hb  # noqa: E402

SEASONS = (2022, 2023, 2024, 2025)
COLUMNS = ['season', 'game_id', 'team', 'family', 'down', 'distance', 'red_zone', 'package', 'package_comparable']


def load_plays():
    plays, excluded = [], collections.Counter()
    for season in SEASONS:
        rows, _ = hb.season_frame(season)
        for r in rows.itertuples(index=False):
            if r.play_class != 'scrimmage':
                excluded['not_scrimmage'] += 1
                continue
            if r.season_type != 'REG':
                excluded['not_regular_season'] += 1
                continue
            if r.play_family not in ('run', 'pass') or r.down_label == 'UNKNOWN' or r.distance == 'UNKNOWN' \
                    or r.distance == 'OUT_OF_RANGE' or r.red_zone == 'UNKNOWN':
                excluded['unknown_cell_field'] += 1
                continue
            plays.append({'season': int(season), 'game_id': r.game_id, 'team': r.posteam, 'family': r.play_family,
                          'down': r.down_label, 'distance': r.distance, 'red_zone': int(r.red_zone),
                          'package': r.package, 'package_comparable': r.package_comparable})
    return plays, excluded


def _git(*args):
    return subprocess.run(['git', '-C', GRID] + list(args), capture_output=True, text=True).stdout.strip()


def _sha(path):
    return hashlib.sha256(open(path, 'rb').read()).hexdigest()


def main():
    plays, excluded = load_plays()
    csv_path = os.path.join(HERE, 'pbv1_training_plays.csv')
    with open(csv_path, 'w', newline='', encoding='utf-8') as handle:
        writer = csv.DictWriter(handle, fieldnames=COLUMNS, lineterminator='\n')
        writer.writeheader()
        writer.writerows(plays)
    by_season = collections.Counter(p['season'] for p in plays)
    manifest = {
        'schema': 'lp-slc-pbv1-training-table-1',
        'source': 'gridiron-playbooks-research pipeline/hpv1_build.py season_frame, as pbv1_eval.py load_plays',
        'gridiron_commit': _git('rev-parse', 'HEAD'),
        'gridiron_hpv1_build_sha256': _sha(os.path.join(GRID, 'pipeline', 'hpv1_build.py')),
        'gridiron_hpv1_contract_sha256': _sha(os.path.join(GRID, 'pipeline', 'hpv1_contract.py')),
        'seasons': list(SEASONS),
        'rows': len(plays),
        'rows_by_season': {str(s): by_season[s] for s in SEASONS},
        'excluded': dict(excluded),
        'csv_file': 'pbv1_training_plays.csv',
        'csv_sha256': _sha(csv_path),
    }
    with open(os.path.join(HERE, 'pbv1_training_manifest.json'), 'w', encoding='utf-8') as handle:
        json.dump(manifest, handle, indent=2, sort_keys=True)
        handle.write('\n')
    print(json.dumps({'rows': len(plays), 'rows_by_season': manifest['rows_by_season'],
                      'excluded': manifest['excluded'], 'csv_sha256': manifest['csv_sha256']}))


if __name__ == '__main__':
    main()
