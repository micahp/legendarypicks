#!/usr/bin/env python3
"""Run reproducible full-game simulations and report their outcome distribution.

Example:
  python3 scripts/nfl_sequence/simulate_pregame_batch.py \
    --game-id 2026_07_KC_SEA --as-of 2026-10-25T22:44:00Z \
    --kickoff-utc 2026-10-26T00:20:00Z \
    --kickoff-source-url https://www.chiefs.com/news/how-to-watch-and-listen-week-7-chiefs-vs-seahawks \
    --games 10000 --seed-start 1 --out batch.json

All seeds are retained. Score forecasts and win rates use only valid, untied complete games, with that sample size and
coverage reported. A separate regulation-end distribution includes ties and guarded games that reached the clock end;
partial-game points are recorded per seed but never presented as final scores.
"""
from __future__ import annotations

import argparse
import copy
from collections import defaultdict
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sqlite3
import sys
import time

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
BACKEND = REPO / 'backend'
sys.path[:0] = [str(HERE), str(BACKEND)]

import e1_drive as e1  # noqa: E402
import e2_reference as er  # noqa: E402
import game_state as gs  # noqa: E402
import pregame_batch as aggregation  # noqa: E402
import pregame_snapshot  # noqa: E402
import simulate_pregame_game as game_cli  # noqa: E402

SCHEMA = 'lp-statistical-game-batch-1'
PLAYER_CATEGORIES = {
    'passing': ('att', 'comp', 'yds', 'td', 'int', 'sacked', 'sack_yds'),
    'rushing': ('att', 'yds', 'td'),
    'receiving': ('tgt', 'rec', 'yds', 'td'),
    'miscellaneous': ('fumbles_lost',),
}
V1_FILES = ('backend/lock_nfl_week.py', 'backend/nfl_ratings.py', 'backend/nfl_ratings_data.py')
V1_CONFIG = {'half_life': 6.0, 'cap': 14.0, 'prior_games': 4.0, 'sigma': 13.295,
             'prior_shrink': 1.0 / 3.0}


def _canonical_sha(value):
    encoded = json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()
    return hashlib.sha256(encoded).hexdigest()


