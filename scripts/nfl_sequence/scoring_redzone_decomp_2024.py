"""Compare score-clock red-zone opportunities and outcomes with 2024 on a matched game cohort.

The pregame replay uses only outcomes before 2024 Week 1 and an artifact fitted through 2023. Red-zone
trips require a run/pass scrimmage snap at or inside the 20. Trip conversion means an offensive touchdown
as the drive terminal. Play-level touchdown rates use the engine's resolved touchdown flag and the
publisher's pass_touchdown/rush_touchdown fields; sampled source-row touchdown flags are not outcomes.

Usage: python3 scoring_redzone_decomp_2024.py --seeds N --out JSON
"""
import argparse
import collections
import hashlib
import json
import random
import sqlite3
import sys
import time
from datetime import date, timedelta
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE))
import e2_reference as er  # noqa: E402
import pregame_snapshot as ps  # noqa: E402
import slc_engine as se  # noqa: E402

DB = '/root/legendarypicks/backend/data/picks.dev.db'
ARTIFACT = ROOT / 'docs/research/SLC-PLAYCALL-ARTIFACT-FIT-2010-2023-v1.json'
SCRIMMAGE_EVENTS = ('run', 'pass_complete', 'pass_incomplete', 'sack', 'interception', 'fumble_lost')
PASS_EVENTS = ('pass_complete', 'pass_incomplete', 'sack', 'interception')
TURNOVER_EVENTS = ('interception', 'fumble_lost')
METRICS = ('trips_per_team_game', 'offense_td_per_trip', 'rz_plays_per_team_game',
           'offense_td_per_rz_play', 'run_share_of_rz_plays', 'goal_to_go_share_of_rz_plays')
BOOTSTRAP_REPLICATES = 10_000
BOOTSTRAP_SEED = 81029


def bump(counter, key, amount=1):
    counter[key] += amount


def play_kind(event, decision):
    """Keep a lost fumble in the called run/pass family instead of treating every fumble as a pass."""
    if event == 'run' or (event == 'fumble_lost' and decision == 'run'):
        return 'run'
    return 'pass'


