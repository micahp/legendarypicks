#!/usr/bin/env python3
"""Free-running games: the E2 control against research clock D, on the same seeds.

Each seed is played twice, once with the E2 clock (control) and once with D, both through game_state.play_game with the
same reference. The outcome sequence matches until the two clocks first disagree about a quarter, after which the games
diverge. The per-seed rows and the summary here are what the comparison reports.

Usage: python3 clock_d_games.py --seeds 300 [--out-dir DIR]
"""
import argparse
import csv
import hashlib
import json
import sqlite3
import statistics
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import clock_d as cd  # noqa: E402
import e1_drive as e1  # noqa: E402
import e2_reference as er  # noqa: E402
import game_state as gs  # noqa: E402

DEV_GAMES = ('2022_05_CIN_BAL', '2022_09_GB_DET', '2022_05_MIA_NYJ', '2022_06_SF_ATL', '2022_07_TB_CAR', '2022_06_DAL_PHI')
LATE = 120
TRAIN_SEASON_FROM = 2022
HOLDOUT_SEASON = 2025


def _quantile(values, fraction):
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(fraction * (len(ordered) - 1)))] if ordered else None


def _describe(values):
    return {'n': len(values), 'mean': round(statistics.fmean(values), 2) if values else None,
            'median': statistics.median(values) if values else None,
            'p10': _quantile(values, .10), 'p90': _quantile(values, .90)}


def holdout_volume(db=e1.DEFAULT_DB, season=HOLDOUT_SEASON):
    """Measure regular-season holdout volume with the same play classifier used by E1."""
    columns = (*e1.COLUMNS, 'drive')
    con = sqlite3.connect(f'file:{db}?mode=ro', uri=True, timeout=10)
    try:
        raw_rows = list(con.execute(
            f"SELECT {', '.join(columns)} FROM nfl_pbp WHERE season=? AND week BETWEEN 1 AND 18 "
            "ORDER BY game_id, play_id", (season,)))
        rows = [dict(zip(columns, row)) for row in raw_rows]
    finally:
        con.close()
    source_digest = hashlib.sha256()
    for row in raw_rows:
        source_digest.update(json.dumps(row, separators=(',', ':'), ensure_ascii=False, default=str).encode())
        source_digest.update(b'\n')
    by_game = defaultdict(list)
    for row in rows:
        by_game[row['game_id']].append(row)

    games = {}
    drive_plays = defaultdict(int)
    excluded = Counter()
    for game_id, sequence in by_game.items():
        game = {'plays': 0, **{f'plays_q{q}': 0 for q in range(1, 5)}, 'drives': set(),
                'event_counts': Counter(), 'event_runoff_sums': Counter(), 'event_runoff_counts': Counter()}
        for i, row in enumerate(sequence):
            if row['qtr'] not in (1, 2, 3, 4) or cd.is_marker(row):
                continue
            nxt = sequence[i + 1] if i + 1 < len(sequence) else None
            hit = e1.classify(row, nxt, excluded)
            if hit is None:
                continue
            event, runoff, _spot = hit
            game['plays'] += 1
            game[f"plays_q{int(row['qtr'])}"] += 1
            game['event_counts'][event] += 1
            game['event_runoff_sums'][event] += runoff
            game['event_runoff_counts'][event] += 1
            if row['drive'] is not None and row['posteam'] is not None:
                drive_key = (game_id, row['posteam'], int(row['drive']))
                game['drives'].add(drive_key)
                drive_plays[drive_key] += 1
        game['drives'] = len(game['drives'])
        games[game_id] = game

    play_counts = [g['plays'] for g in games.values()]
    drive_counts = [g['drives'] for g in games.values()]
    plays_per_drive = [g['plays'] / g['drives'] for g in games.values() if g['drives']]
    all_event_counts = Counter()
    all_event_runoff_sums = Counter()
    all_event_runoff_counts = Counter()
    for game in games.values():
        all_event_counts.update(game['event_counts'])
        all_event_runoff_sums.update(game['event_runoff_sums'])
        all_event_runoff_counts.update(game['event_runoff_counts'])
    total_events = sum(all_event_counts.values())
    return {
        'season': season, 'weeks': [1, 18], 'games': len(games), 'team_games': 2 * len(games),
        'source_rows': len(raw_rows), 'source_rows_sha256': source_digest.hexdigest(),
        'classifier': 'e1.classify on regulation PBP plays with the observed next row',
        'excluded_rows': dict(sorted(excluded.items())),
        'plays_per_game': _describe(play_counts),
        'plays_per_team_game_mean': round(sum(play_counts) / (2 * len(games)), 2) if games else None,
        'regulation_drives_per_game': _describe(drive_counts),
        'regulation_drives_per_team_game_mean': round(sum(drive_counts) / (2 * len(games)), 2) if games else None,
        'plays_per_drive_game_mean': round(statistics.fmean(plays_per_drive), 2) if plays_per_drive else None,
        'plays_per_drive_pooled': round(sum(drive_plays.values()) / len(drive_plays), 2) if drive_plays else None,
        'event_counts_total': dict(sorted(all_event_counts.items())),
        'event_counts_per_game_mean': {event: round(count / len(games), 2)
                                       for event, count in sorted(all_event_counts.items())} if games else {},
        'event_share': {event: round(count / total_events, 4) for event, count in sorted(all_event_counts.items())
                        if total_events},
        'event_runoff_mean_s': {event: round(all_event_runoff_sums[event] / all_event_runoff_counts[event], 2)
                                for event in sorted(all_event_counts) if all_event_runoff_counts[event]},
        'plays_by_quarter_per_game': {
            f'q{q}': _describe([g[f'plays_q{q}'] for g in games.values()]) for q in range(1, 5)},
    }