def _baseline_v1(db, snapshot):
    """Use an immutable pregame v1 lock, or fit v1 on inputs available at the frozen cutoff."""
    schedule = snapshot['schedule']
    season, week = int(schedule['season']), int(schedule['week'])
    cutoff = datetime.fromisoformat(snapshot['as_of'].replace('Z', '+00:00')).astimezone(timezone.utc)
    con = sqlite3.connect(f'file:{db}?mode=ro', uri=True, timeout=30)
    try:
        locked = con.execute(
            "SELECT g.run_id, g.model_version, g.proj_home, g.proj_away, g.proj_margin, g.proj_total, "
            "g.p_home_win, g.locked_at, g.home, g.away, g.season, g.week, r.started_at, r.params_json "
            "FROM game_projections g JOIN model_runs r ON r.run_id=g.run_id "
            "WHERE g.league='nfl' AND g.game_id=? AND g.locked=1 AND r.status='ok' "
            "AND r.model='nfl-ratings-v1' AND g.model_version LIKE 'nfl-v1 %' "
            "ORDER BY g.locked_at DESC LIMIT 1", (schedule['game_id'],)
        ).fetchone()
        row = con.execute(
            "SELECT season, week, home_team, away_team, location, gameday, ingested_at "
            "FROM nfl_schedule WHERE game_id=?", (schedule['game_id'],)
        ).fetchone()
        if row is None:
            raise ValueError('v1 baseline schedule row is missing')
        db_season, db_week, home, away, location, gameday, ingested_at = row
        if (int(db_season), int(db_week), home, away) != (
                season, week, schedule['home_team'], schedule['away_team']):
            raise ValueError('v1 baseline schedule identity disagrees with the frozen snapshot')
        if not ingested_at:
            raise ValueError('v1 baseline schedule provenance has no ingestion timestamp')
        ingested = datetime.fromisoformat(ingested_at.replace('Z', '+00:00'))
        if ingested.tzinfo is None:
            ingested = ingested.replace(tzinfo=timezone.utc)
        if ingested.astimezone(timezone.utc) > cutoff:
            raise ValueError('v1 baseline schedule row was ingested after the frozen cutoff')
        if gameday and datetime.fromisoformat(gameday).date() > cutoff.date():
            raise ValueError('v1 baseline target game date is after the frozen cutoff')

        if locked:
            (run_id, model_version, home_points, away_points, margin, total, p_home, locked_at,
             locked_home, locked_away, locked_season, locked_week, run_started, params_json) = locked
            if (locked_home, locked_away, int(locked_season), int(locked_week)) != (home, away, season, week):
                raise ValueError('stored v1 baseline projection identity disagrees with the frozen snapshot')
            locked_time = datetime.fromisoformat(locked_at.replace('Z', '+00:00'))
            if locked_time.tzinfo is None:
                locked_time = locked_time.replace(tzinfo=timezone.utc)
            kickoff = schedule.get('scheduled_kickoff_utc')
            kickoff_time = datetime.fromisoformat(kickoff.replace('Z', '+00:00')) if kickoff else None
            if kickoff_time is None or locked_time.astimezone(timezone.utc) < kickoff_time.astimezone(timezone.utc):
                cutoff_delta = (locked_time.astimezone(timezone.utc) - cutoff).total_seconds()
                try:
                    params = json.loads(params_json)
                except (TypeError, ValueError):
                    params = {}
                return {
                    'status': 'available', 'source': 'immutable_locked_v1_projection',
                    'model': 'Legendary Picks NFL points model v1', 'model_version': model_version,
                    'run_id': run_id, 'locked_at': locked_at, 'run_started_at': run_started,
                    'snapshot_cutoff_offset_seconds': cutoff_delta,
                    'cutoff_note': ('locked after the frozen snapshot cutoff but before kickoff'
                                    if cutoff_delta > 0 else 'locked by the frozen snapshot cutoff'),
                    'training': {'prior_season': season - 1, 'current_season': season,
                                 'current_season_week_exclusive': week,
                                 'fit_games': params.get('fit_games'), 'as_of': snapshot['as_of']},
                    'projected_home_points': home_points, 'projected_away_points': away_points,
                    'projected_home_minus_away': margin, 'projected_total': total,
                    'home_win_probability': p_home,
                    'win_probability_sigma_points': params.get('sigma', V1_CONFIG['sigma']),
                }

        import nfl_ratings as nr
        import nfl_ratings_data as nrd

        unscored = [game_id for game_id, result in con.execute(
            "SELECT game_id, result FROM nfl_schedule WHERE season=? AND game_type='REG' AND week<? "
            "ORDER BY game_id", (season, week)) if result is None]
        if unscored:
            raise ValueError(f'v1 baseline has {len(unscored)} unscored earlier game(s): {", ".join(unscored[:5])}')
        prior_total, prior_scored, prior_latest = con.execute(
            "SELECT COUNT(*), SUM(home_score IS NOT NULL AND away_score IS NOT NULL), MAX(gameday) "
            "FROM nfl_schedule WHERE season=? AND game_type='REG'", (season - 1,)
        ).fetchone()
        if not prior_total or prior_scored != prior_total:
            raise ValueError(f'v1 baseline prior season {season - 1} is not fully scored')
        if prior_latest and datetime.fromisoformat(prior_latest).date() > cutoff.date():
            raise ValueError('v1 baseline prior season contains games after the frozen cutoff')
        current_latest = con.execute(
            "SELECT MAX(gameday) FROM nfl_schedule WHERE season=? AND game_type='REG' AND week<? "
            "AND home_score IS NOT NULL AND away_score IS NOT NULL", (season, week)
        ).fetchone()[0]
        if current_latest and datetime.fromisoformat(current_latest).date() > cutoff.date():
            raise ValueError('v1 baseline training game date is after the frozen cutoff')

        prior = nrd.prior_for_season(con, season, shrink=V1_CONFIG['prior_shrink'],
                                     half_life=V1_CONFIG['half_life'], cap=V1_CONFIG['cap'],
                                     prior_games=V1_CONFIG['prior_games'])
        fit, games_used = nrd.fit_for_week(con, season, week, prior=prior,
                                           half_life=V1_CONFIG['half_life'], cap=V1_CONFIG['cap'],
                                           prior_games=V1_CONFIG['prior_games'])
        model_version = ('nfl-v1 half_life=6 cap=14 prior_games=4 prior_shrink=%.4f sigma=13.295'
                         % V1_CONFIG['prior_shrink'])
        neutral = (location or '').strip().lower() == 'neutral'
        home_points, away_points = nr.expected_points(fit, home, away, neutral)
        fit_sha = _canonical_sha({'mu': fit.mu, 'h': fit.h, 'offense': fit.o, 'defense': fit.d,
                                  'games_used': games_used})
        baseline = {
            'status': 'available', 'source': 'frozen_v1_fit',
            'model': 'Legendary Picks NFL points model v1',
            'model_version': model_version, 'fit_sha256': fit_sha,
            'training': {'prior_season': season - 1, 'current_season': season,
                         'current_season_week_exclusive': week, 'fit_games': games_used,
                         'as_of': snapshot['as_of']},
            'neutral_site': neutral,
            'projected_home_points': home_points, 'projected_away_points': away_points,
            'projected_home_minus_away': home_points - away_points,
            'projected_total': home_points + away_points,
            'home_win_probability': nr.win_probability(home_points - away_points, V1_CONFIG['sigma']),
            'win_probability_sigma_points': V1_CONFIG['sigma'], 'fit_configuration': V1_CONFIG,
        }
        return baseline
    finally:
        con.close()


