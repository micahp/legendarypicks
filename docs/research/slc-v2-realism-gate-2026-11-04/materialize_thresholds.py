#!/usr/bin/env python3
"""Materialize SLC v2 observed-only realism thresholds from pinned 2022-2024 inputs.

This script has no season-selection option. It verifies every input hash before opening data,
uses only the explicit 2022, 2023, and 2024 files below, checks row seasons, and refuses any
unexpected season or changed input. It does not load SLC simulation output.

Run from any directory with:
    python3 /root/lp-slc-v1/docs/research/slc-v2-realism-gate-2026-11-04/materialize_thresholds.py

DuckDB is required to read the pinned parquet files. The output JSON is deterministic.
"""
from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
import math
import sys
from collections import Counter, defaultdict
from pathlib import Path
from statistics import mean
from typing import Any, Iterable


ALLOWED_SEASONS = (2022, 2023, 2024)
CALIBRATION_SEASONS = (2023, 2024)
REG_WEEKS = range(1, 19)
REPO_ROOT = Path(__file__).resolve().parents[3]
RAW_ROOT = Path('/root/gridiron-playbooks-research/data/raw')
BACKFILL_ROOT = Path('/root/lp-snapshots/nfl-backfill-2026-10-27/raw')
OUTPUT_DEFAULT = Path(__file__).resolve().parent / 'observed_thresholds.json'

# These digests match the source-hash table in SLC-V2-REALISM-GATES-DRAFT-2026-11-04.md.
# Paths are fixed. No globbing, season discovery, network fetch, or fallback source is allowed.
INPUTS: dict[str, tuple[Path, str]] = {
    'pbp_2022.csv.gz': (RAW_ROOT / 'pbp_2022.csv.gz', '0c69a71eb39498956c7b1d5c1ca52ce7fe679934a95d1af249facb5ea9829ea4'),
    'pbp_2023.csv.gz': (RAW_ROOT / 'pbp_2023.csv.gz', '4649804ee0f0a40b41e51ec75a1ce921949d7fab5459213488656b92f78560e8'),
    'pbp_2024.csv.gz': (RAW_ROOT / 'pbp_2024.csv.gz', '23370d5d10f8104d80d46a1fc5e61f4f6f5a3263fe96fe2dd629913cfcb08c06'),
    'pbp_participation_2023.csv': (RAW_ROOT / 'pbp_participation_2023.csv', 'ad01aeb4045ee19a4f086ff38b52b14c8f427d3401e529c3078a4545921650a9'),
    'pbp_participation_2024.csv': (RAW_ROOT / 'pbp_participation_2024.csv', 'b1f436a98b2a7759eb4ed1181e072a35c2666f9aeb356a49c943d28d6be6b0b9'),
    'players.csv': (RAW_ROOT / 'players.csv', 'c5239e1480b397732d004f81c87dbb07565ff6ea4b2a0e6382cbb7ed35f6481e'),
    'snap_counts_2022.parquet': (BACKFILL_ROOT / 'snap_counts' / 'snap_counts_2022.parquet', '3cfde83eb6d859e3477aba4238fa2fb8e0592a5fc5ab8b26128fce085d4b7fea'),
    'snap_counts_2023.parquet': (BACKFILL_ROOT / 'snap_counts' / 'snap_counts_2023.parquet', '97873cab365dfb39286bc1de3ac772fa4b51f09cce52ae5f8317e006cc007f62'),
    'snap_counts_2024.parquet': (BACKFILL_ROOT / 'snap_counts' / 'snap_counts_2024.parquet', '9ec66a0c755939b329d4eba3f90e716bb874b5a6544f325ba220f003991ff99f'),
    'roster_weekly_2022.parquet': (BACKFILL_ROOT / 'weekly_rosters' / 'roster_weekly_2022.parquet', '063c0da93f612811e1c4a4c12727a56fd2716197864795f15aa2f10a591b00c0'),
    'roster_weekly_2023.parquet': (BACKFILL_ROOT / 'weekly_rosters' / 'roster_weekly_2023.parquet', '0fa5abf9b462a087ecb17f3268ed7233ce9935e95d77be94ad6bac66adf8e281'),
    'roster_weekly_2024.parquet': (BACKFILL_ROOT / 'weekly_rosters' / 'roster_weekly_2024.parquet', '4b144e8eda5a159f36037b02e8b7d5a7861acb65b0816b0a063244992038dcf8'),
    'build_tables.py': (REPO_ROOT / 'docs/research/participation-model-2026-11-02/build_tables.py', '733845e294337f60c9ce0b34bdd68fc2f58b37db7e3c46a1e59b11607e0bcf31'),
    'participation_field.py': (REPO_ROOT / 'scripts/nfl_sequence/participation_field.py', 'ce0d3733370a793922284c89cf1435322105446e5d88b174842bf56b85dffa0f'),
    'playcall_model.py': (REPO_ROOT / 'scripts/nfl_sequence/playcall_model.py', 'b472cb80eb4aa76f418a68cb3aaf5316ab99a2c694520fca8fdacc1f761acbec'),
    'e3_football_realism_joint_reference.py': (REPO_ROOT / 'scripts/nfl_sequence/e3_football_realism_joint_reference.py', '935cbeb1ad4266d957fae1816a7bfbb85b29e76626d5c7751de46ed2e532eb98'),
    'football_realism_eval.py': (REPO_ROOT / 'scripts/nfl_sequence/football_realism_eval.py', '6ec2f03871f3962de95240a5e3db39d58330d6a8f8174e323b33ee8437d124dd'),
}


