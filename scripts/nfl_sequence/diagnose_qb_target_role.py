"""Diagnose QB target-role shrinkage on chronological holdouts.

Scores the league-pooled, team-conditioned and QB-conditioned target-role
distributions on 2024 and 2025. The 2024 holdout selects an own-QB shrinkage
strength; 2025 remains the final chronological check. Published weekly depth
charts provide a roster/role proxy, but not timestamped injury eligibility.
"""
import argparse
import hashlib
import json
import math
import random
import sqlite3
import sys
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))
import e0_single_play as e0  # noqa: E402
import qb_decisions as qbd  # noqa: E402
import validate_qb_player_outcomes as validator  # noqa: E402
import nfl_team_codes  # noqa: E402

TARGET_ROLES = qbd.TARGET_ROLES
STRENGTHS = (0, 5, 10, 20, 40, 80, 160)
SUPPORT_BINS = ((0, 0, '0'), (1, 4, '1-4'), (5, 19, '5-19'),
                (20, 49, '20-49'), (50, None, '50+'))
BOOTSTRAPS = 1000


def _normalise(probabilities, categories):
    values = [max(0.0, float(probabilities.get(role, 0.0))) for role in categories]
    total = sum(values)
    if total <= 0:
        return {role: 1.0 / len(categories) for role in categories}
    return {role: value / total for role, value in zip(categories, values)}


def _score(actual, categories, probabilities):
    probabilities = _normalise(probabilities, categories)
    log_loss = -math.log(max(validator.EPSILON, probabilities.get(actual, 0.0)))
    brier = sum((probabilities[role] - float(actual == role)) ** 2 for role in categories)
    return log_loss, brier


def _interval(records, method, baseline, metric, seed):
    by_game = defaultdict(lambda: [0.0, 0])
    for record in records:
        by_game[record['game_id']][0] += (
            record['scores'][baseline][metric] - record['scores'][method][metric])
        by_game[record['game_id']][1] += 1
    games = sorted(by_game)
    rng = random.Random(seed)
    samples = []
    for _ in range(BOOTSTRAPS):
        picked = [games[rng.randrange(len(games))] for _ in games]
        total = sum(by_game[game][0] for game in picked)
        count = sum(by_game[game][1] for game in picked)
        samples.append(total / count)
    samples.sort()
    return [samples[int(0.025 * (len(samples) - 1))],
            samples[int(0.975 * (len(samples) - 1))]]


def _metrics(records, method, baseline, seed):
    if not records:
        return {'n': 0, 'games': 0}
    method_ll = [record['scores'][method][0] for record in records]
    baseline_ll = [record['scores'][baseline][0] for record in records]
    method_br = [record['scores'][method][1] for record in records]
    baseline_br = [record['scores'][baseline][1] for record in records]
    return {
        'n': len(records), 'games': len({record['game_id'] for record in records}),
        'model_log_loss': sum(method_ll) / len(records),
        'model_brier': sum(method_br) / len(records),
        'log_loss_improvement': sum(b - m for b, m in zip(baseline_ll, method_ll)) / len(records),
        'log_loss_improvement_game_bootstrap_95': _interval(records, method, baseline, 0, seed),
        'brier_improvement': sum(b - m for b, m in zip(baseline_br, method_br)) / len(records),
        'brier_improvement_game_bootstrap_95': _interval(records, method, baseline, 1, seed + 1),
    }


def _position_role(position):
    if position in ('RB', 'FB'):
        return 'RB'
    if position in ('WR', 'TE'):
        return position
    return None


def _team_alias(team):
    return nfl_team_codes.to_nflverse_team_code(team)


def _game_metadata(db, season):
    con = sqlite3.connect(f'file:{db}?mode=ro', uri=True, timeout=10)
    try:
        rows = con.execute(
            "SELECT game_id,season,week,game_date,home_team,away_team FROM nfl_pbp "
            "WHERE season=? AND week BETWEEN 1 AND 18 GROUP BY game_id ORDER BY game_id", (season,)
        ).fetchall()
    finally:
        con.close()
    return {row[0]: {'season': int(row[1]), 'week': int(row[2]), 'game_date': row[3],
                     'home_team': row[4], 'away_team': row[5]} for row in rows}