def simulated(seeds, exact_yardline=False, ref=None, arm='default', progress_every=5):
    con = sqlite3.connect(f'file:{DB}?mode=ro', uri=True)
    games = con.execute(
        "SELECT game_id, gameday FROM nfl_schedule WHERE season=2024 AND game_type='REG' "
        "AND week BETWEEN 2 AND 18 ORDER BY week, gameday, game_id").fetchall()
    con.close()
    if ref is None:
        ref, _ = er.load(DB, eligible_before=(2024, 1), playcall_artifact=str(ARTIFACT),
                         playcall_teams={'A': 'X', 'B': 'Y'})
    ref.contextual_sampler.exact_yardline = bool(exact_yardline)
    per_game = collections.defaultdict(collections.Counter)
    per_seed = collections.defaultdict(dict)
    cohort = set()
    snapshot_games = set()
    skipped_snapshots = []
    errors = []
    incomplete = []
    started = time.monotonic()

    def progress(game_number):
        if game_number % progress_every and game_number != len(games):
            return
        elapsed = time.monotonic() - started
        attempted = game_number * seeds
        rate = attempted / elapsed if elapsed else 0.0
        remaining = max(0, len(games) - game_number) * seeds
        eta = remaining / rate if rate else None
        eta_text = f'{eta:.0f}s' if eta is not None else 'unknown'
        print(f'progress arm={arm} games={game_number}/{len(games)} attempted={attempted} '
              f'complete_seeds={sum(g.get("complete_seeds", 0) for g in per_game.values())} '
              f'skipped_snapshots={len(skipped_snapshots)} errors={len(errors)} '
              f'incomplete={len(incomplete)} elapsed={elapsed:.0f}s eta={eta_text}', flush=True)

    for game_number, (game_id, gameday) in enumerate(games, start=1):
        as_of = (date.fromisoformat(gameday) - timedelta(days=1)).isoformat() + 'T12:00:00Z'
        try:
            snapshot = ps.build(DB, game_id, as_of, allow_unverified_current_schedule_exploratory=True,
                                evaluation='exploratory_replay')
        except ValueError as exc:
            skipped_snapshots.append({'game_id': game_id, 'reason': str(exc)[:240]})
            progress(game_number)
            continue
        snapshot_games.add(game_id)
        ref.contextual_sampler.side_teams = se.side_teams(snapshot)
        snapshot['model_reference']['observed_reference'] = ref.model_inputs
        for seed in range(1, seeds + 1):
            try:
                record, _decisions = se.play(seed, ref, snapshot)
            except Exception as exc:
                errors.append({'game_id': game_id, 'seed': seed, 'error': f'{type(exc).__name__}: {exc}'[:240]})
                continue
            if record.get('status') not in ('complete_regulation', 'complete_overtime'):
                incomplete.append({'game_id': game_id, 'seed': seed, 'status': record.get('status'),
                                   'blocker': record.get('blocker')})
                continue
            cohort.add(game_id)
            game = per_game[game_id]
            bump(game, 'complete_seeds')
            seed_counts = collections.Counter()
            bump(seed_counts, 'team_games', 2)
            for drive in record['drives']:
                plays = drive.get('plays', [])
                redzone_trip = any(
                    p['event_type'] in SCRIMMAGE_EVENTS
                    and p['state_before'].get('yardline_100') is not None
                    and p['state_before']['yardline_100'] <= 20 for p in plays)
                if redzone_trip:
                    bump(seed_counts, 'trips')
                    terminal = drive.get('terminal') or 'unknown'
                    bump(seed_counts, f'trip_end_{terminal}')
                    if (terminal == 'touchdown'
                            and drive.get('touchdown_scored_by') == drive.get('offense_team')):
                        bump(seed_counts, 'offense_td_trips')
                for play in plays:
                    state = play['state_before']
                    yl = state.get('yardline_100')
                    if yl is None or yl > 20:
                        continue
                    event = play['event_type']
                    decision = play.get('decision', {}).get('type')
                    if event in SCRIMMAGE_EVENTS:
                        kind = play_kind(event, decision)
                        bump(seed_counts, 'rz_plays')
                        bump(seed_counts, f'rz_{kind}_plays')
                        if state.get('down') is not None:
                            bump(seed_counts, f'rz_{kind}_down{state["down"]}')
                        if state.get('yards_to_go') is not None and state['yards_to_go'] >= yl:
                            bump(seed_counts, 'rz_goal_to_go')
                        if play.get('outcome', {}).get('touchdown'):
                            bump(seed_counts, 'rz_td')
                            bump(seed_counts, f'rz_{kind}_td')
                        if event in TURNOVER_EVENTS:
                            bump(seed_counts, f'rz_{kind}_turnover')
                    if state.get('down') == 4:
                        bump(seed_counts, f'fourth_down_{decision or "unknown"}')
            game.update(seed_counts)
            per_seed[game_id][str(seed)] = dict(seed_counts)
        progress(game_number)
    return {
        'per_game': dict(per_game), 'per_seed': dict(per_seed), 'cohort': cohort, 'snapshot_games': snapshot_games,
        'scheduled_games': len(games), 'skipped_snapshots': skipped_snapshots,
        'errors': errors, 'incomplete': incomplete,
    }


