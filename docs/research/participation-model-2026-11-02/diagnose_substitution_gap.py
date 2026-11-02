#!/usr/bin/env python3
"""Decompose the 2025 substitution gap between observed snaps and the lineup model (diagnostic only).

The model is fitted on 2022 to 2024 (field table from export_field.py). 2025 is the holdout and is only read here, for
comparison. Nothing in this script is fitted on 2025. Observed and simulated snap pairs are aligned by index within each
team-game, so every strata count uses the same pairs on both sides.

Usage: python3 diagnose_substitution_gap.py --tables <scrimmage_participation.csv.gz> --raw-dir <pinned nflverse dir> \
           --pbp <pbp_2025.csv.gz> --field <field_2022_2024.json> --out <json> [--seeds 3]
"""
import argparse
import csv
import gzip
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parents[2] / 'scripts' / 'nfl_sequence'))
import lineup_fit as lf  # noqa: E402
import participation_field as pf  # noqa: E402
import participation_model as pm  # noqa: E402
import validate_lineups as vl  # noqa: E402

CLASSES = pf.SKILL_CLASSES
CAP = pf.STINT_CAP
ORDER = {'RB': 0, 'TE': 1, 'WR': 2}


def load_drives(path):
    """(game_id, play_id) -> drive number, from the nflverse play-by-play for the holdout season."""
    drives = {}
    with gzip.open(path, 'rt', newline='') as handle:
        for row in csv.DictReader(handle):
            if row['play_id'] and row['drive']:
                drives[(row['game_id'], int(float(row['play_id'])))] = int(float(row['drive']))
    return drives


def consistent(group, ids, cls_of):
    counts = Counter(cls_of.get(pid) for pid in ids)
    return all(counts[cls] == pf.group_counts(group)[cls] for cls in CLASSES)


def stint_track(ids_seq):
    """Stint at each snap: consecutive snaps on the field, counting the current snap."""
    out, prev, stint = [], set(), {}
    for ids in ids_seq:
        stint = {pid: (stint[pid] + 1 if pid in prev else 1) for pid in ids}
        out.append(stint)
        prev = set(ids)
    return out


def signature(prev_group, group, enter_cls, leave_cls):
    parts = [f'{cls}:-{leave_cls[cls]}+{enter_cls[cls]}' for cls in CLASSES if leave_cls[cls] or enter_cls[cls]]
    return f'{prev_group}>{group}|' + (' '.join(parts) if parts else 'none')


def pair_records(seq_groups, seq_ids, seq_ok, seq_drive, cls_of):
    """One record per consecutive snap pair. Clean means both snaps match their listed grouping (observed side)."""
    st = stint_track(seq_ids)
    records = []
    for i in range(1, len(seq_ids)):
        prev, cur = seq_ids[i - 1], seq_ids[i]
        enter = cur - prev
        leave = prev - cur
        enter_cls = Counter(cls_of.get(pid) for pid in enter)
        leave_cls = Counter(cls_of.get(pid) for pid in leave)
        exposure = [(cls_of.get(pid), min(st[i - 1][pid], CAP), pid not in cur) for pid in prev]
        drive_known = seq_drive[i] is not None and seq_drive[i - 1] is not None
        records.append({
            'clean': seq_ok[i] and seq_ok[i - 1],
            'changed_group': seq_groups[i] != seq_groups[i - 1],
            'new_drive': (seq_drive[i] != seq_drive[i - 1]) if drive_known else None,
            'entries': len(enter),
            'enter_cls': {cls: enter_cls[cls] for cls in CLASSES},
            'classes_entering': sum(1 for cls in CLASSES if enter_cls[cls]),
            'signature': signature(seq_groups[i - 1], seq_groups[i], enter_cls, leave_cls),
            'exposure': exposure,
        })
    return records


def mean(values):
    return sum(values) / len(values) if values else None


def bucket(n):
    return str(n) if n < 4 else '4+'


def summarize(records):
    """Mean entries per pair, histogram of entries per pair and class means, over a list of records."""
    n = len(records)
    if not n:
        return {'pairs': 0}
    hist = Counter(bucket(r['entries']) for r in records)
    return {'pairs': n, 'entries_per_pair': round(mean([r['entries'] for r in records]), 4),
            'histogram': {k: round(hist[k] / n, 4) for k in ('0', '1', '2', '3', '4+')},
            'entries_per_pair_by_class': {cls: round(mean([r['enter_cls'][cls] for r in records]), 4)
                                          for cls in CLASSES},
            'share_pairs_two_or_more_classes_entering': round(
                sum(1 for r in records if r['classes_entering'] >= 2) / n, 4),
            'unchanged_lineup_share': round(sum(1 for r in records if r['entries'] == 0) / n, 4)}


