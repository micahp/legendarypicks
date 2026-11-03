#!/usr/bin/env python3
"""Candidate substitution mechanics for the lineup model, fit on 2022 to 2024 and scored on the 2025 holdout.

The root-cause diagnostic (diagnose_substitution_gap.py) found the entry gap sits at drive boundaries and in multi-class
churn. This script tests four candidates, one at a time and together, with the metrics the diagnostic uses:

- S, stint-dependent swap: churn in a class whose count changes gets a rate per stint bucket. The rates are fit only on
  classes whose count rises, because a class whose count falls has departures that the count change already explains.
- D, drive-boundary split: rotation and churn at a new drive (play-by-play drive number changes) get their own hazards.
- J, joint leaver counts: each snap draws how many players leave from each class together, from the 2022 to 2024 joint
  distribution for the same grouping transition (and drive boundary, in JD). Which players leave is still stint-weighted.
  A transition with fewer than JOINT_MIN_PAIRS pairs falls back to the per-player draws.
- JD: J with the drive-boundary split.

B0 is the runtime mechanics with the existing 2022 to 2024 table and must reproduce validate_lineups.py. Nothing here
touches scripts/nfl_sequence/. Nothing is tuned: every table is an empirical rate on 2022 to 2024, shrunk to the position
class as the runtime does. The one number that is not empirical is JOINT_MIN_PAIRS, a support threshold fixed before any run.

Usage: python3 candidate_substitution.py --tables <scrimmage_participation.csv.gz> --raw-dir <pinned nflverse dir> \
           --pbp-dir <raw dir with pbp_YYYY.csv.gz> --field <field_2022_2024.json> --out <json> [--seeds 3]
"""
import argparse
import json
import random
import sys
from collections import Counter, defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parents[2] / 'scripts' / 'nfl_sequence'))
import diagnose_substitution_gap as dg  # noqa: E402
import lineup_fit as lf  # noqa: E402
import participation_field as pf  # noqa: E402
import participation_model as pm  # noqa: E402
import validate_lineups as vl  # noqa: E402

FIT_SEASONS = {2022, 2023, 2024}
HOLDOUT = {2025}
CLASSES = pf.SKILL_CLASSES
CAP = pf.STINT_CAP
JOINT_MIN_PAIRS = 30  # a grouping transition seen on fewer pairs than this uses the per-player draws
FEASIBLE_MAX_DRAWS = 200  # redraws before a feasibility-constrained draw is recorded as unresolved


def gc(group):
    return pf.group_counts(group)


def drive_flags(seq_drive, i):
    """True, False or None: whether snap i starts a new drive. None when either snap has no drive number."""
    if seq_drive[i] is None or seq_drive[i - 1] is None:
        return None
    return seq_drive[i] != seq_drive[i - 1]