def actual_by_game(con):
    """Build actual game-level counts and a content hash from the exact PBP fields used below."""
    query = (
        "SELECT game_id, drive, posteam, play_id, play_type, yardline_100, down, pass_touchdown, "
        "rush_touchdown, interception, fumble_lost, ydstogo, series_result "
        "FROM nfl_pbp WHERE season=2024 AND week BETWEEN 2 AND 18 AND posteam IS NOT NULL "
        "AND drive IS NOT NULL ORDER BY game_id, play_id")
    rows = con.execute(query).fetchall()
    digest = hashlib.sha256()
    drives = collections.defaultdict(list)
    teams = collections.defaultdict(set)
    for row in rows:
        digest.update(json.dumps(row, separators=(',', ':'), default=str).encode())
        digest.update(b'\n')
        game_id, drive, team = row[:3]
        teams[game_id].add(team)
        drives[(game_id, drive, team)].append(row)

    per_game = collections.defaultdict(collections.Counter)
    for game_id, team_set in teams.items():
        per_game[game_id]['team_games'] = len(team_set)

    for (game_id, _drive, _team), plays in drives.items():
        game = per_game[game_id]
        trip = any(row[4] in ('run', 'pass') and row[5] is not None and row[5] <= 20 for row in plays)
        if trip:
            bump(game, 'trips')
            terminal = next((row[12] for row in reversed(plays) if row[12]), None) or 'unknown'
            bump(game, f'trip_end_{terminal}')
            if str(terminal).strip().casefold() == 'touchdown':
                bump(game, 'offense_td_trips')
        for row in plays:
            play_type, yl, down = row[4], row[5], row[6]
            if play_type in ('run', 'pass') and yl is not None and yl <= 20:
                kind = play_type
                bump(game, 'rz_plays')
                bump(game, f'rz_{kind}_plays')
                if down is not None:
                    bump(game, f'rz_{kind}_down{int(down)}')
                ydstogo = row[11]
                if ydstogo is not None and ydstogo >= yl:
                    bump(game, 'rz_goal_to_go')
                td = row[8] if kind == 'run' else row[7]
                if td is None:
                    bump(game, 'rz_td_unknown')
                elif int(td) == 1:
                    bump(game, 'rz_td')
                    bump(game, f'rz_{kind}_td')
                if row[9] or row[10]:
                    bump(game, f'rz_{kind}_turnover')
            if down == 4:
                kind = {'run': 'run', 'pass': 'dropback', 'punt': 'punt',
                        'field_goal': 'field_goal_attempt'}.get(play_type)
                if kind:
                    bump(game, f'fourth_down_{kind}')
    return dict(per_game), digest.hexdigest(), len(rows), query


def aggregate(per_game, game_ids):
    result = collections.Counter()
    for game_id in game_ids:
        result.update(per_game[game_id])
    return result


def simulated_equal_game_weights(per_game, game_ids):
    """Average valid seeds within each game, giving every game one cluster in the point estimate and bootstrap."""
    result = collections.Counter()
    for game_id in game_ids:
        game = per_game[game_id]
        n = game.get('complete_seeds', 0)
        if not n:
            continue
        result['team_games'] += 2
        for key, value in game.items():
            if key in ('complete_seeds', 'team_games'):
                continue
            result[key] += value / n
    return result


def rates(counter):
    plays = counter.get('rz_plays', 0)
    trips = counter.get('trips', 0)
    team_games = counter.get('team_games', 0)
    out = {
        'team_games': team_games,
        'trips': trips,
        'offense_td_trips': counter.get('offense_td_trips', 0),
        'red_zone_plays': plays,
        'red_zone_touchdowns': counter.get('rz_td', 0),
        'red_zone_touchdown_unknown_plays': counter.get('rz_td_unknown', 0),
        'trips_per_team_game': trips / team_games if team_games else None,
        'offense_td_per_trip': counter.get('offense_td_trips', 0) / trips if trips else None,
        'rz_plays_per_team_game': plays / team_games if team_games else None,
        'offense_td_per_rz_play': counter.get('rz_td', 0) / plays if plays else None,
        'run_share_of_rz_plays': counter.get('rz_run_plays', 0) / plays if plays else None,
        'goal_to_go_share_of_rz_plays': counter.get('rz_goal_to_go', 0) / plays if plays else None,
        'run_td_per_rz_run': counter.get('rz_run_td', 0) / counter.get('rz_run_plays', 1),
        'pass_td_per_rz_pass': counter.get('rz_pass_td', 0) / counter.get('rz_pass_plays', 1),
        'run_turnover_per_rz_run': counter.get('rz_run_turnover', 0) / counter.get('rz_run_plays', 1),
        'pass_turnover_per_rz_pass': counter.get('rz_pass_turnover', 0) / counter.get('rz_pass_plays', 1),
        'fourth_down_decisions': {k[len('fourth_down_'):]: v for k, v in counter.items()
                                  if k.startswith('fourth_down_')},
        'trip_endings': {k[len('trip_end_'):]: v for k, v in counter.items() if k.startswith('trip_end_')},
    }
    return out


