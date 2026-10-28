"""Score frozen historical replay forecasts without mixing exploratory inputs into fair metrics."""
from __future__ import annotations

import math
import random
import argparse
import hashlib
import json
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import holdout  # noqa: E402


MODELS = ('S0', 'S1', 'v1')
PROVENANCE = {'fair', 'exploratory', 'excluded'}


def _utc(value, label):
    if not isinstance(value, str):
        raise ValueError(f'{label} must be a timezone-qualified timestamp')
    try:
        parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
    except ValueError as exc:
        raise ValueError(f'{label} must be a timezone-qualified timestamp') from exc
    if parsed.tzinfo is None:
        raise ValueError(f'{label} must include a timezone')
    return parsed.astimezone(timezone.utc)


def _number(value, label, *, probability=False):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
        raise ValueError(f'{label} must be a finite number')
    value = float(value)
    if probability and not 0 <= value <= 1:
        raise ValueError(f'{label} must be between 0 and 1')
    return value


def forecast_from_batch(payload: dict) -> dict | None:
    """Extract a game-level forecast and seed coverage from a generated batch payload."""
    schedule = (payload.get('pregame_snapshot') or {}).get('schedule') or {}
    if schedule.get('season') is not None:
        holdout.refuse_if_holdout(schedule['season'], 'replay evaluation')
    summary = payload.get('summary') or {}
    distribution = summary.get('valid_full_game_distribution') or {}
    scores = distribution.get('scores') or {}
    wins = distribution.get('win_probability') or {}
    p_home = wins.get('home')
    p_away = wins.get('away')
    probability_total = (p_home or 0) + (p_away or 0)
    if probability_total <= 0:
        p_home = None
    else:
        p_home = float(p_home or 0) / probability_total
    regulation = summary.get('regulation_end_reached_distribution') or {}
    regulation_scores = regulation.get('scores') or {}
    simulation = payload.get('simulation') or {}
    home_points = (scores.get('home') or {}).get('mean')
    away_points = (scores.get('away') or {}).get('mean')
    return {
        'home_points': (_number(home_points, 'simulated home mean') if home_points is not None else None),
        'away_points': (_number(away_points, 'simulated away mean') if away_points is not None else None),
        'home_win_probability': (_number(p_home, 'simulated home-win probability', probability=True)
                                 if p_home is not None else None),
        'valid_games': int(summary.get('valid_full_games', distribution.get('sample_games', 0))),
        'requested_games': int(summary.get('requested_games', simulation.get('requested_games', 0))),
        'blocked_before_regulation_end': int(summary.get('blocked_before_regulation_end', 0)),
        'tied_at_regulation_end': int(summary.get('tied_at_regulation_end', 0)),
        'regulation_end_games': int(summary.get('regulation_end_reached', regulation.get('sample_games', 0))),
        'regulation_home_points': (regulation_scores.get('home') or {}).get('mean'),
        'regulation_away_points': (regulation_scores.get('away') or {}).get('mean'),
        'context_mode': simulation.get('context_mode', 'unconditioned'),
        'reference_sha256': (payload.get('data_sources') or {}).get('observed_reference_sha256'),
    }


def forecast_from_v1(baseline: dict) -> dict | None:
    """Extract an immutable lock at/before cutoff; schedule-uncertain locks remain exploratory."""
    if baseline.get('source') != 'immutable_locked_v1_projection':
        return None
    status = baseline.get('status')
    cutoff_comparable = status == 'available' and baseline.get('comparable_at_snapshot_cutoff') is True
    if status == 'exploratory_schedule_unverified':
        offset = baseline.get('snapshot_cutoff_offset_seconds')
        if offset is None or _number(offset, 'v1 snapshot cutoff offset') > 0:
            return None
    elif not cutoff_comparable:
        return None
    return {
        'home_points': _number(baseline.get('projected_home_points'), 'v1 projected home points'),
        'away_points': _number(baseline.get('projected_away_points'), 'v1 projected away points'),
        'home_win_probability': _number(baseline.get('home_win_probability'), 'v1 home-win probability',
                                        probability=True),
        'run_id': baseline.get('run_id'), 'locked_at': baseline.get('locked_at'),
        'cutoff_comparable': cutoff_comparable,
    }


