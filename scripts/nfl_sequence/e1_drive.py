#!/usr/bin/env python3
"""E1 complete-drive generator for the NFL pregame play-sequence generator (statistical, not physics).

Starts from an authored possession state and samples observed plays in the same down, distance and field cell
(2022-2025 regular season). Each sampled outcome is applied by the shared reducer (reducer.py), the same one E0 uses.
The drive ends at a legal terminal: touchdown, safety, turnover, turnover on downs, punt, field-goal attempt, or end
of period when the derived clock reaches zero.

Not modelled in E1 (listed in each record's `gaps`): field-goal result (not in the published columns), extra points,
kickoffs, two-point tries, penalties, timeouts, quarter changes, score, points, participants and player stats.

Clock runoff is derived from consecutive published game_seconds_remaining values in the same quarter. A turnover's or
punt's spot is the published position of the receiving offense's next snap, because yards_gained does not encode it.
A fourth-down choice is sampled from the observed plays in its cell (go-for-it, punt or field-goal attempt).

Reads the dev database read-only. Every drive is checked before it is written; a failed check stops the run.
"""
import argparse
import hashlib
import json
import random
import sqlite3
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import e0_single_play as e0  # noqa: E402
import holdout  # noqa: E402
import reducer  # noqa: E402  the shared reducer
import field_goal_feasibility as fg_feasibility  # noqa: E402
import football_assertions  # noqa: E402

DEFAULT_DB = e0.DEFAULT_DB
POOL_SEASONS = (2022, 2023, 2024, 2025)
HOLDOUT_SEASON = holdout.HOLDOUT_SEASON  # sealed for every model; no loader in this package may read it
MODEL_VERSION = 'e1-empirical-v0'
RULES_VERSION = 'e1-drive-2026-10-24'
EVENTS = ('run', 'pass_complete', 'pass_incomplete', 'sack', 'sack_fumble_lost', 'interception', 'fumble_lost', 'punt',
          'field_goal_attempt')
KICK_EVENTS = ('punt', 'field_goal_attempt', 'blocked_punt', 'blocked_field_goal')
POSSESSION_TERMINALS = ('turnover', 'turnover_on_downs', 'punt')  # a play that hands the ball over; a score or a field goal does not
MIN_POOL = 50  # 4th-down cells hold fewer observed plays than the others; sizes are recorded in each play
MAX_PLAYS = 60
PLAY_TYPES = ('run', 'pass', 'punt', 'field_goal')
COLUMNS = ('game_id', 'play_id', 'season', 'week', 'game_date', 'posteam', 'defteam', 'qtr', 'down', 'ydstogo',
           'yardline_100', 'game_seconds_remaining', 'play_type', 'yards_gained', 'touchdown', 'interception',
           'fumble_lost', 'sack', 'complete_pass', 'qb_scramble', 'penalty', 'two_point_attempt')


class SamplingUnavailable(Exception):
    """A contextual sampling cell lacks enough supported historical evidence."""

# Authored demonstration starts. These are not pregame states taken from a real game.
STARTS = {
    'own25_q1_900': {'quarter': 1, 'clock': 900, 'offense': 'OFF', 'defense': 'DEF', 'yl': 75, 'down': 1, 'togo': 10, 'dir': 1},
    'midfield_q3_900': {'quarter': 3, 'clock': 900, 'offense': 'OFF', 'defense': 'DEF', 'yl': 50, 'down': 1, 'togo': 10, 'dir': 1},
    'own25_q4_150': {'quarter': 4, 'clock': 150, 'offense': 'OFF', 'defense': 'DEF', 'yl': 75, 'down': 1, 'togo': 10, 'dir': 1},
    'own40_q4_4th5_600': {'quarter': 4, 'clock': 600, 'offense': 'OFF', 'defense': 'DEF', 'yl': 60, 'down': 4, 'togo': 5, 'dir': 1},
    'own5_q1_900': {'quarter': 1, 'clock': 900, 'offense': 'OFF', 'defense': 'DEF', 'yl': 95, 'down': 1, 'togo': 10, 'dir': 1},
    'own25_q2_120': {'quarter': 2, 'clock': 120, 'offense': 'OFF', 'defense': 'DEF', 'yl': 75, 'down': 1, 'togo': 10, 'dir': 1},
    # Short clocks so that a drive is likely to cross a change of ends after Q1 or Q3.
    'own25_q1_060': {'quarter': 1, 'clock': 60, 'offense': 'OFF', 'defense': 'DEF', 'yl': 75, 'down': 1, 'togo': 10, 'dir': 1},
    'own25_q3_060': {'quarter': 3, 'clock': 60, 'offense': 'OFF', 'defense': 'DEF', 'yl': 75, 'down': 1, 'togo': 10, 'dir': 1},
}
# `dir` is the authored orientation of the start offense in the starting quarter. The rules file requires
# authored orientation to be labeled; it is not a sourced fact about a real game.
QUARTER_LENGTH = 900
FLIP_AFTER = (1, 3)  # both teams change goals after Q1 and Q3 (rules file, section 2); not at halftime


def load(db, eligible_before=None):
    """Read the pinned S0 window by default, or rebuild through weeks before one matchup.

    The dynamic window starts at 2022 and excludes every play in the target week, including earlier games on the same day.
    """
    if eligible_before is None:
        return load_seasons(db, POOL_SEASONS)
    season, week = (int(value) for value in eligible_before)
    holdout.refuse_unless_cutoff(season, 'pool cutoff', eligible_before)
    if season < min(POOL_SEASONS) or week < 1 or week > 18:
        raise ValueError('dynamic pool cutoff must be week 1-18 of 2022 or later')
    con = sqlite3.connect(f'file:{db}?mode=ro', uri=True, timeout=10)
    try:
        columns = ', '.join(COLUMNS)
        query = (f"SELECT {columns} FROM nfl_pbp WHERE season >= ? AND week <= 18 "
                 "AND (season < ? OR (season = ? AND week < ?)) ORDER BY game_id, play_id")
        rows = [dict(zip(COLUMNS, r)) for r in con.execute(query, (min(POOL_SEASONS), season, season, week))]
    finally:
        con.close()
    return rows


def load_seasons(db, seasons):
    """Regular-season plays for the given seasons, in game order. Refuses the 2026 holdout."""
    seasons = sorted(seasons)
    for season in seasons:
        holdout.refuse_if_holdout(season, 'load_seasons')
    con = sqlite3.connect(f'file:{db}?mode=ro', uri=True, timeout=10)
    rows = [dict(zip(COLUMNS, r)) for r in con.execute(
        f"SELECT {', '.join(COLUMNS)} FROM nfl_pbp WHERE season BETWEEN ? AND ? AND week <= 18 "
        "ORDER BY game_id, play_id", (seasons[0], seasons[-1]))]
    con.close()
    return [r for r in rows if r['season'] in seasons]


