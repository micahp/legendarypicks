"""Per-snap offensive position labels, with a reconstructed fallback (research).

The scrimmage table has one row per snap with two aligned lists: offense_ids (GSIS IDs) and offense_positions (the
on-field label for each ID). The 2022 offense_positions list is blank, so pairing it with the IDs by zip silently drops
every 2022 snap. Labels here are used only when the two lists have the same length and every label is present.
Otherwise each ID's label comes from the reconstructed PFR positions (reconstruct_positions.py), keyed by season,
game, team and GSIS ID. An ID with no label from either source is reported as unlabelled, never dropped.

Usage from another module:
    recon = load_reconstruction(path)
    for pid, label, source in aligned_labels(row, recon): ...
"""
import csv
from collections import Counter
from pathlib import Path

ONFIELD = 'onfield'
RECONSTRUCTED = 'reconstructed'
UNLABELLED = 'unlabelled'


def load_reconstruction(path):
    """{(season, game_id, team, gsis_id): position} from the reconstruction CSV."""
    out = {}
    with open(Path(path), newline='', encoding='utf-8') as handle:
        for row in csv.DictReader(handle):
            out[(int(row['season']), row['game_id'], row['team'], row['gsis_id'])] = row['position']
    return out


def aligned_labels(row, recon=None):
    """[(gsis_id, label or None, source)] for every ID in the row's offense list, in order. A label is None when
    neither the on-field list nor the reconstruction has one, so the caller can count it."""
    ids = [x for x in row['offense_ids'].split(';') if x]
    listed = [x for x in row['offense_positions'].split(';') if x]
    use_listed = len(listed) == len(ids) and len(ids) > 0
    season = int(row['season'])
    team = row['posteam']
    out = []
    for index, pid in enumerate(ids):
        if use_listed:
            out.append((pid, listed[index], ONFIELD))
            continue
        label = recon.get((season, row['game_id'], team, pid)) if recon else None
        out.append((pid, label, RECONSTRUCTED if label else UNLABELLED))
    return out


def source_counts(rows, recon=None):
    """Counts of ID-level label sources by season, for the coverage report."""
    counts = Counter()
    for row in rows:
        for _pid, _label, source in aligned_labels(row, recon):
            counts[(row['season'], source)] += 1
    return counts
