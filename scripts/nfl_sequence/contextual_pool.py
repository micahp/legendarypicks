"""Matchup-weighted sampling over the cutoff-eligible historical E1 play pool.

S0 keeps the original uniform empirical pool. The S1 ablations reweight observed
plays by how similar the source game's pregame offense rating and/or opposing
defense rating were to the target matchup. A selected play keeps its recorded NFL
outcome and still passes through the shared reducer.
"""
from __future__ import annotations

import hashlib
import json
import math
import sqlite3
import sys
from collections import defaultdict
from pathlib import Path
from statistics import pstdev

sys.path.insert(0, str(Path(__file__).resolve().parent))
import holdout  # noqa: E402

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import e1_drive as e1  # noqa: E402
import pregame_context as pc  # noqa: E402

sys.path.insert(0, str(HERE.parents[1] / 'backend'))

RATING_CONFIG = pc.RATING_CONFIG
METHOD = 'gaussian_kernel_over_cutoff_safe_v1_offense_and_defense_points_ratings'
MIN_EFFECTIVE_SOURCE_GAMES = 10.0


def _canonical_sha(value) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()
    return hashlib.sha256(raw).hexdigest()


def _rating_rows(source_ratings: dict) -> list[tuple]:
    return [(season, week, team, round(float(values['offense']), 10), round(float(values['defense']), 10))
            for (season, week, team), values in sorted(source_ratings.items())]


def build_source_ratings(con: sqlite3.Connection, rows: list[dict], ratings_backend=None):
    """Fit LP v1 opponent-adjusted team ratings before each historical pool week.

    Every source play is tagged with ratings fit on games from earlier weeks only.
    The target game week is excluded from `rows` by e1.load(eligible_before=...).
    """
    if ratings_backend is None:
        import nfl_ratings_data as ratings_backend  # noqa: E402
    if any(r.get('season') is None or r.get('week') is None or not r.get('posteam') or not r.get('defteam')
           for r in rows):
        raise ValueError('eligible contextual play rows must have season, week, posteam, and defteam')
    if not rows:
        raise ValueError('eligible contextual play pool is empty at this cutoff')
    periods = sorted({(int(r['season']), int(r['week'])) for r in rows})
    for season, _week in periods:
        holdout.refuse_if_holdout(season, 'contextual pool')
    source_ratings = {}
    rating_kwargs = {k: v for k, v in RATING_CONFIG.items() if k != 'prior_shrink'}
    priors = {}
    teams_by_season = {}
    for season, week in periods:
        if season not in priors:
            prior_missing = con.execute(
                """SELECT game_id FROM nfl_schedule
                    WHERE season=? AND game_type='REG' AND (home_score IS NULL OR away_score IS NULL)
                    ORDER BY game_id LIMIT 5""", (season - 1,)).fetchall()
            if prior_missing:
                raise ValueError(f'prior season {season - 1} has unscored rows; cannot fit source-game strengths')
            priors[season] = ratings_backend.prior_for_season(
                con, season, shrink=RATING_CONFIG['prior_shrink'], **rating_kwargs)
            teams_by_season[season] = set(ratings_backend.teams_in_season(con, season))
        prior = priors[season]
        if week == 1:
            fitted = prior
        else:
            missing = con.execute(
                """SELECT game_id FROM nfl_schedule
                    WHERE season=? AND game_type='REG' AND week<?
                      AND (home_score IS NULL OR away_score IS NULL)
                    ORDER BY game_id LIMIT 5""", (season, week)).fetchall()
            if missing:
                raise ValueError(f'{len(missing)} prior-week games in {season} lack final scores: '
                                 + ', '.join(r[0] for r in missing))
            fit, _games_used = ratings_backend.fit_for_week(
                con, season, week, prior=prior, **rating_kwargs)
            fitted = {team: (fit.o[team], fit.d[team]) for team in fit.o}
        for team in teams_by_season[season]:
            offense, defense = fitted.get(team, (0.0, 0.0))
            source_ratings[(season, week, team)] = {'offense': float(offense), 'defense': float(defense)}
    manifest = {
        'model': 'nfl-v1-opponent-adjusted-points',
        'configuration': RATING_CONFIG,
        'source_periods': len(periods),
        'source_team_week_ratings': len(source_ratings),
        'source_ratings_sha256': _canonical_sha(_rating_rows(source_ratings)),
        'weeks_are_exclusive': 'each week is fit using prior seasons and same-season weeks strictly before it',
    }
    return source_ratings, manifest