def classify(row, nxt, excluded, include_qb_scrambles=False, separate_sack_fumbles=False):
    """Return (event, clock_runoff_seconds, spot) or None, counting every exclusion."""
    if row['penalty'] == 1:
        excluded['penalty (not modelled)'] += 1
        return None
    if row['two_point_attempt'] == 1:
        excluded['two_point_attempt (not modelled)'] += 1
        return None
    if row['qb_scramble'] == 1 and not include_qb_scrambles:
        excluded['qb_scramble (not in E1 vocabulary)'] += 1
        return None
    if row['down'] is None or row['ydstogo'] is None or row['yardline_100'] is None:
        excluded['missing down, distance or field'] += 1
        return None
    if (nxt is None or nxt['game_id'] != row['game_id'] or nxt['qtr'] != row['qtr']
            or nxt['game_seconds_remaining'] is None or row['game_seconds_remaining'] is None):
        excluded['no same-quarter next snap for clock runoff'] += 1
        return None
    runoff = int(round(row['game_seconds_remaining'] - nxt['game_seconds_remaining']))
    if runoff < 0:
        excluded['negative derived clock runoff'] += 1
        return None
    if row['play_type'] == 'field_goal':
        return 'field_goal_attempt', runoff, None
    if row['play_type'] == 'punt':
        if nxt['posteam'] != row['defteam'] or nxt['play_type'] not in ('run', 'pass') or nxt['yardline_100'] is None:
            excluded['punt without a clean receiving-team snap'] += 1
            return None
        return 'punt', runoff, int(nxt['yardline_100'])
    if row['yards_gained'] is None:
        excluded['yards_gained null'] += 1
        return None
    if separate_sack_fumbles and row['sack'] == 1 and row['fumble_lost'] == 1:
        if row['touchdown'] == 1:
            excluded['sack-fumble return touchdown lacks modeled recovery geometry'] += 1
            return None
        if nxt['posteam'] != row['defteam'] or nxt['play_type'] not in ('run', 'pass') or nxt['yardline_100'] is None:
            excluded['sack-fumble without a clean new-offense snap'] += 1
            return None
        return 'sack_fumble_lost', runoff, int(nxt['yardline_100'])
    if row['interception'] == 1 or row['fumble_lost'] == 1:
        if row['touchdown'] == 1:
            excluded['turnover that is a touchdown (not modelled)'] += 1
            return None
        if nxt['posteam'] != row['defteam'] or nxt['play_type'] not in ('run', 'pass') or nxt['yardline_100'] is None:
            excluded['turnover without a clean new-offense snap'] += 1
            return None
        event = 'interception' if row['interception'] == 1 else 'fumble_lost'
        return event, runoff, int(nxt['yardline_100'])
    if row['sack'] == 1:
        return 'sack', runoff, None
    if row['play_type'] == 'run':
        return 'run', runoff, None
    if row['play_type'] == 'pass' and row['complete_pass'] == 1:
        return 'pass_complete', runoff, None
    if row['play_type'] == 'pass' and row['complete_pass'] == 0:
        return 'pass_incomplete', runoff, None
    excluded['unclassified play'] += 1
    return None


def build_pool(rows, regulation_only=False, include_qb_scrambles=False, separate_sack_fumbles=False):
    """The sampling pool, keyed on down, distance and field position.

    With `regulation_only`, overtime rows (quarter 5 or later) are not sampled. A regulation-only candidate must not draw its
    outcomes from overtime, and the excluded rows are counted under 'overtime rows (regulation-only pool)', not dropped silently.
    """
    excluded = Counter()
    pool, by_game = {}, {}
    for r in rows:
        by_game.setdefault(r['game_id'], []).append(r)
    for plays in by_game.values():
        for i, row in enumerate(plays):
            if regulation_only and (row['qtr'] is None or int(row['qtr']) > 4):
                excluded['overtime rows (regulation-only pool)'] += 1
                continue
            if row['play_type'] not in PLAY_TYPES or row['down'] is None or not 1 <= row['down'] <= 4:
                continue
            nxt = plays[i + 1] if i + 1 < len(plays) else None
            hit = classify(row, nxt, excluded, include_qb_scrambles=include_qb_scrambles,
                           separate_sack_fumbles=separate_sack_fumbles)
            if hit is None:
                continue
            event, runoff, spot = hit
            key = (int(row['down']), e0.ydstogo_bucket(row['ydstogo']), e0.yardline_bucket(row['yardline_100']))
            pool.setdefault(key, []).append((event, row, runoff, spot))
    return pool, excluded


def build_pools(rows, regulation_only=False, include_qb_scrambles=False, team_before_season=None,
                known_clean_penalties=False, separate_sack_fumbles=False):
    """build_pool(rows, regulation_only, include_qb_scrambles) and, when `team_before_season` is given, the all-quarter pool
    of the rows from seasons before it (what team_tendency.build_from_rows builds from those rows), in one classify pass.

    classify() depends only on a row and its next play in the same game, and every game lies in one season, so each pool
    and its exclusion counts equal what build_pool returns for the same rows. Returns (pool, excluded, team_pool); team_pool
    is None without `team_before_season`.
    """
    excluded = Counter()
    pool, by_game = {}, {}
    team_pool = {} if team_before_season is not None else None
    for r in rows:
        by_game.setdefault(r['game_id'], []).append(r)
    for plays in by_game.values():
        for i, row in enumerate(plays):
            overtime = row['qtr'] is None or int(row['qtr']) > 4
            if regulation_only and overtime:
                excluded['overtime rows (regulation-only pool)'] += 1
            in_main = not (regulation_only and overtime)
            in_team = team_pool is not None and int(row['season']) < team_before_season
            if not (in_main or in_team):
                continue
            if known_clean_penalties and row.get('penalty') != 0:
                reason = ('known penalty row excluded (strict clean pool)' if row.get('penalty') == 1
                          else 'unknown or unrecognized penalty status excluded (strict clean pool)')
                excluded[reason] += 1
                continue
            if row['play_type'] not in PLAY_TYPES or row['down'] is None or not 1 <= row['down'] <= 4:
                continue
            nxt = plays[i + 1] if i + 1 < len(plays) else None
            key = (int(row['down']), e0.ydstogo_bucket(row['ydstogo']), e0.yardline_bucket(row['yardline_100']))
            if in_main:
                counted = Counter()
                hit = classify(row, nxt, counted, include_qb_scrambles=include_qb_scrambles,
                               separate_sack_fumbles=separate_sack_fumbles)
                excluded.update(counted)
                if hit is not None:
                    event, runoff, spot = hit
                    pool.setdefault(key, []).append((event, row, runoff, spot))
            if in_team:
                # The team pool is always built without scrambles (build_from_rows calls build_pool with defaults). classify
                # differs from the main call only on a qb_scramble row, so reuse the main result unless that row is affected.
                if in_main and not (include_qb_scrambles and row['qb_scramble'] == 1):
                    team_hit = hit
                else:
                    team_hit = classify(row, nxt, Counter(), include_qb_scrambles=False,
                                        separate_sack_fumbles=separate_sack_fumbles)
                if team_hit is not None:
                    event, runoff, spot = team_hit
                    team_pool.setdefault(key, []).append((event, row, runoff, spot))
    return pool, excluded, team_pool