def comparison_to_holdout(simulated, observed):
    complete = [row for row in simulated if row['complete_regulation']]
    reached = [row for row in simulated if row.get('regulation_end_reached')]
    if not reached:
        return {'regulation_end_reached_games': 0, 'complete_regulation_games': len(complete)}
    sim_metrics = {
        'plays_per_game': statistics.fmean(row['regulation_plays'] for row in reached),
        'plays_per_team_game': statistics.fmean(row['regulation_plays'] / 2 for row in reached),
        'regulation_drives_per_game': statistics.fmean(row['regulation_drives'] for row in reached),
        'regulation_drives_per_team_game': statistics.fmean(row['regulation_drives'] / 2 for row in reached),
        'plays_per_drive_game_mean': statistics.fmean(row['plays_per_regulation_drive'] for row in reached
                                                     if row['plays_per_regulation_drive'] is not None),
        **{f'plays_q{q}_per_game': statistics.fmean(row[f'plays_q{q}'] for row in reached)
           for q in range(1, 5)},
    }
    observed_metrics = {
        'plays_per_game': observed['plays_per_game']['mean'],
        'plays_per_team_game': observed['plays_per_team_game_mean'],
        'regulation_drives_per_game': observed['regulation_drives_per_game']['mean'],
        'regulation_drives_per_team_game': observed['regulation_drives_per_team_game_mean'],
        'plays_per_drive_game_mean': observed['plays_per_drive_game_mean'],
        **{f'plays_q{q}_per_game': observed['plays_by_quarter_per_game'][f'q{q}']['mean']
           for q in range(1, 5)},
    }
    event_counts, event_runoff_sums, event_runoff_counts = Counter(), Counter(), Counter()
    for row in reached:
        event_counts.update(row.get('event_counts', {}))
        event_runoff_sums.update(row.get('event_runoff_sums', {}))
        event_runoff_counts.update(row.get('event_runoff_counts', {}))
    simulated_event_total = sum(event_counts.values())
    event_types = sorted(set(event_counts) | set(observed['event_counts_total']))
    event_composition = {
        event: {
            'simulated_per_game_mean': round(event_counts[event] / len(reached), 2),
            'observed_per_game_mean': observed['event_counts_per_game_mean'].get(event, 0),
            'simulated_share': round(event_counts[event] / simulated_event_total, 4) if simulated_event_total else None,
            'observed_share': observed['event_share'].get(event, 0),
        }
        for event in event_types
    }
    runoff_means = {
        event: {
            'simulated_mean_s': round(event_runoff_sums[event] / event_runoff_counts[event], 2)
            if event_runoff_counts[event] else None,
            'observed_mean_s': observed['event_runoff_mean_s'].get(event),
            'simulated_minus_observed_s': round(
                event_runoff_sums[event] / event_runoff_counts[event] - observed['event_runoff_mean_s'][event], 2)
            if event_runoff_counts[event] and event in observed['event_runoff_mean_s'] else None,
        }
        for event in event_types
    }
    return {'regulation_end_reached_games': len(reached), 'complete_regulation_games': len(complete),
            'simulated': {k: round(v, 2) for k, v in sim_metrics.items()},
            'observed_2025': observed_metrics,
            'difference_simulated_minus_observed': {
                k: round(sim_metrics[k] - observed_metrics[k], 2)
                for k in sim_metrics if observed_metrics[k] is not None},
            'event_composition': event_composition, 'event_runoff_mean_s': runoff_means}


