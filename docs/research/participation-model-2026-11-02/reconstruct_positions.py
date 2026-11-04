#!/usr/bin/env python3
"""Recover per-game offensive positions for 2022 from the PFR snap counts, and validate them on 2023 to 2025 (research).

The 2022 participation file has no offense_positions labels, so the position-group prior for 2022 is blank. The local
database holds PFR snap counts with one position per player-game (nfl_hist_snap_counts, 2022 to 2025). PFR IDs map to
GSIS IDs through nfl_hist_player_ids. This script:

1. Maps every PFR row to a GSIS ID, and audits the mapping: unmatched PFR IDs, PFR IDs that map to more than one GSIS
   ID, and GSIS IDs that map to more than one PFR ID.
2. Validates the same source where the on-field labels exist (2023 to 2025): for each on-field skill snap, does the
   PFR position for that player in that game agree with the on-field label? Agreement is reported by label.
3. Writes the reconstructed (season, game_id, team, gsis_id, position) rows for 2022 to 2025 to CSV.

Usage: python3 reconstruct_positions.py --tables <scrimmage_participation.csv.gz> --out <json> --out-csv <csv>
"""
import argparse
import csv
import json
import sqlite3
import sys
from collections import Counter, defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import participation_model as pm  # noqa: E402

DB = 'file:/root/legendarypicks/backend/data/picks.dev.db?mode=ro'
SKILL = {'RB', 'FB', 'TE', 'WR'}
# PFR uses LAR and WSH; the participation and play-by-play files use LA and WAS for 2022 to 2025 posteam.
sys.path.insert(0, str(Path(__file__).resolve().parents[3] / 'scripts'))
import nfl_team_codes  # noqa: E402  backend/team_codes.py, the one place team codes are defined


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--tables', type=Path, required=True)
    ap.add_argument('--out', type=Path, required=True)
    ap.add_argument('--out-csv', type=Path, required=True)
    args = ap.parse_args()

    con = sqlite3.connect(DB, uri=True)
    id_rows = con.execute('select gsis_id, pfr_id from nfl_hist_player_ids').fetchall()
    pfr_to_gsis = defaultdict(set)
    gsis_to_pfr = defaultdict(set)
    for gsis, pfr in id_rows:
        if gsis and pfr:
            pfr_to_gsis[pfr].add(gsis)
            gsis_to_pfr[gsis].add(pfr)
    snaps = con.execute(
        "select game_id, season, week, team, pfr_player_id, position, offense_snaps from nfl_hist_snap_counts "
        "where season between 2022 and 2025 and game_type = 'REG'").fetchall()
    con.close()

    audit = Counter()
    recon = {}  # (season, game_id, team, gsis) -> position
    for game_id, season, week, raw_team, pfr, position, offense in snaps:
        team = nfl_team_codes.to_nflverse(raw_team)
        if not offense or not offense > 0:
            audit['no_offense_snaps'] += 1
            continue
        gsis_set = pfr_to_gsis.get(pfr, set())
        if not gsis_set:
            audit['pfr_unmatched'] += 1
            continue
        if len(gsis_set) > 1:
            audit['pfr_ambiguous'] += 1
            continue
        gsis = next(iter(gsis_set))
        audit['matched'] += 1
        recon[(int(season), game_id, team, gsis)] = position
    audit['gsis_with_multiple_pfr'] = sum(1 for g, p in gsis_to_pfr.items() if len(p) > 1)

    rows = [r for r in pm.load_scrimmage(args.tables, {2022, 2023, 2024, 2025}) if r['season_type'] == 'REG']
    onfield = {}
    for row in rows:
        for pid, label in zip(row['offense_ids'].split(';'), row['offense_positions'].split(';')):
            if pid and label in SKILL:
                onfield[(int(row['season']), row['game_id'], row['posteam'], pid)] = label

    agree = defaultdict(Counter)
    for key, label in onfield.items():
        pfr_pos = recon.get(key)
        if pfr_pos is None:
            agree[label]['no_pfr_row'] += 1
        elif pfr_pos == label:
            agree[label]['agree'] += 1
        else:
            agree[label]['disagree'] += 1
    validation = {label: {**dict(c), 'matched_agreement': round(c['agree'] / max(c['agree'] + c['disagree'], 1), 6)}
                  for label, c in sorted(agree.items())}

    coverage = Counter()
    for (season, game, team, gsis), pos in recon.items():
        coverage[(season, pos if pos in SKILL or pos in ('QB', 'T', 'G', 'C') else 'other')] += 1

    args.out_csv.parent.mkdir(parents=True, exist_ok=True)
    with open(args.out_csv, 'w', newline='', encoding='utf-8') as handle:
        writer = csv.writer(handle)
        writer.writerow(['season', 'game_id', 'team', 'gsis_id', 'position'])
        for (season, game, team, gsis), pos in sorted(recon.items()):
            writer.writerow([season, game, team, gsis, pos])

    out = {'audit': dict(audit),
           'pfr_to_gsis_unique_fraction': round(sum(1 for p in pfr_to_gsis.values() if len(p) == 1) / max(len(pfr_to_gsis), 1), 4),
           'reconstructed_player_games_by_season_and_position': {f'{s}|{p}': n for (s, p), n in sorted(coverage.items())},
           'validation_on_onfield_labels_2023_2025': validation,
           'note': 'validation compares the PFR position with the on-field label for the same game, team and player; '
                   'the 2022 rows are reconstructed only and have no on-field labels to check against'}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(out, indent=1, sort_keys=True) + '\n', encoding='utf-8')
    print(json.dumps({'audit': out['audit'], 'validation': out['validation_on_onfield_labels_2023_2025']}, sort_keys=True))


if __name__ == '__main__':
    main()