def _player_template(snapshot):
    roles_by_player = defaultdict(list)
    for side in ('home', 'away'):
        roster = snapshot['rosters'][side]
        for player in roster['players']:
            player_id = str(player['gsis_id'])
            roles_by_player[(side, player_id)].append(player)
    players = {}
    position_priority = {'QB': 0, 'RB': 1, 'FB': 2, 'WR': 3, 'TE': 4}
    for (side, player_id), roles in roles_by_player.items():
        roster = snapshot['rosters'][side]
        primary = min(roles, key=lambda player: (
            position_priority.get(player['pos_abb'], 5), not player.get('starter', False),
            player['pos_rank'], player['group'],
        ))
        players[player_id] = {
            'player_id': player_id, 'player_name': primary['player_name'],
            'position': primary['pos_abb'], 'team': roster['team'], 'side': side,
            'starter': any(player.get('starter', False) for player in roles),
            'roster_roles': [
                {'group': player['group'], 'position': player['pos_abb'], 'depth_rank': player['pos_rank'],
                 'starter': player['starter']}
                for player in sorted(roles, key=lambda item: (item['group'], item['pos_abb'], item['pos_rank']))
            ],
        }
    return players


def _player_projections(snapshot, totals, games):
    if games < 1:
        return {'sample_games': 0, 'attribution': 'pregame_depth_chart_role_sample', 'players': []}
    rows = []
    metadata = _player_template(snapshot)
    for player_id, total in sorted(totals.items()):
        meta = metadata.get(player_id, {'player_id': player_id})
        row = dict(meta)
        for category, fields in PLAYER_CATEGORIES.items():
            row[category] = {field: round(total.get((category, field), 0) / games, 4) for field in fields}
        row['yards_from_scrimmage'] = round(
            (total.get(('rushing', 'yds'), 0) + total.get(('receiving', 'yds'), 0)) / games, 4)
        rows.append(row)
    return {
        'sample_games': games,
        'attribution': 'pregame_depth_chart_role_sample',
        'note': ('Means include zero production for nonparticipating games. Player results are role allocations from '
                 'sampled historical plays, not player-specific performance projections.'),
        'players': rows,
    }


