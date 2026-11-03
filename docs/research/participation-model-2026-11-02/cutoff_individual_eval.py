#!/usr/bin/env python3
"""Cutoff-safe individual substitution evaluation for the 2025 holdout (research, teacher-forced).

Roles. Each week's role map is built only from information before that week: 2024 on-field skill labels (the prior
season), 2025 on-field skill labels from earlier weeks, and 2025 weekly-roster positions from earlier weeks, used only
for a player with no on-field skill snap yet. players.csv is not used: it is a snapshot written after the holdout.
A player with none of these is unseen. He is left out of the candidate pool and counted.

Roster status. The eligible pool is each team-week's ACT players, as in availability_gate_check.py. ACT is a
retrospective record, so these numbers are an upper bound on what a pregame gate could know.

Evaluation. Each observed transition starts from the observed lineup, so the models are scored one snap at a time,
not on their own drifting lineups. Each model draws its next lineup several times. The drawn entrants and leavers
are compared with the observed ones: exact IN set, exact OUT set, precision and recall of entrants, and the class
signature. The class signature uses the role map. The observed snap label is recorded separately, so the mismatch
between the two is counted, not hidden.

Usage: python3 cutoff_individual_eval.py --tables <scrimmage_participation.csv.gz> --raw-dir <pinned nflverse dir> \
           --pbp-dir <raw dir> --field <field_2022_2024.json> --roster-weekly <roster_weekly_2025.csv.gz> \
           --out <json> [--samples 8]
"""
import argparse
import csv
import gzip
import json
import random
import sys
from collections import Counter, defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import availability_gate_check as agc  # noqa: E402
import candidate_substitution as cs  # noqa: E402
import diagnose_substitution_gap as dg  # noqa: E402
import lineup_fit as lf  # noqa: E402
import participation_labels as pl  # noqa: E402
import participation_field as pf  # noqa: E402
import participation_model as pm  # noqa: E402

CLASSES = pf.SKILL_CLASSES
PRIOR_SEASON = max(cs.FIT_SEASONS)
HOLDOUT_SEASON = next(iter(cs.HOLDOUT))
ROSTER_STATUS_TYPES = ('REG', 'WC', 'DIV', 'CON', 'SB')


def drive_map(drives, rows):
    grouped = defaultdict(list)
    for row in rows:
        grouped[(int(row['season']), row['game_id'], row['posteam'])].append(row)
    out = {}
    for key, items in grouped.items():
        items.sort(key=lambda r: int(r['play_id']))
        out[key] = [drives.get((r['game_id'], int(r['play_id']))) for r in items]
    return out


def roster_evidence(path):
    """2025 weekly roster rows: (week, gsis_id, team, status, position) for skill positions, in playoff or regular season."""
    out = []
    with gzip.open(path, 'rt', encoding='utf-8', newline='') as handle:
        for row in csv.DictReader(handle):
            if row['game_type'] in ROSTER_STATUS_TYPES and row['gsis_id'] and row['position'] in lf.SKILL:
                out.append((int(row['week']), row['gsis_id'], row['team'], row['status'], row['position']))
    return out


def role_maps(prior_counts, snap_evidence, roster_rows, weeks):
    """{week: {gsis_id: (label, source)}}: the role each player has before that week's games. Weeks before w only."""
    maps = {}
    for week in weeks:
        counts = defaultdict(Counter)
        for pid, labels in prior_counts.items():
            counts[pid].update(labels)
        for w, pid, label in snap_evidence:
            if w < week:
                counts[pid][label] += 1
        roles = {pid: (agc.primary(labels), 'snaps') for pid, labels in counts.items() if labels}
        roster_counts = defaultdict(Counter)
        for w, pid, _team, _status, pos in roster_rows:
            if w < week and pid not in roles:
                roster_counts[pid][pos] += 1
        for pid, labels in roster_counts.items():
            roles[pid] = (agc.primary(labels), 'roster')
        maps[week] = roles
    return maps


def sig(classes):
    return tuple(sorted(Counter(classes).items(), key=lambda kv: str(kv[0])))


