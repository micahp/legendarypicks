#!/usr/bin/env python3
"""Validate the skill-lineup transitions on the 2025 holdout (fit on 2022 to 2024 with export_field.py).

Three simulated versions of each team's offensive snaps in 2025 are compared with the observed snaps:

- free: the grouping and the lineup are both simulated. Grouping transitions, leaves and entrants all come from the model.
- forced: the observed grouping is given on each snap, and the lineup is simulated. This isolates the substitution mechanics.
- independent: the lineup is drawn fresh on every snap from rates, with no memory. This is the design the owner rejected,
  kept here as the control that the persistence checks should fail.

The bench for the simulated snaps is each team's 2025 skill players who appeared in its scrimmage table. That is a
roster proxy: the simulator will use the pregame snapshot roster, which includes players with no 2025 appearances.

Usage: python3 validate_lineups.py --tables <scrimmage_participation.csv.gz> --raw-dir <pinned nflverse dir> \
           --field <field_2022_2024.json> --out <json> [--seeds 3]
"""
import argparse
import json
import random
import sys
from collections import Counter, defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parents[2] / 'scripts' / 'nfl_sequence'))  # the runtime module the simulator loads
import lineup_fit as lf  # noqa: E402
import participation_field as pf  # noqa: E402
import participation_model as pm  # noqa: E402

HOLDOUT = {2025}
CLASSES = pf.SKILL_CLASSES


def classes_of(positions):
    return {pid: lf.SKILL[pos] for pid, pos in positions.items() if pos in lf.SKILL}


def roster_by_team(rows, cls_of, positions):
    """Each team's 2025 skill players, as dicts the runtime module reads."""
    seen = defaultdict(set)
    for row in rows:
        for pid in row['ids']:
            if pid in cls_of:
                seen[row['posteam']].add(pid)
    return {team: [{'gsis_id': pid, 'pos_abb': positions[pid], 'pos_rank': index}
                   for index, pid in enumerate(sorted(pids))] for team, pids in seen.items()}


def observed(seqs):
    return {key: [(group, frozenset(pid for pid, _ in skill)) for group, _cell, skill in seq]
            for key, seq in seqs.items()}


def simulate(field, seqs, rosters, cls_of, mode, seed):
    out, skipped = {}, 0
    for key, seq in sorted(seqs.items()):
        _season, _game, team = key
        draw = random.Random(f'{key}|{mode}|{seed}')
        roster = rosters[team]
        lineup, prev, snaps = {}, pf.START, []
        for group_obs, cell, _skill in seq:
            group = field.draw_group(team, prev, cell, draw) if mode == 'free' else group_obs
            if group is None:
                skipped += 1
                break
            if mode == 'independent':
                ids = set()
                for cls in CLASSES:
                    pool = [p for p in roster if cls_of.get(p['gsis_id']) == cls]
                    ids |= {p['gsis_id'] for p in field._weighted(pool, pf.group_counts(group)[cls], team, group, draw)}
                snaps.append((group, frozenset(ids)))
            else:
                lineup, _record = field.advance(team, lineup, group, roster, draw, prev_group=prev)
                snaps.append((group, frozenset(lineup)))
            prev = group
        else:
            out[key] = snaps
    return out, skipped


def metrics(sim, cls_of):
    pairs = same_group = same_lineup = same_lineup_given_group = entries = snaps = matched = 0
    entries_by = Counter()
    player_snaps = stint_sum = stint_four_plus = 0
    games = len(sim)
    for key, seq in sim.items():
        prev_group, prev_ids, stint = None, frozenset(), {}
        for group, ids in seq:
            snaps += 1
            counts = Counter(cls_of.get(pid) for pid in ids)
            if all(counts[cls] == pf.group_counts(group)[cls] for cls in CLASSES):
                matched += 1
            stint = {pid: stint[pid] + 1 if pid in stint else 1 for pid in ids}
            player_snaps += len(ids)
            stint_sum += sum(stint.values())
            stint_four_plus += sum(1 for value in stint.values() if value >= 4)
            if prev_group is not None:
                pairs += 1
                same_group += group == prev_group
                same_lineup += ids == prev_ids
                same_lineup_given_group += (group == prev_group) and ids == prev_ids
                came_in = ids - prev_ids
                entries += len(came_in)
                for pid in came_in:
                    entries_by[cls_of.get(pid)] += 1
            prev_group, prev_ids = group, ids
    return {
        'team_games': games, 'snaps': snaps, 'snap_pairs': pairs,
        'grouping_same_as_previous_snap': round(same_group / pairs, 4),
        'skill_lineup_same_as_previous_snap': round(same_lineup / pairs, 4),
        'skill_lineup_same_given_grouping_same': round(same_lineup_given_group / same_group, 4) if same_group else None,
        'entries_per_snap': round(entries / pairs, 4),
        'entries_per_game_by_class': {cls: round(entries_by[cls] / games, 3) for cls in CLASSES},
        'mean_stint_per_player_snap': round(stint_sum / player_snaps, 3),
        'share_player_snaps_stint_four_plus': round(stint_four_plus / player_snaps, 4),
        'counts_match_grouping_share': round(matched / snaps, 4),
    }


def average(dicts):
    out = {}
    for key in dicts[0]:
        values = [d[key] for d in dicts]
        if isinstance(values[0], dict):
            out[key] = {sub: round(sum(v[sub] for v in values) / len(values), 3) for sub in values[0]}
        elif isinstance(values[0], (int, float)):
            out[key] = round(sum(values) / len(values), 4)
        else:
            out[key] = values[0]
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--tables', type=Path, required=True)
    ap.add_argument('--raw-dir', type=Path, required=True)
    ap.add_argument('--field', type=Path, required=True)
    ap.add_argument('--out', type=Path, required=True)
    ap.add_argument('--seeds', type=int, default=3)
    args = ap.parse_args()
    rows = pm.load_scrimmage(args.tables, HOLDOUT)
    positions = pm.load_positions(args.raw_dir)
    cls_of = classes_of(positions)
    seqs = lf.sequences(rows, positions)
    rosters = roster_by_team(rows, cls_of, positions)
    field = pf.Field.load(args.field, pf.sha256_file(args.field))
    result = {'holdout': sorted(HOLDOUT), 'field': {'file': args.field.name, 'sha256': field.sha256},
              'seeds': args.seeds, 'observed': metrics(observed(seqs), cls_of), 'arms': {}}
    for mode in ('free', 'forced', 'independent'):
        per_seed, skipped_total = [], 0
        for seed in range(1, args.seeds + 1):
            sim, skipped = simulate(field, seqs, rosters, cls_of, mode, seed)
            per_seed.append(metrics(sim, cls_of))
            skipped_total += skipped
        result['arms'][mode] = {'metrics': average(per_seed), 'team_games_skipped_no_league_cell': skipped_total}
    result['status_counts'] = dict(field.status)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=1, sort_keys=True) + '\n', encoding='utf-8')
    print(json.dumps(result, indent=1, sort_keys=True))


if __name__ == '__main__':
    main()
