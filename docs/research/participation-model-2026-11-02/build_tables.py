#!/usr/bin/env python3
"""Clean the pinned nflverse play-by-play and participation files into the two tables the participation model reads.

scrimmage_participation: one row per 2022 to 2025 run or pass play that has a participation row. It keeps the on-field
player IDs and the personnel grouping, and flags the rows that break the rules below. The personnel fit reads only the
rows with no flag.

usage_plays: one row per run, pass or dropback with its player IDs, for 2022 to 2026 from play-by-play. It is the only
current-season evidence for 2026, because no 2026 participation file is published (nflverse release pbp_participation
has no 2026 asset, checked 2026-11-02).

Rules, each counted in the cleaning report:
- Scrimmage means play_type run or pass in play-by-play. Kneels, spikes and special teams are not personnel plays here.
- A defensive position label (CB, S, LB, DL and similar) in offense_personnel excludes the row from the personnel fit.
- A count of on-field players other than 11 is kept and flagged. n_offense always equals the number of listed IDs.
- The personnel group is the running back count (RB plus FB) followed by the tight end count, so 1 RB, 1 TE, 3 WR is 11.
  A line other than five adds -OL<n> and a QB count other than one adds -QB<n>, so a six-lineman 12 is 12-OL6 and a
  two-QB 11 is 11-QB2. From 2023 the file lists every position (C, G and T for the line), so a missing QB is zero QBs.
  The 2022 format lists only the skill players, plus OL and QB when they are not five and one.
- A row with no QB, a kicker, punter or long snapper in offense_personnel (a fake kick), or a personnel string that does
  not total eleven is kept and flagged flag_nonstandard_offense, and the personnel fit leaves it out.
- Rows with no offense_personnel are excluded.

Usage: python3 build_tables.py --raw-dir <pinned nflverse CSVs> --out-dir <scratch dir> --report <json path>
"""
import argparse
import csv
import gzip
import hashlib
import io
import json
import re
from collections import Counter
from pathlib import Path

PARTICIPATION_SEASONS = (2022, 2023, 2024, 2025)
USAGE_SEASONS = (2022, 2023, 2024, 2025, 2026)
LINE_POSITIONS = {'OL', 'C', 'G', 'T', 'OT', 'OG'}
SPECIAL_POSITIONS = {'K', 'P', 'LS'}
DEFENSIVE_POSITIONS = {'DL', 'DE', 'DT', 'NT', 'LB', 'ILB', 'OLB', 'MLB', 'CB', 'FS', 'SS', 'S', 'DB', 'NB'}
TOKEN = re.compile(r'(\d+)\s+([A-Z]+)')
SCRIMMAGE_PLAYS = ('run', 'pass')
PLAY_FIELDS = ('season', 'week', 'season_type', 'game_id', 'play_id', 'posteam', 'play_type', 'down', 'ydstogo',
               'yardline_100', 'qtr', 'score_differential', 'passer_player_id', 'rusher_player_id', 'receiver_player_id')


def sha256(path):
    digest = hashlib.sha256()
    with open(path, 'rb') as handle:
        for block in iter(lambda: handle.read(1 << 20), b''):
            digest.update(block)
    return digest.hexdigest()


def parse_personnel(text):
    """Return ({position: count}, has_defensive_label). An empty string returns ({}, False)."""
    counts = {}
    for count, position in TOKEN.findall(text or ''):
        counts[position] = counts.get(position, 0) + int(count)
    return counts, bool(set(counts) & DEFENSIVE_POSITIONS)


def line_and_qb(counts):
    """(linemen, QBs) on the field. The 2023+ format names C, G and T, so absent QB means none. The 2022 format names only
    the skill players, adding OL and QB only when they are not five and one."""
    if counts.keys() & (LINE_POSITIONS - {'OL'}):
        return sum(counts.get(p, 0) for p in LINE_POSITIONS), counts.get('QB', 0)
    return counts.get('OL', 5), counts.get('QB', 1)


def group_code(counts):
    line, qbs = line_and_qb(counts)
    code = f"{counts.get('RB', 0) + counts.get('FB', 0)}{counts.get('TE', 0)}"
    return code + (f'-OL{line}' if line != 5 else '') + (f'-QB{qbs}' if qbs != 1 else '')


def nonstandard_offense(counts):
    """No QB, a kicker, punter or snapper on the field, or a personnel string that does not total eleven (a publisher
    error: the same rows list eleven player IDs)."""
    line, qbs = line_and_qb(counts)
    total = line + qbs + sum(counts.get(p, 0) for p in ('RB', 'FB', 'TE', 'WR'))
    return qbs == 0 or bool(counts.keys() & SPECIAL_POSITIONS) or total != 11


def load_plays(path):
    """Scrimmage plays keyed by (game_id, play_id). Only the columns the model reads are kept."""
    plays = {}
    with gzip.open(path, 'rt', encoding='utf-8', newline='') as handle:
        for row in csv.DictReader(handle):
            if row.get('play_type') not in SCRIMMAGE_PLAYS:
                continue
            key = (row['game_id'], row['play_id'].split('.')[0])
            plays[key] = {field: row.get(field, '') for field in PLAY_FIELDS}
    return plays