def play_rows(record):
    """Every drive play, with its quarter, clock at the snap, runoff and whether it clamped."""
    rows = []
    for d in record['drives']:
        for p in d['plays']:
            s = p['state_before']
            rows.append({'drive': d['index'], 'event': p['event_type'], 'quarter': s['quarter'],
                         'clock': s['clock_seconds'], 'runoff': p['outcome']['clock_runoff_seconds'],
                         'clamped': p['outcome']['clock_clamped_to_zero'],
                         'ends_quarter': p['outcome']['clock_clamped_to_zero'] or p['outcome']['quarter_change']
                         or p['outcome'].get('clock_only_terminal') is not None and
                         p['outcome'].get('clock_only_terminal') is not False})
    return rows


def per_seed(seed, record):
    rows = play_rows(record)
    per_q = Counter(r['quarter'] for r in rows)
    regulation_drives = [d for d in record['drives'] if d.get('quarter_start') in (1, 2, 3, 4)]
    regulation_plays = [r for r in rows if r['quarter'] in (1, 2, 3, 4)]
    drive_seconds = [sum(p['outcome']['clock_runoff_seconds'] for p in d['plays']) for d in regulation_drives]
    event_aliases = {'blocked_punt': 'punt', 'blocked_field_goal': 'field_goal_attempt'}
    event_counts, event_runoff_sums, event_runoff_counts = Counter(), Counter(), Counter()
    for play in regulation_plays:
        event = event_aliases.get(play['event'], play['event'])
        event_counts[event] += 1
        event_runoff_sums[event] += play['runoff']
        event_runoff_counts[event] += 1
    ends = Counter()
    for d in record['drives']:
        last = d['plays'][-1] if d['plays'] else None
        if last and (last['outcome']['clock_clamped_to_zero'] or last['outcome']['quarter_change']):
            ends[last['event_type']] += 1
    late = [r for r in rows if r['quarter'] in cd.LATE_QUARTERS and r['clock'] <= LATE]
    kinds = Counter(b['kind'] for b in record['boundaries'])
    return {
        'seed': seed, 'status': record['status'], 'complete_regulation': record['complete_regulation'],
        'regulation_end_reached': record.get('regulation_end_reached', False),
        'plays': len(rows), 'drives': len(record['drives']),
        'regulation_plays': len(regulation_plays), 'regulation_drives': len(regulation_drives),
        'plays_per_regulation_drive': len(regulation_plays) / len(regulation_drives) if regulation_drives else None,
        'event_counts': dict(event_counts), 'event_runoff_sums': dict(event_runoff_sums),
        'event_runoff_counts': dict(event_runoff_counts),
        'points_A': record['points'].get('A', 0), 'points_B': record['points'].get('B', 0),
        'points': sum(record['points'].values()),
        'plays_q1': per_q[1], 'plays_q2': per_q[2], 'plays_q3': per_q[3], 'plays_q4': per_q[4],
        'clamped_plays': sum(1 for r in rows if r['clamped']),
        'boundaries': dict(kinds), 'quarter_end_events': dict(ends),
        'median_drive_seconds': statistics.median(drive_seconds) if drive_seconds else None,
        'late_plays': len(late), 'late_run_or_pass': sum(1 for r in late if r['event'] in ('run', 'pass_complete',
                                                                                          'pass_incomplete', 'sack')),
        'final_quarter': record['final_quarter'], 'final_clock_seconds': record['final_clock_seconds'],
        'blocker': record.get('blocker'),
    }