def refuse_season(season: Any, *, source: str) -> int:
    """Accept only the fixed 2022-2024 window, even if a source has unexpected rows."""
    try:
        value = int(float(season))
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError(f'{source}: missing or invalid season {season!r}') from exc
    if value not in ALLOWED_SEASONS:
        raise ValueError(f'{source}: refusing season {value}; allowed seasons are {ALLOWED_SEASONS}')
    return value


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open('rb') as handle:
        for block in iter(lambda: handle.read(1 << 20), b''):
            digest.update(block)
    return digest.hexdigest()


def verify_inputs() -> dict[str, str]:
    hashes: dict[str, str] = {}
    for name, (path, expected) in INPUTS.items():
        if not path.is_file():
            raise FileNotFoundError(f'missing pinned input {name}: {path}')
        actual = sha256_file(path)
        print(f'input_sha256  {name}  {actual}')
        if actual != expected:
            raise ValueError(f'hash mismatch for {name}: expected {expected}, got {actual}')
        hashes[name] = actual
    return hashes


def integer(value: Any) -> int | None:
    try:
        if value in ('', None):
            return None
        return int(float(value))
    except (TypeError, ValueError, OverflowError):
        return None


def number(value: Any) -> float | None:
    try:
        if value in ('', None):
            return None
        return float(value)
    except (TypeError, ValueError, OverflowError):
        return None


def tvd(left: Counter, right: Counter) -> float:
    n_left, n_right = sum(left.values()), sum(right.values())
    if not n_left or not n_right:
        raise ValueError('TVD requires non-empty distributions on both sides')
    return 0.5 * sum(abs(left.get(key, 0) / n_left - right.get(key, 0) / n_right)
                     for key in set(left) | set(right))


def wasserstein_1(left: Iterable[float], right: Iterable[float]) -> float:
    a = sorted(float(x) for x in left)
    b = sorted(float(x) for x in right)
    if not a or not b:
        raise ValueError('Wasserstein-1 requires non-empty samples on both sides')
    ca, cb = Counter(a), Counter(b)
    support = sorted(set(ca) | set(cb))
    cdf_difference = 0.0
    distance = 0.0
    for index, value in enumerate(support):
        cdf_difference += ca[value] / len(a) - cb[value] / len(b)
        if index + 1 < len(support):
            distance += abs(cdf_difference) * (support[index + 1] - value)
    return distance


def quantile(values: Iterable[float], probability: float) -> float:
    sample = sorted(float(x) for x in values)
    if not sample:
        raise ValueError('quantile requires a non-empty sample')
    rank = (len(sample) - 1) * probability
    low, high = math.floor(rank), math.ceil(rank)
    return sample[low] + (sample[high] - sample[low]) * (rank - low)


def distance_bucket(value: int) -> str:
    bins = ((1, 2, 'd1_2'), (3, 4, 'd3_4'), (5, 6, 'd5_6'),
            (7, 9, 'd7_9'), (10, 14, 'd10_14'), (15, 99, 'd15p'))
    for low, high, label in bins:
        if low <= value <= high:
            return label
    raise ValueError(f'invalid distance {value}')


def field_bucket(value: int) -> str:
    if value >= 80:
        return 'own_deep'
    if value >= 51:
        return 'own_side'
    if value >= 21:
        return 'opp_side'
    if value > 10:
        return 'red_zone'
    return 'goal_line'


def score_bucket(value: int) -> str:
    if value == 0:
        return 'tied'
    magnitude = abs(value)
    band = ('1_2' if magnitude <= 2 else '3' if magnitude == 3 else
            '4_6' if magnitude <= 6 else '7' if magnitude == 7 else
            '8_10' if magnitude <= 10 else '11_14' if magnitude <= 14 else '15p')
    return ('up' if value > 0 else 'dn') + band


def clock_bucket(quarter: int, game_clock: int) -> str | None:
    seconds_in_quarter = game_clock - (4 - quarter) * 900
    if not 0 <= seconds_in_quarter <= 900:
        return None
    if quarter == 1:
        return 'q1'
    if quarter == 3:
        return 'q3'
    if quarter == 2:
        return 'q2_2min' if seconds_in_quarter <= 120 else 'q2'
    return 'q4_2min' if seconds_in_quarter <= 120 else 'q4_late' if seconds_in_quarter <= 300 else 'q4'