def baseline_step(kind, prev_stint, group, role_cls, last_on, rate_of, draw):
    """Persistence or rate-only lineup for one snap. role_cls maps each pool player to his class; anyone else is off-pool.
    Returns (kept stints, entrants, leavers, short classes). Surplus players leave shortest-stint first."""
    target = cs.gc(group)
    kept = {pid: st for pid, st in prev_stint.items() if role_cls.get(pid) is not None}
    leavers = set(prev_stint) - set(kept)
    entrants, short = set(), {}
    for cls in CLASSES:
        on = sorted((pid for pid in kept if role_cls.get(pid) == cls), key=lambda p: (-kept[p], p))
        while len(on) > target[cls]:
            pid = on.pop()
            del kept[pid]
            leavers.add(pid)
        need = target[cls] - len(on)
        if need > 0:
            bench = [pid for pid, c in role_cls.items() if c == cls and pid not in kept and pid not in leavers]
            if kind == 'persistence':
                picked = sorted(bench, key=lambda p: (-last_on.get(p, -1), p))[:need]
            else:  # rate_only: deficit drawn in proportion to the pre-cutoff rate, no leave model
                picked = []
                pool = list(bench)
                for _ in range(min(need, len(pool))):
                    pick = draw.choices(pool, weights=[max(rate_of(p), pf.FLOOR) for p in pool], k=1)[0]
                    picked.append(pick)
                    pool.remove(pick)
            for pid in picked:
                kept[pid] = 0
                entrants.add(pid)
            if len(picked) < need:
                short[cls] = need - len(picked)
    return kept, entrants, leavers, short


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--tables', type=Path, required=True)
    ap.add_argument('--raw-dir', type=Path, required=True)
    ap.add_argument('--pbp-dir', type=Path, required=True)
    ap.add_argument('--field', type=Path, required=True)
    ap.add_argument('--roster-weekly', type=Path, required=True)
    ap.add_argument('--out', type=Path, required=True)
    ap.add_argument('--samples', type=int, default=8)
    args = ap.parse_args()

    positions = pm.load_positions(args.raw_dir)
    drives = {}
    for season in (2022, 2023, 2024, 2025):
        drives.update(dg.load_drives(args.pbp_dir / f'pbp_{season}.csv.gz'))

    fit_rows = pm.load_scrimmage(args.tables, cs.FIT_SEASONS)
    rows = pm.load_scrimmage(args.tables, cs.HOLDOUT)

    # Fit exactly as the gate does: each fit season's labels, then the tables and the position prior.
    season_pos = agc.season_positions(fit_rows, args.roster_weekly, positions, sorted(cs.FIT_SEASONS))
    seqs_fit = {}
    for season in sorted(cs.FIT_SEASONS):
        seqs_fit.update(lf.sequences([row for row in fit_rows if int(row['season']) == season], season_pos[season],
                                     snap_labels=True))
    tables, joint_tables, _checks = cs.fit_tables(seqs_fit, drive_map(drives, fit_rows), cs.FIT_SEASONS)
    base = json.loads(args.field.read_text(encoding='utf-8'))
    base['position_prior'] = [[pos, group, value] for (pos, group), value in
                              sorted(agc.position_prior(fit_rows, season_pos, cs.FIT_SEASONS).items())]
    fields = {'B0_feasible': (cs.variant_field(base, tables['pooled'], False, False, 'pooled'), False, None),
              'JD_feasible': (cs.variant_field(base, tables['split'], False, True, 'split'), True,
                              {key: dict(c) for key, c in joint_tables['split'].items()
                               if sum(c.values()) >= cs.JOINT_MIN_PAIRS})}

    # Cutoff-safe roles. Prior-season labels come from the fit rows, so only 2025 snaps and rosters are weekly.
    prior_counts = defaultdict(Counter)
    for row in fit_rows:
        if int(row['season']) != PRIOR_SEASON:
            continue
        for pid, label, _source in pl.aligned_labels(row):
            if label in lf.SKILL:
                prior_counts[pid][label] += 1
    snap_evidence = []
    for row in rows:
        for pid, label, _source in pl.aligned_labels(row):
            if label in lf.SKILL:
                snap_evidence.append((int(row['week']), pid, label))
    roster_rows = roster_evidence(args.roster_weekly)
    weeks = sorted({int(row['week']) for row in rows})
    roles = role_maps(prior_counts, snap_evidence, roster_rows, weeks)

    # Pool per team-week: ACT skill players with a role before that week. Anyone else is off-pool.
    act = defaultdict(set)
    for w, pid, team, status, _pos in roster_rows:
        if status == 'ACT':
            act[(w, team)].add(pid)

    seqs = lf.sequences(rows, positions, snap_labels=True)
    play_drive = drive_map(drives, rows)
    week_of = {(int(row['season']), row['game_id'], row['posteam']): int(row['week']) for row in rows}

    coverage = defaultdict(Counter)  # week -> source counts for the ACT skill players of that week
    for week in weeks:
        for (w, team), pids in act.items():
            if w != week:
                continue
            for pid in pids:
                coverage[week][roles[week][pid][1] if pid in roles[week] else 'unseen'] += 1

    metrics = {name: Counter() for name in ('B0_feasible', 'JD_feasible', 'persistence', 'rate_only')}
    sums = {name: defaultdict(float) for name in metrics}
    counted = Counter()
    role_mismatch = Counter()
    for key, seq in sorted(seqs.items()):
        season, _game, team = key
        week = week_of[key]
        role = roles[week]
        roster = [{'gsis_id': pid, 'pos_abb': role[pid][0], 'pos_rank': i}
                  for i, pid in enumerate(sorted(p for p in act[(week, team)] if p in role))]
        role_cls = {p['gsis_id']: pf.SKILL[p['pos_abb']] for p in roster}
        ids = [frozenset(pid for pid, _ in skill) for _g, _c, skill in seq]
        stints = dg.stint_track(ids)
        drv = play_drive[key]
        last_on = {}
        for i in range(1, len(seq)):
            prev, cur = ids[i - 1], ids[i]
            for pid in prev:
                last_on[pid] = i - 1
            o_in, o_out = cur - prev, prev - cur
            group, prev_group = seq[i][0], seq[i - 1][0]
            for pid in o_in:
                if pid in role:
                    role_mismatch['entrant_snaps'] += 1
                    snap_cls = dict(seq[i][2]).get(pid)
                    if snap_cls != pf.SKILL[role[pid][0]]:
                        role_mismatch['snap_label_differs_from_role'] += 1
                else:
                    role_mismatch['entrant_unseen'] += 1
            off_pool = [pid for pid in prev if pid not in role_cls]
            counted['transitions'] += 1
            counted['entrants_off_pool'] += sum(1 for pid in o_in if pid not in role_cls)
            counted['entrant_snaps'] += len(o_in)
            prev_stint = {pid: stints[i - 1][pid] for pid in prev}
            new_drive = cs.drive_flags(drv, i)
            if group is None or prev_group is None:
                continue
            target = cs.gc(group)
            sig_obs = sig(role_cls.get(p) for p in o_in if role_cls.get(p) is not None)
            for name, (field, joint_on, joint) in fields.items():
                for s in range(args.samples):
                    draw = random.Random(f'{key}|{i}|{name}|{s}')
                    lineup = dict(prev_stint)
                    nxt, rec = field.advance(team, lineup, group, roster, draw, prev_group=prev_group,
                                             new_drive=new_drive, stint_swap=False, drive_split=joint_on,
                                             joint=joint, feasible=True)
                    if nxt is None:
                        metrics[name]['unsupported'] += 1
                        continue
                    entrants = set(rec['entrants'])
                    kept = set(nxt)
                    leavers = prev - kept
                    record_model(metrics[name], sums[name], entrants, leavers, o_in, o_out, kept, role_cls, target,
                                 rec['status'], sig_obs)
            for name, kind in (('persistence', 'persistence'), ('rate_only', 'rate_only')):
                for s in range(1 if kind == 'persistence' else args.samples):
                    draw = random.Random(f'{key}|{i}|{name}|{s}')
                    kept_st, entrants, leavers, short = baseline_step(
                        kind, prev_stint, group, role_cls, last_on,
                        lambda p, t=team, g=group, r=role: fields['JD_feasible'][0].rate(p, t, g, r[p][0]), draw)
                    record_model(metrics[name], sums[name], entrants, leavers, o_in, o_out, set(kept_st), role_cls,
                                 target, 'short' if short else 'ok', sig_obs)

    result = {'holdout': sorted(cs.HOLDOUT), 'fit_seasons': sorted(cs.FIT_SEASONS), 'samples': args.samples,
              'leakage_check': 'roles for week w use only snaps and roster rows from weeks before w; players.csv unused',
              'roster_status': 'ACT is retrospective; the pool is an upper bound on a pregame gate',
              'transitions': counted['transitions'], 'entrant_snaps': counted['entrant_snaps'],
              'entrants_off_pool_rate': counted['entrants_off_pool'] / max(counted['entrant_snaps'], 1),
              'role_mismatch': dict(role_mismatch),
              'role_source_by_week': {str(w): dict(c) for w, c in sorted(coverage.items())},
              'models': {}}
    for name in metrics:
        n = metrics[name]['draws']
        result['models'][name] = {'draws': n, 'unsupported': metrics[name]['unsupported'],
                                  'legal_rate': metrics[name]['legal'] / max(n, 1),
                                  'exact_in_rate': metrics[name]['exact_in'] / max(n, 1),
                                  'exact_out_rate': metrics[name]['exact_out'] / max(n, 1),
                                  'exact_both_rate': metrics[name]['exact_both'] / max(n, 1),
                                  'nonempty_draws': metrics[name]['nonempty_draws'],
                                  'exact_in_nonempty_rate': metrics[name]['exact_in_nonempty'] / max(metrics[name]['nonempty_draws'], 1),
                                  'exact_both_nonempty_rate': metrics[name]['exact_both_nonempty'] / max(metrics[name]['nonempty_draws'], 1),
                                  'signature_match_rate': metrics[name]['signature'] / max(n, 1),
                                  'precision_in': sums[name]['precision'] / max(metrics[name]['precision_n'], 1),
                                  'recall_in': sums[name]['recall'] / max(metrics[name]['recall_n'], 1),
                                  'entrants_per_draw': sums[name]['entrants'] / max(n, 1)}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=1, sort_keys=True) + '\n', encoding='utf-8')
    print(json.dumps({'out': str(args.out), 'transitions': counted['transitions'],
                      'models': {k: {m: round(v, 4) for m, v in r.items() if isinstance(v, float)}
                                 for k, r in result['models'].items()}}, sort_keys=True))