def build_participation(raw, out_dir, report):
    out_path = out_dir / 'scrimmage_participation.csv.gz'
    fields = ['season', 'week', 'season_type', 'game_id', 'play_id', 'posteam', 'play_type', 'down', 'ydstogo',
              'yardline_100', 'qtr', 'score_differential', 'group', 'n_rb', 'n_te', 'n_wr', 'personnel_raw',
              'n_offense', 'offense_ids', 'offense_positions', 'flag_defensive_label', 'flag_count_not_11',
              'flag_nonstandard_offense']
    counts = Counter()
    per_season = {}
    with gzip.GzipFile(out_path, 'wb', mtime=0) as raw_out, \
            io.TextIOWrapper(raw_out, encoding='utf-8', newline='') as out:  # mtime 0: the file hash is the content's
        writer = csv.DictWriter(out, fieldnames=fields)
        writer.writeheader()
        for season in PARTICIPATION_SEASONS:
            plays = load_plays(raw / f'pbp_{season}.csv.gz')
            season_counts = Counter()
            with open(raw / f'pbp_participation_{season}.csv', encoding='utf-8', newline='') as handle:
                for row in csv.DictReader(handle):
                    season_counts['participation_rows'] += 1
                    key = (row['nflverse_game_id'], row['play_id'])
                    play = plays.get(key)
                    if play is None or play['play_type'] not in SCRIMMAGE_PLAYS:
                        season_counts['not_scrimmage_or_unmatched'] += 1
                        continue
                    season_counts['scrimmage_rows'] += 1
                    personnel, defensive = parse_personnel(row['offense_personnel'])
                    if not personnel:
                        season_counts['excluded_blank_personnel'] += 1
                        continue
                    ids = [x for x in row['offense_players'].split(';') if x]
                    n_offense = row['n_offense']
                    flag_count = str(len(ids)) != '11' or n_offense != str(len(ids))
                    writer.writerow({
                        'season': season, 'week': play['week'], 'season_type': play['season_type'],
                        'game_id': play['game_id'], 'play_id': play['play_id'], 'posteam': play['posteam'],
                        'play_type': play['play_type'], 'down': play['down'], 'ydstogo': play['ydstogo'],
                        'yardline_100': play['yardline_100'], 'qtr': play['qtr'],
                        'score_differential': play['score_differential'], 'group': group_code(personnel),
                        'n_rb': personnel.get('RB', 0) + personnel.get('FB', 0), 'n_te': personnel.get('TE', 0),
                        'n_wr': personnel.get('WR', 0), 'personnel_raw': row['offense_personnel'],
                        'n_offense': n_offense, 'offense_ids': ';'.join(ids),
                        'offense_positions': row.get('offense_positions', ''),  # absent from the 2022 file
                        'flag_defensive_label': int(defensive), 'flag_count_not_11': int(flag_count),
                        'flag_nonstandard_offense': int(nonstandard_offense(personnel)),
                    })
                    season_counts['nonstandard_offense'] += nonstandard_offense(personnel)
                    season_counts['written'] += 1
                    season_counts['defensive_label' if defensive else 'clean_personnel'] += 1
                    season_counts['count_not_11' if flag_count else 'count_11'] += 1
            per_season[season] = dict(season_counts)
            counts.update(season_counts)
    report['scrimmage_participation'] = {'file': out_path.name, 'sha256': sha256(out_path), 'fields': fields,
                                         'per_season': per_season, 'totals': dict(counts)}
    return out_path


def build_usage(raw, out_dir, report):
    out_path = out_dir / 'usage_plays.csv.gz'
    fields = ['season', 'week', 'season_type', 'game_id', 'play_id', 'posteam', 'play_type', 'role', 'player_id']
    per_season = {}
    with gzip.open(out_path, 'wt', encoding='utf-8', newline='') as out:
        writer = csv.DictWriter(out, fieldnames=fields)
        writer.writeheader()
        for season in USAGE_SEASONS:
            counts = Counter()
            with gzip.open(raw / f'pbp_{season}.csv.gz', 'rt', encoding='utf-8', newline='') as handle:
                for row in csv.DictReader(handle):
                    if row.get('play_type') not in ('run', 'pass'):
                        continue
                    if row.get('season_type') not in ('REG', 'POST'):
                        continue
                    base = {k: row.get(k, '') for k in ('season', 'week', 'season_type', 'game_id', 'play_id',
                                                        'posteam', 'play_type')}
                    roles = []
                    if row['play_type'] == 'run' and row.get('rusher_player_id'):
                        roles.append(('carry', row['rusher_player_id']))
                    if row['play_type'] == 'pass':
                        if row.get('passer_player_id'):
                            roles.append(('dropback', row['passer_player_id']))
                        if row.get('receiver_player_id'):
                            roles.append(('target', row['receiver_player_id']))
                    if not roles:
                        counts['no_player_id'] += 1
                    for role, player in roles:
                        writer.writerow({**base, 'role': role, 'player_id': player})
                        counts[role] += 1
            per_season[season] = dict(counts)
    report['usage_plays'] = {'file': out_path.name, 'sha256': sha256(out_path), 'fields': fields,
                             'per_season': per_season}
    return out_path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--raw-dir', type=Path, required=True)
    ap.add_argument('--out-dir', type=Path, required=True)
    ap.add_argument('--report', type=Path, required=True)
    args = ap.parse_args()
    args.out_dir.mkdir(parents=True, exist_ok=True)
    report = {'schema': 'lp.nfl.participation-model-tables.v1', 'rules': __doc__.split('Rules, each counted in the cleaning report:')[1].split('Usage:')[0].strip()}
    build_participation(args.raw_dir, args.out_dir, report)
    build_usage(args.raw_dir, args.out_dir, report)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2, sort_keys=True) + '\n', encoding='utf-8')
    print(json.dumps(report['scrimmage_participation']['totals'], sort_keys=True))


if __name__ == '__main__':
    main()