def team_position_group(position: str | None) -> str:
    value = (position or '').upper()
    if value in {'QB', 'RB', 'FB', 'TE', 'WR'}:
        return value
    if value in {'C', 'G', 'T', 'OT', 'OG', 'OL'}:
        return 'OL'
    return 'OTHER'


def coverage_position_group(position: str | None) -> str:
    """Weekly roster labels combine some FBs with RB; the interval strata do too."""
    value = (position or '').upper()
    if value == 'FB':
        return 'RB'
    return team_position_group(value)


def load_player_crosswalk() -> tuple[dict[str, str], dict[str, str], dict[str, str]]:
    path = INPUTS['players.csv'][0]
    gsis_to_pfr: dict[str, str] = {}
    pfr_to_gsis: dict[str, str] = {}
    gsis_position: dict[str, str] = {}
    with path.open(encoding='utf-8', newline='') as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            # Only identity and position fields are used. Season/status/team fields are ignored.
            gsis, pfr = row.get('gsis_id'), row.get('pfr_id')
            position = row.get('position') or ''
            if gsis and pfr:
                if pfr in pfr_to_gsis and pfr_to_gsis[pfr] != gsis:
                    raise ValueError(f'duplicate PFR identity {pfr}')
                gsis_to_pfr[gsis] = pfr
                pfr_to_gsis[pfr] = gsis
            if gsis and position:
                gsis_position[gsis] = position
    return gsis_to_pfr, pfr_to_gsis, gsis_position


def load_pbp() -> tuple[dict, dict, dict, dict, dict, dict, dict, dict]:
    """Load only the three hash-pinned regular-season PBP releases."""
    pbp_by_play: dict[tuple[str, str], dict] = {}
    week_team_game: dict[tuple[int, int, str], str] = {}
    situation_counts: dict[tuple[int, tuple], Counter] = defaultdict(Counter)
    pass_run_calls: dict[tuple[int, str, str], Counter] = defaultdict(Counter)
    identified_targets: Counter = Counter()
    targets_by_player: dict[tuple[int, str, str], Counter] = defaultdict(Counter)
    opportunities: Counter = Counter()
    player_lines: dict[tuple[int, str, str, str], Counter] = defaultdict(Counter)

    for season in ALLOWED_SEASONS:
        refuse_season(season, source='PBP season loop')
        path = INPUTS[f'pbp_{season}.csv.gz'][0]
        with gzip.open(path, 'rt', encoding='utf-8', newline='') as handle:
            for row in csv.DictReader(handle):
                row_season = refuse_season(row.get('season'), source=path.name)
                if row_season != season:
                    raise ValueError(f'{path.name}: row season {row_season} does not match file season {season}')
                week = integer(row.get('week'))
                if row.get('season_type') != 'REG' or week not in REG_WEEKS:
                    continue
                game = row.get('game_id') or ''
                team = row.get('posteam') or ''
                play_id = str(row.get('play_id') or '').split('.')[0]
                play_type = row.get('play_type') or ''
                if not game:
                    continue
                if team:
                    week_team_game[(season, week, team)] = game
                record = {
                    'season': season, 'week': week, 'game': game, 'team': team, 'play_id': play_id,
                    'play_type': play_type, 'quarter': integer(row.get('qtr')),
                    'down': integer(row.get('down')), 'distance': integer(row.get('ydstogo')),
                    'yardline': integer(row.get('yardline_100')),
                    'clock': integer(row.get('game_seconds_remaining')),
                    'score_diff': integer(row.get('score_differential')),
                    'pass_attempt': integer(row.get('pass_attempt')),
                    'rush_attempt': integer(row.get('rush_attempt')),
                    'receiver': row.get('receiver_player_id') or None,
                    'rusher': row.get('rusher_player_id') or None,
                    'passer': row.get('passer_player_id') or None,
                    'complete_pass': integer(row.get('complete_pass')),
                    'yards': number(row.get('yards_gained')),
                    'pass_td': integer(row.get('pass_touchdown')),
                    'rush_td': integer(row.get('rush_touchdown')),
                    'td_player': row.get('td_player_id') or None,
                }
                pbp_by_play[(game, play_id)] = record
                if not team:
                    continue

                action = {
                    'pass': 'pass', 'qb_spike': 'pass', 'run': 'run', 'qb_kneel': 'run',
                    'punt': 'punt', 'field_goal': 'field_goal',
                }.get(play_type)
                if action:
                    q, down, togo = record['quarter'], record['down'], record['distance']
                    yline, score, game_clock = record['yardline'], record['score_diff'], record['clock']
                    if (q is not None and 1 <= q <= 4 and down is not None and 1 <= down <= 4
                            and togo is not None and 1 <= togo <= 99
                            and yline is not None and 0 <= yline <= 99
                            and score is not None and game_clock is not None and game_clock >= 0):
                        clock = clock_bucket(q, game_clock)
                        if clock:
                            context = (q, down, distance_bucket(togo), field_bucket(yline),
                                       score_bucket(score), clock)
                            situation_counts[(season, context)][action] += 1

                if play_type in {'pass', 'qb_spike'}:
                    pass_run_calls[(season, game, team)]['pass'] += 1
                if play_type in {'run', 'qb_kneel'}:
                    pass_run_calls[(season, game, team)]['run'] += 1

                receiver = record['receiver']
                rusher = record['rusher']
                passer = record['passer']
                if record['pass_attempt'] == 1 and receiver:
                    identified_targets[(season, game, team)] += 1
                    targets_by_player[(season, game, team)][receiver] += 1
                    opportunities[(season, game, team, receiver)] += 1
                    player_lines[(season, game, team, receiver)]['targets'] += 1
                if record['rush_attempt'] == 1 and rusher:
                    opportunities[(season, game, team, rusher)] += 1
                    player_lines[(season, game, team, rusher)]['rushing_attempts'] += 1
                    if record['yards'] is not None:
                        player_lines[(season, game, team, rusher)]['rushing_yards'] += record['yards']
                if record['pass_attempt'] == 1 and passer:
                    player_lines[(season, game, team, passer)]['passing_attempts'] += 1
                if record['complete_pass'] == 1 and receiver:
                    player_lines[(season, game, team, receiver)]['receptions'] += 1
                    if record['yards'] is not None:
                        player_lines[(season, game, team, receiver)]['receiving_yards'] += record['yards']
                if record['td_player'] and (record['pass_td'] == 1 or record['rush_td'] == 1):
                    player_lines[(season, game, team, record['td_player'])]['offensive_touchdowns'] += 1

    return (pbp_by_play, week_team_game, situation_counts, pass_run_calls,
            identified_targets, targets_by_player, opportunities, player_lines)