def flips_between(start_quarter, quarter):
    """Number of change-of-ends boundaries crossed between the start quarter and `quarter` (rules file, section 2)."""
    return sum(1 for b in FLIP_AFTER if start_quarter <= b < quarter)


def _credit_field_boundary_yards(event, sampled_yards, yardline):
    """Stop a sampled scrimmage result at a goal line and retain the raw sample for audit."""
    if event in ('run', 'pass_complete') and sampled_yards > yardline:
        return yardline, {'boundary': 'opponent_goal_line', 'sampled_yards_gained': sampled_yards,
                          'credited_yards_gained': yardline}
    own_goal_limit = yardline - 100
    if event in ('run', 'pass_complete', 'sack') and sampled_yards < own_goal_limit:
        return own_goal_limit, {'boundary': 'own_goal_line', 'sampled_yards_gained': sampled_yards,
                                'credited_yards_gained': own_goal_limit}
    return sampled_yards, None


def _turnover_geometry_eligible(sample, state):
    """Reject turnover samples whose implied net gain crosses a goal line.

    A clean next-offense snap does NOT identify the fumble spot/recovery in
    either end zone. A transition of this class cannot be transported to a
    synthetic field position where that net gain crosses a goal line without
    additional data. Research V1.7 conditions only *these* source rows out,
    reports the exclusion, and preserves V1.6's source sampling untouched.
    An end-zone turnover/score distribution is still a separate model.
    """
    event, row, _runoff, _spot = sample
    if event not in ('fumble_lost', 'sack_fumble_lost'):
        return True
    yards = row.get('yards_gained')
    yl = state['yl']
    if type(yards) not in (int, float):
        return False
    destination = yl - yards
    return 0 < destination < 100


def _pre_snap_penalty_play(st, resolved, simulation_id, sequence, direction):
    """A dead-ball penalty is a game event, never an invented snap or player play."""
    runoff = resolved.runoff_seconds
    now = st['clock'] - runoff
    if now < 0:
        raise ValueError("penalty clock runoff exceeded period")
    flip = now == 0 and st['quarter'] in FLIP_AFTER
    terminal = ('halftime' if now == 0 and st['quarter'] == 2 else
                'end_of_regulation' if now == 0 and st['quarter'] == 4 else None)
    next_quarter = st['quarter'] + int(flip)
    clock_after = QUARTER_LENGTH if flip else now
    new = resolved.state
    after = {'quarter': next_quarter, 'clock_seconds': clock_after,
             'offense_team': new['offense'], 'defense_team': new['defense'],
             'down': new['down'] if terminal is None else None,
             'yards_to_go': new['togo'] if terminal is None else None,
             'yardline_100': new['yl'] if terminal is None else None,
             'home_score': None, 'away_score': None, 'home_timeouts': None,
             'away_timeouts': None, 'drive_index': 1}
    if terminal is not None:
        after['end_of_drive'] = terminal
    before = {'quarter': st['quarter'], 'clock_seconds': st['clock'],
              'offense_team': st['offense'], 'defense_team': st['defense'],
              'down': st['down'], 'yards_to_go': st['togo'], 'yardline_100': st['yl'],
              'home_score': None, 'away_score': None, 'home_timeouts': None,
              'away_timeouts': None, 'drive_index': 1}
    from_dir = direction(st['offense'], st['quarter'])
    to_dir = direction(new['offense'], next_quarter) if terminal is None else None
    outcome = {
        **reducer._no_flags(), 'first_down': bool(resolved.enforcement.get('automatic_first_down')),
        'yards_gained': None, 'sampled_yards_gained': None,
        'yardage_boundary_adjustment': None, 'scoring_team': None,
        'clock_runoff_seconds': runoff, 'clock_clamped_to_zero': False,
        'quarter_change': flip, 'clock_only_terminal': terminal is not None,
        'final_play_yardline_100': new['yl'] if terminal is not None else None,
        'sampled_touchdown_flag': False,
        'dead_ball_position': new if terminal is None else None,
        'penalty': True, 'penalty_resolved': True,
        'penalty_phase': 'pre_snap', 'penalty_proposal': resolved.proposal,
        'penalty_enforcement': resolved.enforcement, 'penalty_ruling': resolved.ruling,
        'sampled_from': None,
    }
    return {'sequence': sequence, 'id': f'{simulation_id}:{sequence}',
            'event_type': 'penalty',
            'state_before': before, 'state_after': after,
            'sampling': {'penalty_opportunity': True},
            'decision': {'type': 'penalty', 'concept': None, 'coverage': None, 'note': 'dead-ball foul, no snap'},
            'outcome': outcome,
            'field': {'assignment_version': 'e1-field-end-v2', 'source': 'authored_demo_orientation',
                      'before': {'dir': from_dir, 'los': e0.los(from_dir, st['yl'])},
                      'after': {'dir': to_dir, 'los': e0.los(to_dir, new['yl']) if to_dir else None}}}, terminal


