"""Score QB decisions and player outcome marginals on a chronological NFL play holdout.

Fits 2022-2024, scores 2025, and bootstraps paired score differences by game. This is a historical source-row benchmark;
it does not validate full-game calibration or the joint QB-receiver distribution used by SLC.
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
import e0_single_play as e0  # noqa: E402
import e1_drive as e1  # noqa: E402
import player_outcomes as po  # noqa: E402
import qb_decisions as qbd  # noqa: E402

FIT_CUTOFF = 2025
HOLDOUT_SEASON = 2025
BOOTSTRAPS = 1000
EPSILON = 1e-12


def _normalise(probabilities, categories):
    values = [max(0.0, float(probabilities.get(category, 0.0))) for category in categories]
    total = sum(values)
    if total <= 0:
        return {category: 1.0 / len(categories) for category in categories}
    return {category: value / total for category, value in zip(categories, values)}


def _adjusted(base, posterior, categories):
    """Apply the same clipped marginal likelihood ratio used by the SLC adapter, then renormalize."""
    weights = {}
    for category in categories:
        p0 = float(base.get(category, 0.0))
        p1 = float(posterior.get(category, p0))
        ratio = 1.0 if p0 <= 0 else min(po.MAX_RATIO, max(po.MIN_RATIO, p1 / p0))
        weights[category] = p0 * ratio
    return _normalise(weights, categories)


def _score(actual, categories, probabilities):
    p = _normalise(probabilities, categories)
    log_loss = -math.log(max(EPSILON, p.get(actual, 0.0)))
    brier = sum((p[category] - float(category == actual)) ** 2 for category in categories)
    return log_loss, brier


def _cluster_interval(records, index, seed):
    by_game = defaultdict(list)
    for record in records:
        by_game[record['game_id']].append(record['improvement'][index])
    games = sorted(by_game)
    rng = random.Random(seed)
    draws = []
    for _ in range(BOOTSTRAPS):
        selected = [games[rng.randrange(len(games))] for _ in games]
        values = [value for game in selected for value in by_game[game]]
        draws.append(sum(values) / len(values))
    draws.sort()
    return [draws[int(0.025 * (len(draws) - 1))], draws[int(0.975 * (len(draws) - 1))]]


def _summary(records, categories, seed):
    if not records:
        return {'n': 0, 'games': 0, 'players': 0, 'history_rows': 0, 'status': 'no_scored_rows'}
    baseline_scores = [_score(r['actual'], categories, r['baseline']) for r in records]
    model_scores = [_score(r['actual'], categories, r['model']) for r in records]
    deltas = [[b[0] - m[0], b[1] - m[1]] for b, m in zip(baseline_scores, model_scores)]
    paired = [{**record, 'improvement': delta} for record, delta in zip(records, deltas)]
    return {
        'n': len(records), 'games': len({r['game_id'] for r in records}),
        'players': len({r['player_id'] for r in records}),
        'history_rows': sum(bool(r['history']) for r in records),
        'baseline_log_loss': sum(x[0] for x in baseline_scores) / len(records),
        'model_log_loss': sum(x[0] for x in model_scores) / len(records),
        'log_loss_improvement': sum(x[0] for x in deltas) / len(records),
        'log_loss_improvement_game_bootstrap_95': _cluster_interval(paired, 0, seed),
        'baseline_brier': sum(x[1] for x in baseline_scores) / len(records),
        'model_brier': sum(x[1] for x in model_scores) / len(records),
        'brier_improvement': sum(x[1] for x in deltas) / len(records),
        'brier_improvement_game_bootstrap_95': _cluster_interval(paired, 1, seed + 1),
    }


def _holdout_rows(db, season=HOLDOUT_SEASON):
    columns = ('season', 'game_id', 'play_id', 'posteam', 'passer_player_id', 'rusher_player_id',
               'receiver_player_id', 'qb_dropback', 'qb_scramble', 'pass_attempt', 'rush_attempt',
               'complete_pass', 'sack', 'interception', 'fumble_lost', 'yards_gained', 'passing_yards',
               'receiving_yards', 'rushing_yards', 'pass_touchdown', 'touchdown', 'rush_touchdown',
               'down', 'ydstogo', 'yardline_100', 'receiver_position', 'rusher_position',
               'passer_position', 'qb_position', 'qb_id')
    con = sqlite3.connect(f'file:{db}?mode=ro', uri=True, timeout=10)
    try:
        rows = con.execute(
            "SELECT p.season,p.game_id,p.play_id,p.posteam,p.passer_player_id,p.rusher_player_id,"
            "p.receiver_player_id,p.qb_dropback,p.qb_scramble,p.pass_attempt,p.rush_attempt,p.complete_pass,"
            "p.sack,p.interception,p.fumble_lost,p.yards_gained,p.passing_yards,p.receiving_yards,p.rushing_yards,"
            "p.pass_touchdown,p.touchdown,p.rush_touchdown,p.down,p.ydstogo,p.yardline_100,r.position,s.position,q.position,"
            "CASE WHEN q.position='QB' OR (p.qb_scramble=1 AND s.position='QB') THEN 'QB' ELSE COALESCE(q.position,s.position) END,"
            "COALESCE(CASE WHEN q.position='QB' THEN p.passer_player_id END,"
            "CASE WHEN p.qb_scramble=1 AND s.position='QB' THEN p.rusher_player_id END) "
            "FROM nfl_pbp p LEFT JOIN (SELECT nfl_gsis_id, MIN(position) AS position FROM players "
            "WHERE lower(league)='nfl' GROUP BY nfl_gsis_id) r ON r.nfl_gsis_id=p.receiver_player_id "
            "LEFT JOIN (SELECT nfl_gsis_id, MIN(position) AS position FROM players "
            "WHERE lower(league)='nfl' GROUP BY nfl_gsis_id) s ON s.nfl_gsis_id=p.rusher_player_id "
            "LEFT JOIN (SELECT nfl_gsis_id, MIN(position) AS position FROM players "
            "WHERE lower(league)='nfl' GROUP BY nfl_gsis_id) q ON q.nfl_gsis_id=p.passer_player_id "
            "WHERE p.season=? AND p.week BETWEEN 1 AND 18 ORDER BY p.game_id,p.play_id", (int(season),)
        ).fetchall()
    finally:
        con.close()
    return [dict(zip(columns, row)) for row in rows]


def _score_data(db):
    qb_table = qbd.load(db, FIT_CUTOFF)
    outcome_table = po.load(db, FIT_CUTOFF)
    rows = _holdout_rows(db)
    if not rows:
        raise ValueError(f'no rows found for holdout season {HOLDOUT_SEASON}')
    holdout_sha = hashlib.sha256(json.dumps(rows, sort_keys=True, separators=(',', ':')).encode()).hexdigest()

    # Restrict player outcome validation to rows the SLC E1 adapter could actually sample in its held-out season.
    con = sqlite3.connect(f'file:{db}?mode=ro', uri=True, timeout=10)
    try:
        e1_rows = [dict(zip(e1.COLUMNS, row)) for row in con.execute(
            f"SELECT {', '.join(e1.COLUMNS)} FROM nfl_pbp WHERE season=? AND week BETWEEN 1 AND 18 ORDER BY game_id,play_id",
            (HOLDOUT_SEASON,))]
    finally:
        con.close()
    eligible_pool, eligible_excluded = e1.build_pool(e1_rows, include_qb_scrambles=True)
    eligible_keys = {(row['game_id'], int(row['play_id']))
                     for cell in eligible_pool.values() for _event, row, _runoff, _spot in cell}

    scores = defaultdict(list)
    qbd_counts = Counter()
    for row in rows:
        team, qb = row['posteam'], row['qb_id']
        if (not team or not qb or row['qb_position'] != 'QB' or row['down'] is None
                or row['ydstogo'] is None or row['yardline_100'] is None):
            continue
        cell = qbd.cell_of(row['down'], row['ydstogo'], row['yardline_100'])
        if row['qb_dropback'] == 1:
            actual = 'scramble' if row['qb_scramble'] == 1 else 'pass'
            p_model, own_n = qbd._scramble_probability(qb_table, team, qb, cell)
            p_team, _ = qbd._scramble_probability(qb_table, team, None, cell)
            categories = ('pass', 'scramble')
            scores['qb_action'].append({
                'game_id': row['game_id'], 'player_id': qb, 'actual': actual, 'history': own_n > 0,
                'baseline': {'pass': 1 - p_team, 'scramble': p_team},
                'model': {'pass': 1 - p_model, 'scramble': p_model},
            })
            qbd_counts['dropbacks'] += 1
            qbd_counts['dropbacks_with_qb_history'] += int(own_n > 0)

        if row['pass_attempt'] == 1 and row['receiver_player_id']:
            receiver = row['receiver_player_id']
            actual_role = qbd.target_role(row['receiver_position'])
            model_dist, own_n = qbd._target_distribution(qb_table, team, qb, cell)
            team_dist, _ = qbd._target_distribution(qb_table, team, None, cell)
            categories = qbd.TARGET_ROLES
            scores['qb_target_role'].append({
                'game_id': row['game_id'], 'player_id': qb, 'actual': actual_role, 'history': own_n > 0,
                'baseline': team_dist, 'model': model_dist,
            })
            qbd_counts['targets_with_receiver_id'] += 1
            qbd_counts['targets_with_qb_target_history'] += int(own_n > 0)

    for row in rows:
        if (row['game_id'], int(row['play_id'])) not in eligible_keys:
            continue
        game = row['game_id']
        candidates = []
        if (row['qb_dropback'] == 1 and row['qb_scramble'] != 1 and row['passer_player_id']
                and row['passer_position'] == 'QB'):
            if row['sack'] == 1:
                candidates.append(('qb', row['passer_player_id'], 'sack', row['yards_gained'], False))
            elif row['interception'] == 1:
                candidates.append(('qb', row['passer_player_id'], 'interception', None, False))
            elif row['pass_attempt'] == 1 and row['complete_pass'] == 1:
                candidates.append(('qb', row['passer_player_id'], 'pass_complete', row['passing_yards'], row['pass_touchdown']))
            elif row['pass_attempt'] == 1 and row['complete_pass'] == 0:
                candidates.append(('qb', row['passer_player_id'], 'pass_incomplete', None, False))
        if row['pass_attempt'] == 1 and row['receiver_player_id']:
            if row['interception'] == 1:
                candidates.append(('receiver', row['receiver_player_id'], 'interception', None, False))
            elif row['complete_pass'] == 1:
                candidates.append(('receiver', row['receiver_player_id'], 'pass_complete', row['receiving_yards'], row['touchdown']))
            elif row['complete_pass'] == 0:
                candidates.append(('receiver', row['receiver_player_id'], 'pass_incomplete', None, False))
        if row['rush_attempt'] == 1 and row['rusher_player_id']:
            event = 'fumble_lost' if row['fumble_lost'] == 1 else 'run'
            candidates.append(('rusher', row['rusher_player_id'], event, row['rushing_yards'], row['rush_touchdown']))

        for role, player, event, yards, touchdown in candidates:
            categories = po.EVENTS[role]
            if event not in categories or not outcome_table['base_events'][role]:
                continue
            base_events = po._base_distribution(outcome_table['base_events'][role], categories)
            player_events = po.event_distribution(outcome_table, role, player)
            scores[f'{role}_event'].append({
                'game_id': game, 'player_id': player, 'actual': event,
                'history': po.support(outcome_table, role, player) > 0,
                'baseline': base_events, 'model': _adjusted(base_events, player_events, categories),
            })
            if yards is None:
                continue
            label = f"{po._yards_bin(yards, role, event)}|td={int(bool(touchdown))}"
            base_results = outcome_table['base_results'][role].get(event, Counter())
            categories = tuple(sorted(base_results))
            if label not in categories:
                continue
            player_results = outcome_table['result_counts'][role].get(player, {}).get(event, Counter())
            n_results = sum(player_results.values())
            base_dist = po._base_distribution(base_results, categories)
            posterior = {category: (player_results.get(category, 0) + po.PRIOR_STRENGTH * base_dist[category]) /
                         (n_results + po.PRIOR_STRENGTH) for category in categories}
            scores[f'{role}_result_{event}'].append({
                'game_id': game, 'player_id': player, 'actual': label,
                'history': n_results > 0,
                'baseline': base_dist, 'model': _adjusted(base_dist, posterior, categories),
            })

    result = {
        'report_version': 'slc-qb-player-outcomes-holdout-v1',
        'created_on': date.today().isoformat(),
        'fit': {'cutoff_season_exclusive': FIT_CUTOFF,
                'source_seasons': list(range(qbd.FIRST_SEASON, FIT_CUTOFF))},
        'holdout': {'season': HOLDOUT_SEASON, 'nfl_pbp_rows': len(rows), 'source_sha256': holdout_sha,
                    'player_outcome_e1_eligible_rows': len(eligible_keys),
                    'e1_exclusions': dict(sorted(eligible_excluded.items()))},
        'models': {
            'qb_decisions': qbd.manifest(qb_table, None),
            'player_outcomes': po.manifest(outcome_table, None),
        },
        'code_sha256': {path.name: hashlib.sha256(path.read_bytes()).hexdigest()
                        for path in (Path(__file__), HERE / 'e1_drive.py', HERE / 'e2_reference.py',
                                     HERE / 'game_state.py', HERE / 'game_stats.py', HERE / 'pre_event.py',
                                     HERE / 'qb_decisions.py', HERE / 'player_outcomes.py',
                                     HERE / 'run_slc_game.py', HERE / 'simulate_pregame_batch.py',
                                     HERE / 'slc_engine.py', HERE / 'slc_playcall.py')},
        'qb_decision_source_counts': dict(qbd_counts),
        'scores': {name: _summary(records, (qbd.TARGET_ROLES if name == 'qb_target_role' else
                                             ('pass', 'scramble') if name == 'qb_action' else
                                             po.EVENTS[name.split('_event')[0]] if name.endswith('_event') else
                                             tuple(sorted(outcome_table['base_results'][name.split('_result_')[0]].get(
                                                 name.split('_result_')[1], Counter())))),
                                   20251000 + index)
                   for index, (name, records) in enumerate(sorted(scores.items()))},
        'interpretation': {
            'positive_improvement': 'the cutoff-safe player/QB model has lower held-out log loss or Brier score than its stated pooled baseline',
            'uncertainty': 'paired percentile bootstrap, resampling whole NFL games with replacement',
            'limits': [
                'QB action and target-role scores cover held-out nfl_pbp dropbacks and identified targets; target roles are not conditioned on a reconstructed frozen injury report.',
                'Player outcome scores use only 2025 rows eligible for the SLC E1 outcome pool and compare marginal player distributions with role-level pooled distributions.',
                'Scores do not reproduce SLC candidate-cell reweighting, the joint passer-receiver weighting, full-game state feedback, or scoring calibration.',
                'QB outcomes cover completions, incompletions, interceptions and sacks; this first slice does not model QB progressions, pressure response, throwaways or defensive adaptation.',
                'Game movement uses yards_gained. Player result distributions and box-score lines use passing_yards, receiving_yards or rushing_yards where present; missing role-specific fields fall back only for emitted box-score lines.',
            ],
        },
    }
    return result


def _markdown(report):
    lines = [
        '# SLC QB and player outcome holdout validation', '',
        f"Fit cutoff: before {report['fit']['cutoff_season_exclusive']} "
        f"({', '.join(map(str, report['fit']['source_seasons']))}); holdout: {report['holdout']['season']}.",
        f"Holdout source rows: {report['holdout']['nfl_pbp_rows']}; E1-eligible player outcome rows: "
        f"{report['holdout']['player_outcome_e1_eligible_rows']}.", '',
        'Positive score improvement favors the player/QB model over the pooled baseline. Intervals resample complete NFL games.', '',
        '| Distribution | Rows | Players | History rows | Log-loss improvement (95% CI) | Brier improvement (95% CI) |',
        '|---|---:|---:|---:|---:|---:|',
    ]
    for name, score in report['scores'].items():
        if not score['n']:
            continue
        ll = score['log_loss_improvement']
        ll_ci = score['log_loss_improvement_game_bootstrap_95']
        br = score['brier_improvement']
        br_ci = score['brier_improvement_game_bootstrap_95']
        lines.append(f"| {name} | {score['n']} | {score['players']} | {score['history_rows']} | "
                     f"{ll:+.5f} [{ll_ci[0]:+.5f}, {ll_ci[1]:+.5f}] | {br:+.5f} [{br_ci[0]:+.5f}, {br_ci[1]:+.5f}] |")
    lines.extend(['', '## Limits', ''])
    lines.extend(f"- {item}" for item in report['interpretation']['limits'])
    lines.extend(['', 'The JSON companion records model versions, source cutoffs, fitted-source hashes, holdout hash, source counts and bootstrap results.', ''])
    return '\n'.join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--db', default=e0.DEFAULT_DB)
    parser.add_argument('--out-json', type=Path, required=True)
    parser.add_argument('--out-md', type=Path, required=True)
    args = parser.parse_args(argv)
    report = _score_data(args.db)
    args.out_json.write_text(json.dumps(report, indent=2, sort_keys=True) + '\n')
    args.out_md.write_text(_markdown(report))
    for name, score in report['scores'].items():
        if score['n']:
            print(f"{name}: n={score['n']} ll_improvement={score['log_loss_improvement']:+.4f} "
                  f"brier_improvement={score['brier_improvement']:+.4f}")
    print(f"wrote {args.out_json} and {args.out_md}")


if __name__ == '__main__':
    main()