def load_participation(pbp_by_play: dict) -> tuple[dict, dict, dict]:
    # Local import keeps the hash-pinned builder and decoder as the grouping authority.
    sys.path.insert(0, str(REPO_ROOT / 'docs/research/participation-model-2026-11-02'))
    sys.path.insert(0, str(REPO_ROOT / 'scripts/nfl_sequence'))
    from build_tables import group_code, line_and_qb, nonstandard_offense, parse_personnel
    from participation_field import group_counts

    packages: dict[tuple[int, str], Counter] = defaultdict(Counter)
    rb_only: dict[tuple[int, str], Counter] = defaultdict(Counter)
    accepted_rows: Counter = Counter()
    for season in CALIBRATION_SEASONS:
        refuse_season(season, source='participation season loop')
        path = INPUTS[f'pbp_participation_{season}.csv'][0]
        with path.open(encoding='utf-8', newline='') as handle:
            for row in csv.DictReader(handle):
                key = (row.get('nflverse_game_id') or '', str(row.get('play_id') or '').split('.')[0])
                play = pbp_by_play.get(key)
                if not play or play['season'] != season or play['play_type'] not in {'run', 'pass'}:
                    continue
                team = play['team']
                if not team:
                    continue
                counts, defensive_label = parse_personnel(row.get('offense_personnel') or '')
                if not counts or defensive_label:
                    continue
                try:
                    code = group_code(counts)
                    group_counts(code)
                except (TypeError, ValueError):
                    continue
                if nonstandard_offense(counts):
                    continue
                packages[(season, team)][code] += 1
                accepted_rows[season] += 1
                line, qbs = line_and_qb(counts)
                rb_only_code = (f"{counts.get('RB', 0)}-{counts.get('FB', 0)}-"
                                f"{counts.get('TE', 0)}-{counts.get('WR', 0)}")
                if line != 5:
                    rb_only_code += f'-OL{line}'
                if qbs != 1:
                    rb_only_code += f'-QB{qbs}'
                rb_only[(season, team)][rb_only_code] += 1
    return packages, rb_only, accepted_rows


def metric_1(packages: dict, rb_only: dict, accepted_rows: Counter) -> dict:
    teams = sorted({team for season, team in packages if season == 2023}
                   & {team for season, team in packages if season == 2024})
    if len(teams) != 32:
        raise ValueError(f'metric 1 expected 32 common teams, found {len(teams)}')
    distances = [tvd(packages[(2023, team)], packages[(2024, team)]) for team in teams]
    sensitivity = [tvd(rb_only[(2023, team)], rb_only[(2024, team)]) for team in teams]
    return {
        'T_personnel': mean(distances),
        'T_personnel_RB_only_sensitivity': mean(sensitivity),
        'team_count': len(teams),
        'accepted_grouped_plays': {str(year): accepted_rows[year] for year in CALIBRATION_SEASONS},
    }