def simulate(start, seed, pool, simulation_id, special_teams=None, clock=None, partial=None, sampling_policy=None,
             score_diff=None, play_index_start=1, drive_index=1, paired_random_streams=None, sampling_guard=None,
             penalty_controller=None):
    """`clock` is an optional research clock (clock_d.BoundaryClock). None keeps the E2 runoff from the pool.
    `partial`, when given, receives the plays made before a block, so a blocked drive keeps its evidence.
    `sampling_policy`, when given, samples events and source plays using the current simulated teams' context.
    `sampling_guard` may remove source rows that are illegal in the live simulation state."""
    rng = random.Random(seed)
    start_offense, start_defense = start['offense'], start['defense']
    start_quarter, start_dir = start['quarter'], start['dir']

    def dir_of(team, quarter):
        """Attacking direction of `team` in `quarter`. The start offense flips at each change of ends; the other team
        is always opposite. Halftime is not a change of ends, and E1 does not reach a second half."""
        d = start_dir * (-1) ** flips_between(start_quarter, quarter)
        return d if team == start_offense else -d

    st = {'quarter': start_quarter, 'offense': start_offense, 'defense': start_defense, 'down': start['down'],
          'togo': start['togo'], 'yl': start['yl'], 'clock': start['clock']}
    plays, terminal = [], None
    def halt(reason):
        if partial is not None:
            partial.extend(plays)
        return None, reason
    while terminal is None:
        if len(plays) >= MAX_PLAYS:
            return halt(f'exceeded {MAX_PLAYS} plays without a terminal')
        play_index = play_index_start + len(plays)
        if paired_random_streams is None:
            event_rng = row_rng = playcall_rng = special_rng = rng
            stream_keys = None
        else:
            event_rng = paired_random_streams.rng('e1_event_selection', drive_index, play_index)
            row_rng = paired_random_streams.rng('e1_source_row', drive_index, play_index)
            playcall_rng = paired_random_streams.rng('e1_playcall', drive_index, play_index)
            special_rng = paired_random_streams.rng('e1_special_teams', drive_index, play_index)
            stream_keys = {
                'event_selection': paired_random_streams.key('e1_event_selection', drive_index, play_index),
                'source_row': paired_random_streams.key('e1_source_row', drive_index, play_index),
                'playcall': paired_random_streams.key('e1_playcall', drive_index, play_index),
                'special_teams': paired_random_streams.key('e1_special_teams', drive_index, play_index),
            }
            if clock is not None and getattr(clock, 'paired_random_streams', None) is not None:
                stream_keys['clock_hazard'] = paired_random_streams.key(
                    'clock_quarter_end_hazard', drive_index, play_index)
                stream_keys['clock_runoff'] = paired_random_streams.key('clock_runoff', drive_index, play_index)
        if penalty_controller is not None:
            try:
                pre_penalty = penalty_controller.resolve(
                    phase='pre_snap', state=st, drive_index=drive_index,
                    play_index=play_index)
            except ValueError as exc:
                return halt(f'penalty_resolution_unavailable: {exc}')
            if pre_penalty is not None:
                try:
                    penalty_play, penalty_terminal = _pre_snap_penalty_play(
                        st, pre_penalty, simulation_id, len(plays) + 1, dir_of)
                except ValueError as exc:
                    return halt(f'penalty_transition_unavailable: {exc}')
                plays.append(penalty_play)
                after_penalty = penalty_play['state_after']
                if penalty_terminal is not None:
                    terminal = penalty_terminal
                    break
                st = {'quarter': after_penalty['quarter'], 'clock': after_penalty['clock_seconds'],
                      'offense': after_penalty['offense_team'], 'defense': after_penalty['defense_team'],
                      'down': after_penalty['down'], 'togo': after_penalty['yards_to_go'],
                      'yl': after_penalty['yardline_100']}
                continue
        key = (st['down'], e0.ydstogo_bucket(st['togo']), e0.yardline_bucket(st['yl']))
        source_cell = pool.get(key, [])
        geometry_rejections = 0
        if penalty_controller is not None:
            # Sample only turnover outcomes whose original net gain remains
            # in the field of play in this *simulated* situation. This is a
            # V1.7 research conditional, never a silent V1.6 change.
            legal_cell = [sample for sample in source_cell
                          if _turnover_geometry_eligible(sample, st)]
            geometry_rejections = len(source_cell) - len(legal_cell)
        else:
            legal_cell = source_cell
        cell = sampling_guard.filter_cell(legal_cell, st) if sampling_guard is not None else legal_cell
        if not cell and source_cell:
            return halt(sampling_guard.unavailable_reason())
        if len(cell) < MIN_POOL and not getattr(sampling_policy, 'allow_sparse_cells', False):
            return halt(f'thin pool cell {key} ({len(cell)} observed plays, floor {MIN_POOL}); no fallback')
        field_goal_distance = fg_feasibility.evaluate(st['yl'])
        shares = Counter(ev for ev, _, _, _ in cell
                         if ev != 'field_goal_attempt' or field_goal_distance['eligible'])
        if not shares:
            return halt('no eligible scrimmage or special-teams actions remain in this cell')
        if sampling_policy is None:
            selected_event = event_rng.choices(EVENTS, weights=[shares[e] for e in EVENTS])[0]
            cands = sorted([x for x in cell if x[0] == selected_event],
                           key=lambda x: (x[1]['game_id'], x[1]['play_id']))
            _, row, runoff, spot = row_rng.choice(cands)
        else:
            sampling_state = {'quarter': st['quarter'], 'clock': st['clock'], 'offense': st['offense'],
                              'defense': st['defense'], 'down': st['down'], 'togo': st['togo'],
                              'yl': st['yl'], 'score_diff': score_diff,
                              'field_goal_feasibility': field_goal_distance,
                              '_source_cell_filtered': cell is not source_cell or
                              geometry_rejections > 0}
            if penalty_controller is not None:
                def source_row_filter(sample, target_state):
                    return (_turnover_geometry_eligible(sample, target_state)
                            and (sampling_guard is None or
                                 not sampling_guard.requires_source_filter or
                                 sampling_guard.permits(sample, target_state)))
                sampling_state['_source_row_filter'] = source_row_filter
            elif sampling_guard is not None and sampling_guard.requires_source_filter:
                sampling_state['_source_row_filter'] = sampling_guard.permits
            try:
                selected_event, row, runoff, spot = sampling_policy.sample(
                    playcall_rng, cell, offense=st['offense'], defense=st['defense'], state=sampling_state)
            except SamplingUnavailable as unavailable:
                return halt(str(unavailable))
        event = selected_event
        if penalty_controller is not None and not _turnover_geometry_eligible(
                (selected_event, row, runoff, spot), st):
            return halt('goal_line_fumble_geometry_requires_source_conditional')
        if sampling_guard is not None:
            selected_sample = (selected_event, row, runoff, spot)
            rejection = sampling_guard.rejection_reason(selected_sample, st)
            if rejection:
                return halt(f'timeout_sampling_guard_rejected_source_row:{rejection}')
            if penalty_controller is None:
                sampling_guard.observe(selected_sample, st)
        if event == 'field_goal_attempt' and not field_goal_distance['eligible']:
            return halt('field_goal_attempt_exceeds_historical_feasibility_ceiling')
        kick_outcome = None
        kick_metadata = None
        if special_teams and selected_event in ('punt', 'field_goal_attempt'):
            resolution = special_teams(selected_event, st, row, runoff, spot, special_rng)
            if resolution and resolution.get('blocker'):
                return halt(resolution['blocker'])
            if resolution:
                event = resolution.get('event', selected_event)
                runoff = resolution.get('clock_runoff_seconds', runoff)
                spot = resolution.get('spot', spot)
                kick_outcome = resolution.get('kick_outcome')
                kick_metadata = resolution.get('metadata')
        sampled_yards = None if event in KICK_EVENTS else int(row['yards_gained'])
        yards = 0 if sampled_yards is None else sampled_yards
        yardage_boundary_adjustment = None
        if sampled_yards is not None:
            yards, yardage_boundary_adjustment = _credit_field_boundary_yards(event, sampled_yards, st['yl'])
        try:
            after, play_terminal, flags = reducer.apply_play(st, event, yards, spot, kick_outcome)
        except reducer.UnmodelledOutcome as blocked:
            return halt(blocked.reason)
        except (AssertionError, ValueError) as invalid:
            policy_decisions = getattr(sampling_policy, 'decisions', None)
            sampled_decision = policy_decisions[-1] if isinstance(policy_decisions, list) and policy_decisions else None
            context = {
                'play_index': play_index_start + len(plays),
                'state_before': {**st, 'dir': dir_of(st['offense'], st['quarter'])},
                'decision': {
                    'event': selected_event,
                    'sampling_decision': sampled_decision,
                    'paired_random_stream_keys': stream_keys,
                    'source_play': {key: row.get(key) for key in ('game_id', 'play_id', 'season', 'week')},
                },
                'outcome': {
                    'event_type': event,
                    'sampled_yards_gained': sampled_yards,
                    'credited_yards_gained': yards,
                    'next_snap_spot': spot,
                    'kick_outcome': kick_outcome,
                },
                'state_after': 'not_applied',
            }
            raise football_assertions.FootballAssertionError(
                football_assertions.classify_failure(invalid), str(invalid), context=context) from invalid
        penalty_info = None
        if penalty_controller is not None:
            try:
                source_class = ('kick' if selected_event in ('punt', 'field_goal_attempt')
                                else 'run' if row.get('play_type') == 'run'
                                else 'dropback')
                penalty_info = penalty_controller.resolve(
                    phase='live_ball',
                    state={**st, 'selected_play_class': source_class,
                           'sampled_runoff_seconds': runoff,
                           'sampled_event_terminal': play_terminal,
                           'sampled_event_yards': yards},
                    drive_index=drive_index,
                    play_index=play_index, event=event, after=after,
                    kick_type=('punt' if selected_event == 'punt' else
                               'field_goal' if selected_event == 'field_goal_attempt' else None))
            except ValueError as exc:
                return halt(f'penalty_resolution_unavailable: {exc}')
            if penalty_info is not None and penalty_info.enforcement.get('accepted'):
                # Accepted fouls that nullify the snap remove its touchdown,
                # turnover, return and all player/team play statistics.
                after = dict(penalty_info.state)
                if not penalty_info.play_counts:
                    play_terminal = ('turnover_on_downs' if
                                     penalty_info.enforcement.get('turnover_on_downs') else None)
                    flags = reducer._no_flags()
                    if play_terminal:
                        flags['turnover_on_downs'] = True
                    event = 'penalty'
                    sampled_yards = None
                    yards = 0
                    yardage_boundary_adjustment = None
                else:
                    # Completed passes with roughing keep the play. Receiving
                    # team add-on enforcement keeps the legal punt and its
                    # possession change. Do not turn a punt into another snap.
                    if event == 'punt' and after.get('offense') == st['defense']:
                        play_terminal = 'punt'
                    elif after.get('offense') == st['offense']:
                        play_terminal = None
                    else:
                        return halt('penalty_kept_play_with_possession_change_unsupported')
                runoff = penalty_info.runoff_seconds
        if (sampling_guard is not None and penalty_controller is not None
                and not (penalty_info is not None and
                         penalty_info.enforcement.get('accepted') and not penalty_info.play_counts)):
            # A nullified historical sample did not cause the source play's
            # timeout or personnel state transition.
            sampling_guard.observe(selected_sample, st)
        period_expired = bool(kick_outcome and kick_outcome.get('classification_status') == 'period_expired')
        if clock is not None and penalty_info is None:
            runoff, _, refusal = clock.draw(row, event, play_terminal, st['quarter'], st['clock'],
                                             drive_index=drive_index, play_index=play_index,
                                             force_period_end=period_expired)
            if refusal:
                return halt(f'clock model refused: {refusal}')
        elif period_expired and penalty_info is None:
            # The sampled source outcome says this kick ends the period. Use this simulated state's exact remaining clock.
            runoff = st['clock']
        clock_raw = st['clock'] - runoff
        clock_after = max(0, clock_raw)
        quarter_change = False
        terminal = play_terminal
        # The clock runs out on this play. A play that also hands the ball over still ends at the expiry. In Q1 or Q3 the quarter
        # changes on it and the other team starts the next quarter. In Q2 or Q4 the half or the game ends, and no possession
        # carries over: the next snap is the half-start kickoff.
        clock_expired = clock_after == 0 and play_terminal in (None,) + POSSESSION_TERMINALS
        if clock_expired and st['quarter'] in FLIP_AFTER:
            quarter_change = True  # change of ends; the drive and series continue, no kickoff; a turnover here still ends the drive
        elif clock_expired and st['quarter'] == 2:
            terminal = 'halftime'  # the first-half drive ends; second-half choices and kickoff are not modelled
        elif clock_expired and st['quarter'] == 5:
            terminal = 'end_of_overtime'  # the 10-minute overtime period ends; Rule 16 decides the game
        elif clock_expired:
            terminal = 'end_of_regulation'  # Q4 expiry; a tie goes to overtime (game_state)
        if after is None:  # touchdown, safety, field-goal attempt, halftime, end of regulation: no scrimmage spot
            after = {'offense': st['offense'], 'defense': st['defense'], 'down': None, 'togo': None, 'yl': None}
        ended_by_clock_only = clock_expired and not quarter_change and play_terminal is None  # a possession change keeps its spot
        next_quarter = st['quarter'] + 1 if quarter_change else st['quarter']
        state_clock_after = QUARTER_LENGTH if quarter_change else clock_after
        yl_after = after['yl']
        state_before = {'quarter': st['quarter'], 'clock_seconds': st['clock'], 'offense_team': st['offense'],
                        'defense_team': st['defense'], 'home_score': None, 'away_score': None, 'down': st['down'],
                        'yards_to_go': st['togo'], 'yardline_100': st['yl'], 'home_timeouts': None,
                        'away_timeouts': None, 'drive_index': 1}
        state_after = {'quarter': next_quarter, 'clock_seconds': state_clock_after,
                       'offense_team': after['offense'], 'defense_team': after['defense'], 'home_score': None,
                       'away_score': None, 'down': after['down'], 'yards_to_go': after['togo'],
                       'yardline_100': yl_after, 'home_timeouts': None, 'away_timeouts': None, 'drive_index': 1}
        if terminal is not None:
            state_after['end_of_drive'] = terminal
        if ended_by_clock_only:  # the half or the game is over: no scrimmage state continues
            state_after['down'] = None
            state_after['yards_to_go'] = None
            state_after['yardline_100'] = None
        if selected_event == 'punt':
            decision_type = 'punt'
        elif selected_event == 'field_goal_attempt':
            decision_type = 'field_goal_attempt'
        else:
            decision_type = 'run' if row['play_type'] == 'run' else 'dropback'
        # A half or regulation end has no scrimmage state, so no field endpoint is recorded for it (schema 1.1).
        # The final play's position is kept in outcome.final_play_yardline_100 instead.
        after_has_position = yl_after is not None and not ended_by_clock_only
        after_dir = dir_of(after['offense'], next_quarter) if after_has_position else None
        sequence = len(plays) + 1
        sampling = {'cell': list(key), 'cell_size': len(cell), 'cell_event_counts': dict(shares),
                    'field_goal_feasibility': field_goal_distance}
        if penalty_controller is not None:
            sampling['research_turnover_geometry_rejected_source_rows'] = geometry_rejections
            sampling['research_turnover_geometry_basis'] = (
                'fumble_lost/sack_fumble_lost with cross-goal sampled net gain:'
                ' exclude until recovery-geometry model exists')
        if (sampling_guard is not None and sampling_guard.last_filter['excluded_rows']
                and not sampling_guard.last_filter_reused):
            sampling['timeout_source_filter'] = dict(sampling_guard.last_filter)
        if stream_keys is not None:
            sampling['paired_random_streams'] = stream_keys
        play = {
            'sequence': sequence, 'id': f'{simulation_id}:{sequence}', 'event_type': event,
            'state_before': state_before,
            'sampling': sampling,
            'decision': {'type': decision_type, 'concept': None, 'coverage': None,
                         'note': ('4th-down choice sampled from observed plays in the cell (go-for-it, punt or '
                                  'field-goal attempt)') if st['down'] == 4 else None},
            'outcome': {'passer_id': None, 'receiver_id': None, 'rusher_id': None,
                        'yards_gained': None if event in KICK_EVENTS or event == 'penalty' else yards,
                        'sampled_yards_gained': sampled_yards,
                        'yardage_boundary_adjustment': yardage_boundary_adjustment,
                        'touchdown': flags['touchdown'],
                        'turnover': flags['turnover'] or flags['turnover_on_downs'],
                        'turnover_on_downs': flags['turnover_on_downs'],
                        'punt': flags['punt'], 'punt_attempt': flags['punt_attempt'],
                        'field_goal_attempt': flags['field_goal_attempt'],
                        'safety': flags['safety'], 'scoring_team': flags.get('scoring_team'),
                        'first_down': (flags.get('first_down', False) or bool(
                            penalty_info and penalty_info.enforcement.get('accepted')
                            and penalty_info.enforcement.get('automatic_first_down'))),
                        'clock_runoff_seconds': runoff,
                        'dead_ball_position': (None if after is None else {'offense': after['offense'],
                            'defense': after['defense'], 'down': after['down'], 'togo': after['togo'], 'yl': after['yl']}),
                        'clock_clamped_to_zero': clock_raw < 0,
                        'quarter_change': quarter_change,
                        'clock_only_terminal': ended_by_clock_only,
                        'final_play_yardline_100': yl_after if ended_by_clock_only else None,
                        'sampled_touchdown_flag': bool(row['touchdown'] == 1),
                        # the observed play's penalty flag. The pool excludes penalty plays, so this is False on every
                        # sampled play; a True would be an unmodelled transition and blocks the game (see game_state)
                        'penalty': bool(row.get('penalty') == 1),
                        'sampled_from': {'game_id': row['game_id'], 'play_id': int(row['play_id']),
                                         'game_date': row['game_date']}},
            'state_after': state_after,
            'field': {'assignment_version': 'e1-field-end-v2', 'source': 'authored_demo_orientation',
                      'before': {'dir': dir_of(st['offense'], st['quarter']),
                                 'los': e0.los(dir_of(st['offense'], st['quarter']), st['yl'])},
                      'after': {'dir': after_dir,
                                'los': e0.los(after_dir, yl_after) if after_has_position else None}},
        }
        if penalty_info is not None:
            play['outcome']['penalty'] = True
            play['outcome']['penalty_resolved'] = True
            play['outcome']['penalty_phase'] = 'live_ball'
            play['outcome']['penalty_proposal'] = penalty_info.proposal
            play['outcome']['penalty_ruling'] = penalty_info.ruling
            play['outcome']['penalty_enforcement'] = penalty_info.enforcement
            play['outcome']['penalty_original_event'] = selected_event
            if penalty_info.enforcement.get('accepted') and not penalty_info.play_counts:
                play['outcome']['sampled_touchdown_flag'] = False
                play['outcome']['cancelled_event'] = selected_event
                play['decision']['type'] = 'penalty'
                play['decision']['note'] = 'accepted penalty nullified sampled event'
        cancelled = bool(penalty_info is not None
                         and penalty_info.enforcement.get('accepted')
                         and not penalty_info.play_counts)
        if cancelled and (kick_metadata or kick_outcome):
            play['outcome']['nullified_kick_source'] = {
                'metadata': kick_metadata, 'outcome': kick_outcome}
        else:
            if kick_metadata:
                play['outcome'].update(kick_metadata)
            if kick_outcome:
                play['outcome']['blocked_kick'] = kick_outcome
        if row.get('pre_event') is not None:  # SLC: participants chosen before the outcome; absent for the S0 control
            play['outcome']['pre_event'] = row['pre_event']
        plays.append(play)
        if (quarter_change and kick_outcome is not None
                and kick_outcome.get('classification_status') == 'period_expired'):
            # A period-ending blocked kick has no observed next possession or field position. Q1/Q3 continue the game,
            # so do not carry a null scrimmage state into the next quarter or invent who gets the ball.
            return halt('blocked_kick_period_expired_next_possession_unresolved')
        st = {'quarter': next_quarter, 'offense': after['offense'], 'defense': after['defense'],
              'down': after['down'], 'togo': after['togo'], 'yl': yl_after, 'clock': state_clock_after}
    return plays, terminal