def stratum_gap(obs, mod, field_name, label_fn):
    """Decomposition by one factor over the same observed pairs: gap = sum over strata of share * (obs mean - model mean)."""
    groups = defaultdict(lambda: ([], []))
    for o, m in zip(obs, mod):
        key = label_fn(o)
        groups[key][0].append(o['entries'])
        groups[key][1].append(m['entries'])
    total = len(obs)
    out = {}
    for key, (o_vals, m_vals) in sorted(groups.items(), key=lambda kv: str(kv[0])):
        share = len(o_vals) / total
        out[str(key)] = {'share_of_pairs': round(share, 4), 'observed_entries_per_pair': round(mean(o_vals), 4),
                         'model_entries_per_pair': round(mean(m_vals), 4),
                         'contribution_to_gap': round(share * (mean(o_vals) - mean(m_vals)), 4)}
    return out


def signature_table(obs_clean, mod_clean, top=5):
    """Signature frequencies on the clean pairs. contribution = (obs count - model count) * entries in signature / N."""
    n_obs, n_mod = len(obs_clean), len(mod_clean)
    obs_c, mod_c = Counter(r['signature'] for r in obs_clean), Counter(r['signature'] for r in mod_clean)
    entries_of = {}
    for r in obs_clean + mod_clean:
        entries_of.setdefault(r['signature'], r['entries'])
    rows = []
    for sig in set(obs_c) | set(mod_c):
        contribution = (obs_c[sig] - mod_c[sig] * n_obs / n_mod) * entries_of[sig] / n_obs
        rows.append({'signature': sig, 'entries_in_signature': entries_of[sig],
                     'observed_share': round(obs_c[sig] / n_obs, 5),
                     'model_share': round(mod_c[sig] / n_mod, 5),
                     'contribution_to_entries_gap': round(contribution, 5)})
    rows.sort(key=lambda row: -abs(row['contribution_to_entries_gap']))
    return rows[:top]


def exposure_rates(records):
    """Leave rate per (class, stint bucket) per player-snap on the previous snap."""
    seen, left = Counter(), Counter()
    for r in records:
        for cls, b, gone in r['exposure']:
            seen[(cls, b)] += 1
            left[(cls, b)] += gone
    return {f'{cls}|{b}': {'player_snaps': seen[(cls, b)], 'leave_rate': round(left[(cls, b)] / seen[(cls, b)], 4)}
            for (cls, b) in sorted(seen, key=lambda k: (ORDER.get(k[0], 9), k[1]))}


