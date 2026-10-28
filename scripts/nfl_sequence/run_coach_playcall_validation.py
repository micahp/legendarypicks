"""Historical-only coaching feature experiment for the play-call model.

This runner has a single fixed window: train on 2010-2022, choose the added
coach-by-down/distance penalty on 2023, and report only that validation year.
It never loads later-season play-by-play or scoring files.
"""
import argparse
import csv
import hashlib
import json
import sqlite3
import sys
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np
from scipy import sparse

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import playcall_model as pm  # noqa: E402
import playcall_observations as pco  # noqa: E402

TRAIN_FIRST = 2010
TRAIN_LAST = 2022
VALIDATION = 2023
SCHEDULE_AS_OF = '2024-01-15'
SCHEDULE_COMMIT = '9f757c1db27b61966c30956fce4b9b78dc3f274a'
SCHEDULE_SHA256 = '7e74008b2f5a17be41a75426980da2131284c6e435247616a9f607901d35d029'
SCHEDULE_URL = (
    'https://github.com/nflverse/nfldata/blob/' + SCHEDULE_COMMIT + '/data/games.csv'
)
SCHEDULE_RAW_URL = (
    'https://raw.githubusercontent.com/nflverse/nfldata/' + SCHEDULE_COMMIT + '/data/games.csv'
)
CALLER_AS_OF = '2023-12-22'
CALLER_COMMIT = '65827e24649ef606d3c052236f2250f771e28b96'
CALLER_SHA256 = 'a048a51ed8153365c709484eab4fbc8462dd9c46af8eadd3fe2250e6418cf85e'
CALLER_URL = (
    'https://github.com/samhoppen/NFL_public/blob/' + CALLER_COMMIT + '/data/all_playcallers.csv'
)
CALLER_RAW_URL = (
    'https://raw.githubusercontent.com/samhoppen/NFL_public/' + CALLER_COMMIT + '/data/all_playcallers.csv'
)
COACH_GROUP = 'caller_down_dist'
PENALTY_GRID = (0.3, 3.0, 30.0, 300.0)
BASE_PENALTY_GRID = (0.3, 3.0, 30.0, 300.0)
TAU_GRID = (None, 6.0, 3.0)