def check_drive(plays, terminal):
    """Fail loudly on any inconsistency. Returns a summary recomputed from the play records."""
    if not plays:
        raise AssertionError('empty drive')
    if plays[-1]['state_after'].get('end_of_drive') != terminal:
        raise AssertionError('last play does not carry the terminal')
    for i, p in enumerate(plays):
        sb, sa, o = p['state_before'], p['state_after'], p['outcome']
        if p['event_type'] in ('run', 'pass_complete', 'pass_incomplete', 'sack', 'sack_fumble_lost'):
            yards = o.get('yards_gained')
            yardline = sb.get('yardline_100')
            if (type(yards) not in (int, float) or type(yardline) not in (int, float)):
                raise AssertionError(f'play {i + 1}: scrimmage gain and spot must be numeric')
            if p['event_type'] == 'pass_incomplete' and yards != 0:
                raise AssertionError(f'play {i + 1}: an incomplete pass must have zero credited gain')
            if p['event_type'] in ('sack', 'sack_fumble_lost') and yards > 0:
                raise AssertionError(f'play {i + 1}: a sack cannot have positive credited gain')
            if p['event_type'] in ('run', 'pass_complete', 'sack', 'sack_fumble_lost') \
                    and (yards > yardline or yardline - yards > 100):
                raise AssertionError(f'play {i + 1}: credited gain crosses a goal line without ending at it')
            sampled_yards = o.get('sampled_yards_gained')
            adjustment = o.get('yardage_boundary_adjustment')
            if sampled_yards is not None and sampled_yards != yards:
                boundary = 'opponent_goal_line' if sampled_yards > yardline else 'own_goal_line'
                credited = yardline if boundary == 'opponent_goal_line' else yardline - 100
                if (not isinstance(adjustment, dict) or adjustment.get('boundary') != boundary
                        or adjustment.get('sampled_yards_gained') != sampled_yards
                        or adjustment.get('credited_yards_gained') != credited or yards != credited):
                    raise AssertionError(f'play {i + 1}: sampled yardage differs without a matching goal-line credit record')
            elif adjustment is not None:
                raise AssertionError(f'play {i + 1}: goal-line adjustment has no changed sampled yardage')
        if i:
            prev = plays[i - 1]['state_after']
            for k in ('quarter', 'offense_team', 'down', 'yards_to_go', 'yardline_100', 'clock_seconds'):
                if sb[k] != prev[k]:
                    raise AssertionError(f'play {i + 1}: state_before.{k} {sb[k]} != previous state_after {prev[k]}')
        if sa['clock_seconds'] < 0:
            raise AssertionError(f'play {i + 1}: negative clock')
        if sa['quarter'] == sb['quarter']:
            if sa['clock_seconds'] > sb['clock_seconds']:
                raise AssertionError(f'play {i + 1}: clock increased within a quarter')
            if o['quarter_change']:
                raise AssertionError(f'play {i + 1}: quarter_change flagged without a quarter change')
        else:
            if sa['quarter'] != sb['quarter'] + 1 or not o['quarter_change'] or sa['clock_seconds'] != QUARTER_LENGTH:
                raise AssertionError(f'play {i + 1}: illegal quarter transition')
            if sa.get('end_of_drive') not in (None,) + POSSESSION_TERMINALS:
                raise AssertionError(f'play {i + 1}: a quarter change can end the drive only with a possession change')
        if sa.get('end_of_drive') in POSSESSION_TERMINALS and sa['quarter'] in (2, 4) and sa['clock_seconds'] == 0:
            raise AssertionError(f'play {i + 1}: a {sa["end_of_drive"]} at the end of Q{sa["quarter"]} ends the half, not the drive')
        if sa.get('end_of_drive') == 'halftime' and (sa['quarter'] != 2 or sa['clock_seconds'] != 0):
            raise AssertionError(f'play {i + 1}: halftime terminal outside the end of Q2')
        if sa.get('end_of_drive') == 'end_of_regulation' and (sa['quarter'] != 4 or sa['clock_seconds'] != 0):
            raise AssertionError(f'play {i + 1}: regulation terminal outside the end of Q4')
        if sa.get('end_of_drive') == 'end_of_overtime' and (sa['quarter'] != 5 or sa['clock_seconds'] != 0):
            raise AssertionError(f'play {i + 1}: overtime terminal outside the end of overtime')
        if i < len(plays) - 1:
            if sa['down'] is None or not 1 <= sa['down'] <= 4 or sa['yardline_100'] is None:
                raise AssertionError(f'play {i + 1}: non-terminal play has no legal down or field')
            if not 0 < sa['yardline_100'] < 100 or sa['yards_to_go'] <= 0:
                raise AssertionError(f'play {i + 1}: illegal field or distance after the play')
        for side in ('before', 'after'):
            los = p['field'][side]['los']
            if los is not None and not 0 <= los <= 100:
                raise AssertionError(f'play {i + 1}: los {side} out of range')
        for side in ('before', 'after'):
            if p['field'][side]['dir'] not in (None, 1, -1):
                raise AssertionError(f'play {i + 1}: direction {side} is not +1 or -1')
        changed = sb['offense_team'] != sa['offense_team']
        if changed != (o['turnover'] or o['punt']):
            raise AssertionError(f'play {i + 1}: possession change does not match the turnover or punt flag')
        if p['event_type'] == 'penalty' and not o.get('penalty_resolved'):
            raise AssertionError(f'play {i + 1}: unadjudicated penalty inserted into game')
        if o['touchdown'] != (sa.get('end_of_drive') == 'touchdown'):
            raise AssertionError(f'play {i + 1}: touchdown flag and terminal disagree')
        if p['event_type'] == 'field_goal_attempt' and o['field_goal_attempt'] != (sa.get('end_of_drive') == 'field_goal_attempt'):
            raise AssertionError(f'play {i + 1}: field-goal flag and terminal disagree')
        if p['event_type'] == 'blocked_field_goal' and not o['field_goal_attempt']:
            raise AssertionError(f'play {i + 1}: blocked field goal is missing its attempt flag')
        if (sa['yardline_100'] is None) != (p['field']['after']['dir'] is None):
            raise AssertionError(f'play {i + 1}: field endpoint and scrimmage state disagree about a position')
        if o['field_goal_attempt'] and p['event_type'] == 'field_goal_attempt' and sa['yardline_100'] is not None:
            raise AssertionError(f'play {i + 1}: a field-goal attempt has no next field position')
        if o['punt'] and sa['yardline_100'] is None:
            raise AssertionError(f'play {i + 1}: a punt must give the receiving spot')
    first_downs = sum(
        1 for p in plays
        if p['outcome'].get('first_down') or (p['state_before']['offense_team'] == p['state_after']['offense_team']
        and p['state_after'].get('end_of_drive') is None and p['state_after']['down'] == 1
        and p['outcome']['yards_gained'] is not None
        and p['outcome']['yards_gained'] >= p['state_before']['yards_to_go']))
    return {'plays': len(plays), 'yards': sum(p['outcome']['yards_gained'] or 0 for p in plays),
            'first_downs': first_downs, 'terminal': terminal, 'touchdown': plays[-1]['outcome']['touchdown'],
            'turnovers': sum(1 for p in plays if p['outcome']['turnover']),
            'punts': sum(1 for p in plays if p['outcome']['punt']),
            'field_goal_attempts': sum(1 for p in plays if p['outcome']['field_goal_attempt']),
            'quarter_changes': sum(1 for p in plays if p['outcome']['quarter_change']),
            'clock_clamped_plays': sum(1 for p in plays if p['outcome']['clock_clamped_to_zero']),
            'clock_runoff_total_seconds': sum(p['outcome']['clock_runoff_seconds'] for p in plays),
            'plays_with_negative_yards': sum(1 for p in plays if (p['outcome']['yards_gained'] or 0) < 0)}