def _record_outcome(seed, record=None, error=None, validation_error=False):
    if record is None:
        return {'seed': seed, 'status': 'simulation_error', 'blocker': None,
                'valid_full_game': False, 'complete_game': False, 'regulation_end_reached': False,
                'tied_at_regulation_end': False, 'home_points': None, 'away_points': None,
                'score_scope': 'none', 'error': str(error)[:500]}
    blocker = record.get('blocker')
    regulation_end = bool(record.get('regulation_end_reached') or (
        blocker == 'overtime_not_modelled' and record.get('final_quarter') == 4
        and record.get('final_clock_seconds') == 0))
    tied_at_end = bool(record.get('tied') and regulation_end)
    valid = bool(record.get('valid_full_game') and record.get('complete_game') and not validation_error)
    status = 'validation_error' if validation_error else record.get('status', 'unknown')
    return {
        'seed': seed, 'status': status, 'blocker': blocker,
        'valid_full_game': valid, 'complete_game': bool(record.get('complete_game') and not validation_error),
        'regulation_end_reached': regulation_end, 'tied_at_regulation_end': tied_at_end,
        'home_points': record.get('points', {}).get('A'), 'away_points': record.get('points', {}).get('B'),
        'score_scope': 'valid_final' if valid else 'regulation_end_only' if regulation_end else 'partial',
        'unsupported_rules': record.get('unsupported_rules', []),
        'error': str(error)[:500] if error else None,
    }


def _replay_examples(outcomes):
    valid = [row for row in outcomes if row['valid_full_game']]
    if not valid:
        return {}
    mean_margin = sum(row['home_points'] - row['away_points'] for row in valid) / len(valid)
    highest = max(valid, key=lambda row: (row['home_points'] + row['away_points'], -row['seed']))
    lowest = min(valid, key=lambda row: (row['home_points'] + row['away_points'], row['seed']))
    closest = min(valid, key=lambda row: (abs(row['home_points'] - row['away_points'] - mean_margin), row['seed']))
    return {
        'high_total': {'seed': highest['seed'], 'total': highest['home_points'] + highest['away_points']},
        'low_total': {'seed': lowest['seed'], 'total': lowest['home_points'] + lowest['away_points']},
        'closest_to_mean_margin': {'seed': closest['seed'], 'home_minus_away': closest['home_points'] - closest['away_points']},
        'reproduction': 'Run simulate_pregame_game.py with the same snapshot, reference inputs, and listed seed.',
    }