def fit_tables(seqs, play_drive, seasons):
    """Leave counts for the pooled and split tables, plus the joint leaver counts for each transition.

    Swap rows: bucket 0 is the runtime's one rate per class (count-change departures allocated across stints, the
    same accounting as lineup_fit.fit). Buckets 1 to 6 are the stint rates, fit only on classes whose count rises."""
    tables = {'pooled': defaultdict(lambda: [0.0, 0.0]), 'split': defaultdict(lambda: [0.0, 0.0])}
    joint = {'pooled': defaultdict(Counter), 'split': defaultdict(Counter)}
    checks = Counter()
    for key, seq in sorted(seqs.items()):
        season, _game, _team = key
        if season not in seasons:
            continue
        w = pm.RECENCY[season]
        drives = play_drive[key]
        prev_skill, prev_ok, prev_group, stint = None, False, None, {}
        for i, (group, _cell, skill) in enumerate(seq):
            on = {pid for pid, _ in skill}
            counted = Counter(cls for _, cls in skill)
            ok_now = all(counted[cls] == gc(group)[cls] for cls in CLASSES)
            if prev_skill is None:
                stint = {pid: 1 for pid in on}
            else:
                new_drive = drive_flags(drives, i)
                checks['snaps_with_drive_unknown'] += new_drive is None
                if prev_ok and ok_now:
                    leaves_by_cls = {cls: sum(1 for pid, c in prev_skill if c == cls and pid not in on)
                                     for cls in CLASSES}
                    for table_name, drive_on in (('pooled', False), ('split', True)):
                        drive_key = bool(new_drive) if drive_on else None
                        suffix = '_drive' if drive_on and new_drive else ''
                        kind = ('held' if group == prev_group else 'changed') + suffix
                        joint[table_name][(drive_key, prev_group, group)][
                            tuple(leaves_by_cls[cls] for cls in CLASSES)] += w
                        for pid, cls in prev_skill:
                            if gc(group)[cls] != gc(prev_group)[cls]:
                                continue
                            bucket = (kind, cls, min(stint[pid], CAP))
                            tables[table_name][bucket][1] += w
                            if pid not in on:
                                tables[table_name][bucket][0] += w
                        for cls in CLASSES:
                            old, new = gc(prev_group)[cls], gc(group)[cls]
                            if old == new:
                                continue
                            players = [pid for pid, c in prev_skill if c == cls]
                            if not players:
                                continue
                            swap_kind = 'swap' + suffix
                            per_bucket = Counter(min(stint[pid], CAP) for pid in players)
                            leavers = Counter(min(stint[pid], CAP) for pid in players if pid not in on)
                            n = len(players)
                            if new > old:  # no count-change departures: every leaver is churn, so the stint rate is exact
                                for b in per_bucket:
                                    tables[table_name][(swap_kind, cls, b)][0] += w * leavers[b]
                                    tables[table_name][(swap_kind, cls, b)][1] += w * per_bucket[b]
                            for b in per_bucket:  # bucket 0: the runtime's class total, count-change departures allocated
                                expected_change = max(0, old - new) * per_bucket[b] / n
                                excess = leavers[b] - expected_change
                                tables[table_name][(swap_kind, cls, 0)][0] += w * excess
                                tables[table_name][(swap_kind, cls, 0)][1] += w * per_bucket[b]
                checks['transitions'] += 1
                stint = {pid: stint[pid] + 1 if pid in {p for p, _ in prev_skill} else 1 for pid in on}
            prev_skill, prev_ok, prev_group = skill, ok_now, group
    rows = {name: {bucket: (round(leaves, 6), round(total, 6)) for bucket, (leaves, total) in table.items()}
            for name, table in tables.items()}
    joint_tables = {name: {key: dict(counts) for key, counts in table.items()} for name, table in joint.items()}
    return rows, joint_tables, checks