def _depth_snapshots(path, season):
    try:
        import pandas as pd
    except ImportError as exc:
        raise RuntimeError('pandas and a parquet reader are required for depth-chart reconstruction') from exc
    frame = pd.read_parquet(path)
    snapshots = {}
    if season == 2024:
        required = {'week', 'club_code', 'formation', 'gsis_id', 'position', 'game_type'}
        if not required.issubset(frame.columns):
            raise ValueError(f'unexpected 2024 depth-chart schema: missing {sorted(required - set(frame.columns))}')
        frame = frame[(frame['game_type'] == 'REG') & (frame['formation'] == 'Offense')]
        for (team, week), group in frame.groupby(['club_code', 'week'], dropna=True):
            ids = {str(value) for value in group['gsis_id'].dropna()}
            roles = {_position_role(value) for value in group['position'].dropna()}
            snapshots[(str(team), int(week))] = {'players': ids, 'roles': roles - {None}}
        return snapshots, hashlib.sha256(path.read_bytes()).hexdigest()

    required = {'dt', 'team', 'gsis_id', 'pos_abb'}
    if not required.issubset(frame.columns):
        raise ValueError(f'unexpected 2025 depth-chart schema: missing {sorted(required - set(frame.columns))}')
    frame['_dt'] = pd.to_datetime(frame['dt'], utc=True, errors='raise')
    for (team, stamp), group in frame.groupby(['team', '_dt'], dropna=True):
        ids = {str(value) for value in group['gsis_id'].dropna()}
        roles = {_position_role(value) for value in group['pos_abb'].dropna()}
        snapshots.setdefault(str(team), []).append(
            (stamp, {'players': ids, 'roles': roles - {None}}))
    for team in snapshots:
        snapshots[team].sort(key=lambda value: value[0])
    return snapshots, hashlib.sha256(path.read_bytes()).hexdigest()


def _snapshot_for(season, game, offense, snapshots):
    team = _team_alias(offense)
    if season == 2024:
        return snapshots.get((team, game['week']))
    import pandas as pd
    game_day = pd.Timestamp(game['game_date'], tz='UTC')
    eligible = [snapshot for stamp, snapshot in snapshots.get(team, ())
                if stamp.normalize() < game_day.normalize()]
    return eligible[-1] if eligible else None


def _target_records(db, season, depth_path):
    table = qbd.load(db, season)
    rows = validator._holdout_rows(db, season)
    game_map = _game_metadata(db, season)
    snapshots, depth_sha = _depth_snapshots(depth_path, season)
    records = []
    counts = Counter()
    snapshot_cache = {}
    for row in rows:
        team, qb = row['posteam'], row['qb_id']
        if (row['pass_attempt'] != 1 or not row['receiver_player_id'] or not team or not qb
                or row['qb_position'] != 'QB' or row['down'] is None or row['ydstogo'] is None
                or row['yardline_100'] is None):
            continue
        actual = qbd.target_role(row['receiver_position'])
        game = game_map.get(row['game_id'])
        if game is None:
            continue
        snapshot_key = (row['game_id'], team)
        if snapshot_key not in snapshot_cache:
            snapshot_cache[snapshot_key] = _snapshot_for(season, game, team, snapshots)
        snapshot = snapshot_cache[snapshot_key]
        counts['target_rows'] += 1
        if snapshot is None:
            counts['no_pregame_depth_snapshot'] += 1
            roster_roles, roster_ids = set(), set()
        else:
            counts['with_pregame_depth_snapshot'] += 1
            roster_roles, roster_ids = snapshot['roles'], snapshot['players']
        on_chart = str(row['receiver_player_id']) in roster_ids
        if on_chart:
            counts['receiver_id_on_chart'] += 1
        if actual in roster_roles:
            counts['actual_role_in_chart'] += 1
        cell = qbd.cell_of(row['down'], row['ydstogo'], row['yardline_100'])
        league_counts = table['target_league_cell'].get(cell, Counter())
        team_counts = table['target_team_cell'].get((team, cell), Counter())
        qb_counts = table['target_qb_cell'].get((team, qb, cell), Counter())
        league = qbd._distribution(Counter(), league_counts, 0, TARGET_ROLES)
        team_prior = qbd._distribution(team_counts, league, qbd.SHRINKAGE, TARGET_ROLES)
        distributions = {'pooled': league, 'team': team_prior}
        for strength in STRENGTHS:
            distributions[f'qb_{strength}'] = qbd._distribution(
                qb_counts, team_prior, strength, TARGET_ROLES)
        records.append({
            'game_id': row['game_id'], 'player_id': qb, 'actual': actual,
            'history_n': sum(qb_counts.values()), 'available_roles': tuple(
                role for role in TARGET_ROLES if role in roster_roles),
            'receiver_on_chart': on_chart, 'snapshot_present': snapshot is not None,
            'distributions': distributions,
        })
    return table, records, counts, depth_sha


def _score_populations(records):
    populations = {'all_targets': records}
    charted = []
    role_only = []
    for record in records:
        roles = record['available_roles']
        if record['actual'] in roles:
            role_only.append(record)
        if record['receiver_on_chart'] and record['actual'] in roles:
            charted.append(record)
    populations['actual_role_in_pregame_depth_chart'] = role_only
    populations['receiver_id_and_role_in_pregame_depth_chart'] = charted
    return populations