def run_batch(args):
    snapshot = pregame_snapshot.build(args.db, args.game_id, args.as_of, args.kickoff_utc,
                                      args.kickoff_source_url)
    if bool(args.roster_snapshot) != bool(args.roster_provenance):
        raise ValueError('--roster-snapshot and --roster-provenance must be supplied together')
    if args.roster_snapshot:
        pregame_snapshot.apply_full_depth_roster_snapshot(snapshot, args.roster_snapshot, args.roster_provenance)
    ref, excluded_kickoffs = er.load(args.db)
    snapshot['model_reference']['observed_reference'] = ref.model_inputs
    pregame_snapshot.reseal(snapshot)

    baseline_files = {name: hashlib.sha256((REPO / name).read_bytes()).hexdigest() for name in V1_FILES}
    try:
        baseline = _baseline_v1(args.db, snapshot)
    except Exception as exc:  # remain explicit while retaining the statistical batch if the comparison is unavailable
        baseline = {'status': 'unavailable', 'reason': f'{type(exc).__name__}: {str(exc)}'}

    outcomes = []
    player_totals = defaultdict(lambda: defaultdict(float))
    games_with_player_stats = 0
    started = time.monotonic()
    for player_id in _player_template(snapshot):
        player_totals[player_id]
    for seed in range(args.seed_start, args.seed_start + args.games):
        record = None
        error = None
        validation_error = False
        try:
            record = gs.play_game(seed, ref, pregame_snapshot=copy.deepcopy(snapshot))
            gs.validate_game(record)
        except Exception as exc:  # every requested seed gets an outcome row, including generator/validator failures
            error = f'{type(exc).__name__}: {exc}'
            validation_error = record is not None
        outcome = _record_outcome(seed, record, error, validation_error)
        outcomes.append(outcome)
        if outcome['valid_full_game'] and record:
            games_with_player_stats += 1
            for player in record.get('stats', {}).get('player', []):
                player_id = str(player['player_id'])
                for category, fields in PLAYER_CATEGORIES.items():
                    for field in fields:
                        player_totals[player_id][(category, field)] += player.get(category, {}).get(field, 0)
        completed = len(outcomes)
        if args.progress_every and completed % args.progress_every == 0:
            elapsed = time.monotonic() - started
            rate = completed / elapsed if elapsed else 0
            remaining = (args.games - completed) / rate if rate else 0
            print(f'progress {completed}/{args.games}; elapsed {elapsed:.0f}s; ETA {remaining:.0f}s',
                  file=sys.stderr, flush=True)

    summary = aggregation.summarize_outcomes(outcomes, args.games,
                                             home_market_margin=args.home_market_margin,
                                             market_total=args.market_total)
    projected = summary['valid_full_game_distribution']
    comparison = {'sample_games': projected['sample_games'], 'baseline_status': baseline['status']}
    if projected['sample_games'] and baseline['status'] == 'available':
        comparison.update({
            'home_points_mean_minus_v1': round(projected['scores']['home']['mean'] - baseline['projected_home_points'], 4),
            'away_points_mean_minus_v1': round(projected['scores']['away']['mean'] - baseline['projected_away_points'], 4),
            'home_minus_away_mean_minus_v1': round(projected['home_minus_away']['mean'] - baseline['projected_home_minus_away'], 4),
            'total_mean_minus_v1': round(projected['total']['mean'] - baseline['projected_total'], 4),
        })
    payload = {
        'contract': {'name': 'gridiron.lp-full-game-batch', 'version': '1.0.0'},
        'schema': SCHEMA,
        'game_id': args.game_id,
        'teams': {'home': snapshot['schedule']['home_team'], 'away': snapshot['schedule']['away_team']},
        'simulation': {
            'model': 'seeded statistical full-game simulator', 'requested_games': args.games,
            'seed_start': args.seed_start, 'seed_end_inclusive': args.seed_start + args.games - 1,
            'seed_rule': 'one deterministic game per consecutive non-negative integer seed',
            'regulation_score_policy': ('all runs whose simulation reached the regulation end, including ties and '
                                        'guarded regulation-end outcomes; descriptive, not validated finals'),
            'valid_score_policy': ('only valid_full_game=true, complete_game=true, untied outcomes; all other '
                                   'seeds remain in outcomes and coverage counts'),
        },
        'source': {**game_cli.producer_source(), 'v1_model_file_sha256': baseline_files},
        'pregame_snapshot': snapshot,
        'data_sources': {
            'database': 'SQLite, opened read-only',
            'play_window': 'nfl_pbp seasons 2022-2025, weeks 1-18',
            'observed_reference_sha256': ref.model_inputs['sha256'],
            'kickoff_pool_excluded_rows': sum(excluded_kickoffs.values()),
        },
        'baseline_v1': baseline,
        'comparison_to_v1': comparison,
        'summary': summary,
        'player_projections': _player_projections(snapshot, player_totals, games_with_player_stats),
        'replay_examples': _replay_examples(outcomes),
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=1, sort_keys=True) + '\n')
    print(f'wrote {out}: {summary["valid_full_games"]}/{args.games} valid games, '
          f'{summary["tied_at_regulation_end"]} regulation ties, '
          f'{summary["blocked_before_regulation_end"]} blocked before regulation')
    print(f"baseline_v1={baseline['status']} reference_sha256={ref.model_inputs['sha256']}")
    return payload


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--game-id', required=True)
    ap.add_argument('--as-of', required=True)
    ap.add_argument('--kickoff-utc')
    ap.add_argument('--kickoff-source-url')
    ap.add_argument('--games', type=int, default=10000)
    ap.add_argument('--seed-start', type=int, default=1)
    ap.add_argument('--db', default=e1.DEFAULT_DB, help='SQLite database opened read-only')
    ap.add_argument('--roster-snapshot', help='optional pinned full-depth roster JSON with starter flags and jersey numbers')
    ap.add_argument('--roster-provenance', help='source and checksum manifest for --roster-snapshot')
    ap.add_argument('--home-market-margin', type=float,
                    help='optional home-team expected-margin line; positive means the home team is favored')
    ap.add_argument('--market-total', type=float, help='optional over/under total line')
    ap.add_argument('--progress-every', type=int, default=1000,
                    help='print a progress line every N games; use 0 to disable')
    ap.add_argument('--out', required=True)
    args = ap.parse_args(argv)
    if args.games < 1:
        ap.error('--games must be positive')
    if args.seed_start < 0:
        ap.error('--seed-start must be non-negative')
    if args.progress_every < 0:
        ap.error('--progress-every must be non-negative')
    run_batch(args)


if __name__ == '__main__':
    main()
