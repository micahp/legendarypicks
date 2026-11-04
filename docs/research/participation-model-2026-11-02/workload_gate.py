#!/usr/bin/env python3
"""Workload gate: do simulated games spread on-field workload the way the 2025 games did? (research, not wired).

The feasible joint substitution model (JD, with the ACT eligible bench, as in availability_gate_check.py) simulates each
2025 team-game in free mode: the grouping and the substitutions are drawn from the fitted model. For each simulated and
each observed team-game this measures:

- Snap share per player (his snaps over the team's plays), by position class and by rank within the class on the team
  (rank 1 is the most-used player that game).
- Longest consecutive-snap stint per player-game, by class.
- Entries (players coming on) per team-game, by class.
- Legality: the share of snaps whose five skill players are unique and match the grouping counts.

Carries and targets are not in the simulator. They need a carrier and target allocation model that is not built, so
they are not measured here. This gate is a research check of the participation and workload layer only.

Usage: python3 workload_gate.py --tables <scrimmage_participation.csv.gz> --raw-dir <pinned nflverse dir> \
           --pbp-dir <raw dir> --field <field_2022_2024.json> --roster-weekly <roster_weekly_2025.csv.gz> \
           --positions <position_reconstruction_2022_2025.csv> --out <json> [--seeds 3]
"""
import argparse
import json
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
import participation_model as pm  # noqa: E402
import validate_lineups as vl  # noqa: E402

CLASSES = ('RB', 'TE', 'WR')
SKILL_PER_SNAP = 5  # RB + TE + WR is five in every grouping


def quantile(values, q):
    if not values:
        return None
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, int(round(q * (len(ordered) - 1)))))
    return ordered[index]


def summarize_games(games):
    """games: list of dicts {'plays': int, 'snaps': {pid: n}, 'stint': {pid: max stint}, 'cls': {pid: class},
    'entries': {class: n}, 'legal': bool}. Returns per-class snap shares, stints, entries, and legality."""
    shares = defaultdict(list)
    ranked = defaultdict(lambda: defaultdict(list))
    stints = defaultdict(list)
    entries = defaultdict(list)
    legal = Counter()
    for game in games:
        plays = game['plays']
        per_class = defaultdict(list)
        for pid, n in game['snaps'].items():
            cls = game['cls'].get(pid)
            if cls is None:
                continue
            per_class[cls].append((n, pid))
            shares[cls].append(n / plays)
            stints[cls].append(game['stint'].get(pid, 0))
        for cls, items in per_class.items():
            for rank, (n, _pid) in enumerate(sorted(items, reverse=True), start=1):
                ranked[cls][rank].append(n / plays)
        for cls in CLASSES:
            entries[cls].append(game['entries'].get(cls, 0))
        legal['games'] += 1
        legal['legal'] += int(game['legal'])
    out = {'legal_rate': round(legal['legal'] / max(legal['games'], 1), 6), 'classes': {}}
    for cls in CLASSES:
        s = shares[cls]
        out['classes'][cls] = {
            'player_games': len(s),
            'snap_share_mean': round(sum(s) / len(s), 4) if s else None,
            'snap_share_p95': round(quantile(s, 0.95), 4) if s else None,
            'snap_share_p99': round(quantile(s, 0.99), 4) if s else None,
            'max_stint_p95': quantile(stints[cls], 0.95),
            'max_stint_p99': quantile(stints[cls], 0.99),
            'entries_per_team_game_mean': round(sum(entries[cls]) / max(len(entries[cls]), 1), 4),
            'rank_mean_snap_share': {str(rank): round(sum(v) / len(v), 4)
                                     for rank, v in sorted(ranked[cls].items())[:4]},
        }
    return out