def _score_records(population, seed, role_conditioned=False):
    scored = []
    for record in population:
        categories = record['available_roles'] if role_conditioned else TARGET_ROLES
        # The all-target score uses the full four-role space. Depth-chart subsets
        # use only role groups present in that game and renormalize every model.
        if record['actual'] not in categories:
            categories = TARGET_ROLES
        scores = {name: _score(record['actual'], categories, distribution)
                  for name, distribution in record['distributions'].items()}
        scored.append({**record, 'scores': scores})
    metrics = {}
    for strength in STRENGTHS:
        method = f'qb_{strength}'
        metrics[method] = {
            'vs_team_conditioned': _metrics(scored, method, 'team', seed + strength * 3),
            'vs_league_pooled': _metrics(scored, method, 'pooled', seed + strength * 3 + 1),
        }
    return scored, metrics


def _support_summary(records):
    out = []
    for low, high, label in SUPPORT_BINS:
        group = [record for record in records
                 if record['history_n'] >= low and (high is None or record['history_n'] <= high)]
        if not group:
            continue
        scores = [_score(record['actual'], TARGET_ROLES, record['distributions']['qb_20'])
                  for record in group]
        baseline = [_score(record['actual'], TARGET_ROLES, record['distributions']['team'])
                    for record in group]
        out.append({
            'support': label, 'n': len(group), 'games': len({r['game_id'] for r in group}),
            'log_loss_improvement_vs_team': sum(b[0] - m[0] for b, m in zip(baseline, scores)) / len(group),
            'brier_improvement_vs_team': sum(b[1] - m[1] for b, m in zip(baseline, scores)) / len(group),
        })
    return out


def run(db, depth_dir):
    result = {
        'report_version': 'slc-qb-target-role-support-v1',
        'created_on': date.today().isoformat(),
        'method': {
            'holdouts': {'2024': 'fit 2022-2023; tuning holdout',
                         '2025': 'fit 2022-2024; final chronological holdout'},
            'candidate_qb_shrinkage_strengths': list(STRENGTHS),
            'team_prior_strength': qbd.SHRINKAGE,
            'uncertainty': f'{BOOTSTRAPS} paired game-cluster bootstrap draws; percentile 95% intervals',
            'baselines': 'league pooled situation distribution and existing SLC team-cell distribution shrunk toward league by 20 rows',
            'depth_chart_filter': '2024 official weekly offense depth chart for matching week; 2025 latest official chart timestamp strictly before game-date UTC. Score subsets by normalizing all distributions over listed RB/WR/TE groups. The feed does not provide frozen injury eligibility.',
        },
        'seasons': {},
    }
    for season in (2024, 2025):
        path = depth_dir / f'depth_charts_{season}.parquet'
        table, records, counts, depth_sha = _target_records(db, season, path)
        populations = _score_populations(records)
        season_data = {
            'fit': {'cutoff_exclusive': season, 'source_seasons': table['source_seasons'],
                    'source_sha256': table['sha256'], 'source_counts': table['source_counts']},
            'holdout': {'season': season, 'target_source_counts': dict(counts),
                        'depth_chart_sha256': depth_sha,
                        'depth_chart_target_coverage': {
                            'snapshot_rows_pct': counts['with_pregame_depth_snapshot'] / max(1, counts['target_rows']),
                            'actual_role_listed_pct': counts['actual_role_in_chart'] / max(1, counts['target_rows']),
                            'receiver_id_listed_pct': counts['receiver_id_on_chart'] / max(1, counts['target_rows']),
                        }},
            'populations': {},
        }
        for index, (name, population) in enumerate(populations.items()):
            scored, metrics = _score_records(population, season * 10000 + index * 100,
                                             role_conditioned=name != 'all_targets')
            season_data['populations'][name] = {
                'n': len(scored), 'games': len({r['game_id'] for r in scored}),
                'shrinkage_sweep': metrics,
                'fixed_20_support_bins': _support_summary(population) if name == 'all_targets' else [],
            }
        result['seasons'][str(season)] = season_data

    tuning = result['seasons']['2024']['populations']['all_targets']['shrinkage_sweep']
    selected = max(STRENGTHS, key=lambda value:
                   tuning[f'qb_{value}']['vs_team_conditioned']['log_loss_improvement'])
    result['tuning'] = {
        'selected_qb_shrinkage_strength': selected,
        'selection_rule': 'maximize 2024 all-target log-loss improvement over the team-conditioned baseline; this choice is carried unchanged to the 2025 report',
        '2025_primary': result['seasons']['2025']['populations']['all_targets']['shrinkage_sweep'][f'qb_{selected}'],
        '2025_charted_receiver_subset': result['seasons']['2025']['populations']['receiver_id_and_role_in_pregame_depth_chart']['shrinkage_sweep'][f'qb_{selected}'],
    }
    result['code_sha256'] = {
        path.name: hashlib.sha256(path.read_bytes()).hexdigest()
        for path in (Path(__file__), HERE / 'qb_decisions.py', HERE / 'validate_qb_player_outcomes.py')
    }
    result['limitations'] = [
        'The depth-chart feed is a role and roster proxy; it is not a frozen game-day active roster.',
        'Historical injury rows for 2025 have no date_modified timestamps, so injury eligibility cannot be reconstructed as of kickoff and no claim of fully roster-valid calibration is made.',
        'The 2024 official depth-chart file is weekly without a publication timestamp; its matching-week roster filter is exploratory.',
        'This evaluates target-role marginals, not participant selection, full-game outcomes, target counts, scoring, or win probabilities.',
        'The 2024 sweep is used to select shrinkage strength; only 2025 is the final untouched chronological comparison.',
    ]
    return result