def classify_provenance(batch: dict) -> dict:
    """Fail closed: a replay is fair only with a clean producer, verified as-of data, schedule and v1 lock."""
    reasons = []
    source = batch.get('source') or {}
    data = batch.get('data_sources') or {}
    availability = data.get('input_availability') or {}
    baseline = batch.get('baseline_v1') or {}
    if not source.get('base_commit') or source.get('producer_worktree_dirty') is not False:
        reasons.append('producer_not_cleanly_committed')
    if availability.get('historical_replay_fairness') != 'fair':
        reasons.append('historical_input_availability_unverified')
    if not data.get('source_snapshot_sha256'):
        reasons.append('source_snapshot_hash_missing')
    if not batch.get('forecast_frozen_at_utc'):
        reasons.append('forecast_freeze_time_missing')
    if (baseline.get('source') != 'immutable_locked_v1_projection'
            or baseline.get('status') != 'available'
            or baseline.get('comparable_at_snapshot_cutoff') is not True):
        reasons.append('v1_lock_not_cutoff_comparable')
    schedule_provenance = baseline.get('schedule_provenance') or {}
    if schedule_provenance.get('verified') is not True:
        reasons.append('schedule_version_unverified')
    return {'status': 'fair' if not reasons else 'exploratory', 'reasons': reasons}


def replay_record(game_id: str, actual: dict, batches: dict[str, dict]) -> dict:
    """Join frozen S0/S1 batch payloads to actuals added after forecasting; keep provenance per model."""
    if not game_id:
        raise ValueError('replay game_id is required')
    home = actual.get('home_points')
    away = actual.get('away_points')
    if isinstance(home, bool) or not isinstance(home, int) or home < 0:
        raise ValueError('actual home points must be a non-negative integer')
    if isinstance(away, bool) or not isinstance(away, int) or away < 0:
        raise ValueError('actual away points must be a non-negative integer')
    if actual.get('attached_after_forecasts_frozen') is not True:
        raise ValueError('actual scores may be attached only after forecasts are frozen')
    attached_at = _utc(actual.get('attached_at_utc'), 'actual attached_at_utc')
    freeze_times = []
    for model in ('S0', 'S1'):
        batch = batches.get(model)
        if batch:
            freeze_times.append(_utc(batch.get('forecast_frozen_at_utc'), f'{model} forecast_frozen_at_utc'))
    if batches.get('v1') and batches.get('v1') not in (batches.get('S0'), batches.get('S1')):
        freeze_times.append(_utc(batches['v1'].get('forecast_frozen_at_utc'), 'v1 forecast_frozen_at_utc'))
    if not freeze_times:
        raise ValueError('at least one frozen forecast batch is required')
    if attached_at <= max(freeze_times):
        raise ValueError('actual score attachment must be later than the frozen forecasts')
    source_sha256 = actual.get('source_sha256')
    if not isinstance(source_sha256, str) or len(source_sha256) != 64:
        raise ValueError('actual score source must have a SHA-256 pin')
    if not actual.get('source'):
        raise ValueError('actual score source is required')
    forecasts = {}
    provenance = {}
    for model in ('S0', 'S1'):
        batch = batches.get(model)
        if batch is None:
            forecasts[model] = None
            provenance[model] = {'status': 'excluded', 'reasons': ['batch_missing']}
            continue
        mode = (batch.get('simulation') or {}).get('context_mode', 'unconditioned')
        if model == 'S0' and mode != 'unconditioned':
            raise ValueError('S0 must use the legacy unconditioned reference')
        if model == 'S1' and mode not in ('offense', 'defense', 'both'):
            raise ValueError('S1 must use an offense and/or defense contextual mode')
        forecasts[model] = forecast_from_batch(batch)
        provenance[model] = classify_provenance(batch)
    v1_payload = batches.get('v1') or batches.get('S0') or batches.get('S1')
    baseline = (v1_payload or {}).get('baseline_v1') or {}
    forecasts['v1'] = forecast_from_v1(baseline)
    provenance['v1'] = classify_provenance(v1_payload) if v1_payload else {
        'status': 'excluded', 'reasons': ['v1_source_batch_missing']}
    if forecasts['v1'] is None and 'v1_lock_not_cutoff_comparable' not in provenance['v1']['reasons']:
        provenance['v1']['reasons'].append('v1_projection_missing')
    statuses = [provenance[model]['status'] for model in MODELS]
    status = ('excluded' if any(value == 'excluded' for value in statuses)
              else 'fair' if all(value == 'fair' for value in statuses) else 'exploratory')
    return {
        'game_id': game_id,
        'comparison_status': status,
        'exclusion_reason': ([f'{model}:{reason}' for model in MODELS
                             for reason in provenance[model]['reasons']]
                            if status == 'excluded' else None),
        'actual': {'home_points': home, 'away_points': away,
                   'source': actual['source'], 'source_sha256': source_sha256,
                   'attached_at_utc': actual['attached_at_utc']},
        'forecasts': forecasts,
        'model_provenance': provenance,
    }


