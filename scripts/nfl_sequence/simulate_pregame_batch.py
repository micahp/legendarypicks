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
import pregame_context  # noqa: E402
import try_policy as try_policy_module  # noqa: E402
import simulate_pregame_game as game_cli  # noqa: E402
import slc_engine  # noqa: E402

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


def _utc_timestamp(value, label):
    if not value:
        raise ValueError(f'{label} is missing')
    parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _baseline_v1(db, snapshot):
    """Use an immutable pregame v1 lock, or fit v1 on inputs available at the frozen cutoff."""
    schedule = snapshot['schedule']
    season, week = int(schedule['season']), int(schedule['week'])
    if season >= e1.HOLDOUT_SEASON:
        # the v1 lock and its fit both read this season's results, which the holdout forbids
        return {'status': 'unavailable', 'reason': f'{e1.HOLDOUT_SEASON} is the holdout; v1 comparison not computed'}
    cutoff = datetime.fromisoformat(snapshot['as_of'].replace('Z', '+00:00')).astimezone(timezone.utc)
    con = sqlite3.connect(f'file:{db}?mode=ro', uri=True, timeout=30)
    try:
        locked_rows = con.execute(
            "SELECT g.run_id, g.model_version, g.proj_home, g.proj_away, g.proj_margin, g.proj_total, "
            "g.p_home_win, g.locked_at, g.home, g.away, g.season, g.week, r.started_at, r.params_json "
            "FROM game_projections g JOIN model_runs r ON r.run_id=g.run_id "
            "WHERE g.league='nfl' AND g.game_id=? AND g.locked=1 AND r.status='ok' "
            "AND r.model='nfl-ratings-v1' AND g.model_version LIKE 'nfl-v1 %' "
            "ORDER BY g.locked_at", (schedule['game_id'],)
        ).fetchall()
        row = None
        schedule_source = None
        schedule_ingested_at = schedule.get('ingested_at')
        explicitly_unverified = (schedule.get('availability_classification')
                                 == 'current_row_unverified_exploratory')
        if (not explicitly_unverified and schedule_ingested_at
                and _utc_timestamp(schedule_ingested_at, 'snapshot schedule ingested_at') <= cutoff):
            row = schedule
            schedule_source = 'hash_pinned_snapshot_schedule_version'
        elif not explicitly_unverified:
            try:
                row = pregame_snapshot.schedule_at(con, schedule['game_id'], cutoff)
            except sqlite3.OperationalError as exc:
                if 'nfl_schedule_versions' not in str(exc):
                    raise
            if row is not None:
                schedule_source = 'nfl_schedule_versions'
        schedule_verified = row is not None
        if row is not None:
            db_season, db_week, db_type, home, away, gameday = (
                row[key] for key in ('season', 'week', 'game_type', 'home_team', 'away_team', 'gameday'))
            location = row.get('location', schedule.get('location'))
            if (int(db_season), int(db_week), db_type, home, away) != (
                    season, week, schedule['game_type'], schedule['home_team'], schedule['away_team']):
                raise ValueError('v1 baseline schedule identity disagrees with the frozen snapshot')
            for key in ('gameday', 'gametime', 'location', 'source'):
                if schedule.get(key) is not None and row.get(key) != schedule[key]:
                    raise ValueError(f'v1 baseline schedule {key} disagrees with the frozen snapshot')
        else:
            db_season, db_week = season, week
            home, away = schedule['home_team'], schedule['away_team']
            gameday, location = schedule.get('gameday'), schedule.get('location')
        if gameday and datetime.fromisoformat(gameday).date() > cutoff.date():
            raise ValueError('v1 baseline target game date is after the frozen cutoff')

        kickoff = schedule.get('scheduled_kickoff_utc')
        kickoff_time = _utc_timestamp(kickoff, 'snapshot scheduled kickoff') if kickoff else None
        if locked_rows:
            if kickoff_time is None:
                raise ValueError('stored v1 lock cannot be classified without a verified kickoff timestamp')
            candidates = []
            for row in locked_rows:
                lock_time = _utc_timestamp(row[7], 'stored v1 lock timestamp')
                if lock_time >= kickoff_time.astimezone(timezone.utc):
                    continue
                if (row[8], row[9], int(row[10]), int(row[11])) != (home, away, season, week):
                    continue
                candidates.append((lock_time, row))
            if not candidates:
                raise ValueError('no stored v1 lock matches the cutoff schedule identity before kickoff')
            eligible_locks = [item for item in candidates if item[0] <= cutoff]
            locked_time, locked = max(eligible_locks or candidates, key=lambda item: item[0])
            (run_id, model_version, home_points, away_points, margin, total, p_home, locked_at,
             locked_home, locked_away, locked_season, locked_week, run_started, params_json) = locked
            cutoff_delta = (locked_time - cutoff).total_seconds()
            try:
                params = json.loads(params_json)
            except (TypeError, ValueError):
                params = {}
            lock_is_comparable = cutoff_delta <= 0 and schedule_verified
            if cutoff_delta > 0:
                lock_status = 'exploratory_later_lock'
                cutoff_note = 'v1 lock is later than the frozen simulation cutoff'
            elif not schedule_verified:
                lock_status = 'exploratory_schedule_unverified'
                cutoff_note = 'v1 lock is within the cutoff, but schedule availability at the cutoff is unverified'
            else:
                lock_status = 'available'
                cutoff_note = 'v1 lock and schedule version were recorded by the frozen simulation cutoff'
            return {
                'status': lock_status,
                'comparable_at_snapshot_cutoff': lock_is_comparable,
                'source': 'immutable_locked_v1_projection',
                'model': 'Legendary Picks NFL points model v1', 'model_version': model_version,
                'run_id': run_id, 'locked_at': locked_at, 'run_started_at': run_started,
                'snapshot_cutoff_offset_seconds': cutoff_delta,
                'cutoff_note': cutoff_note,
                'schedule_provenance': {'verified': schedule_verified, 'source': schedule_source,
                                        'snapshot_schedule_ingested_at': schedule_ingested_at},
                'training': {'prior_season': season - 1, 'current_season': season,
                             'current_season_week_exclusive': week,
                             'fit_games': params.get('fit_games'), 'as_of': snapshot['as_of']},
                'projected_home_points': home_points, 'projected_away_points': away_points,
                'projected_home_minus_away': margin, 'projected_total': total,
                'home_win_probability': p_home,
                'win_probability_sigma_points': params.get('sigma', V1_CONFIG['sigma']),
            }

        if not schedule_verified:
            raise ValueError('cannot reconstruct v1 without a schedule version observed by the frozen cutoff')

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
            'status': 'exploratory_reconstructed_fit', 'comparable_at_snapshot_cutoff': False,
            'source': 'frozen_v1_fit_from_current_chronologically_filtered_rows',
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
            player['pos_rank'], player.get('group', 'unclassified'),
        ))
        players[player_id] = {
            'player_id': player_id, 'player_name': primary['player_name'],
            'position': primary['pos_abb'], 'team': roster['team'], 'side': side,
            'starter': any(player.get('starter', player['pos_rank'] == 1) for player in roles),
            'roster_roles': [
                {'group': player.get('group', 'unclassified'), 'position': player['pos_abb'],
                 'depth_rank': player['pos_rank'],
                 'starter': player.get('starter', player['pos_rank'] == 1)}
                for player in sorted(roles, key=lambda item: (item.get('group', 'unclassified'),
                                                               item['pos_abb'], item['pos_rank']))
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
        'reproduction': ('Save the payload pregame_snapshot as JSON, then run simulate_pregame_batch.py with the same '
                         'database and model options, --snapshot-file PATH, --games 1, and the listed --seed-start.'),
    }


ERROR_STATUSES = ('simulation_error', 'validation_error')


def _simulate_seed(seed, ref, snapshot):
    record = None
    error = None
    validation_error = False
    decisions = None
    try:
        if slc_engine.is_slc(ref):
            record, decisions = slc_engine.play(seed, ref, snapshot)
        else:
            record = gs.play_game(seed, ref, pregame_snapshot=copy.deepcopy(snapshot))
        gs.validate_game(record)
    except Exception as exc:  # every requested seed gets an outcome row, including generator/validator failures
        error = f'{type(exc).__name__}: {exc}'
        validation_error = record is not None
    outcome = _record_outcome(seed, record, error, validation_error)
    if decisions is not None:
        outcome['playcall'] = slc_engine.summary(decisions)
    contribution = None
    if outcome['valid_full_game'] and record:
        contribution = {
            str(player['player_id']): {f'{category}.{field}': player.get(category, {}).get(field, 0)
                                       for category, fields in PLAYER_CATEGORIES.items() for field in fields}
            for player in record.get('stats', {}).get('player', [])}
    return outcome, contribution


def _open_seed_ledger(path, header, resume):
    """Return (finished seeds by number, handle for appending). Line one pins the inputs a resume must match."""
    if not resume and path.exists():
        raise FileExistsError(f'{path} exists; pass --resume to continue it or remove it to start over')
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        handle = path.open('w')
        handle.write(json.dumps({'header': header}, sort_keys=True) + '\n')
        handle.flush()
        return {}, handle
    lines = path.read_text().splitlines()
    if not lines or json.loads(lines[0]).get('header') != header:
        raise ValueError(f'{path} was written from different inputs; use a new --out or remove the ledger')
    finished = {}
    for index, line in enumerate(lines[1:], start=2):
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            if index != len(lines):
                raise
            print(f'{path}: dropping a partial last line left by an interrupted run', file=sys.stderr)
            lines = lines[:-1]
            break
        finished[row['seed']] = row
    path.write_text(''.join(line + '\n' for line in lines))
    return finished, path.open('a')


def _seed_outcome(seed, finished, ledger, ref, snapshot):
    """A finished seed is reused from the ledger unless it errored; anything else is simulated and appended."""
    cached = finished.get(seed)
    if cached is not None and cached['outcome']['status'] not in ERROR_STATUSES:
        return cached['outcome'], cached['players']
    outcome, contribution = _simulate_seed(seed, ref, snapshot)
    ledger.write(json.dumps({'seed': seed, 'outcome': outcome, 'players': contribution}, sort_keys=True) + '\n')
    ledger.flush()
    return outcome, contribution


def run_batch(args):
    batch_started = time.monotonic()
    snapshot_started = batch_started
    if args.snapshot_file:
        if args.allow_unverified_current_schedule_exploratory:
            raise ValueError('--allow-unverified-current-schedule-exploratory cannot be used with --snapshot-file')
        snapshot = pregame_snapshot.load_frozen_snapshot(args.snapshot_file)
        if args.game_id and args.game_id != snapshot['schedule']['game_id']:
            raise ValueError('--game-id does not match the frozen snapshot')
        if args.as_of and pregame_snapshot.parse_as_of(args.as_of) != pregame_snapshot.parse_as_of(snapshot['as_of']):
            raise ValueError('--as-of does not match the frozen snapshot')
        if bool(args.kickoff_utc) != bool(args.kickoff_source_url):
            raise ValueError('--kickoff-utc and --kickoff-source-url must be supplied together')
        if args.kickoff_utc and pregame_snapshot.parse_as_of(args.kickoff_utc) != pregame_snapshot.parse_as_of(
                snapshot['schedule'].get('scheduled_kickoff_utc')):
            raise ValueError('--kickoff-utc does not match the frozen snapshot')
        args.game_id = snapshot['schedule']['game_id']
        args.as_of = snapshot['as_of']
    else:
        if not args.game_id or not args.as_of:
            raise ValueError('provide --snapshot-file or both --game-id and --as-of')
        snapshot = pregame_snapshot.build(
            args.db, args.game_id, args.as_of, args.kickoff_utc, args.kickoff_source_url,
            allow_unverified_current_schedule_exploratory=args.allow_unverified_current_schedule_exploratory)
    source_snapshot_sha256 = snapshot['snapshot_sha256']
    if bool(args.roster_snapshot) != bool(args.roster_provenance):
        raise ValueError('--roster-snapshot and --roster-provenance must be supplied together')
    if args.roster_snapshot:
        pregame_snapshot.apply_full_depth_roster_snapshot(snapshot, args.roster_snapshot, args.roster_provenance)
    snapshot_seconds = time.monotonic() - snapshot_started
    contextual = None
    if args.team_tendency and args.context_mode != 'cutoff_unconditioned':
        raise SystemExit('--team-tendency needs --context-mode cutoff_unconditioned (a cutoff-matched pool, no points kernel)')
    cutoff_pool_mode = args.context_mode != 'unconditioned'
    try_policy = try_policy_module.TryPolicy.from_fixture() if args.try_policy == 'k1' else None
    safety_kick_table = not args.no_safety_table
    reference_started = time.monotonic()
    if args.playcall_artifact:
        if args.team_tendency or args.context_mode != 'unconditioned' or args.try_policy != 'unconditional' or args.no_safety_table:
            raise SystemExit('--playcall-artifact is the SLC v1 policy: it takes no team-tendency, contextual, try-policy or '
                             'safety option')
        ref, excluded_kickoffs = slc_engine.load_reference(args.db, snapshot, args.playcall_artifact,
                                                           team_outcomes=args.playcall_team_outcomes,
                                                           formation=args.playcall_formation,
                                                           player_shares=args.playcall_player_shares,
                                                           exact_yardline=args.playcall_exact_yardline,
                                                           coverage=args.playcall_coverage,
                                                           point_splits=(str(args.playcall_point_splits_cache) if args.playcall_point_splits_cache else args.playcall_point_splits),
                                                           streak=(str(args.playcall_streak_cache) if args.playcall_streak_cache else args.playcall_streak_splits),
                                                           streak_file=args.playcall_streak_file,
                                                           target_roles=args.playcall_target_roles,
                                                           decision=args.playcall_decision,
                                                           decision_filter=not args.playcall_decision_unfiltered,
                                                           dirichlet_shares=args.playcall_dirichlet_shares,
                                                           streak_league=(str(args.playcall_streak_cache) if (args.playcall_streak_cache and args.playcall_streak_league)
                                                                          else args.playcall_streak_league))
    elif args.context_mode == 'unconditioned':
        ref, excluded_kickoffs = er.load(args.db, try_policy=try_policy,
                                         safety_kick_table=safety_kick_table)
    else:
        contextual = pregame_context.build(args.db, snapshot['schedule'], snapshot['as_of'], snapshot)
        eligible_before = (int(snapshot['schedule']['season']), int(snapshot['schedule']['week']))
        if args.context_mode == 'cutoff_unconditioned':
            ref, excluded_kickoffs = er.load(args.db, try_policy=try_policy,
                                             eligible_before=eligible_before,
                                             safety_kick_table=safety_kick_table,
                                             team_tendency=args.team_tendency,
                                             team_tendency_teams={'A': snapshot['schedule']['home_team'],
                                                                  'B': snapshot['schedule']['away_team']})
        else:
            ref, excluded_kickoffs = er.load(
                args.db, try_policy=try_policy, eligible_before=eligible_before,
                contextual_context=contextual, contextual_mode=args.context_mode,
                contextual_bandwidth=args.context_bandwidth,
                contextual_min_effective_games=args.context_min_source_games,
                safety_kick_table=safety_kick_table)
    reference_seconds = time.monotonic() - reference_started
    snapshot['model_reference']['observed_reference'] = ref.model_inputs
    snapshot['model_reference']['pool_scope'] = ref.pool_scope
    pregame_snapshot.reseal(snapshot)

    baseline_files = {name: hashlib.sha256((REPO / name).read_bytes()).hexdigest() for name in V1_FILES}
    baseline_started = time.monotonic()
    try:
        baseline = _baseline_v1(args.db, snapshot)
    except Exception as exc:  # remain explicit while retaining the statistical batch if the comparison is unavailable
        baseline = {'status': 'unavailable', 'reason': f'{type(exc).__name__}: {str(exc)}'}
    baseline_seconds = time.monotonic() - baseline_started

    outcomes = []
    player_totals = defaultdict(lambda: defaultdict(float))
    games_with_player_stats = 0
    errors = 0
    ledger_header = {
        'schema': SCHEMA, 'game_id': args.game_id, 'as_of': snapshot['as_of'],
        'source_snapshot_sha256': source_snapshot_sha256, 'observed_reference_sha256': ref.model_inputs['sha256'],
        'context_mode': args.context_mode, 'try_policy': args.try_policy, 'safety_kick_table': safety_kick_table,
        'seed_start': args.seed_start, 'playcall_artifact_sha256': (slc_engine.describe(ref) or {}).get('artifact_sha256'),
        'playcall_team_outcomes': bool(args.playcall_team_outcomes), 'playcall_formation': bool(args.playcall_formation),
        'playcall_coverage': bool(args.playcall_coverage), 'playcall_player_shares': bool(args.playcall_player_shares),
        'playcall_decision': bool(args.playcall_decision), 'playcall_dirichlet_shares': bool(args.playcall_dirichlet_shares),
        'playcall_exact_yardline': bool(args.playcall_exact_yardline),
    }
    ledger_path = Path(args.out).with_suffix('.seeds.jsonl')
    finished, ledger = _open_seed_ledger(ledger_path, ledger_header, args.resume)
    started = time.monotonic()
    for player_id in _player_template(snapshot):
        player_totals[player_id]
    try:
        for seed in range(args.seed_start, args.seed_start + args.games):
            outcome, contribution = _seed_outcome(seed, finished, ledger, ref, snapshot)
            outcomes.append(outcome)
            if outcome['status'] in ERROR_STATUSES:
                errors += 1
            if contribution is not None:
                games_with_player_stats += 1
                for player_id, values in contribution.items():
                    for key, value in values.items():
                        category, field = key.split('.')
                        player_totals[player_id][(category, field)] += value
            completed = len(outcomes)
            if args.progress_every and completed % args.progress_every == 0:
                elapsed = time.monotonic() - started
                rate = completed / elapsed if elapsed else 0
                remaining = (args.games - completed) / rate if rate else 0
                print(f'progress {completed}/{args.games}; errors {errors}; elapsed {elapsed:.0f}s; ETA {remaining:.0f}s',
                      file=sys.stderr, flush=True)
            if args.max_simulation_errors is not None and errors > args.max_simulation_errors:
                raise RuntimeError(f'{errors} error seeds after {completed} of {args.games}; stopped. Finished seeds are '
                                   f'in {ledger_path}; fix the cause and rerun with --resume')
    finally:
        ledger.close()

    simulation_seconds = time.monotonic() - started
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
    replay_examples = _replay_examples(outcomes)
    if replay_examples:
        replay_examples['reproduction_command'] = (
            'python3 scripts/nfl_sequence/simulate_pregame_batch.py --snapshot-file SNAPSHOT.json '
            f'--db {args.db} --games 1 --seed-start SEED --context-mode {args.context_mode} '
            f'--context-bandwidth {args.context_bandwidth} --context-min-source-games {args.context_min_source_games} '
            f'--try-policy {args.try_policy} --out REPLAY.json')
        if args.no_safety_table:
            replay_examples['reproduction_command'] += ' --no-safety-table'
    payload = {
        'contract': {'name': 'gridiron.lp-full-game-batch', 'version': '1.0.0'},
        'schema': SCHEMA,
        'forecast_frozen_at_utc': datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z'),
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
            'context_mode': args.context_mode,
            'context_bandwidth_in_source_rating_sd': (args.context_bandwidth
                                                       if args.context_mode in ('offense', 'defense', 'both')
                                                       else None),
            'pool_control': ('legacy_unconditioned_2022_2025' if args.context_mode == 'unconditioned'
                             else 'cutoff_eligible_uniform_pool'),
            'safety_kick_table': ('observed_2022_2025' if safety_kick_table else 'disabled_control'),
            'try_policy': 'K=1 research policy' if args.try_policy == 'k1' else 'unconditional control',
        },
        'runtime_seconds': {
            'snapshot_load': round(snapshot_seconds, 4),
            'context_and_reference_build': round(reference_seconds, 4),
            'v1_baseline_lookup_or_fit': round(baseline_seconds, 4),
            'game_generation': round(simulation_seconds, 4),
            'total_before_report_write': round(time.monotonic() - batch_started, 4),
        },
        'source': {**game_cli.producer_source(), 'v1_model_file_sha256': baseline_files},
        'pregame_snapshot': snapshot,
        'pregame_context': contextual,
        'contextual_pool_manifest': ref.contextual_pool_manifest,
        'playcall_layer': slc_engine.describe(ref),
        'data_sources': {
            'database': 'SQLite, opened read-only',
            'source_snapshot_sha256': source_snapshot_sha256,
            'input_availability': {
                'classification': 'chronological_filter_only',
                'historical_replay_fairness': 'exploratory_until_row_level_source_availability_is_verified',
                'limitations': ['nfl_pbp has no row-level publication/ingestion timestamp',
                                'historical schedule score revisions are not available in the current database'],
            },
            'play_window': ('nfl_pbp seasons 2022-2025, weeks 1-18' if not cutoff_pool_mode else
                            f"nfl_pbp seasons 2022 through weeks before {snapshot['schedule']['season']} week "
                            f"{snapshot['schedule']['week']}"),
            'observed_reference_sha256': ref.model_inputs['sha256'],
            'reference_pool_scope': ref.pool_scope,
            'kickoff_pool_excluded_rows': sum(excluded_kickoffs.values()),
        },
        'baseline_v1': baseline,
        'comparison_to_v1': comparison,
        'summary': summary,
        'player_projections': _player_projections(snapshot, player_totals, games_with_player_stats),
        'replay_examples': replay_examples,
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
    ap.add_argument('--game-id', help='published nfl_schedule game_id; required unless --snapshot-file is used')
    ap.add_argument('--as-of', help='timezone-qualified ISO-8601 cutoff; required unless --snapshot-file is used')
    ap.add_argument('--kickoff-utc')
    ap.add_argument('--kickoff-source-url')
    ap.add_argument('--allow-unverified-current-schedule-exploratory', action='store_true',
                    help=('explicitly use the current schedule row when no as-of version exists; preserves its real '
                          'ingestion timestamp and classifies the v1 comparison as exploratory'))
    ap.add_argument('--snapshot-file', help='hash-pinned pregame snapshot JSON or game payload containing one')
    ap.add_argument('--games', type=int, default=10000)
    ap.add_argument('--seed-start', type=int, default=1)
    ap.add_argument('--db', default=e1.DEFAULT_DB, help='SQLite database opened read-only')
    ap.add_argument('--roster-snapshot', help='optional pinned full-depth roster JSON with starter flags and jersey numbers')
    ap.add_argument('--roster-provenance', help='source and checksum manifest for --roster-snapshot')
    ap.add_argument('--home-market-margin', type=float,
                    help='optional home-team expected-margin line; positive means the home team is favored')
    ap.add_argument('--market-total', type=float, help='optional over/under total line')
    ap.add_argument('--context-mode', choices=('unconditioned', 'cutoff_unconditioned', 'offense', 'defense', 'both'),
                    default='unconditioned',
                    help=('legacy S0, cutoff-matched uniform control, or research-only offense/defense kernel '
                          'ablation'))
    ap.add_argument('--context-bandwidth', type=float, default=1.0,
                    help='Gaussian kernel bandwidth in source team-rating standard deviations')
    ap.add_argument('--context-min-source-games', type=float, default=10.0,
                    help='minimum effective source games in a sampled contextual pool cell')
    ap.add_argument('--team-tendency', action='store_true',
                    help='research: drive policy from prior-season team tendencies; needs --context-mode cutoff_unconditioned')
    ap.add_argument('--try-policy', choices=('unconditional', 'k1'), default='unconditional',
                    help='research try-policy ablation; unconditional remains the control/default')
    ap.add_argument('--no-safety-table', action='store_true',
                    help='control arm: disable observed safety free kicks and retain the old safety blocker')
    ap.add_argument('--playcall-point-splits-cache', type=Path, default=None,
                    help='frame cache for the point splits; used instead of rebuilding the frame from the database')
    ap.add_argument('--playcall-streak-splits', action='store_true',
                    help='SLC v1 research: team win-loss streak splits from prior seasons (needs --playcall-streak-file)')
    ap.add_argument('--playcall-streak-cache', type=Path, default=None, help='frame cache for the streak splits')
    ap.add_argument('--playcall-target-roles', action='store_true',
                    help='SLC v1 research: decision model category A (target role) as a team-by-situation pre-event prior')
    ap.add_argument('--playcall-dirichlet-shares', action='store_true',
                    help='SLC v1 research: per-game Dirichlet target and carry shares, fitted on the prior season; the receiver and '
                         'rusher are drawn from each game\'s shares')
    ap.add_argument('--playcall-decision-unfiltered', action='store_true',
                    help='experiment: with --playcall-decision, the outcome lifts apply but the row is drawn from the whole cell')
    ap.add_argument('--playcall-decision', action='store_true',
                    help='SLC v1 research: decision model categories A to N as pre-event draws (team priors from the prior season) '
                         'and outcomes conditioned on them')
    ap.add_argument('--playcall-streak-league', action='store_true',
                    help='SLC v1 research: league-wide streak splits (dropback shift and outcome mix by streak state)')
    ap.add_argument('--playcall-streak-file', type=Path, default=None,
                    help='the verified W-L records (wl-streaks JSON) giving each team\'s current streak')
    ap.add_argument('--playcall-point-splits', action='store_true',
                    help='SLC v1 research: team score-state shifts of the dropback rate from prior seasons')
    ap.add_argument('--playcall-coverage', action='store_true',
                    help='SLC v1 research: defensive coverage on dropbacks from prior-season defense shares, conditioning the outcome')
    ap.add_argument('--playcall-player-shares', action='store_true',
                    help='SLC v1 research: pre-event receivers and carriers drawn by prior-season player shares')
    ap.add_argument('--playcall-exact-yardline', action='store_true',
                    help='SLC v1 research: inside the 20, draw the outcome from rows at the exact yard line')
    ap.add_argument('--playcall-formation', action='store_true',
                    help='SLC v1 research: pre-event formation and personnel from prior seasons, and outcomes conditioned '
                         'on the chosen formation. Needs --playcall-artifact')
    ap.add_argument('--playcall-team-outcomes', action='store_true',
                    help='SLC v1 research: reweight which historical outcome is drawn by prior-season team event splits '
                         '(offense and defense), within the play-call intent. Needs --playcall-artifact')
    ap.add_argument('--playcall-artifact',
                    help='SLC v1: the frozen score-clock play-call artifact, fitted before the game season; the pool is cut to '
                         'the weeks before the game. Omit for the S0 control')
    ap.add_argument('--progress-every', type=int, default=1000,
                    help='print a progress line every N games; use 0 to disable')
    ap.add_argument('--resume', action='store_true',
                    help='continue the seed ledger next to --out (<out stem>.seeds.jsonl); refuses a ledger from other inputs')
    ap.add_argument('--max-simulation-errors', type=int,
                    help='stop once more than this many seeds have errored; finished seeds stay in the ledger')
    ap.add_argument('--out', required=True)
    args = ap.parse_args(argv)
    if args.games < 1:
        ap.error('--games must be positive')
    if args.seed_start < 0:
        ap.error('--seed-start must be non-negative')
    if args.progress_every < 0:
        ap.error('--progress-every must be non-negative')
    if args.max_simulation_errors is not None and args.max_simulation_errors < 0:
        ap.error('--max-simulation-errors must be non-negative')
    run_batch(args)


if __name__ == '__main__':
    main()