def game_record(seq_ids, seq_groups, plays_n, seq_cls_by_pid, seq_entries_ok):
    stints = dg.stint_track(seq_ids)
    snaps = Counter()
    for ids in seq_ids:
        snaps.update(ids)
    max_stint = defaultdict(int)
    for stint_map in stints:
        for pid, st in stint_map.items():
            max_stint[pid] = max(max_stint[pid], st)
    entries = Counter()
    for i in range(1, len(seq_ids)):
        for pid in seq_ids[i] - seq_ids[i - 1]:
            entries[seq_cls_by_pid.get(pid)] += 1
    legal = all(seq_entries_ok)
    return {'plays': plays_n, 'snaps': snaps, 'stint': max_stint, 'cls': seq_cls_by_pid, 'entries': entries,
            'legal': legal}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--tables', type=Path, required=True)
    ap.add_argument('--raw-dir', type=Path, required=True)
    ap.add_argument('--pbp-dir', type=Path, required=True)
    ap.add_argument('--field', type=Path, required=True)
    ap.add_argument('--roster-weekly', type=Path, required=True)
    ap.add_argument('--positions', type=Path, required=True)
    ap.add_argument('--out', type=Path, required=True)
    ap.add_argument('--seeds', type=int, default=3)
    ap.add_argument('--leave-beta', type=float, default=0.0,
                    help='0 is the runtime leave model; 1 is the pre-declared depth-scaled variant')
    args = ap.parse_args()

    positions = pm.load_positions(args.raw_dir)
    drives = {}
    for season in (2022, 2023, 2024, 2025):
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

    fit_rows = pm.load_scrimmage(args.tables, cs.FIT_SEASONS)
    rows = pm.load_scrimmage(args.tables, cs.HOLDOUT)
    (holdout_season,) = cs.HOLDOUT
    recon = pl.load_reconstruction(args.positions)
    season_pos = agc.season_positions(fit_rows + rows, args.roster_weekly, positions,
                                      sorted(cs.FIT_SEASONS | cs.HOLDOUT), recon)
    seqs_fit = {}
    for season in sorted(cs.FIT_SEASONS):
        seqs_fit.update(lf.sequences([r for r in fit_rows if int(r['season']) == season], season_pos[season],
                                     snap_labels=True, recon=recon))
    tables, joint_tables, _checks = cs.fit_tables(seqs_fit, drive_map(fit_rows), cs.FIT_SEASONS)
    base = json.loads(args.field.read_text(encoding='utf-8'))
    fit_prior = agc.position_prior(fit_rows, season_pos, cs.FIT_SEASONS)
    base['position_prior'] = [[pos, group, value] for (pos, group), value in sorted(fit_prior.items())]
    field = cs.variant_field(base, tables['split'], False, True, 'split')
    field.leave_beta = args.leave_beta
    joint = {key: dict(c) for key, c in joint_tables['split'].items() if sum(c.values()) >= cs.JOINT_MIN_PAIRS}

    positions_h = season_pos[holdout_season]
    cls_of = vl.classes_of(positions_h)
    seqs = lf.sequences(rows, positions_h, snap_labels=True, recon=recon)
    play_drive = drive_map(rows)
    rosters = vl.roster_by_team(rows, cls_of, positions_h)
    status = agc.weekly_status(args.roster_weekly)
    week_of = {(int(r['season']), r['game_id'], r['posteam']): int(r['week']) for r in rows}
    gated = {}
    for key in seqs:
        _season, _game, team = key
        week = week_of[key]
        gated[key] = [{'gsis_id': pid, 'pos_abb': positions_h[pid], 'pos_rank': i}
                      for i, pid in enumerate(sorted(p['gsis_id'] for p in rosters[team]
                                                     if status.get((p['gsis_id'], team, week)) == 'ACT'))]

    observed_games = []
    observed_snaps = Counter()
    for key, seq in seqs.items():
        ids = [frozenset(pid for pid, _ in skill) for _g, _c, skill in seq]
        # The season-primary class the simulator uses, so the observed and simulated checks measure the same thing.
        cls = {pid: cls_of[pid] for pid in set().union(*ids) if pid in cls_of}
        # A real snap whose skill players are not five is a personnel the grouping model has no code for (mostly six
        # linemen, four skill players). It is counted apart and left out of the legality check. A simulated short snap is
        # a simulator failure, so it stays in.
        complete = [len(i) == SKILL_PER_SNAP for i in ids]
        observed_snaps['all'] += len(ids)
        observed_snaps['not_five_skill'] += sum(1 for ok in complete if not ok)
        entries_ok = [dg.consistent(g, i, cls_of) for (g, _c, _s), i, ok in zip(seq, ids, complete) if ok]
        observed_games.append(game_record(ids, [g for g, _c, _s in seq], len(seq), cls, entries_ok))

    sim_games = []
    for seed in range(1, args.seeds + 1):
        sim, _dropped = cs.simulate(field, seqs, rosters, cls_of, play_drive, seed, False, True, joint, 'free',
                                    roster_for_key=gated, feasible=True)
        for key, snaps in sim.items():
            if not snaps:
                continue
            ids = [s for _g, s in snaps]
            cls = {}
            for pid in set().union(*ids):
                c = cls_of.get(pid)
                if c is not None:
                    cls[pid] = c
            entries_ok = []
            for group, s in snaps:
                counts = Counter(cls.get(pid) for pid in s)
                entries_ok.append(all(counts[c] == cs.gc(group)[c] for c in CLASSES) and len(s) == len(set(s)))
            sim_games.append(game_record(ids, [g for g, _s in snaps], len(snaps), cls, entries_ok))

    result = {'holdout': sorted(cs.HOLDOUT), 'seeds': args.seeds, 'leave_beta': args.leave_beta,
              'simulator_status': dict(field.status),
              'leave_r0': cs.LEAVE_R0,
              'observed': summarize_games(observed_games), 'simulated': summarize_games(sim_games),
              'observed_games': len(observed_games), 'simulated_games': len(sim_games),
              'observed_snaps': dict(observed_snaps),
              'legality': 'a snap is legal when its skill players match the grouping counts by season-primary class; '
                          'observed snaps with other than five skill players (mostly six linemen) are excluded and counted in '
                          'observed_snaps.not_five_skill; simulated short snaps are illegal',
              'not_measured': 'carries and targets: no carrier or target allocation model in the simulator',
              'notes': 'ACT eligibility is retrospective (weekly roster status). Stints are measured per player-game '
                       'as the longest run of consecutive snaps.'}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=1, sort_keys=True) + '\n', encoding='utf-8')
    print(json.dumps({'observed_games': len(observed_games), 'simulated_games': len(sim_games),
                      'legal': {'observed': result['observed']['legal_rate'],
                                'simulated': result['simulated']['legal_rate']}}, sort_keys=True))


if __name__ == '__main__':
    main()