def _wilson(successes: int, trials: int, z=1.959963984540054):
    if trials <= 0:
        return None
    p = successes / trials
    denominator = 1 + z * z / trials
    center = (p + z * z / (2 * trials)) / denominator
    radius = z * math.sqrt(p * (1 - p) / trials + z * z / (4 * trials * trials)) / denominator
    return [round(max(0.0, center - radius), 6), round(min(1.0, center + radius), 6)]


def _quantile(values, probability):
    if not values:
        return None
    ordered = sorted(values)
    index = (len(ordered) - 1) * probability
    low, high = math.floor(index), math.ceil(index)
    if low == high:
        return ordered[low]
    return ordered[low] + (ordered[high] - ordered[low]) * (index - low)


def _metrics(rows):
    if not rows:
        return {'games': 0, 'team_score_mae': None, 'team_score_rmse': None,
                'margin_mae': None, 'margin_rmse': None, 'total_mae': None, 'total_rmse': None,
                'winner_brier': None, 'winner_log_loss': None, 'calibration': []}
    home_errors, away_errors, margin_errors, total_errors = [], [], [], []
    probability_rows = []
    for row in rows:
        actual = row['actual']
        forecast = row['forecast']
        ah, aa = actual['home_points'], actual['away_points']
        fh, fa = forecast['home_points'], forecast['away_points']
        home_errors.append(fh - ah)
        away_errors.append(fa - aa)
        margin_errors.append((fh - fa) - (ah - aa))
        total_errors.append((fh + fa) - (ah + aa))
        p_home = forecast.get('home_win_probability')
        if p_home is not None and ah != aa:
            probability_rows.append((p_home, int(ah > aa)))

    team_sq = home_errors + away_errors
    margin_sq = margin_errors
    total_sq = total_errors
    brier, logloss = None, None
    calibration = []
    ece = None
    if probability_rows:
        epsilon = 1e-15
        brier = sum((p - y) ** 2 for p, y in probability_rows) / len(probability_rows)
        logloss = -sum(y * math.log(max(epsilon, min(1 - epsilon, p)))
                       + (1 - y) * math.log(max(epsilon, min(1 - epsilon, 1 - p)))
                       for p, y in probability_rows) / len(probability_rows)
        gaps = []
        for index in range(10):
            bucket = [(p, y) for p, y in probability_rows
                      if index / 10 <= p < (index + 1) / 10 or (index == 9 and p == 1)]
            if not bucket:
                continue
            predicted = sum(p for p, _ in bucket) / len(bucket)
            observed = sum(y for _, y in bucket) / len(bucket)
            gaps.append(len(bucket) * abs(predicted - observed))
            calibration.append({'bin': [index / 10, (index + 1) / 10], 'games': len(bucket),
                                'mean_probability': round(predicted, 6),
                                'home_win_rate': round(observed, 6),
                                'home_win_rate_ci95': _wilson(sum(y for _, y in bucket), len(bucket))})
        ece = sum(gaps) / len(probability_rows)

    out = {
        'games': len(rows),
        'team_score_mae': sum(abs(value) for value in team_sq) / len(team_sq),
        'team_score_rmse': math.sqrt(sum(value * value for value in team_sq) / len(team_sq)),
        'margin_mae': sum(abs(value) for value in margin_sq) / len(margin_sq),
        'margin_rmse': math.sqrt(sum(value * value for value in margin_sq) / len(margin_sq)),
        'total_mae': sum(abs(value) for value in total_sq) / len(total_sq),
        'total_rmse': math.sqrt(sum(value * value for value in total_sq) / len(total_sq)),
        'winner_games': len(probability_rows),
        'actual_ties_excluded_from_winner_scores': len(rows) - len(probability_rows),
        'winner_brier': brier, 'winner_log_loss': logloss,
        'calibration_expected_error': ece, 'calibration': calibration,
    }
    for key, value in list(out.items()):
        if isinstance(value, float):
            out[key] = round(value, 6)
    return out