def metric_2(situation_counts: dict) -> dict:
    by_context: dict[tuple, dict[int, Counter]] = defaultdict(dict)
    eligible = Counter()
    for (season, context), actions in situation_counts.items():
        by_context[context][season] = actions
        eligible[season] += sum(actions.values())
    supported = [context for context, folds in by_context.items()
                 if all(sum(folds.get(year, Counter()).values()) >= 30 for year in CALIBRATION_SEASONS)]
    if not supported:
        raise ValueError('metric 2 has no shared situation cells at the 30-action floor')
    weighted_distances = []
    weights = []
    for context in supported:
        a, b = by_context[context][2023], by_context[context][2024]
        weights.append((sum(a.values()) + sum(b.values())) / 2)
        weighted_distances.append(tvd(a, b))
    t_situation = sum(w * d for w, d in zip(weights, weighted_distances)) / sum(weights)
    support_share = {
        str(year): sum(sum(by_context[context][year].values()) for context in supported) / eligible[year]
        for year in CALIBRATION_SEASONS
    }
    return {
        'T_situation': t_situation,
        'supported_contexts': len(supported),
        'minimum_supported_decision_share': min(support_share.values()),
        'supported_decision_share_by_fold': support_share,
        'eligible_decisions_by_fold': {str(y): eligible[y] for y in CALIBRATION_SEASONS},
    }


def metric_3(identified_targets: Counter, targets_by_player: dict) -> dict:
    shares: dict[int, dict[str, list[float]]] = {year: defaultdict(list) for year in CALIBRATION_SEASONS}
    team_game_counts = Counter()
    for (season, game, team), total in identified_targets.items():
        if season not in CALIBRATION_SEASONS or total <= 0:
            continue
        counts = targets_by_player[(season, game, team)]
        shares[season][team].append(max(counts.values()) / total)
        team_game_counts[season] += 1
    terms = []
    for team in sorted(set(shares[2023]) & set(shares[2024])):
        if min(len(shares[2023][team]), len(shares[2024][team])) < 10:
            raise ValueError(f'metric 3 team {team} has fewer than 10 supported team-games')
        terms.extend(abs(quantile(shares[2023][team], p) - quantile(shares[2024][team], p))
                     for p in (0.10, 0.50, 0.90))
    if len(terms) != 96:
        raise ValueError(f'metric 3 expected 96 team-quantile terms, found {len(terms)}')
    return {
        'T_top': mean(terms),
        'team_count': len(set(shares[2023]) & set(shares[2024])),
        'team_games_with_identified_targets': {str(y): team_game_counts[y] for y in CALIBRATION_SEASONS},
        'quantile_terms': len(terms),
    }


def load_snap_and_rosters(pfr_to_gsis: dict[str, str], gsis_to_pfr: dict[str, str],
                          gsis_position: dict[str, str], week_team_game: dict):
    try:
        import duckdb
    except ImportError as exc:
        raise RuntimeError('DuckDB is required to read the pinned parquet inputs') from exc

    connection = duckdb.connect(':memory:')
    snaps: dict[tuple[int, str, str, str], dict] = {}
    team_games: dict[int, set[tuple[str, str]]] = {year: set() for year in CALIBRATION_SEASONS}
    snap_week_team_game: dict[tuple[int, int, str], str] = {}
    snap_values: dict[int, list[float]] = {year: [] for year in CALIBRATION_SEASONS}
    snap_by_position: dict[int, dict[str, list[float]]] = {
        year: defaultdict(list) for year in CALIBRATION_SEASONS
    }
    snap_share_by_gsis: dict[tuple[int, str, str, str], float] = {}

    for year in ALLOWED_SEASONS:
        refuse_season(year, source='snap-count season loop')
        path = INPUTS[f'snap_counts_{year}.parquet'][0]
        sql_path = str(path).replace("'", "''")
        rows = connection.execute(
            f"SELECT season, game_id, week, game_type, pfr_player_id, position, team, "
            f"offense_snaps, offense_pct FROM read_parquet('{sql_path}') "
            "WHERE game_type='REG' AND week BETWEEN 1 AND 18"
        ).fetchall()
        for row_season, game, week, game_type, pfr, position, team, off_snaps, off_pct in rows:
            observed_year = refuse_season(row_season, source=path.name)
            if observed_year != year:
                raise ValueError(f'{path.name}: row season {observed_year} does not match file season {year}')
            if not game or not team:
                continue
            if year in CALIBRATION_SEASONS:
                team_games[year].add((game, team))
            if week is not None:
                snap_week_team_game[(year, int(week), team)] = game
            player_snaps = float(off_snaps or 0.0)
            share = None if off_pct is None else float(off_pct)
            if pfr:
                snaps[(year, game, team, pfr)] = {
                    'position': position or '', 'snaps': player_snaps, 'share': share,
                }
                gsis = pfr_to_gsis.get(pfr)
                if gsis and share is not None:
                    snap_share_by_gsis[(year, game, team, gsis)] = share
            if year in CALIBRATION_SEASONS and player_snaps > 0 and share is not None:
                snap_values[year].append(share)
                snap_by_position[year][team_position_group(position)].append(share)

    roster_rows: dict[int, list[dict]] = {year: [] for year in ALLOWED_SEASONS}
    for year in ALLOWED_SEASONS:
        refuse_season(year, source='roster season loop')
        path = INPUTS[f'roster_weekly_{year}.parquet'][0]
        sql_path = str(path).replace("'", "''")
        rows = connection.execute(
            f"SELECT season, week, team, gsis_id, position, status, game_type "
            f"FROM read_parquet('{sql_path}') WHERE game_type='REG' AND week BETWEEN 1 AND 18 "
            "AND status='ACT'"
        ).fetchall()
        for row_season, week, team, gsis, position, status, game_type in rows:
            observed_year = refuse_season(row_season, source=path.name)
            if observed_year != year:
                raise ValueError(f'{path.name}: row season {observed_year} does not match file season {year}')
            if week not in REG_WEEKS or not team or not gsis:
                continue
            game = week_team_game.get((year, int(week), team))
            if not game:
                continue
            roster_rows[year].append({
                'year': year, 'game': game, 'team': team, 'gsis': gsis,
                'position': position or '', 'role': coverage_position_group(position),
                'offensive_snap_share': snap_share_by_gsis.get((year, game, team, gsis), 0.0),
            })

    connection.close()
    return (snaps, team_games, snap_week_team_game, snap_values, snap_by_position,
            snap_share_by_gsis, roster_rows)