class CandidateField(pf.Field):
    """The runtime Field with the hazard lookup made explicit by bucket, and an advance that can switch on the drive
    boundary, the stint-dependent swap and the joint leaver counts. With all switches off it draws exactly as
    participation_field.advance, which is what the B0 variant checks."""

    def hazard(self, kind, cls, bucket):
        leaves, total = self.leave_counts.get((kind, cls, bucket), (0.0, 0.0))
        pooled_leaves, pooled_total = self.leave_class.get((kind, cls), (0.0, 0.0))
        prior = pooled_leaves / pooled_total if pooled_total else 0.0
        return max(0.0, leaves + pf.HAZARD_PRIOR_PLAYS * prior) / (total + pf.HAZARD_PRIOR_PLAYS)

    def _joint_leavers(self, lineup, cls_of, kind, options, draw):
        """Draw the leaver count of each class together, then which players of that class leave, stint-weighted."""
        tuples = sorted(options)
        pick = draw.choices(tuples, weights=[options[t] for t in tuples], k=1)[0]
        leavers = {pid for pid in lineup if cls_of.get(pid) is None}
        for cls, n in zip(CLASSES, pick):
            on = sorted(pid for pid in lineup if cls_of.get(pid) == cls)
            if n > len(on):
                self.status['joint_capped'] += 1
            for _ in range(min(n, len(on))):
                weights = [max(self.hazard(kind, cls, min(lineup[pid], CAP)), pf.FLOOR) for pid in on]
                chosen = draw.choices(on, weights=weights, k=1)[0]
                on.remove(chosen)
                leavers.add(chosen)
        return leavers

    def _per_player_leavers(self, lineup, cls_of, prev_group, target, rotation_kind, suffix, stint_swap, draw):
        """The per-player leave draws: rotation in a class whose count holds, then churn in a class whose count changes."""
        leavers = set()
        for pid in sorted(lineup):
            cls = cls_of.get(pid)
            if cls is None:
                leavers.add(pid)
            elif prev_group is not None and gc(prev_group)[cls] == target[cls] \
                    and draw.random() < self.hazard(rotation_kind, cls, min(lineup[pid], CAP)):
                leavers.add(pid)
        for pid in sorted(lineup):
            cls = cls_of.get(pid)
            if pid not in leavers and cls is not None and prev_group is not None \
                    and gc(prev_group)[cls] != target[cls]:
                bucket = min(lineup[pid], CAP) if stint_swap else 0
                if draw.random() < self.hazard('swap' + suffix, cls, bucket):
                    leavers.add(pid)
        return leavers

    def advance(self, team, lineup, group, roster, draw, prev_group=None, new_drive=None, stint_swap=False,
                drive_split=False, joint=None, feasible=False):
        if group is None or len(group) != 2 or not group.isdigit() or gc(group)['WR'] < 0:
            self.status['unsupported_grouping'] += 1
            return None, {'status': 'unsupported_grouping', 'group': group}
        cls_of = {p['gsis_id']: pf.SKILL[p['pos_abb']] for p in roster if p['pos_abb'] in pf.SKILL}
        target = gc(group)
        suffix = '_drive' if drive_split and new_drive else ''
        rotation_kind = ('held' if prev_group == group else 'changed') + suffix
        # A leave is feasible when no more players of a class leave than are on the field, and the roster players of that
        # class who are not on the field (they cannot re-enter on the same snap) cover the class's deficit.
        held = Counter(cls_of[pid] for pid in lineup if pid in cls_of)
        pool = Counter(cls_of.values())
        allowed = {cls: max(0, min(held[cls], max(held[cls], pool[cls]) - target[cls])) for cls in CLASSES}
        leavers = None
        if joint is not None and prev_group is not None:
            drive_key = bool(new_drive) if drive_split else None
            options = joint.get((drive_key, prev_group, group))
            if options is not None and feasible:
                options = {t: w for t, w in options.items() if all(n <= allowed[cls] for cls, n in zip(CLASSES, t))}
                if not options:
                    self.status['joint_no_feasible'] += 1
            if options:
                leavers = self._joint_leavers(lineup, cls_of, rotation_kind, options, draw)
            else:
                self.status['joint_fallback'] += 1
        if leavers is None:
            for _attempt in range(FEASIBLE_MAX_DRAWS):
                leavers = self._per_player_leavers(lineup, cls_of, prev_group, target, rotation_kind, suffix, stint_swap,
                                                   draw)
                leave_counts = Counter(cls_of[pid] for pid in leavers if pid in cls_of)
                if not feasible or all(leave_counts[cls] <= allowed[cls] for cls in CLASSES):
                    break
                self.status['feasible_redraw'] += 1
            else:
                self.status['infeasible_unresolved'] += 1
        kept = {pid: stint for pid, stint in lineup.items() if pid not in leavers}
        removed = set(leavers)
        count_removed, entrants, short = [], [], {}
        for cls in pf.SKILL_CLASSES:  # the grouping's counts: surplus leaves by hazard, deficit enters from the bench
            on = sorted(pid for pid in kept if cls_of.get(pid) == cls)
            while len(on) > target[cls]:
                weights = [max(self.hazard(rotation_kind, cls, min(kept[pid], CAP)), pf.FLOOR) for pid in on]
                pid = draw.choices(on, weights=weights, k=1)[0]
                on.remove(pid)
                del kept[pid]
                removed.add(pid)
                count_removed.append(pid)
            need = target[cls] - len(on)
            if need > 0:
                bench = [p for p in sorted(roster, key=lambda p: (p['pos_rank'], p['gsis_id']))
                         if cls_of.get(p['gsis_id']) == cls and p['gsis_id'] not in kept and p['gsis_id'] not in removed]
                picked = self._weighted(bench, need, team, group, draw)
                for player in picked:
                    kept[player['gsis_id']] = 0
                    entrants.append(player['gsis_id'])
                if len(picked) < need:
                    short[cls] = need - len(picked)
                    # the cause: the roster cannot staff the grouping, or it can but the bench is exhausted
                    cause = 'roster_below_target' if pool[cls] < target[cls] else 'roster_covers_target'
                    self.status[f'short_{cls}_{cause}'] += 1
        nxt = {pid: (lineup[pid] + 1 if pid in lineup else 1) for pid in kept}
        status = 'short' if short else 'ok'
        self.status[status] += 1
        return nxt, {'status': status, 'group': group, 'entrants': sorted(entrants), 'short': short}