def ledger(rows, cls_of, positions):
    """Each 2025 snap's listed skill players against its grouping. Categories are reported as counts, not dropped."""
    counts = Counter()
    by_team = Counter()
    by_group = Counter()
    for row in rows:
        listed = [pid for pid in row['ids'] if positions.get(pid) in pf.SKILL]
        group_ok = all(Counter(cls_of.get(pid) for pid in listed)[cls] == pf.group_counts(row['group'])[cls]
                       for cls in CLASSES)
        if group_ok:
            category = 'consistent'
        elif len(listed) < 5:
            category = 'missing_skill_labels'
        elif len(listed) > 5:
            category = 'extra_skill_labels'
        else:
            category = 'five_labels_wrong_position_mix'
        counts[category] += 1
        if category != 'consistent':
            by_team[row['posteam']] += 1
            by_group[row['group']] += 1
    total = sum(counts.values())
    return {'snaps': total, 'categories': {k: {'snaps': v, 'share': round(v / total, 4)}
                                          for k, v in sorted(counts.items())},
            'inconsistent_by_grouping': dict(by_group.most_common(8)),
            'inconsistent_teams_top': dict(by_team.most_common(5))}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--tables', type=Path, required=True)
    ap.add_argument('--raw-dir', type=Path, required=True)
    ap.add_argument('--pbp', type=Path, required=True)
    ap.add_argument('--field', type=Path, required=True)
    ap.add_argument('--out', type=Path, required=True)
    ap.add_argument('--seeds', type=int, default=3)
    args = ap.parse_args()

    rows = pm.load_scrimmage(args.tables, {2025})
    positions = pm.load_positions(args.raw_dir)
    cls_of = vl.classes_of(positions)
    seqs = lf.sequences(rows, positions)
    rosters = vl.roster_by_team(rows, cls_of, positions)
    field = pf.Field.load(args.field, pf.sha256_file(args.field))
    drives = load_drives(args.pbp)

    play_drive = {}
    grouped = defaultdict(list)
    for row in rows:
        grouped[(int(row['season']), row['game_id'], row['posteam'])].append(row)
    for key, items in grouped.items():
        items.sort(key=lambda r: int(r['play_id']))
        play_drive[key] = [drives.get((r['game_id'], int(r['play_id']))) for r in items]
    missing_drive = sum(1 for values in play_drive.values() for d in values if d is None)

    obs_units = {}
    for key, seq in seqs.items():
        groups = [g for g, _c, _s in seq]
        ids = [frozenset(pid for pid, _ in skill) for _g, _c, skill in seq]
        ok = [consistent(g, i, cls_of) for g, i in zip(groups, ids)]
        obs_units[key] = (groups, ids, ok, play_drive[key])

    result = {'holdout': 2025, 'field': {'file': args.field.name, 'sha256': field.sha256},
              'seeds': args.seeds,
              'alignment': {'team_games_observed': len(seqs), 'snaps_missing_drive_id': missing_drive},
              'ledger_2025': ledger(rows, cls_of, positions),
              'arms': {}}

    for mode in ('forced', 'free'):
        obs_pairs, mod_pairs, dropped = [], [], 0
        for seed in range(1, args.seeds + 1):
            sim, _skipped = vl.simulate(field, seqs, rosters, cls_of, mode, seed)
            for key, (groups, ids, ok, drv) in obs_units.items():
                if key not in sim:
                    dropped += 1  # a team-game the simulator could not finish (no league cell for a grouping)
                    continue
                sim_groups = [g for g, _s in sim[key]]
                sim_ids = [s for _g, s in sim[key]]
                o = pair_records(groups, ids, ok, drv, cls_of)
                m = pair_records(sim_groups, sim_ids, ok, drv, cls_of)
                assert len(o) == len(m)  # aligned by index: the same snap pairs on both sides
                obs_pairs.extend(o)
                mod_pairs.extend(m)
        obs_clean = [r for r in obs_pairs if r['clean']]
        mod_clean = [r for r in mod_pairs if r['clean']]
        arm = {'team_games_dropped_per_seed_summed': dropped,
               'observed_on_same_pairs': {'all_pairs': summarize(obs_pairs), 'clean_pairs': summarize(obs_clean)},
               'model': {'all_pairs': summarize(mod_pairs), 'clean_pairs': summarize(mod_clean)},
               'leave_rate_by_class_stint_clean': {'observed': exposure_rates(obs_clean),
                                                   'model': exposure_rates(mod_clean)}}
        if mode == 'forced':
            # Forced grouping is the same on both sides, so each split below covers the same observed pairs.
            arm['gap_by_factor'] = {
                'clean_vs_contradicting': stratum_gap(
                    obs_pairs, mod_pairs, 'clean', lambda o: 'clean' if o['clean'] else 'contradict'),
                'package_change': stratum_gap(
                    obs_pairs, mod_pairs, 'changed_group', lambda o: 'changed' if o['changed_group'] else 'same'),
                'drive_boundary': stratum_gap(
                    obs_pairs, mod_pairs, 'new_drive',
                    lambda o: 'unknown' if o['new_drive'] is None else ('new_drive' if o['new_drive'] else 'same_drive')),
            }
            arm['clean_signature_top5'] = signature_table(obs_clean, mod_clean)
        result['arms'][mode] = arm
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=1, sort_keys=True) + '\n', encoding='utf-8')
    print(json.dumps({'out': str(args.out),
                      'forced_clean_observed_vs_model': {
                          'observed': result['arms']['forced']['observed_on_same_pairs']['clean_pairs'],
                          'model': result['arms']['forced']['model']['clean_pairs']},
                      'free_clean_observed_vs_model': {
                          'observed': result['arms']['free']['observed_on_same_pairs']['clean_pairs'],
                          'model': result['arms']['free']['model']['clean_pairs']}}, indent=1, sort_keys=True))


if __name__ == '__main__':
    main()
