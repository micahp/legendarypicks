#!/usr/bin/env python3
"""Does gating the lineup bench to the players active on the weekly roster change the 2025 substitution metrics?

The validation bench is each team's full-season 2025 skill players (validate_lineups.roster_by_team). That list keeps players
who are on the practice squad, reserve or inactive in a given week. This check restricts each game's bench to the players
the weekly roster lists as ACT in that week, and reruns the B0 and JD variants on both arms with the 2022 to 2024 tables
unchanged. A third arm, gated_all_act, takes the bench from every ACT skill player on the weekly roster, including players
with no 2025 appearance, so zero-usage eligible players can enter. The 2025 weekly status is a retrospective record. The production availability snapshot is frozen before kickoff,
so this is an upper bound on what a pregame gate can know.

Usage: python3 availability_gate_check.py --tables <scrimmage_participation.csv.gz> --raw-dir <pinned nflverse dir> \
           --pbp-dir <raw dir> --field <field_2022_2024.json> --roster-weekly <roster_weekly_2025.csv.gz> --out <json>
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
import candidate_substitution as cs  # noqa: E402
import diagnose_substitution_gap as dg  # noqa: E402
import lineup_fit as lf  # noqa: E402
import participation_model as pm  # noqa: E402
import validate_lineups as vl  # noqa: E402
import participation_field as pf  # noqa: E402


def weekly_status(path):
    status = {}
    with gzip.open(path, 'rt', encoding='utf-8', newline='') as handle:
        for row in csv.DictReader(handle):
            if row['game_type'] == 'REG' and row['gsis_id']:
                status[(row['gsis_id'], row['team'], int(row['week']))] = row['status']
    return status


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--tables', type=Path, required=True)
    ap.add_argument('--raw-dir', type=Path, required=True)
    ap.add_argument('--pbp-dir', type=Path, required=True)
    ap.add_argument('--field', type=Path, required=True)
    ap.add_argument('--roster-weekly', type=Path, required=True)
    ap.add_argument('--out', type=Path, required=True)
    ap.add_argument('--seeds', type=int, default=3)
    args = ap.parse_args()

    positions = pm.load_positions(args.raw_dir)
    cls_of = vl.classes_of(positions)
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
    tables, joint_tables, _checks = cs.fit_tables(lf.sequences(fit_rows, positions), drive_map(fit_rows), cs.FIT_SEASONS)
    base = json.loads(args.field.read_text(encoding='utf-8'))

    rows = pm.load_scrimmage(args.tables, cs.HOLDOUT)
    seqs = lf.sequences(rows, positions)
    play_drive = drive_map(rows)
    rosters = vl.roster_by_team(rows, cls_of, positions)
    status = weekly_status(args.roster_weekly)
    week_of = {}
    for row in rows:
        week_of[(int(row['season']), row['game_id'], row['posteam'])] = int(row['week'])

    gated, bench_size = {}, Counter()
    for key in seqs:
        _season, _game, team = key
        week = week_of[key]
        gated[key] = [p for p in rosters[team] if status.get((p['gsis_id'], team, week)) == 'ACT']
        bench_size['ungated_players'] += len(rosters[team])
        bench_size['gated_players'] += len(gated[key])

    act_by_team_week = defaultdict(list)
    for (pid, team, week), state in status.items():
        if state == 'ACT' and pid in cls_of:
            act_by_team_week[(team, week)].append(pid)
    gated_all = {}
    for key in seqs:
        _season, _game, team = key
        pids = sorted(act_by_team_week[(team, week_of[key])])
        gated_all[key] = [{'gsis_id': pid, 'pos_abb': positions[pid], 'pos_rank': index}
                          for index, pid in enumerate(pids)]
        bench_size['gated_all_act_players'] += len(pids)

    def joint_for(name):
        return {key: dict(counts) for key, counts in joint_tables[name].items()
                if sum(counts.values()) >= cs.JOINT_MIN_PAIRS}

    variants = {
        'B0_runtime': (cs.variant_field(base, tables['pooled'], False, False, 'pooled'), False, False, None),
        'JD_joint_drive': (cs.variant_field(base, tables['split'], False, True, 'split'), False, True, joint_for('split')),
    }
    result = {'holdout': sorted(cs.HOLDOUT), 'fit_seasons': sorted(cs.FIT_SEASONS), 'seeds': args.seeds,
              'bench_players_per_game_mean': {k: round(v / len(seqs), 2) for k, v in bench_size.items()},
              'observed': cs.summarise(
                  [r for key, seq in seqs.items() for r in dg.pair_records(
                      [g for g, _c, _s in seq], [frozenset(p for p, _ in s) for _g, _c, s in seq],
                      [dg.consistent(g, frozenset(p for p, _ in s), cls_of) for g, _c, s in seq],
                      play_drive[key], cls_of)]),
              'variants': {}}
    for mode in ('forced', 'free'):
        result['variants'][mode] = {}
        for name, (field, stint_swap, drive_split, joint) in variants.items():
            for label, roster_for_key in (('ungated', None), ('gated_to_active_week', gated),
                                          ('gated_all_act', gated_all)):
                field.status.clear()
                runs = [cs.simulate(field, seqs, rosters, cls_of, play_drive, seed, stint_swap, drive_split, joint,
                                    mode, roster_for_key=roster_for_key) for seed in range(1, args.seeds + 1)]
                sims = [sim for sim, _d in runs]
                summary = cs.summarise(cs.evaluate(sims, seqs, play_drive, cls_of))
                result['variants'][mode][f'{name}|{label}'] = {
                    'summary': summary, 'status': dict(field.status),
                    'team_games_dropped_no_league_cell': sum(d for _s, d in runs)}
                print(mode, name, label, summary['clean']['entries_per_pair'], dict(field.status), flush=True)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=1, sort_keys=True) + '\n', encoding='utf-8')
    print(json.dumps({'out': str(args.out), 'bench': result['bench_players_per_game_mean']}, sort_keys=True))


if __name__ == '__main__':
    main()