def _bootstrap_ci(rows, resamples, seed):
    if len(rows) < 2 or resamples <= 0:
        return {}
    rng = random.Random(seed)
    metrics = defaultdict(list)
    for _ in range(resamples):
        sample = [rng.choice(rows) for _ in rows]
        for key, value in _metrics(sample).items():
            if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value):
                metrics[key].append(float(value))
    return {key: [round(_quantile(values, 0.025), 6), round(_quantile(values, 0.975), 6)]
            for key, values in sorted(metrics.items()) if len(values) >= max(1, resamples // 2)}


def _model_report(group, model, resamples, seed):
    available = [(row, row.get('forecasts', {}).get(model)) for row in group
                 if row.get('forecasts', {}).get(model) is not None]
    scored = [(row, forecast) for row, forecast in available
              if forecast.get('home_points') is not None and forecast.get('away_points') is not None]
    shaped = [{'game_id': row['game_id'], 'actual': row['actual'], 'forecast': forecast}
              for row, forecast in scored]
    metric = _metrics(shaped)
    metric['bootstrap_ci95_by_game'] = _bootstrap_ci(shaped, resamples, seed)
    has_seed_coverage = any('requested_games' in forecast or 'valid_games' in forecast
                            for _, forecast in available)
    valid = sum(int(forecast.get('valid_games', 0)) for _, forecast in available)
    requested = sum(int(forecast.get('requested_games', 0)) for _, forecast in available)
    coverage_ci = _wilson(valid, requested) if has_seed_coverage else None
    selection = []
    for _, forecast in available:
        valid_home = forecast.get('home_points')
        valid_away = forecast.get('away_points')
        reg_home = forecast.get('regulation_home_points')
        reg_away = forecast.get('regulation_away_points')
        if all(value is not None for value in (valid_home, valid_away, reg_home, reg_away)):
            selection.append({'home': float(valid_home) - float(reg_home),
                              'away': float(valid_away) - float(reg_away),
                              'total': (float(valid_home) + float(valid_away))
                                        - (float(reg_home) + float(reg_away))})
    metric.update({
        'available_game_ids': [row['game_id'] for row, _ in available],
        'missing_game_ids': [row['game_id'] for row in group if row.get('forecasts', {}).get(model) is None],
        'no_valid_score_forecast_game_ids': [row['game_id'] for row, forecast in available
                                             if forecast.get('home_points') is None
                                             or forecast.get('away_points') is None],
        'valid_seed_coverage': ({'valid': valid, 'requested': requested,
                                 'rate': valid / requested if requested else None,
                                 'wilson_ci95': coverage_ci} if has_seed_coverage else None),
        'blockers': ({'before_regulation_end': sum(int(f.get('blocked_before_regulation_end', 0))
                                                    for _, f in available),
                      'regulation_ties': sum(int(f.get('tied_at_regulation_end', 0))
                                             for _, f in available)} if has_seed_coverage else None),
        'valid_minus_regulation_end_means': ({
            key: round(sum(item[key] for item in selection) / len(selection), 6)
            for key in ('home', 'away', 'total')
        } if selection else None),
    })
    return metric


def _group_report(group, models, resamples, seed):
    reports = {}
    for index, model in enumerate(models):
        reports[model] = _model_report(group, model, resamples, seed + index)
    common_ids = [row['game_id'] for row in group
                  if all(row.get('forecasts', {}).get(model) is not None
                         and row['forecasts'][model].get('home_points') is not None
                         and row['forecasts'][model].get('away_points') is not None
                         for model in models)]
    paired = {}
    common = [row for row in group if row['game_id'] in set(common_ids)]
    for index, model in enumerate(models):
        paired[model] = _model_report(common, model, resamples, seed + 100 + index)
    return {'candidate_games': len(group), 'common_game_ids': common_ids,
            'models': reports, 'paired_models': paired}


def evaluate_replays(rows, models=MODELS, bootstrap_resamples=1000, seed=20261026):
    """Report fair and exploratory cohorts separately, retaining all provenance exclusions."""
    seen = set()
    for row in rows:
        game_id = row.get('game_id')
        if not game_id or game_id in seen:
            raise ValueError('replay rows need unique game ids')
        seen.add(game_id)
        if row.get('comparison_status') not in PROVENANCE:
            raise ValueError(f'{game_id}: comparison_status must be one of {sorted(PROVENANCE)}')
        actual = row.get('actual') or {}
        for key in ('home_points', 'away_points'):
            value = actual.get(key)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError(f'{game_id}: actual {key} must be a non-negative integer')
        for model in models:
            forecast = (row.get('forecasts') or {}).get(model)
            if forecast is None:
                continue
            if forecast.get('home_points') is None and forecast.get('away_points') is None:
                continue
            if forecast.get('home_points') is None or forecast.get('away_points') is None:
                raise ValueError(f'{game_id} {model} has only one team score forecast')
            _number(forecast.get('home_points'), f'{game_id} {model} home points')
            _number(forecast.get('away_points'), f'{game_id} {model} away points')
            if forecast.get('home_win_probability') is not None:
                _number(forecast['home_win_probability'], f'{game_id} {model} home-win probability',
                        probability=True)
    fair = [row for row in rows if row['comparison_status'] == 'fair']
    exploratory = [row for row in rows if row['comparison_status'] == 'exploratory']
    excluded = [{'game_id': row['game_id'], 'reason': row.get('exclusion_reason', 'provenance_not_fair')}
                for row in rows if row['comparison_status'] == 'excluded']
    return {
        'candidate_games': len(rows), 'fair_game_count': len(fair),
        'exploratory_game_count': len(exploratory), 'excluded_games': excluded,
        'per_game': [{'game_id': row['game_id'], 'comparison_status': row['comparison_status'],
                      'actual': row['actual'], 'forecasts': row.get('forecasts', {}),
                      'exclusion_reason': row.get('exclusion_reason'),
                      'model_provenance': row.get('model_provenance', {})} for row in rows],
        'fair': _group_report(fair, models, bootstrap_resamples, seed),
        'exploratory_diagnostic_only': _group_report(exploratory, models, bootstrap_resamples, seed + 1000),
    }


def build_replay_report(bundle: dict, *, bootstrap_resamples=1000, seed=20261026,
                        input_sha256=None, evaluator_sha256=None):
    """Build a reproducible report from forecast batches and post-freeze actuals."""
    if (bundle.get('schema') != 'gridiron.lp-historical-replay-inputs'
            or bundle.get('version') != 1):
        raise ValueError('unsupported historical replay input bundle schema/version')
    entries = bundle.get('replays')
    if not isinstance(entries, list):
        raise ValueError('historical replay bundle must contain a replays list')
    rows = [replay_record(entry.get('game_id'), entry.get('actual') or {},
                          entry.get('batches') or {}) for entry in entries]
    report = evaluate_replays(rows, bootstrap_resamples=bootstrap_resamples, seed=seed)
    report['experiment'] = {
        'input_manifest_sha256': input_sha256,
        'evaluator_source_sha256': evaluator_sha256,
        'bootstrap_resamples': bootstrap_resamples,
        'bootstrap_seed': seed,
    }
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', required=True, help='JSON replay-input bundle with frozen batches and actuals')
    parser.add_argument('--out', required=True, help='JSON evaluation report output path')
    parser.add_argument('--bootstrap-resamples', type=int, default=1000)
    parser.add_argument('--seed', type=int, default=20261026)
    args = parser.parse_args(argv)
    if args.bootstrap_resamples < 0:
        parser.error('--bootstrap-resamples must be non-negative')
    input_path = Path(args.input)
    source_bytes = input_path.read_bytes()
    bundle = json.loads(source_bytes)
    evaluator_bytes = Path(__file__).read_bytes()
    report = build_replay_report(
        bundle,
        bootstrap_resamples=args.bootstrap_resamples,
        seed=args.seed,
        input_sha256=hashlib.sha256(source_bytes).hexdigest(),
        evaluator_sha256=hashlib.sha256(evaluator_bytes).hexdigest(),
    )
    Path(args.out).write_text(json.dumps(report, indent=2, sort_keys=True) + '\n')


if __name__ == '__main__':
    main()