def _markdown(report):
    lines = [
        '# QB target-role shrinkage and support diagnostic', '',
        'The 2024 holdout selects the QB-specific shrinkage strength. The selected value is evaluated unchanged on the 2025 chronological holdout. Positive improvement means lower loss than the named baseline.', '',
        '| Holdout | Population | Rows | Games | Shrinkage | Log-loss improvement vs team (95% CI) | Brier improvement vs team (95% CI) | Log-loss improvement vs pooled |',
        '|---:|---|---:|---:|---:|---:|---:|---:|',
    ]
    for season in ('2024', '2025'):
        for population, block in report['seasons'][season]['populations'].items():
            for strength in STRENGTHS:
                score = block['shrinkage_sweep'][f'qb_{strength}']['vs_team_conditioned']
                pooled = block['shrinkage_sweep'][f'qb_{strength}']['vs_league_pooled']
                ci, bci = score.get('log_loss_improvement_game_bootstrap_95', [0, 0]), score.get('brier_improvement_game_bootstrap_95', [0, 0])
                lines.append(f"| {season} | {population} | {score.get('n', 0)} | {score.get('games', 0)} | {strength} | "
                             f"{score.get('log_loss_improvement', 0):+.5f} [{ci[0]:+.5f}, {ci[1]:+.5f}] | "
                             f"{score.get('brier_improvement', 0):+.5f} [{bci[0]:+.5f}, {bci[1]:+.5f}] | "
                             f"{pooled.get('log_loss_improvement', 0):+.5f} |")
    lines.extend(['', f"**2024-selected own-QB shrinkage:** {report['tuning']['selected_qb_shrinkage_strength']} observations.", '',
                  '## Exact-cell QB history support', '',
                  'The following groups use the current 20-observation shrinkage and compare against the team-conditioned baseline on all identified 2025 targets.', '',
                  '| QB/team/situation history rows | Targets | Games | Log-loss improvement | Brier improvement |',
                  '|---|---:|---:|---:|---:|'])
    for row in report['seasons']['2025']['populations']['all_targets']['fixed_20_support_bins']:
        lines.append(f"| {row['support']} | {row['n']} | {row['games']} | {row['log_loss_improvement_vs_team']:+.5f} | {row['brier_improvement_vs_team']:+.5f} |")
    lines.extend(['', '## Eligibility and limits', '',
                  'The depth-chart subset renormalizes over role groups listed for that team and date and, in its strictest form, scores only targets whose receiver GSIS ID is present in that chart. It does not reconstruct game-day injuries. 2025 historical injury rows lack `date_modified`; the result is therefore a role-roster proxy, not a complete frozen-roster validation.', '',
                  'The 2024 candidate sweep is tuning evidence. Treat the 2025 result as the chronological test. Neither result establishes full-game calibration or improved scoring/win probabilities.', '',
                  'See the JSON companion for fit and source hashes, row coverage, intervals, support counts and limitations.', ''])
    return '\n'.join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--db', default=e0.DEFAULT_DB)
    parser.add_argument('--depth-dir', type=Path, default=Path(__file__).resolve().parents[2] /
                        'docs/research/SLC-PLAYER-CONDITIONING-2026-10-29/inputs')
    parser.add_argument('--out-json', type=Path, required=True)
    parser.add_argument('--out-md', type=Path, required=True)
    args = parser.parse_args(argv)
    report = run(args.db, args.depth_dir)
    args.out_json.write_text(json.dumps(report, indent=2, sort_keys=True) + '\n')
    args.out_md.write_text(_markdown(report))
    for season, data in report['seasons'].items():
        block = data['populations']['all_targets']['shrinkage_sweep']
        print(f"{season}: n={data['populations']['all_targets']['n']} "
              f"fixed20_vs_team={block['qb_20']['vs_team_conditioned']['log_loss_improvement']:+.5f} "
              f"selected={report['tuning']['selected_qb_shrinkage_strength']}")


if __name__ == '__main__':
    main()