def metric_4(snaps: dict, team_games: dict, roster_rows: dict, gsis_to_pfr: dict,
             gsis_position: dict, opportunities: Counter) -> dict:
    ranked: dict[int, dict[tuple[str, str], list[tuple[str, float]]]] = {
        year: defaultdict(list) for year in CALIBRATION_SEASONS
    }
    excluded = {str(year): Counter() for year in CALIBRATION_SEASONS}
    for year in CALIBRATION_SEASONS:
        for row in roster_rows[year]:
            if row['position'].upper() != 'RB':
                continue
            gsis, game, team = row['gsis'], row['game'], row['team']
            pfr = gsis_to_pfr.get(gsis)
            if not pfr:
                excluded[str(year)]['missing_pfr_identity'] += 1
                continue
            snap_row = snaps.get((year, game, team, pfr))
            observed_position = (snap_row['position'] if snap_row else gsis_position.get(gsis, row['position'])).upper()
            if observed_position == 'FB':
                excluded[str(year)]['fullback_excluded'] += 1
                continue
            if observed_position != 'RB':
                excluded[str(year)]['position_unresolved_or_other'] += 1
                continue
            ranked[year][(game, team)].append((gsis, snap_row['snaps'] if snap_row else 0.0))

    values: dict[int, dict[tuple[str, str], tuple[float, int]]] = {year: {} for year in CALIBRATION_SEASONS}
    for year in CALIBRATION_SEASONS:
        if len(team_games[year]) != 544:
            raise ValueError(f'metric 4 expected 544 team-games in {year}, got {len(team_games[year])}')
        for game, team in team_games[year]:
            players = sorted(ranked[year].get((game, team), []), key=lambda item: (-item[1], item[0]))
            if len(players) < 2:
                values[year][(game, team)] = (0.0, 0)
                continue
            gsis, snap_count = players[1]
            opportunities_count = opportunities[(year, game, team, gsis)]
            values[year][(game, team)] = (snap_count, opportunities_count)

    appear_rate = {
        year: mean(float(snap_count > 0) for snap_count, _ in values[year].values())
        for year in CALIBRATION_SEASONS
    }
    return {
        'T_RB2_appears': abs(appear_rate[2023] - appear_rate[2024]),
        'T_RB2_snaps': wasserstein_1(
            [value[0] for value in values[2023].values()], [value[0] for value in values[2024].values()]),
        'T_RB2_opportunities': wasserstein_1(
            [value[1] for value in values[2023].values()], [value[1] for value in values[2024].values()]),
        'appearance_rate_by_fold': {str(y): appear_rate[y] for y in CALIBRATION_SEASONS},
        'team_games_by_fold': {str(y): len(values[y]) for y in CALIBRATION_SEASONS},
        'position_exclusions': {year: dict(counts) for year, counts in excluded.items()},
    }


