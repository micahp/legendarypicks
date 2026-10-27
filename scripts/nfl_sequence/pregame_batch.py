"""Pure aggregation helpers for deterministic batches of frozen-snapshot NFL games."""
from __future__ import annotations

from collections import Counter
import math


def _round(value):
    if value is None:
        return None
    rounded = round(float(value), 4)
    return 0.0 if rounded == 0 else rounded


def _percentile(values, probability):
    if not values:
        return None
    ordered = sorted(float(value) for value in values)
    index = (len(ordered) - 1) * probability
    lower = math.floor(index)
    upper = math.ceil(index)
    if lower == upper:
        return ordered[lower]
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (index - lower)


def _interval(values):
    if not values:
        return {'mean': None, 'p10': None, 'median': None, 'p90': None}
    return {
        'mean': _round(sum(values) / len(values)),
        'p10': _round(_percentile(values, 0.10)),
        'median': _round(_percentile(values, 0.50)),
        'p90': _round(_percentile(values, 0.90)),
    }


def _distribution(outcomes, home_market_margin=None, market_total=None):
    rows = [row for row in outcomes
            if isinstance(row.get('home_points'), int) and isinstance(row.get('away_points'), int)]
    if not rows:
        return {'sample_games': 0, 'scores': None, 'home_minus_away': None, 'total': None,
                'win_probability': None, 'most_frequent_exact_score': None,
                'market_settlement': None}

    home = [row['home_points'] for row in rows]
    away = [row['away_points'] for row in rows]
    margins = [h - a for h, a in zip(home, away)]
    totals = [h + a for h, a in zip(home, away)]
    home_wins = sum(margin > 0 for margin in margins)
    away_wins = sum(margin < 0 for margin in margins)
    ties = len(margins) - home_wins - away_wins
    score_counts = Counter(zip(home, away))
    modal_score, modal_count = min(score_counts.items(), key=lambda item: (-item[1], item[0]))
    market = None
    if home_market_margin is not None or market_total is not None:
        market = {'home_margin_line': home_market_margin, 'total_line': market_total,
                  'sample_games': len(rows)}
        if home_market_margin is not None:
            home_covers = sum(margin > home_market_margin for margin in margins)
            away_covers = sum(margin < home_market_margin for margin in margins)
            pushes = len(margins) - home_covers - away_covers
            market['home_cover_probability'] = _round(home_covers / len(rows))
            market['away_cover_probability'] = _round(away_covers / len(rows))
            market['spread_push_probability'] = _round(pushes / len(rows))
        if market_total is not None:
            overs = sum(total > market_total for total in totals)
            unders = sum(total < market_total for total in totals)
            pushes = len(totals) - overs - unders
            market['over_probability'] = _round(overs / len(rows))
            market['under_probability'] = _round(unders / len(rows))
            market['total_push_probability'] = _round(pushes / len(rows))
    return {
        'sample_games': len(rows),
        'scores': {'home': _interval(home), 'away': _interval(away)},
        'home_minus_away': _interval(margins),
        'total': _interval(totals),
        'win_probability': {
            'home': _round(home_wins / len(rows)), 'away': _round(away_wins / len(rows)),
            'tie': _round(ties / len(rows)), 'home_wins': home_wins,
            'away_wins': away_wins, 'ties': ties,
        },
        'most_frequent_exact_score': {
            'home': modal_score[0], 'away': modal_score[1], 'count': modal_count,
            'probability': _round(modal_count / len(rows)),
        },
        'market_settlement': market,
    }


def summarize_outcomes(outcomes, requested, home_market_margin=None, market_total=None):
    """Retain all attempted seeds and separately summarize legally complete and regulation-end samples."""
    if requested < 1 or len(outcomes) != requested:
        raise ValueError(f'expected {requested} explicit seed outcomes, received {len(outcomes)}')
    seeds = [row.get('seed') for row in outcomes]
    if any(not isinstance(seed, int) for seed in seeds) or len(set(seeds)) != len(seeds):
        raise ValueError('every requested simulation must have one unique integer seed outcome')

    complete = [row for row in outcomes if row.get('valid_full_game') and row.get('complete_game')
                and not row.get('tied_at_regulation_end')]
    regulation_end = [row for row in outcomes if row.get('regulation_end_reached')]
    statuses = Counter(row.get('status') or 'unknown' for row in outcomes)
    blockers = Counter(row['blocker'] for row in outcomes if row.get('blocker'))
    failures = sum(row.get('status') in ('simulation_error', 'validation_error') for row in outcomes)
    tied = sum(bool(row.get('tied_at_regulation_end')) for row in outcomes)
    blocked = sum(bool(row.get('blocker')) and not row.get('regulation_end_reached') for row in outcomes)
    guarded_at_end = sum(row.get('status') == 'regulation_end_guarded' for row in outcomes)

    return {
        'requested_games': requested,
        'valid_full_games': len(complete),
        'valid_full_game_coverage': _round(len(complete) / requested),
        'regulation_end_reached': len(regulation_end),
        'tied_at_regulation_end': tied,
        'blocked_before_regulation_end': blocked,
        'regulation_end_guarded': guarded_at_end,
        'simulation_or_validation_errors': failures,
        'status_counts': dict(sorted(statuses.items())),
        'blocker_counts': dict(sorted(blockers.items())),
        'valid_full_game_distribution': _distribution(complete, home_market_margin, market_total),
        'regulation_end_reached_distribution': _distribution(regulation_end, home_market_margin, market_total),
        'outcomes': outcomes,
    }