def value(counter, metric):
    return rates(counter)[metric]


def bootstrap_comparison(sim_games, actual_games, game_ids, replicates=BOOTSTRAP_REPLICATES,
                         seed=BOOTSTRAP_SEED):
    """Paired, game-cluster percentile intervals for simulated minus actual ratios/rates."""
    ids = sorted(game_ids)
    rng = random.Random(seed)
    draws = {metric: [] for metric in METRICS}
    point_sim = simulated_equal_game_weights(sim_games, ids)
    point_actual = aggregate(actual_games, ids)
    point = {}
    for metric in METRICS:
        s, a = value(point_sim, metric), value(point_actual, metric)
        point[metric] = {'simulated': s, 'actual': a, 'difference': s - a}
    for _ in range(replicates):
        sample = [rng.choice(ids) for _ in ids]
        sim = simulated_equal_game_weights(sim_games, sample)
        act = aggregate(actual_games, sample)
        for metric in METRICS:
            draws[metric].append(value(sim, metric) - value(act, metric))
    intervals = {}
    for metric, vals in draws.items():
        vals.sort()
        intervals[metric] = {
            'point': point[metric],
            'cluster_bootstrap_95pct_ci_difference': [vals[int(0.025 * replicates)],
                                                       vals[min(replicates - 1, int(0.975 * replicates))]],
        }
    return {'n_game_clusters': len(ids), 'replicates': replicates, 'seed': seed,
            'intervals': intervals, 'equal_game_weight_simulated': rates(point_sim),
            'matched_actual': rates(point_actual)}


def paired_exact_yardline_comparison(default, exact, game_ids, replicates=BOOTSTRAP_REPLICATES,
                                     seed=BOOTSTRAP_SEED):
    """Compare exact-yardline and default draws over the same complete game-seed pairs."""
    baseline_by_game = {}
    exact_by_game = {}
    paired_seed_counts = {}
    for game_id in sorted(game_ids):
        default_seeds = default['per_seed'].get(game_id, {})
        exact_seeds = exact['per_seed'].get(game_id, {})
        shared = sorted(set(default_seeds) & set(exact_seeds), key=int)
        if not shared:
            continue
        paired_seed_counts[game_id] = shared
        baseline_counts = collections.Counter()
        exact_counts = collections.Counter()
        for seed_id in shared:
            baseline_counts.update(default_seeds[seed_id])
            exact_counts.update(exact_seeds[seed_id])
        n = len(shared)
        baseline_by_game[game_id] = collections.Counter({k: v / n for k, v in baseline_counts.items()})
        exact_by_game[game_id] = collections.Counter({k: v / n for k, v in exact_counts.items()})
        baseline_by_game[game_id]['complete_seeds'] = 1
        exact_by_game[game_id]['complete_seeds'] = 1

    ids = sorted(paired_seed_counts)
    if not ids:
        raise ValueError('no common completed game-seed pairs for exact-yardline comparison')

    def differences(sample):
        default_counts = simulated_equal_game_weights(baseline_by_game, sample)
        exact_counts = simulated_equal_game_weights(exact_by_game, sample)
        return {metric: value(exact_counts, metric) - value(default_counts, metric) for metric in METRICS}

    point = differences(ids)
    rng = random.Random(seed)
    draws = {metric: [] for metric in METRICS}
    for _ in range(replicates):
        sample = [rng.choice(ids) for _ in ids]
        for metric, difference in differences(sample).items():
            draws[metric].append(difference)
    intervals = {}
    for metric, values in draws.items():
        values.sort()
        intervals[metric] = {
            'difference_exact_minus_default': point[metric],
            'cluster_bootstrap_95pct_ci': [values[int(0.025 * replicates)],
                                           values[min(replicates - 1, int(0.975 * replicates))]],
        }
    return {
        'n_common_game_clusters': len(ids),
        'n_common_game_seed_pairs': sum(len(v) for v in paired_seed_counts.values()),
        'common_seed_ids_by_game': paired_seed_counts,
        'replicates': replicates,
        'seed': seed,
        'intervals': intervals,
        'default_equal_game_weight': rates(simulated_equal_game_weights(baseline_by_game, ids)),
        'exact_equal_game_weight': rates(simulated_equal_game_weights(exact_by_game, ids)),
        'default_per_game_counts': baseline_by_game,
        'exact_per_game_counts': exact_by_game,
        'uncertainty_note': 'Game-cluster intervals do not include a separate Monte Carlo seed uncertainty component.',
    }