def summarise(rows):
    complete = [r for r in rows if r['complete_regulation']]
    reached = [r for r in rows if r.get('regulation_end_reached')]
    out = {'games': len(rows), 'complete_regulation': len(complete),
           'regulation_end_reached': len(reached),
           'blocked': sum(1 for r in rows if r['status'] == 'blocked'),
           'status_counts': dict(sorted(Counter(r['status'] for r in rows).items()))}
    for k in ('plays', 'drives', 'regulation_plays', 'regulation_drives', 'points', 'plays_q1', 'plays_q2',
              'plays_q3', 'plays_q4', 'clamped_plays', 'late_plays'):
        vals = [r[k] for r in reached]
        out[k] = {'mean': round(statistics.fmean(vals), 2), 'median': statistics.median(vals),
                  'p10': sorted(vals)[len(vals) // 10], 'p90': sorted(vals)[(9 * len(vals)) // 10]} if vals else None
    ends = Counter()
    for r in reached:
        ends.update(r['quarter_end_events'])
    out['quarter_end_events'] = dict(ends)
    out['boundaries'] = dict(sum((Counter(r['boundaries']) for r in reached), Counter()))
    out['plays_per_regulation_drive'] = _describe(
        [r['plays_per_regulation_drive'] for r in reached if r['plays_per_regulation_drive'] is not None])
    event_counts, event_runoff_sums, event_runoff_counts = Counter(), Counter(), Counter()
    for row in reached:
        event_counts.update(row.get('event_counts', {}))
        event_runoff_sums.update(row.get('event_runoff_sums', {}))
        event_runoff_counts.update(row.get('event_runoff_counts', {}))
    total_events = sum(event_counts.values())
    out['event_counts_total'] = dict(sorted(event_counts.items()))
    out['event_counts_per_game_mean'] = {
        event: round(count / len(reached), 2) for event, count in sorted(event_counts.items())} if reached else {}
    out['event_share'] = {event: round(count / total_events, 4) for event, count in sorted(event_counts.items())
                          if total_events}
    out['event_runoff_mean_s'] = {
        event: round(event_runoff_sums[event] / event_runoff_counts[event], 2)
        for event in sorted(event_counts) if event_runoff_counts[event]}
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--seeds', type=int, default=300)
    ap.add_argument('--out-dir', default=str(Path(__file__).resolve().parents[2] / 'docs' / 'research' / 'e3'
                                                / 'clock-d-games-2025-holdout-train-2022-2024'))
    args = ap.parse_args()

    ref, _ = er.load(eligible_before=(HOLDOUT_SEASON, 1))
    train_all = cd.load_window(e1.DEFAULT_DB, TRAIN_SEASON_FROM, HOLDOUT_SEASON - 1, 1, 18)
    train = [r for r in train_all if r['game_id'] not in DEV_GAMES]
    model = cd.fit(train, cd.load_flags())
    observed = holdout_volume(season=HOLDOUT_SEASON)

    runs = {}
    for label, clock_model in (('E2', None), ('D', model)):
        ref.clock_model = clock_model
        rows = []
        for seed in range(1, args.seeds + 1):
            record = gs.play_game(seed, ref)
            rows.append(per_seed(seed, record))
        runs[label] = rows

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    with open(out_dir / 'clock-d-games-per-seed.csv', 'w', newline='') as f:
        fields = list(runs['E2'][0].keys())
        writer = csv.DictWriter(f, fieldnames=['clock'] + fields)
        writer.writeheader()
        for label in ('E2', 'D'):
            for r in runs[label]:
                writer.writerow({'clock': label, **{k: json.dumps(v) if isinstance(v, dict) else v for k, v in r.items()}})
    summary = {label: summarise(rows) for label, rows in runs.items()}
    summary['model'] = {'fit_counts': {k: v for k, v in model.fit_counts.items()
                                        if not k.startswith('plays fitted') and not k.startswith('quarter-ending')},
                        'train': {'seasons': [TRAIN_SEASON_FROM, HOLDOUT_SEASON - 1], 'weeks': [1, 18],
                                  'source_games_before_dev_exclusion': len({r['game_id'] for r in train_all}),
                                  'games_fitted': len({r['game_id'] for r in train}),
                                  'plays_fitted': sum(v for k, v in model.fit_counts.items()
                                                      if k.startswith('plays fitted'))},
                        'holdout': {'season': HOLDOUT_SEASON, 'weeks': [1, 18]},
                        'reference_sha256': ref.model_inputs['sha256'],
                        'reference_scope': ref.pool_scope,
                        'source_sha256': {
                            str(path): hashlib.sha256(Path(path).read_bytes()).hexdigest()
                            for path in (e1.DEFAULT_DB, cd.EXTRAS, cd.__file__, __file__, e1.__file__, er.__file__)}}
    summary['observed_2025_volume'] = observed
    summary['simulation_vs_2025'] = {
        label: comparison_to_holdout(rows, observed) for label, rows in runs.items()}
    (out_dir / 'clock-d-games-summary.json').write_text(json.dumps(summary, indent=1, sort_keys=True) + '\n')
    print(json.dumps(summary, indent=1, sort_keys=True))


if __name__ == '__main__':
    main()