def pool_digest(pool):
    items = sorted((k, ev, r['game_id'], int(r['play_id']), r['play_type'], r['yards_gained'], rn, sp)
                   for k, lst in pool.items() for ev, r, rn, sp in lst)
    return hashlib.sha256(json.dumps(items, default=str).encode()).hexdigest()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--db', default=DEFAULT_DB)
    ap.add_argument('--start', choices=sorted(STARTS), required=True)
    ap.add_argument('--seed', type=int)
    ap.add_argument('--out')
    ap.add_argument('--survey', type=int, default=0, help='run seeds 1..N and print terminal counts only')
    args = ap.parse_args()

    rows = load(args.db)
    pool, excluded = build_pool(rows)
    usable = sum(len(v) for v in pool.values())
    print(f'pool: {usable} observed plays usable for E1 (seasons {POOL_SEASONS[0]}-{POOL_SEASONS[-1]})')
    print('excluded from pool:', dict(excluded))
    start = STARTS[args.start]
    if args.survey:
        counts, reasons = Counter(), Counter()
        for s in range(1, args.survey + 1):
            simulation_id = f'e1-{args.start}-seed{s}'
            plays, terminal = simulate(start, s, pool, simulation_id)
            if plays is None:
                counts['incomplete'] += 1
                reasons[terminal.split(' (')[0]] += 1
            else:
                counts[terminal] += 1
        print(f'survey {args.start} seeds 1..{args.survey}:', dict(counts))
        print('incomplete reasons:', dict(reasons))
        return
    if args.seed is None:
        raise SystemExit('pass --seed or --survey')
    simulation_id = f'e1-{args.start}-seed{args.seed}'
    plays, terminal = simulate(start, args.seed, pool, simulation_id)
    if plays is None:
        raise SystemExit(f'drive incomplete: {terminal}')
    summary = check_drive(plays, terminal)
    record = {
        'schema_version': '1.1', 'mode': 'drive_statistical_demo', 'valid_full_game': False,
        'simulation_id': simulation_id, 'seed': args.seed,
        'model_version': MODEL_VERSION, 'rules_version': RULES_VERSION,
        'start_state': {'source': 'authored demonstration state, not a pregame state', **start},
        'plays': plays,
        'drive': summary,
        'provenance': {'outcomes': 'sampled_empirical_nfl_pbp', 'lineups': None, 'routes': None, 'motion': None,
                       'sources_as_of_verified': False, 'as_of_utc': None, 'snapshot_hash': None},
        'outcome_pool': {'seasons': list(POOL_SEASONS), 'usable_plays': usable,
                         'excluded_from_pool': dict(excluded), 'pool_sha256': pool_digest(pool),
                         'temporal_eligibility': {'status': 'retrospective', 'as_of_date': None,
                                                   'note': 'pool spans 2022-2025 with no as-of cutoff; not an as-of simulation'}},
        'gaps': ['field-goal result (made or missed) is not in the published columns: an attempt ends the drive with no points and '
                 'no next possession. The kickoff after a made kick and the change of possession after a missed kick are not modelled',
                 'clock runoff is the interval between consecutive published snaps in the same quarter, sampled from observed plays. '
                 'It is not a game-clock model: no clock-stop rules, timeouts or two-minute warning. A runoff longer than the '
                 'remaining quarter time is clamped to zero and flagged per play, so the clock shows bookkeeping, not realistic clock behaviour',
                 'extra points, kickoffs, two-point tries: not modelled',
                 'not modelled: kickoff after a score, second-half choices and kickoff, real clock-stop rules (timeouts, two-minute warning, out-of-bounds stoppage), penalties',
                 'score, points and player stats: null; touchdown points are not computed',
                 'participants: null; no pregame roster',
                 'punt yardage is not recorded: a punt gives the receiving spot only',
                 'punt pool excludes return touchdowns, penalties and plays with no following snap',
                 'turnovers that are touchdowns excluded from the pool',
                 'personnel is not conditioned; game time is conditioned only through the derived clock',
                 'halftime: the second-half choices and kickoff are not modelled. Normal simulations give each team one half-opening kickoff; that is an authored simulation default for E2, not a rule that the opposite of the opening receiver kicks',
                 'modelled: change of ends at 0:00 of Q1 and Q3 as bookkeeping (direction flips, the same drive and series continue, the period clock resets to 15:00, no kickoff)',
                 'overtime and tie-breaking: not modelled'],
    }
    text = json.dumps(record, indent=2, sort_keys=True) + '\n'
    if args.out:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(text)
    print(json.dumps({'terminal': terminal, 'drive': summary, 'out': args.out}, indent=2))


if __name__ == '__main__':
    main()