def record_model(count, total, entrants, leavers, o_in, o_out, kept, role_cls, target, status, sig_obs):
    """Score one drawn lineup against the observed entrants and leavers."""
    count['draws'] += 1
    count['legal'] += int(status == 'ok' and all(
        sum(1 for pid in kept if role_cls.get(pid) == cls) == target[cls] for cls in CLASSES))
    exact_in = entrants == o_in
    exact_out = leavers == o_out
    count['exact_in'] += int(exact_in)
    count['exact_out'] += int(exact_out)
    count['exact_both'] += int(exact_in and exact_out)
    if o_in:  # the stratum where a model has to pick players: an unchanged lineup matches exactly for free
        count['nonempty_draws'] += 1
        count['exact_in_nonempty'] += int(exact_in)
        count['exact_both_nonempty'] += int(exact_in and exact_out)
    sig_draw = sig(role_cls.get(p) for p in entrants if role_cls.get(p) is not None)
    count['signature'] += int(sig_draw == sig_obs)
    total['entrants'] += len(entrants)
    if entrants:
        count['precision_n'] += 1
        total['precision'] += len(entrants & o_in) / len(entrants)
    if o_in:
        count['recall_n'] += 1
        total['recall'] += len(entrants & o_in) / len(o_in)


if __name__ == '__main__':
    main()