class ContextualSampler:
    """Sample an observed play with a Gaussian weight on one or both team ratings."""

    MODES = ('offense', 'defense', 'both')

    def __init__(self, source_ratings: dict, target_context: dict, mode='both', bandwidth=1.0,
                 min_effective_games=MIN_EFFECTIVE_SOURCE_GAMES):
        if mode not in self.MODES:
            raise ValueError(f'unknown contextual mode {mode!r}')
        if not math.isfinite(bandwidth) or bandwidth <= 0:
            raise ValueError('context bandwidth must be a positive finite number')
        if not math.isfinite(min_effective_games) or min_effective_games <= 0:
            raise ValueError('minimum effective source-game count must be positive and finite')
        self.source_ratings = source_ratings
        self.mode = mode
        self.bandwidth = float(bandwidth)
        self.min_effective_games = float(min_effective_games)
        self.target_context_sha256 = target_context.get('context_sha256')
        home = target_context['teams']['home']['opponent_adjusted']
        away = target_context['teams']['away']['opponent_adjusted']
        ratings = {
            'A': (home.get('offense_points_rating'), away.get('defense_strength_points_rating')),
            'B': (away.get('offense_points_rating'), home.get('defense_strength_points_rating')),
        }
        for side, pair in ratings.items():
            if any(value is None or not math.isfinite(float(value)) for value in pair):
                raise ValueError(f'target {side} matchup has missing/nonfinite opponent-adjusted ratings')
        self.targets = ratings
        offense_values = [v['offense'] for v in source_ratings.values()]
        defense_values = [v['defense'] for v in source_ratings.values()]
        self.scales = {'offense': pstdev(offense_values) if len(offense_values) > 1 else 0.0,
                       'defense': pstdev(defense_values) if len(defense_values) > 1 else 0.0}
        active = ('offense', 'defense') if mode == 'both' else (mode,)
        if any(self.scales[name] <= 0 for name in active):
            raise ValueError(f'context source ratings have no variation in active dimension(s): {active}')
        self._cache = {}

    def _weights(self, cell, offense, defense):
        cache_key = (id(cell), offense, defense)
        cached = self._cache.get(cache_key)
        if cached is not None:
            return cached
        target_o, target_d = self.targets[offense]
        weights = []
        by_game = defaultdict(float)
        for sample in cell:
            event, row, _runoff, _spot = sample
            key_o = (int(row['season']), int(row['week']), row['posteam'])
            key_d = (int(row['season']), int(row['week']), row['defteam'])
            source_o = self.source_ratings.get(key_o)
            source_d = self.source_ratings.get(key_d)
            if source_o is None or source_d is None:
                raise ValueError(f'historical source ratings missing for {row.get("game_id")}:{row.get("play_id")}')
            distance_sq = 0.0
            if self.mode in ('offense', 'both'):
                distance_sq += ((source_o['offense'] - target_o) / self.scales['offense'] / self.bandwidth) ** 2
            if self.mode in ('defense', 'both'):
                distance_sq += ((source_d['defense'] - target_d) / self.scales['defense'] / self.bandwidth) ** 2
            weight = math.exp(-0.5 * distance_sq)
            weights.append((sample, weight))
            by_game[row['game_id']] += weight
        total = sum(by_game.values())
        square_total = sum(weight * weight for weight in by_game.values())
        effective_games = total * total / square_total if square_total else 0.0
        if effective_games < self.min_effective_games:
            raise e1.SamplingUnavailable(
                f'contextual_pool_low_effective_games:{effective_games:.2f}<'
                f'{self.min_effective_games:g}:{offense}:{defense}')
        result = (weights, effective_games)
        self._cache[cache_key] = result
        return result

    def sample(self, rng, cell, offense, defense):
        weighted, _effective_games = self._weights(cell, offense, defense)
        event_weights = defaultdict(float)
        for sample, weight in weighted:
            event_weights[sample[0]] += weight
        events = [event for event in e1.EVENTS if event_weights[event] > 0]
        if not events:
            raise e1.SamplingUnavailable(f'contextual_pool_has_no_supported_events:{offense}:{defense}')
        selected_event = rng.choices(events, weights=[event_weights[event] for event in events])[0]
        candidates = [(sample, weight) for sample, weight in weighted if sample[0] == selected_event and weight > 0]
        chosen = rng.choices([sample for sample, _ in candidates], weights=[weight for _, weight in candidates])[0]
        return chosen

    def describe(self):
        return {'method': METHOD, 'mode': self.mode, 'bandwidth_in_source_rating_sd': self.bandwidth,
                'minimum_effective_source_games': self.min_effective_games,
                'source_rating_scales': {name: round(value, 10) for name, value in self.scales.items()},
                'target_context_sha256': self.target_context_sha256,
                'source_ratings_sha256': _canonical_sha(_rating_rows(self.source_ratings))}


def build(db: str, rows: list[dict], target_context: dict, mode='both', bandwidth=1.0,
          min_effective_games=MIN_EFFECTIVE_SOURCE_GAMES, ratings_backend=None):
    """Build a frozen contextual sampler and its source-data manifest for one batch."""
    con = sqlite3.connect(f'file:{db}?mode=ro', uri=True, timeout=30)
    try:
        source_ratings, source_manifest = build_source_ratings(con, rows, ratings_backend=ratings_backend)
    finally:
        con.close()
    missing_ratings = []
    for row in rows:
        for team in (row['posteam'], row['defteam']):
            if (int(row['season']), int(row['week']), team) not in source_ratings:
                missing_ratings.append((row['game_id'], row['play_id'], team))
                if len(missing_ratings) == 5:
                    break
        if len(missing_ratings) == 5:
            break
    if missing_ratings:
        raise ValueError(f'eligible pool plays lack a pregame team rating: {missing_ratings}')
    sampler = ContextualSampler(source_ratings, target_context, mode=mode, bandwidth=bandwidth,
                                min_effective_games=min_effective_games)
    pool_manifest = {
        'method': METHOD,
        'eligible_pool_samples': len(rows),
        'eligible_play_sha256': _canonical_sha([
            [r.get('game_id'), r.get('play_id'), r.get('season'), r.get('week'), r.get('posteam'), r.get('defteam')]
            for r in rows]),
        'source_rating_fit': source_manifest,
        'sampler': sampler.describe(),
        'special_teams_reference_window': 'pinned 2022-2025 outcomes and rates',
        'same_week_excluded': True,
        'failed_support_policy': 'block the seed with a named contextual_pool_low_effective_games outcome',
    }
    pool_manifest['sha256'] = _canonical_sha(pool_manifest)
    return sampler, pool_manifest