def variant_field(base, table, stint_swap, drive_split, table_name):
    """A CandidateField from the base table, with its leave rows replaced by the fitted table for this variant. Swap
    rows keep only the buckets this variant reads (bucket 0 is the class total, the one-rate runtime row), so the
    per-class prior is not counted twice."""
    data = dict(base)
    leave_rows = [[kind, cls, bucket, leaves, total] for (kind, cls, bucket), (leaves, total) in sorted(table.items())
                  if not kind.startswith('swap') or ((bucket != 0) if stint_swap else (bucket == 0))]
    data['leave_counts'] = leave_rows
    data['source'] = dict(base.get('source', {}), candidate_table=table_name)
    return CandidateField(data, f'{table_name}|stint_swap={stint_swap}|drive_split={drive_split}')


def fits_roster(group, pool):
    """Whether the roster has enough players of each class for the grouping, all on the field at once."""
    if group is None or len(group) != 2 or not group.isdigit() or gc(group)['WR'] < 0:
        return False
    return all(pool[cls] >= gc(group)[cls] for cls in CLASSES)


def simulate(field, seqs, rosters, cls_of, play_drive, seed, stint_swap, drive_split, joint, mode,
             roster_for_key=None, feasible=False):
    """forced: the observed grouping on each snap, the lineup simulated. free: the grouping is drawn from the field too.
    The draws follow validate_lineups.simulate, so the B0 variant reproduces the runtime numbers exactly.
    roster_for_key, when given, replaces each team's full-season bench with the roster for that game.
    feasible, when set, only allows leaves the roster can refill, and in free mode redraws a grouping the roster cannot
    staff; both are counted in field.status, so nothing is dropped silently."""
    out, dropped = {}, 0
    for key, seq in sorted(seqs.items()):
        _season, _game, team = key
        draw = random.Random(f'{key}|{mode}|{seed}')
        roster = roster_for_key[key] if roster_for_key is not None else rosters[team]
        pool = Counter(cls_of[p['gsis_id']] for p in roster if p['gsis_id'] in cls_of)
        lineup, prev, snaps = {}, pf.START, []
        drives = play_drive[key]
        for i, (group_obs, cell, _skill) in enumerate(seq):
            group = field.draw_group(team, prev, cell, draw) if mode == 'free' else group_obs
            if feasible and mode == 'free':
                for _attempt in range(FEASIBLE_MAX_DRAWS):
                    if group is None or fits_roster(group, pool):
                        break
                    field.status['group_redraw'] += 1
                    group = field.draw_group(team, prev, cell, draw)
                else:
                    field.status['group_unresolved'] += 1
            if group is None:
                dropped += 1
                break
            new_drive = drive_flags(drives, i) if i else None
            lineup, _record = field.advance(team, lineup, group, roster, draw, prev_group=prev,
                                            new_drive=new_drive, stint_swap=stint_swap, drive_split=drive_split,
                                            joint=joint, feasible=feasible)
            snaps.append((group, frozenset(lineup)))
            prev = group
        else:
            out[key] = snaps
    return out, dropped