def main():
    global DB
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--seeds', type=int, default=2)
    ap.add_argument('--out', type=Path, required=True)
    ap.add_argument('--db', type=Path, default=Path(DB), help='read-only SQLite database with nfl_pbp and nfl_schedule')
    ap.add_argument('--compare-exact-yardline', action='store_true',
                    help='run default and exact-yardline arms with the same seeds and compare paired game-seed results')
    ap.add_argument('--progress-every', type=int, default=5,
                    help='print flushed progress every N schedule games; default 5')
    args = ap.parse_args()
    if args.progress_every < 1:
        ap.error('--progress-every must be positive')
    DB = str(args.db)
    ref, _ = er.load(DB, eligible_before=(2024, 1), playcall_artifact=str(ARTIFACT),
                     playcall_teams={'A': 'X', 'B': 'Y'})
    sim = simulated(args.seeds, exact_yardline=False, ref=ref, arm='default',
                    progress_every=args.progress_every)
    exact_sim = (simulated(args.seeds, exact_yardline=True, ref=ref, arm='exact-yardline',
                           progress_every=args.progress_every) if args.compare_exact_yardline else None)
    ref.contextual_sampler.exact_yardline = False
    con = sqlite3.connect(f'file:{DB}?mode=ro', uri=True)
    actual_games, pbp_sha, pbp_rows, actual_query = actual_by_game(con)
    con.close()
    cohort = sim['cohort']
    if not cohort:
        raise SystemExit('no completed simulated games; refusing to report an empty comparison')
    actual_cohort = aggregate(actual_games, cohort)
    if actual_cohort['team_games'] != 2 * len(cohort):
        raise SystemExit(f"matched actual roster coverage is incomplete: {actual_cohort['team_games']} team-games for "
                         f'{len(cohort)} games')
    sim_raw = aggregate(sim['per_game'], cohort)
    sim_raw['team_games'] = sum(2 * game.get('complete_seeds', 0)
                                for game in (sim['per_game'][gid] for gid in cohort))
    full_actual = aggregate(actual_games, actual_games.keys())
    comparison = bootstrap_comparison(sim['per_game'], actual_games, cohort)
    artifact_bytes = ARTIFACT.read_bytes()
    db_stat = Path(DB).stat()
    result = {
        'metadata': {
            'season': 2024, 'weeks': [2, 18], 'requested_seeds_per_game': args.seeds,
            'exact_yardline_comparison_enabled': bool(args.compare_exact_yardline),
            'schedule_games': sim['scheduled_games'], 'valid_pregame_snapshots': len(sim['snapshot_games']),
            'skipped_snapshot_games': sim['skipped_snapshots'], 'matched_cohort_games': len(cohort),
            'matched_cohort_game_ids': sorted(cohort), 'completed_game_seeds': sum(
                game.get('complete_seeds', 0) for game in sim['per_game'].values()),
            'incomplete_game_seeds': sim['incomplete'], 'engine_errors': sim['errors'],
            'actual_population_team_games': full_actual.get('team_games', 0),
            'trip_definition': 'at least one run/pass scrimmage play with yardline_100 <= 20 within the drive',
            'offensive_touchdown_trip_definition': 'simulated drive terminal is touchdown and touchdown_scored_by equals offense_team; '
                'actual terminal series_result is exactly Touchdown (Opp touchdown is excluded)',
            'red_zone_play_touchdown_definition': 'simulated outcome.touchdown; actual rush_touchdown for run and pass_touchdown for pass; '
                'sampled_touchdown_flag is a source-row property and is excluded',
            'red_zone_play_definition': 'run/pass scrimmage event at state/observed yardline_100 <= 20; sacks and turnovers are included '
                'in the pass/run family when the engine labels them as such',
            'actual_pbp_query': actual_query,
            'bootstrap': {'method': 'paired game-cluster resampling, percentile interval',
                          'clusters': len(cohort), 'replicates': BOOTSTRAP_REPLICATES, 'seed': BOOTSTRAP_SEED},
            'cutoff': 'simulation reference eligible before 2024 Week 1; play-call artifact fit through 2023',
            'evaluation': 'exploratory retrospective replay; historical schedule availability is unverified',
            'hashes': {
                'decomposition_script_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                'playcall_artifact_sha256': hashlib.sha256(artifact_bytes).hexdigest(),
                'actual_pbp_rows_sha256': pbp_sha,
                'db_file_size_bytes': db_stat.st_size,
                'db_file_mtime_ns': db_stat.st_mtime_ns,
            },
        },
        'simulated_all_completed_seeds': rates(sim_raw),
        'simulated_equal_game_weight': comparison['equal_game_weight_simulated'],
        'actual_matched_cohort': comparison['matched_actual'],
        'actual_full_weeks_2_18': rates(full_actual),
        'comparison_simulated_minus_actual': comparison['intervals'],
        'actual_pbp_rows_hashed': pbp_rows,
        'per_game': {
            gid: {'completed_sim_seeds': sim['per_game'][gid].get('complete_seeds', 0),
                  'simulated_counts_over_completed_seeds': dict(sim['per_game'][gid]),
                  'actual_counts': dict(actual_games[gid])}
            for gid in sorted(cohort)
        },
    }
    if exact_sim is not None:
        common_games = sim['cohort'] & exact_sim['cohort']
        common_seed_comparison = paired_exact_yardline_comparison(sim, exact_sim, common_games)
        common_ids = set(common_seed_comparison['common_seed_ids_by_game'])
        default_common_per_game = common_seed_comparison['default_per_game_counts']
        exact_common_per_game = common_seed_comparison['exact_per_game_counts']
        result['exact_yardline_ablation'] = {
            'enabled': True,
            'common_game_clusters': len(common_ids),
            'common_game_seed_pairs': common_seed_comparison['n_common_game_seed_pairs'],
            'default': {
                'equal_game_weight': common_seed_comparison['default_equal_game_weight'],
                'versus_actual': bootstrap_comparison(default_common_per_game, actual_games, common_ids)['intervals'],
                'per_game': {
                    gid: {'completed_seed_ids': sorted(sim['per_seed'][gid], key=int),
                          'seed_counts': sim['per_seed'][gid]}
                    for gid in sorted(common_ids)
                },
            },
            'exact_yardline': {
                'equal_game_weight': common_seed_comparison['exact_equal_game_weight'],
                'versus_actual': bootstrap_comparison(exact_common_per_game, actual_games, common_ids)['intervals'],
                'per_game': {
                    gid: {'completed_seed_ids': sorted(exact_sim['per_seed'][gid], key=int),
                          'seed_counts': exact_sim['per_seed'][gid]}
                    for gid in sorted(common_ids)
                },
            },
            'paired_exact_minus_default': {
                k: v for k, v in common_seed_comparison.items()
                if k not in ('default_equal_game_weight', 'exact_equal_game_weight',
                             'default_per_game_counts', 'exact_per_game_counts')
            },
        }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=1, sort_keys=True) + '\n')
    print(json.dumps({
        'cohort_games': len(cohort),
        'completed_game_seeds': result['metadata']['completed_game_seeds'],
        'engine_errors': len(sim['errors']),
        'simulated': {k: result['simulated_equal_game_weight'][k] for k in METRICS},
        'actual': {k: result['actual_matched_cohort'][k] for k in METRICS},
        'difference_ci': {k: result['comparison_simulated_minus_actual'][k]['cluster_bootstrap_95pct_ci_difference']
                          for k in METRICS},
        'output': str(args.out),
    }, sort_keys=True))


if __name__ == '__main__':
    main()