def metric_5(snap_values: dict, snap_by_position: dict) -> dict:
    t_all = wasserstein_1(snap_values[2023], snap_values[2024])
    supported_positions = sorted(
        position for position in set(snap_by_position[2023]) & set(snap_by_position[2024])
        if min(len(snap_by_position[2023][position]), len(snap_by_position[2024][position])) >= 100
    )
    per_position = {
        position: {
            'n_2023': len(snap_by_position[2023][position]),
            'n_2024': len(snap_by_position[2024][position]),
            'W1': wasserstein_1(snap_by_position[2023][position], snap_by_position[2024][position]),
        }
        for position in sorted(set(snap_by_position[2023]) & set(snap_by_position[2024]))
    }
    return {
        'T_snap_all': t_all,
        'T_snap_position': max(per_position[position]['W1'] for position in supported_positions),
        'supported_position_groups': supported_positions,
        'positive_snap_player_games': {str(y): len(snap_values[y]) for y in CALIBRATION_SEASONS},
        'position_detail': per_position,
    }


def metric_6(snaps: dict, pass_run_calls: dict, identified_targets: Counter,
             targets_by_player: dict, pfr_to_gsis: dict) -> dict:
    def pass_bin(value: float) -> int:
        return 0 if value <= .40 else 1 if value <= .50 else 2 if value <= .60 else 3 if value <= .70 else 4

    def snap_bin(value: float) -> int:
        return 0 if value <= .10 else 1 if value <= .25 else 2 if value <= .50 else 3 if value <= .75 else 4

    def target_bin(value: float) -> int:
        return 0 if value == 0 else 1 if value <= .05 else 2 if value <= .10 else 3 if value <= .20 else 4 if value <= .35 else 5

    histograms = {year: Counter() for year in CALIBRATION_SEASONS}
    sample_counts = Counter()
    supported_positions = {'RB', 'FB', 'TE', 'WR'}
    for year in CALIBRATION_SEASONS:
        for (snap_year, game, team, pfr), row in snaps.items():
            if snap_year != year or row['snaps'] <= 0 or row['position'].upper() not in supported_positions:
                continue
            gsis = pfr_to_gsis.get(pfr)
            total_targets = identified_targets[(year, game, team)]
            calls = pass_run_calls[(year, game, team)]
            call_total = calls['pass'] + calls['run']
            if not gsis or not total_targets or not call_total:
                continue
            player_targets = targets_by_player[(year, game, team)].get(gsis, 0)
            target_share = player_targets / total_targets
            pass_rate = calls['pass'] / call_total
            cell = (pass_bin(pass_rate), snap_bin(row['share']), target_bin(target_share))
            histograms[year][cell] += 1
            sample_counts[year] += 1
    return {
        'T_joint': tvd(histograms[2023], histograms[2024]),
        'skill_player_games': {str(y): sample_counts[y] for y in CALIBRATION_SEASONS},
        'nonempty_joint_bins': {str(y): len(histograms[y]) for y in CALIBRATION_SEASONS},
    }