def sha256(path):
    digest = hashlib.sha256()
    with open(path, 'rb') as source:
        for block in iter(lambda: source.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def verify_source(path, expected):
    actual = sha256(path)
    if actual != expected:
        raise ValueError(f'published source checksum mismatch for {path}: {actual}')


def historical_alias(season, team):
    """Translate published caller-file franchise labels to the schedule's era label."""
    if team == 'WSH':
        return 'WAS'
    if team == 'LAR':
        return 'STL' if season <= 2015 else 'LA'
    if team == 'LA' and season <= 2015:
        return 'STL'
    if team == 'LAC' and season <= 2016:
        return 'SD'
    if team == 'LV' and season <= 2019:
        return 'OAK'
    return team


def load_schedule(path):
    games = {}
    with open(path, newline='') as source:
        for row in csv.DictReader(source):
            season = int(row['season'])
            if not TRAIN_FIRST <= season <= VALIDATION or row['game_type'] != 'REG':
                continue
            games[row['game_id']] = row
    if not games:
        raise ValueError('no regular-season schedule rows in the fixed historical window')
    return games


def load_callers(path, games):
    candidates = defaultdict(set)
    unmapped_rows = 0
    with open(path, newline='') as source:
        for row in csv.DictReader(source):
            season = int(row['season'])
            if not TRAIN_FIRST <= season <= VALIDATION:
                continue
            game = games.get(row['game_id'])
            if game is None:
                continue
            team = historical_alias(season, row['team'])
            if team not in (game['home_team'], game['away_team']):
                unmapped_rows += 1
                continue
            caller = row['off_play_caller'].strip()
            if caller:
                candidates[(row['game_id'], team)].add(caller)
    callers, conflicts = {}, 0
    for key, names in candidates.items():
        if len(names) == 1:
            callers[key] = next(iter(names))
        else:
            conflicts += 1
    return callers, conflicts, unmapped_rows


def build_ledger(schedule_path, caller_path, output_path):
    games = load_schedule(schedule_path)
    callers, caller_conflicts, unmapped_caller_rows = load_callers(caller_path, games)
    team_games = defaultdict(list)
    for game_id, game in games.items():
        season = int(game['season'])
        for side in ('home', 'away'):
            team = game[f'{side}_team']
            team_games[(season, team)].append({
                'game_id': game_id,
                'head_coach': game[f'{side}_coach'].strip(),
                'off_play_caller': callers.get((game_id, team), ''),
            })

    fields = (
        'season', 'team', 'regular_season_games', 'head_coach_games_known',
        'head_coach_names', 'head_coach_game_counts', 'off_play_caller_games_known',
        'off_play_caller_names', 'off_play_caller_game_counts',
        'head_coach_source_url', 'head_coach_source_as_of', 'head_coach_source_sha256',
        'play_caller_source_url', 'play_caller_source_as_of', 'play_caller_source_sha256',
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, 'w', newline='') as target:
        writer = csv.DictWriter(target, fieldnames=fields)
        writer.writeheader()
        for (season, team), rows in sorted(team_games.items()):
            hc_counts = Counter(row['head_coach'] for row in rows if row['head_coach'])
            oc_counts = Counter(row['off_play_caller'] for row in rows if row['off_play_caller'])
            hcs, ocs = sorted(hc_counts), sorted(oc_counts)
            writer.writerow({
                'season': season,
                'team': team,
                'regular_season_games': len(rows),
                'head_coach_games_known': sum(bool(row['head_coach']) for row in rows),
                'head_coach_names': '; '.join(hcs),
                'head_coach_game_counts': '; '.join(f'{name}:{hc_counts[name]}' for name in hcs),
                'off_play_caller_games_known': sum(bool(row['off_play_caller']) for row in rows),
                'off_play_caller_names': '; '.join(ocs),
                'off_play_caller_game_counts': '; '.join(f'{name}:{oc_counts[name]}' for name in ocs),
                'head_coach_source_url': SCHEDULE_URL,
                'head_coach_source_as_of': SCHEDULE_AS_OF,
                'head_coach_source_sha256': SCHEDULE_SHA256,
                'play_caller_source_url': CALLER_URL,
                'play_caller_source_as_of': CALLER_AS_OF,
                'play_caller_source_sha256': CALLER_SHA256,
            })

    return games, callers, {
        'team_season_rows': len(team_games),
        'regular_season_team_games': sum(map(len, team_games.values())),
        'head_coach_games_known': sum(bool(r['head_coach']) for rows in team_games.values() for r in rows),
        'play_caller_games_known': sum(bool(r['off_play_caller']) for rows in team_games.values() for r in rows),
        'caller_conflict_team_games': caller_conflicts,
        'unmapped_caller_rows': unmapped_caller_rows,
    }


def historical_score_flags():
    flags = {}
    with open(pco.FLAGS_PATH, newline='') as source:
        for row in csv.DictReader(source):
            season = int(row['game_id'][:4])
            if TRAIN_FIRST <= season <= VALIDATION:
                flags[(row['game_id'], int(float(row['play_id'])))] = row['label']
    return flags


def load_historical_frame(db, games, callers):
    """Load model rows from 2010-2023 with indexed season queries and verified raw scores."""
    flags = historical_score_flags()
    collected = {key: [] for key in pm.FRAME_KEYS}
    team_codes, caller_names, hc_known = [], [], []
    con = sqlite3.connect(f'file:{db}?mode=ro', uri=True, timeout=30)
    con.row_factory = sqlite3.Row
    try:
        for season in range(TRAIN_FIRST, VALIDATION + 1):
            scores = pco.scores_for_season(season)
            sql = (
                f"SELECT {', '.join(pco.COLUMNS)} FROM nfl_pbp "
                'WHERE season = ? AND week <= 18'
            )
            for row in con.execute(sql, (season,)):
                key = (row['game_id'], int(row['play_id']))
                obs = pco.observation(dict(row), scores.get(key), flags.get(key))
                if not pm.keep_play(obs, include_flagged=True):
                    continue
                team_codes.append(obs['posteam'])
                schedule_team = historical_alias(season, obs['posteam'])
                caller_names.append(callers.get((obs['game_id'], schedule_team), ''))
                game = games.get(obs['game_id'])
                if game and schedule_team == game['home_team']:
                    hc_known.append(bool(game['home_coach'].strip()))
                elif game and schedule_team == game['away_team']:
                    hc_known.append(bool(game['away_coach'].strip()))
                else:
                    hc_known.append(False)
                collected['season'].append(season)
                collected['team'].append(0)  # replaced by a stable sorted team map below
                collected['down'].append(obs['down'] - 1)
                collected['dist'].append(pm.distance_bucket(obs['ydstogo']))
                collected['field'].append(pm.field_bucket(obs['yardline_100']))
                collected['score'].append(pm.score_bucket(obs['score_differential']))
                collected['clock'].append(pm.clock_bucket(obs['qtr'], obs['seconds_in_quarter']))
                collected['y'].append(1 if obs['intent'] == 'dropback' else 0)
                collected['flagged'].append(obs['score_status'] == 'flagged_continuity_exception')
                collected['game'].append(0)
    finally:
        con.close()
    teams = {code: i for i, code in enumerate(sorted(set(team_codes)))}
    caller_vocab = {name: i for i, name in enumerate(sorted({name for name in caller_names if name}))}
    collected['team'] = [teams[code] for code in team_codes]
    arrays = {key: np.asarray(values, dtype=bool if key == 'flagged' else np.int64)
              for key, values in collected.items()}
    arrays['caller'] = np.asarray([caller_vocab.get(name, -1) for name in caller_names], dtype=np.int64)
    arrays['head_coach_known'] = np.asarray(hc_known, dtype=bool)
    return pm.Frame(arrays, teams), caller_vocab


def rows_for(frame, seasons):
    mask = np.isin(frame.a['season'], np.asarray(tuple(seasons))) & ~frame.a['flagged']
    return np.flatnonzero(mask)


def tune_base(design, frame):
    """Match the committed runner's coordinate search, with only its 2023 validation window."""
    train_rows = rows_for(frame, range(TRAIN_FIRST, TRAIN_LAST + 1))
    val_rows = rows_for(frame, (VALIDATION,))
    prep = pm.prepare(design, train_rows, pm.GROUP_NAMES)
    val_x = design.X[val_rows][:, prep['cols']]
    y_train = frame.a['y'][train_rows].astype(float)
    y_val = frame.a['y'][val_rows]
    season_train = frame.a['season'][train_rows]
    penalties = {group: 10.0 for group in pm.GROUP_NAMES}
    best_tau, best_beta, best = None, None, float('inf')

    for tau in TAU_GRID:
        weights = pm.recency_weights(season_train, VALIDATION, tau)
        beta, _ = pm.fit_prepared(design, prep, y_train, weights, penalties)
        value = pm.log_loss(pm.expit(val_x @ beta), y_val)
        if value < best:
            best, best_tau, best_beta = value, tau, beta

    weights = pm.recency_weights(season_train, VALIDATION, best_tau)
    beta = best_beta
    for _ in range(2):
        for group in pm.GROUP_NAMES:
            for value in BASE_PENALTY_GRID:
                trial = dict(penalties, **{group: value})
                candidate, _ = pm.fit_prepared(design, prep, y_train, weights, trial, start=beta)
                loss = pm.log_loss(pm.expit(val_x @ candidate), y_val)
                if loss < best:
                    best, penalties, beta = loss, trial, candidate
    return train_rows, val_rows, prep, penalties, best_tau, beta


class CoachDesign:
    """Existing play-call design plus one regularized caller x down-distance block."""

    def __init__(self, frame, train_rows):
        self.base = pm.Design(frame)
        observed_callers = sorted(set(frame.a['caller'][train_rows].tolist()) - {-1})
        self.caller_index = {caller: i for i, caller in enumerate(observed_callers)}
        caller_code = np.asarray([self.caller_index.get(x, -1) for x in frame.a['caller']], dtype=np.int64)
        cell = pm.cell_index(frame.a)
        valid = np.flatnonzero(caller_code >= 0)
        feature_col = caller_code[valid] * (pm.DOWN_COUNT * len(pm.DISTANCE_BUCKETS)) + cell[valid]
        feature = sparse.csr_matrix(
            (np.ones(len(valid)), (valid, feature_col)),
            shape=(len(frame), len(observed_callers) * pm.DOWN_COUNT * len(pm.DISTANCE_BUCKETS)),
        )
        self.X = sparse.hstack((self.base.X, feature), format='csr')
        self.base_width = self.base.width
        self.feature_width = feature.shape[1]
        self.new_code = len(pm.GROUP_NAMES) + 1
        self.col_group = np.concatenate((self.base.col_group, np.full(self.feature_width, self.new_code)))

    def columns(self, groups):
        base_groups = [group for group in groups if group in pm.GROUP_NAMES]
        cols = self.base.columns(base_groups)
        if COACH_GROUP not in groups:
            return cols
        extra = self.base_width + np.arange(self.feature_width, dtype=np.int64)
        return np.concatenate((cols, extra))

    def penalty(self, cols, penalties):
        by_code = np.zeros(self.new_code + 1)
        for group, value in penalties.items():
            if group == COACH_GROUP:
                by_code[self.new_code] = value
            else:
                by_code[pm.GROUP_CODE[group]] = value
        return by_code[self.col_group[cols]]


def metrics(probability, target):
    return {
        'n': int(len(target)),
        'log_loss': round(pm.log_loss(probability, target), 6),
        'brier': round(pm.brier(probability, target), 6),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--db', type=Path, required=True)
    parser.add_argument('--schedule-csv', type=Path, required=True)
    parser.add_argument('--playcallers-csv', type=Path, required=True)
    parser.add_argument('--ledger-out', type=Path, required=True)
    parser.add_argument('--report-out', type=Path, required=True)
    parser.add_argument('--baseline-parameters', type=Path)
    args = parser.parse_args()

    verify_source(args.schedule_csv, SCHEDULE_SHA256)
    verify_source(args.playcallers_csv, CALLER_SHA256)
    games, callers, ledger_summary = build_ledger(args.schedule_csv, args.playcallers_csv, args.ledger_out)
    print('Loading only 2010-2023 play-call observations and verified pre-play scores.', flush=True)
    frame, caller_vocab = load_historical_frame(args.db, games, callers)
    if int(frame.a['season'].max()) > VALIDATION:
        raise AssertionError('historical frame exceeded the fixed 2023 validation cutoff')

    if args.baseline_parameters:
        # This accepts only the 2023-only report from this experiment, never the all-season evaluation report.
        frozen = json.loads(args.baseline_parameters.read_text())
        if frozen.get('window', {}).get('fit_seasons') != [TRAIN_FIRST, TRAIN_LAST] or \
                frozen.get('window', {}).get('validation_season') != VALIDATION:
            raise ValueError('baseline parameter report does not match the fixed 2010-2022/2023 window')
        base_penalties = frozen['baseline']['chosen_group_penalties']
        base_tau = frozen['baseline']['chosen_recency_tau']
        train_rows = rows_for(frame, range(TRAIN_FIRST, TRAIN_LAST + 1))
        val_rows = rows_for(frame, (VALIDATION,))
        base_design = pm.Design(frame)
        base_prep = pm.prepare(base_design, train_rows, pm.GROUP_NAMES)
        base_weights = pm.recency_weights(frame.a['season'][train_rows], VALIDATION, base_tau)
        y_train = frame.a['y'][train_rows].astype(float)
        base_beta, _ = pm.fit_prepared(base_design, base_prep, y_train, base_weights, base_penalties)
        print('Reused only the 2023-selected baseline parameters from the prior bounded run.', flush=True)
    else:
        print(f'Loaded {len(frame)} eligible play rows; tuning the existing model on 2023.', flush=True)
        train_rows, val_rows, base_prep, base_penalties, base_tau, base_beta = tune_base(pm.Design(frame), frame)
    print(f'Historical frame has {len(frame)} rows; validation has {len(val_rows)} plays.', flush=True)
    base_design = pm.Design(frame)
    val_x = base_design.X[val_rows][:, base_prep['cols']]
    y_train = frame.a['y'][train_rows].astype(float)
    y_val = frame.a['y'][val_rows]
    base_probability = pm.expit(val_x @ base_beta)

    coach_design = CoachDesign(frame, train_rows)
    groups = tuple(pm.GROUP_NAMES) + (COACH_GROUP,)
    coach_prep = pm.prepare(coach_design, train_rows, groups)
    coach_val_x = coach_design.X[val_rows][:, coach_prep['cols']]
    base_start = np.concatenate((base_beta, np.zeros(coach_design.feature_width)))
    base_weights = pm.recency_weights(frame.a['season'][train_rows], VALIDATION, base_tau)
    coach_scores = {}
    best_penalty, best_loss, best_beta = None, float('inf'), None
    print(f'Tuning caller x down-distance penalty on {len(val_rows)} 2023 plays.', flush=True)
    for penalty in PENALTY_GRID:
        penalties = dict(base_penalties, **{COACH_GROUP: penalty})
        candidate, _ = pm.fit_prepared(
            coach_design, coach_prep, y_train, base_weights, penalties, start=base_start
        )
        probability = pm.expit(coach_val_x @ candidate)
        loss = pm.log_loss(probability, y_val)
        coach_scores[str(penalty)] = {
            'log_loss': round(loss, 6),
            'brier': round(pm.brier(probability, y_val), 6),
        }
        if loss < best_loss:
            best_penalty, best_loss, best_beta = penalty, loss, candidate
    coach_probability = pm.expit(coach_val_x @ best_beta)

    known_caller = frame.a['caller'][val_rows] >= 0
    train_caller_ids = set(frame.a['caller'][train_rows].tolist()) - {-1}
    train_supported = np.isin(frame.a['caller'][val_rows], np.asarray(sorted(train_caller_ids)))
    caller_ids_val = frame.a['caller'][val_rows]
    cells_val = pm.cell_index(frame.a)[val_rows]
    in_feature_vocab = np.asarray([int(x) in coach_design.caller_index for x in caller_ids_val])
    feature_level_supported = np.zeros(len(val_rows), dtype=bool)
    usable = np.flatnonzero(in_feature_vocab)
    if len(usable):
        compact_caller = np.asarray([coach_design.caller_index[int(caller_ids_val[i])] for i in usable])
        feature_level = compact_caller * 24 + cells_val[usable]
        train_caller_compact = np.asarray([
            coach_design.caller_index.get(int(x), -1) for x in frame.a['caller'][train_rows]
        ])
        train_cells = pm.cell_index(frame.a)[train_rows]
        valid_train = train_caller_compact >= 0
        counts = np.bincount(
            train_caller_compact[valid_train] * 24 + train_cells[valid_train],
            minlength=max(coach_design.feature_width, 1),
        )
        feature_level_supported[usable] = counts[feature_level] > 0

    def subset_metrics(mask):
        return {
            'n': int(mask.sum()),
            'current_model': metrics(base_probability[mask], y_val[mask]),
            'with_caller_feature': metrics(coach_probability[mask], y_val[mask]),
            'delta_log_loss': round(
                pm.log_loss(coach_probability[mask], y_val[mask]) - pm.log_loss(base_probability[mask], y_val[mask]),
                6,
            ),
            'delta_brier': round(
                pm.brier(coach_probability[mask], y_val[mask]) - pm.brier(base_probability[mask], y_val[mask]),
                6,
            ),
        }

    unknown_2023_team_callers = sorted({
        team
        for game_id, game in games.items()
        if int(game['season']) == VALIDATION
        for team in (game['home_team'], game['away_team'])
        if not callers.get((game_id, team))
    })
    report = {
        'window': {'fit_seasons': [TRAIN_FIRST, TRAIN_LAST], 'validation_season': VALIDATION,
                   'metric_population': 'regular-season run/dropback plays with complete model state; flagged scores excluded'},
        'source_files': [
            {'role': 'head_coach_per_game', 'url': SCHEDULE_URL, 'raw_url': SCHEDULE_RAW_URL,
             'as_of': SCHEDULE_AS_OF, 'sha256': SCHEDULE_SHA256},
            {'role': 'offensive_play_caller_per_game', 'url': CALLER_URL, 'raw_url': CALLER_RAW_URL,
             'as_of': CALLER_AS_OF, 'sha256': CALLER_SHA256},
        ],
        'ledger': ledger_summary,
        'team_code_normalization': [
            'WSH -> WAS', 'LAR -> LA (2016 onward)', 'LA -> STL (through 2015)',
            'LAR -> STL (through 2015)', 'LAC -> SD (through 2016)', 'LV -> OAK (through 2019)',
        ],
        'validation_2023_team_seasons_without_published_caller': unknown_2023_team_callers,
        'play_sample': {
            'training_2010_2022_plays': int(len(train_rows)),
            'validation_2023_plays': int(len(val_rows)),
            'validation_2023_known_head_coach_plays': int(frame.a['head_coach_known'][val_rows].sum()),
            'validation_2023_known_head_coach_share': round(
                float(frame.a['head_coach_known'][val_rows].mean()), 6
            ),
            'validation_2023_known_offensive_caller_plays': int(known_caller.sum()),
            'validation_2023_known_offensive_caller_share': round(float(known_caller.mean()), 6),
            'validation_2023_caller_seen_in_2010_2022_plays': int(train_supported.sum()),
            'validation_2023_caller_seen_in_2010_2022_share': round(float(train_supported.mean()), 6),
            'validation_2023_caller_down_distance_seen_in_training_plays': int(feature_level_supported.sum()),
            'validation_2023_caller_down_distance_seen_in_training_share': round(float(feature_level_supported.mean()), 6),
        },
        'feature': {
            'name': 'published offensive play caller x 24 down-distance cells',
            'unknown_or_unseen_caller': 'zero added effect; existing current-model prediction retained',
            'penalty_selection_metric': '2023 validation log loss',
            'penalty_grid': list(PENALTY_GRID),
            'selected_penalty': best_penalty,
            'candidate_metrics_2023': coach_scores,
            'caller_feature_columns': coach_design.feature_width,
        },
        'baseline': {
            'chosen_group_penalties': base_penalties,
            'chosen_recency_tau': base_tau,
            'validation_all_plays': metrics(base_probability, y_val),
        },
        'comparison_2023': {
            'all_validation_plays': subset_metrics(np.ones(len(val_rows), dtype=bool)),
            'known_caller_plays': subset_metrics(known_caller),
            'training_supported_caller_plays': subset_metrics(train_supported),
        },
        'interpretation_limit': '2023 both selects the added penalty and scores the reported validation comparison; this is tuning validation, not independent test performance.',
        'caller_provenance_limit': 'The offensive caller source is a pinned public per-game curated dataset, but it does not publish supporting citations per row. Its caller labels are used verbatim; missing labels are not inferred.',
    }

    args.report_out.parent.mkdir(parents=True, exist_ok=True)
    args.report_out.write_text(json.dumps(report, indent=2, sort_keys=True) + '\n')
    print(json.dumps({
        'ledger': ledger_summary,
        'training_plays': len(train_rows),
        'validation_plays': len(val_rows),
        'known_caller_share': report['play_sample']['validation_2023_known_offensive_caller_share'],
        'selected_caller_penalty': best_penalty,
        'comparison_2023': report['comparison_2023'],
    }, indent=2))


if __name__ == '__main__':
    main()
