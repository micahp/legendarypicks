#!/usr/bin/env python3
"""Export the skill-lineup tables for the SLC participation field (research, option A).

Reads the scrimmage table written by build_tables.py and the pinned players.csv, and writes one JSON file with the grouping
transitions, the leave hazards and the on-field rates (lineup_fit.py and participation_model.py). The simulator loads it
with its sha256 (scripts/nfl_sequence/participation_field.py). Only the seasons named by --seasons are read. Production
uses 2022 to 2025. Validation fits 2022 to 2024 and holds out 2025.

Usage: python3 export_field.py --tables <scrimmage_participation.csv.gz> --raw-dir <pinned nflverse dir> \
           --seasons 2022,2023,2024,2025 --out <json>
"""
import argparse
import hashlib
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import lineup_fit  # noqa: E402
import participation_model as pm  # noqa: E402

SCHEMA = 'lp.nfl.participation-field.v4'  # v3 codes (-OL<n>, -QB<n>) plus transitions conditioned on the call


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--tables', type=Path, required=True)
    ap.add_argument('--raw-dir', type=Path, required=True)
    ap.add_argument('--seasons', required=True, help='comma-separated, for example 2022,2023,2024,2025')
    ap.add_argument('--out', type=Path, required=True)
    args = ap.parse_args()
    seasons = {int(season) for season in args.seasons.split(',')}
    rows = pm.load_scrimmage(args.tables, seasons)
    positions = pm.load_positions(args.raw_dir)
    seqs = lineup_fit.sequences(rows, positions, with_intent=True)
    fitted = lineup_fit.fit(seqs, seasons)
    rates = pm.fit_player_rates(rows, seasons, positions)
    data = {
        'schema': SCHEMA,
        'seasons': sorted(seasons),
        'recency': {str(season): weight for season, weight in pm.RECENCY.items()},
        'source': {'scrimmage_table': args.tables.name, 'scrimmage_table_sha256': sha256(args.tables),
                   'players_csv_sha256': sha256(args.raw_dir / 'players.csv'), 'scrimmage_rows': len(rows),
                   'game_sequences': len(seqs)},
        'fit_checks': fitted['checks'],
        'league_transitions': fitted['league_transitions'],
        'team_transitions': fitted['team_transitions'],
        'league_transitions_by_intent': fitted['league_transitions_by_intent'],
        'team_transitions_by_intent': fitted['team_transitions_by_intent'],
        'leave_counts': fitted['leave_counts'],
        'appearances': [[pid, team, group, weight]
                        for (pid, team, group), weight in sorted(rates['appearances'].items())],
        'team_plays': [[team, group, weight] for (team, group), weight in sorted(rates['team_plays'].items())],
        'position_prior': [[pos, group, value] for (pos, group), value in sorted(rates['position_prior'].items())],
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(data, separators=(',', ':'), sort_keys=True) + '\n', encoding='utf-8')
    print(json.dumps({'out': str(args.out), 'sha256': sha256(args.out), 'seasons': data['seasons'],
                      'scrimmage_rows': len(rows), 'game_sequences': len(seqs), 'fit_checks': fitted['checks'],
                      'league_transitions': len(data['league_transitions']),
                      'team_transitions': len(data['team_transitions']), 'leave_counts': len(data['leave_counts'])},
                     sort_keys=True))


if __name__ == '__main__':
    main()