def metric_7(roster_rows: dict, player_lines: dict) -> dict:
    specifications = {
        'offensive_snap_share': ('QB', 'RB', 'TE', 'WR', 'OL', 'OTHER'),
        'passing_attempts': ('QB',),
        'rushing_attempts': ('QB', 'RB', 'TE', 'WR'),
        'rushing_yards': ('QB', 'RB', 'TE', 'WR'),
        'targets': ('RB', 'TE', 'WR'),
        'receptions': ('RB', 'TE', 'WR'),
        'receiving_yards': ('RB', 'TE', 'WR'),
        'offensive_touchdowns': ('QB', 'RB', 'TE', 'WR'),
    }
    rows_by_season = {year: roster_rows[year] for year in ALLOWED_SEASONS}
    for year in ALLOWED_SEASONS:
        for row in rows_by_season[year]:
            stats = player_lines[(year, row['game'], row['team'], row['gsis'])]
            for stat in specifications:
                if stat != 'offensive_snap_share':
                    row[stat] = stats.get(stat, 0)

    folds: dict[str, dict] = {}
    for test_year, train_years in ((2023, (2022,)), (2024, (2022, 2023))):
        fold: dict[str, dict] = {}
        for stat, roles in specifications.items():
            train_by_role: dict[str, list[float]] = defaultdict(list)
            for train_year in train_years:
                refuse_season(train_year, source='metric 7 training fold')
                for row in rows_by_season[train_year]:
                    if row['role'] in roles:
                        train_by_role[row['role']].append(row[stat])
            covered = total = 0
            role_details = {}
            for role in roles:
                training = train_by_role.get(role, [])
                if not training:
                    test_role_count = sum(row['role'] == role for row in rows_by_season[test_year])
                    if test_role_count:
                        raise ValueError(f'metric 7 has test rows for unsupported role {role} in {test_year}')
                    continue
                low, high = quantile(training, .10), quantile(training, .90)
                held_out = [row for row in rows_by_season[test_year] if row['role'] == role]
                count_covered = sum(low <= row[stat] <= high for row in held_out)
                covered += count_covered
                total += len(held_out)
                role_details[role] = {
                    'training_player_games': len(training),
                    'held_out_player_games': len(held_out),
                    'covered': count_covered,
                    'p10': low,
                    'p90': high,
                }
            if total < 100:
                raise ValueError(f'metric 7 {stat} has only {total} held-out lines in {test_year}')
            fold[stat] = {
                'coverage': covered / total,
                'covered': covered,
                'player_game_lines': total,
                'training_player_games': sum(len(values) for values in train_by_role.values()),
                'game_clusters': len({row['game'] for row in rows_by_season[test_year]
                                      if row['role'] in roles}),
                'position_role_detail': role_details,
            }
        folds[str(test_year)] = fold

    envelopes = {}
    for stat in specifications:
        first, second = folds['2023'][stat]['coverage'], folds['2024'][stat]['coverage']
        envelopes[stat] = {
            'lower': min(first, second), 'upper': max(first, second),
            'coverage_2023': first, 'coverage_2024': second,
        }
    return {
        'coverage_envelopes': envelopes,
        'fold_details': folds,
        'active_roster_player_games': {str(y): len(rows_by_season[y]) for y in ALLOWED_SEASONS},
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=OUTPUT_DEFAULT,
                        help='output JSON path; inputs and seasons are fixed')
    args = parser.parse_args()

    input_hashes = verify_inputs()
    gsis_to_pfr, pfr_to_gsis, gsis_position = load_player_crosswalk()
    (pbp_by_play, week_team_game, situation_counts, pass_run_calls,
     identified_targets, targets_by_player, opportunities, player_lines) = load_pbp()
    packages, rb_only, accepted_personnel_rows = load_participation(pbp_by_play)
    metric1_result = metric_1(packages, rb_only, accepted_personnel_rows)
    metric2_result = metric_2(situation_counts)
    metric3_result = metric_3(identified_targets, targets_by_player)
    (snaps, team_games, _snap_week_team_game, snap_values, snap_by_position,
     snap_share_by_gsis, roster_rows) = load_snap_and_rosters(
         pfr_to_gsis, gsis_to_pfr, gsis_position, week_team_game)
    metric4_result = metric_4(snaps, team_games, roster_rows, gsis_to_pfr, gsis_position, opportunities)
    metric5_result = metric_5(snap_values, snap_by_position)
    metric6_result = metric_6(snaps, pass_run_calls, identified_targets, targets_by_player, pfr_to_gsis)
    metric7_result = metric_7(roster_rows, player_lines)

    result = {
        'schema': 'lp.nfl.slc-v2-observed-realism-thresholds.v1',
        'calibration_seasons': list(CALIBRATION_SEASONS),
        'allowed_source_seasons': list(ALLOWED_SEASONS),
        'season_policy': 'Fixed explicit files only; row season is validated; no other season is accepted.',
        'threshold_method': {
            'distance_gates': 'Point statistic between observed 2023 and observed 2024; no candidate simulation data.',
            'coverage': 'For 2023, fit on 2022. For 2024, fit on 2022-2023. Envelope is min/max held-out coverage.',
            'quantile': 'Linear interpolation at rank (n-1)*p.',
            'tvd': '0.5 times the sum of absolute differences in normalized cell shares.',
            'wasserstein_1': 'Integral of absolute empirical CDF difference in the native unit.',
        },
        'thresholds': {
            'metric_1': metric1_result,
            'metric_2': metric2_result,
            'metric_3': metric3_result,
            'metric_4': metric4_result,
            'metric_5': metric5_result,
            'metric_6': metric6_result,
        },
        'metric_7': metric7_result,
        'input_sha256': input_hashes,
        'simulation_outputs_read': False,
    }
    output = args.output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + '\n', encoding='utf-8')
    print(f'output_json  {output}')
    print(json.dumps({
        'metric_1': {'T_personnel': metric1_result['T_personnel'],
                     'T_personnel_RB_only_sensitivity': metric1_result['T_personnel_RB_only_sensitivity']},
        'metric_2': {'T_situation': metric2_result['T_situation'],
                     'minimum_supported_decision_share': metric2_result['minimum_supported_decision_share']},
        'metric_3': {'T_top': metric3_result['T_top']},
        'metric_4': {k: metric4_result[k] for k in ('T_RB2_appears', 'T_RB2_snaps', 'T_RB2_opportunities')},
        'metric_5': {k: metric5_result[k] for k in ('T_snap_all', 'T_snap_position')},
        'metric_6': {'T_joint': metric6_result['T_joint']},
        'metric_7_envelopes': metric7_result['coverage_envelopes'],
    }, indent=2, sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