def evaluate(sim_by_seed, seqs, play_drive, cls_of):
    """Pairs pooled across seeds, with the observed clean flags, as diagnose_substitution_gap.py pools them."""
    records = []
    for sims in sim_by_seed:
        for key, seq in seqs.items():
            if key not in sims:
                continue
            groups = [g for g, _c, _s in seq]
            ids = [frozenset(pid for pid, _ in skill) for _g, _c, skill in seq]
            # the observed grouping is checked against the class listed on each snap, not the player's primary class
            ok = [dg.consistent(g, i, dict(skill)) for g, i, (_g, _c, skill) in zip(groups, ids, seq)]
            sim_groups = [g for g, _s in sims[key]]
            sim_ids = [s for _g, s in sims[key]]
            records.extend(dg.pair_records(sim_groups, sim_ids, ok, play_drive[key], cls_of))
    return records


def summarise(records):
    clean = [r for r in records if r['clean']]
    out = {}
    for name, subset in (('clean', clean), ('all', records)):
        n = len(subset)
        out[name] = {'pairs': n, 'entries_per_pair': round(sum(r['entries'] for r in subset) / n, 4),
                     'entries_per_pair_by_class': {cls: round(sum(r['enter_cls'][cls] for r in subset) / n, 4)
                                                   for cls in CLASSES},
                     'histogram': {str(k): round(sum(1 for r in subset if min(r['entries'], 4) == k) / n, 4)
                                   for k in range(5)},
                     'share_two_or_more_classes_entering': round(
                         sum(1 for r in subset if r['classes_entering'] >= 2) / n, 4)}
    for flag, label in ((False, 'same_drive'), (True, 'new_drive')):
        subset = [r for r in clean if r['new_drive'] is flag]
        n = len(subset)
        out[label] = {'pairs': n, 'entries_per_pair': round(sum(r['entries'] for r in subset) / n, 4)}
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--tables', type=Path, required=True)
    ap.add_argument('--raw-dir', type=Path, required=True)
    ap.add_argument('--pbp-dir', type=Path, required=True)
    ap.add_argument('--field', type=Path, required=True)
    ap.add_argument('--out', type=Path, required=True)
    ap.add_argument('--seeds', type=int, default=3)
    args = ap.parse_args()

    positions = pm.load_positions(args.raw_dir)
    cls_of = vl.classes_of(positions)
    drives = {}
    for season in sorted(FIT_SEASONS | HOLDOUT):
        drives.update(dg.load_drives(args.pbp_dir / f'pbp_{season}.csv.gz'))

    def drive_map(rows):
        grouped = defaultdict(list)
        for row in rows:
            grouped[(int(row['season']), row['game_id'], row['posteam'])].append(row)
        out = {}
        for key, items in grouped.items():
            items.sort(key=lambda r: int(r['play_id']))
            out[key] = [drives.get((r['game_id'], int(r['play_id']))) for r in items]
        return out

    fit_rows = pm.load_scrimmage(args.tables, FIT_SEASONS)
    fit_seqs = lf.sequences(fit_rows, positions)
    fit_drive = drive_map(fit_rows)
    tables, joint_tables, fit_checks = fit_tables(fit_seqs, fit_drive, FIT_SEASONS)

    base = json.loads(args.field.read_text(encoding='utf-8'))
    base_field = pf.Field(base, pf.sha256_file(args.field))
    pooled_rows = tables['pooled']
    mismatch = []  # the pooled table must reproduce the runtime's rotation and swap rows, or B0 is not the runtime
    for (kind, cls, bucket), (leaves, total) in base_field.leave_counts.items():
        if kind == 'swap' and bucket == 0 or kind in ('held', 'changed'):
            ours = pooled_rows.get((kind, cls, bucket), (0.0, 0.0))
            if abs(ours[0] - leaves) > 1e-3 or abs(ours[1] - total) > 1e-3:
                mismatch.append([kind, cls, bucket, leaves, total, list(ours)])

    rows = pm.load_scrimmage(args.tables, HOLDOUT)
    seqs = lf.sequences(rows, positions)
    play_drive = drive_map(rows)
    rosters = vl.roster_by_team(rows, cls_of, positions)

    def joint_for(name):
        return {key: {t: w for t, w in counts.items()} for key, counts in joint_tables[name].items()
                if sum(counts.values()) >= JOINT_MIN_PAIRS}

    variants = {
        'B0_runtime': (variant_field(base, pooled_rows, False, False, 'pooled'), False, False, None),
        'S_stint_swap': (variant_field(base, pooled_rows, True, False, 'pooled'), True, False, None),
        'D_drive_split': (variant_field(base, tables['split'], False, True, 'split'), False, True, None),
        'SD_both': (variant_field(base, tables['split'], True, True, 'split'), True, True, None),
        'J_joint': (variant_field(base, pooled_rows, False, False, 'pooled'), False, False, joint_for('pooled')),
        'JD_joint_drive': (variant_field(base, tables['split'], False, True, 'split'), False, True,
                           joint_for('split')),
    }
    result = {'holdout': sorted(HOLDOUT), 'fit_seasons': sorted(FIT_SEASONS), 'seeds': args.seeds,
              'joint_min_pairs': JOINT_MIN_PAIRS,
              'base_field': {'file': args.field.name, 'sha256': base_field.sha256},
              'fit_checks': dict(fit_checks), 'pooled_vs_runtime_mismatch_count': len(mismatch),
              'pooled_vs_runtime_mismatch': mismatch[:10], 'joint_keys': {}, 'observed': None, 'variants': {}}
    for name, options in (('pooled', joint_for('pooled')), ('split', joint_for('split'))):
        result['joint_keys'][name] = {'transitions_with_support': len(options),
                                      'transitions_total': len(joint_tables[name])}
    observed_records = []
    for key, seq in seqs.items():
        groups = [g for g, _c, _s in seq]
        ids = [frozenset(pid for pid, _ in skill) for _g, _c, skill in seq]
        ok = [dg.consistent(g, i, cls_of) for g, i in zip(groups, ids)]
        observed_records.extend(dg.pair_records(groups, ids, ok, play_drive[key], cls_of))
    result['observed'] = summarise(observed_records)
    for mode in ('forced', 'free'):
        result['variants'][mode] = {}
        for name, (field, stint_swap, drive_split, joint) in variants.items():
            field.status.clear()
            runs = [simulate(field, seqs, rosters, cls_of, play_drive, seed, stint_swap, drive_split, joint, mode)
                    for seed in range(1, args.seeds + 1)]
            sims = [sim for sim, _dropped in runs]
            dropped = sum(d for _sim, d in runs)
            result['variants'][mode][name] = {'summary': summarise(evaluate(sims, seqs, play_drive, cls_of)),
                                              'team_games_dropped_no_league_cell': dropped,
                                              'status': dict(field.status)}
            print(mode, name, json.dumps(result['variants'][mode][name]['summary']['clean']['entries_per_pair']),
                  flush=True)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=1, sort_keys=True) + '\n', encoding='utf-8')
    print(json.dumps({'out': str(args.out), 'pooled_vs_runtime_mismatch_count': len(mismatch),
                      'joint_keys': result['joint_keys']}, sort_keys=True))


if __name__ == '__main__':
    main()
