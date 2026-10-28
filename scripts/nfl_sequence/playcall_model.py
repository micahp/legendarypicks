"""Hierarchical situational play-calling model (research infrastructure, not adopted).

Target: whether a scrimmage play is a called dropback (y=1) or a designed run (y=0), from the play-call observations.

Model: penalized logistic regression with one L2 penalty per factor group. Each group's penalty is its own precision, so a group
is shrunk toward zero (the league-wide rate for interactions and tendencies) by an amount chosen on validation data. Groups:
down x distance, field, score, clock, score x clock (the score-by-clock interaction), down x field, team x down (team tendency),
and season (era). Recency weights down-weight older seasons by exp(-(test season - season) / tau).

Efficiency. The frame (every scrimmage play, 2010 to 2025) is built once and cached to disk. The sparse design matrix is built
once per frame, with all seasons and teams as columns; a fit selects its groups by column. A row split is sliced once and reused
across the penalty search, and each search fit starts from the previous coefficients. Nothing is rebuilt per fit or per predict.

Chronology: a test season S is fitted only on seasons before S. Hyperparameters are chosen on 2023 with fitting on 2010 to 2022.
2026 is refused before any query (holdout.refuse_if_holdout).

Baselines: the league-wide rate, and a 24-cell model (4 downs x 6 distance buckets) fitted on the same training seasons. The
existing splits-branch 24-cell decision model is fitted on 2025 and its test is spent, so it cannot be a chronological comparator;
this baseline is a reconstruction on the same definition.
"""
import math

import numpy as np
from scipy import sparse
from scipy.optimize import minimize
from scipy.special import expit

import e1_drive as e1
import holdout
import playcall_observations as pco

DOWN_COUNT = 4
DISTANCE_BUCKETS = ((1, 2, 'd1_2'), (3, 4, 'd3_4'), (5, 6, 'd5_6'), (7, 9, 'd7_9'), (10, 14, 'd10_14'), (15, 99, 'd15p'))
FIELD_BUCKETS = ('own_deep', 'own_side', 'opp_side', 'red_zone', 'goal_line')  # ordered by yardline_100, deepest first
SCORE_BUCKETS = ('dn15p', 'dn11_14', 'dn8_10', 'dn7', 'dn4_6', 'dn3', 'dn1_2', 'tied',
                 'up1_2', 'up3', 'up4_6', 'up7', 'up8_10', 'up11_14', 'up15p')
CLOCK_BUCKETS = ('q1', 'q2', 'q2_2min', 'q3', 'q4', 'q4_late', 'q4_2min', 'ot')
FRAME_KEYS = ('season', 'team', 'down', 'dist', 'field', 'score', 'clock', 'y', 'flagged', 'game')

# Fixed-size groups. Team x down and season are sized from the frame.
GROUP_NAMES = ('down_dist', 'field', 'score', 'clock', 'score_clock', 'down_field', 'team_down', 'season')
GROUP_CODE = {name: code for code, name in enumerate(GROUP_NAMES, start=1)}  # code 0 is the intercept
GROUP_SIZES = {'down_dist': DOWN_COUNT * len(DISTANCE_BUCKETS), 'field': len(FIELD_BUCKETS),
               'score': len(SCORE_BUCKETS), 'clock': len(CLOCK_BUCKETS),
               'score_clock': len(SCORE_BUCKETS) * len(CLOCK_BUCKETS),
               'down_field': DOWN_COUNT * len(FIELD_BUCKETS)}


def distance_bucket(ydstogo):
    for low, high, label in DISTANCE_BUCKETS:
        if low <= ydstogo <= high:
            return DISTANCE_BUCKETS.index((low, high, label))
    raise ValueError(f'distance {ydstogo} is outside the buckets')


def field_bucket(yardline_100):
    if yardline_100 >= 80:
        return 0
    if yardline_100 >= 51:
        return 1
    if yardline_100 >= 21:
        return 2
    if yardline_100 > 10:
        return 3
    return 4


def score_bucket(diff):
    """Offense minus defense before the play, in the 15 buckets from the score specification."""
    if diff == 0:
        return SCORE_BUCKETS.index('tied')
    sign = 1 if diff > 0 else -1
    size = abs(diff)
    if size <= 2:
        label = '1_2'
    elif size == 3:
        label = '3'
    elif size <= 6:
        label = '4_6'
    elif size == 7:
        label = '7'
    elif size <= 10:
        label = '8_10'
    elif size <= 14:
        label = '11_14'
    else:
        label = '15p'
    return SCORE_BUCKETS.index(('up' if sign > 0 else 'dn') + label)


def clock_bucket(qtr, seconds_in_quarter):
    if qtr is None:
        raise ValueError('a play needs a quarter')
    qtr = int(qtr)
    if qtr >= 5:
        return CLOCK_BUCKETS.index('ot')
    if qtr == 1:
        return CLOCK_BUCKETS.index('q1')
    if qtr == 3:
        return CLOCK_BUCKETS.index('q3')
    if seconds_in_quarter is None:
        raise ValueError('a regulation play needs a clock')
    if qtr == 2:
        return CLOCK_BUCKETS.index('q2_2min' if seconds_in_quarter <= 120 else 'q2')
    if seconds_in_quarter <= 120:
        return CLOCK_BUCKETS.index('q4_2min')
    if seconds_in_quarter <= 300:
        return CLOCK_BUCKETS.index('q4_late')
    return CLOCK_BUCKETS.index('q4')


def keep_play(obs, include_flagged):
    """Scrimmage dropback or run with a complete pre-play state. Flagged score rows are kept only when asked for."""
    if obs['intent'] not in ('run', 'dropback'):
        return False
    if obs['down'] not in (1, 2, 3, 4) or obs['ydstogo'] is None or obs['yardline_100'] is None or obs['qtr'] is None:
        return False
    if obs['score_status'] == 'pre_play_nflverse_raw':
        return True
    return include_flagged and obs['score_status'] == 'flagged_continuity_exception'


class Frame:
    """Arrays for the scrimmage plays. `teams` maps team code to index; `games` is unused by the fit."""

    def __init__(self, arrays, teams, games=None):
        self.a = arrays
        self.teams = teams
        self.games = games or {}

    def __len__(self):
        return len(self.a['y'])

    def take(self, mask):
        return Frame({k: v[mask] for k, v in self.a.items()}, self.teams, self.games)


def load_frame(seasons, db=e1.DEFAULT_DB, include_flagged=True):
    """Build the frame for the given seasons from the observations. Refuses the holdout before reading anything."""
    seasons = tuple(sorted(seasons))
    holdout.refuse_if_holdout(seasons[-1], 'play-call model frame')
    team_index = {}
    cols = {k: [] for k in FRAME_KEYS}
    wanted = set(seasons)
    for obs in pco.observations(db, first_season=seasons[0], last_season=seasons[-1]):
        if obs['season'] not in wanted or not keep_play(obs, include_flagged):
            continue
        cols['season'].append(obs['season'])
        cols['team'].append(team_index.setdefault(obs['posteam'], len(team_index)))
        cols['down'].append(obs['down'] - 1)
        cols['dist'].append(distance_bucket(obs['ydstogo']))
        cols['field'].append(field_bucket(obs['yardline_100']))
        cols['score'].append(score_bucket(obs['score_differential']))
        cols['clock'].append(clock_bucket(obs['qtr'], obs['seconds_in_quarter']))
        cols['y'].append(1 if obs['intent'] == 'dropback' else 0)
        cols['flagged'].append(obs['score_status'] == 'flagged_continuity_exception')
        cols['game'].append(0)  # game identity is not needed by the fit; observed counts use it through game_id when built
    arrays = {k: np.asarray(v, dtype=bool if k == 'flagged' else np.int64) for k, v in cols.items()}
    return Frame(arrays, team_index)


def save_frame(frame, path, seasons, include_flagged):
    codes = [''] * len(frame.teams)
    for code, index in frame.teams.items():
        codes[index] = code
    np.savez(path, team_codes=np.array(codes), seasons_built=np.array(seasons, dtype=np.int64),
             include_flagged=np.array(include_flagged), **{k: frame.a[k] for k in FRAME_KEYS})


def load_frame_cached(path, seasons, include_flagged=True):
    """The frame for these seasons, read from the cache when it was built for the same seasons and flag setting."""
    seasons = tuple(sorted(seasons))
    holdout.refuse_if_holdout(seasons[-1], 'play-call model frame')
    if path.exists():
        cached = np.load(path)
        if tuple(int(s) for s in cached['seasons_built']) == seasons and bool(cached['include_flagged']) == include_flagged:
            teams = {str(code): index for index, code in enumerate(cached['team_codes'])}
            return Frame({k: cached[k] for k in FRAME_KEYS}, teams)
    frame = load_frame(seasons, include_flagged=include_flagged)
    save_frame(frame, path, seasons, include_flagged)
    return frame


class Design:
    """One sparse design for a frame: intercept, then one block of columns per group. Season and team columns cover every
    season and team in the frame. A row whose level is absent from the layout gets no entry for that group, which is the
    prior mean under a penalty of zero."""

    def __init__(self, frame):
        self.seasons = np.unique(frame.a['season']).astype(np.int64)
        self.team_count = max(len(frame.teams), 1)
        self.sizes = dict(GROUP_SIZES)
        self.sizes['team_down'] = self.team_count * DOWN_COUNT  # relocated codes (STL, SD, OAK) make this more than 32 teams
        self.sizes['season'] = len(self.seasons)
        self.offsets, total = {}, 1
        for g in GROUP_NAMES:
            self.offsets[g] = total
            total += self.sizes[g]
        self.width = total
        self.col_group = np.zeros(total, dtype=np.int64)
        for g in GROUP_NAMES:
            self.col_group[self.offsets[g]:self.offsets[g] + self.sizes[g]] = GROUP_CODE[g]
        self.X = self.matrix(frame.a)

    def season_index(self, season):
        pos = np.searchsorted(self.seasons, season)
        pos = np.minimum(pos, len(self.seasons) - 1)
        return np.where(self.seasons[pos] == season, pos, -1)

    def matrix(self, a):
        """Sparse design for any arrays with the frame's keys. Unknown seasons and team index -1 are dropped."""
        n = len(a['y'])
        levels = {
            'down_dist': a['down'] * len(DISTANCE_BUCKETS) + a['dist'],
            'field': a['field'],
            'score': a['score'],
            'clock': a['clock'],
            'score_clock': a['score'] * len(CLOCK_BUCKETS) + a['clock'],
            'down_field': a['down'] * len(FIELD_BUCKETS) + a['field'],
            'team_down': a['team'] * DOWN_COUNT + a['down'],
            'season': self.season_index(a['season']),
        }
        rows, cols = [np.arange(n)], [np.zeros(n, dtype=np.int64)]
        for g in GROUP_NAMES:
            level = levels[g]
            keep = np.flatnonzero(level >= 0)
            rows.append(keep)
            cols.append(self.offsets[g] + level[keep])
        r, c = np.concatenate(rows), np.concatenate(cols)
        return sparse.csr_matrix((np.ones(len(r)), (r, c)), shape=(n, self.width))

    def columns(self, groups):
        """Column indices for the intercept and the chosen groups, in ascending order (the intercept is first)."""
        codes = [0] + [GROUP_CODE[g] for g in groups]
        return np.flatnonzero(np.isin(self.col_group, codes))

    def penalty(self, cols, penalties):
        by_code = np.zeros(len(GROUP_NAMES) + 1)
        for g, value in penalties.items():
            by_code[GROUP_CODE[g]] = value
        return by_code[self.col_group[cols]]


def prepare(design, rows, groups):
    """Slice the rows and columns once. Reused across every penalty and every tau for the same split and groups."""
    cols = design.columns(groups)
    X = design.X[rows][:, cols].tocsr()
    return {'X': X, 'XT': X.T.tocsr(), 'cols': cols}


def fit_prepared(design, prep, y, weights, penalties, start=None):
    """Penalized logistic fit on prepared matrices. Returns (beta over prep['cols'], iterations)."""
    X, XT = prep['X'], prep['XT']
    lam = design.penalty(prep['cols'], penalties)
    w = np.ones(len(y)) if weights is None else weights
    if start is None:
        start = np.zeros(X.shape[1])
        rate = float(np.clip(np.dot(w, y) / w.sum(), 1e-6, 1 - 1e-6))
        start[0] = math.log(rate / (1 - rate))

    def objective(beta):
        eta = X @ beta
        loss = np.dot(w, np.logaddexp(0.0, eta) - y * eta) + 0.5 * np.dot(lam, beta * beta)
        grad = XT @ (w * (expit(eta) - y)) + lam * beta
        return loss, grad

    result = minimize(objective, start, jac=True, method='L-BFGS-B', options={'maxiter': 300})
    return result.x, int(result.nit)


def predict_prepared(design, prep_cols, beta, rows):
    """Modelled dropback probability for the given rows, using the coefficients of a prepared fit."""
    X = design.X[rows][:, prep_cols]
    return expit(X @ beta)


def recency_weights(season, test_season, tau):
    if tau is None:
        return None
    return np.exp(-(test_season - season) / float(tau))


def log_loss(p, y):
    p = np.clip(p, 1e-9, 1 - 1e-9)
    return float(-np.mean(y * np.log(p) + (1 - y) * np.log(1 - p)))


def brier(p, y):
    return float(np.mean((p - y) ** 2))


def calibration_error(p, y, bins=10):
    edges = np.linspace(0.0, 1.0, bins + 1)
    total, error = len(p), 0.0
    for low, high in zip(edges[:-1], edges[1:]):
        mask = (p >= low) & (p < high) if high < 1.0 else (p >= low) & (p <= high)
        if mask.any():
            error += mask.sum() / total * abs(p[mask].mean() - y[mask].mean())
    return float(error)


def cell_index(a):
    """Row index in the 24-cell (down x distance) grid."""
    return a['down'] * len(DISTANCE_BUCKETS) + a['dist']


def cell24(y_train, cells_train, minimum=20):
    """The 24-cell baseline: rate by down and distance bucket, the league rate where a cell has fewer than `minimum` plays."""
    league = float(y_train.mean())
    rates = np.full(DOWN_COUNT * len(DISTANCE_BUCKETS), league)
    counts = np.bincount(cells_train, minlength=len(rates))
    sums = np.bincount(cells_train, weights=y_train, minlength=len(rates))
    enough = counts >= minimum
    rates[enough] = sums[enough] / counts[enough]
    return rates


def situation_mask(frame, down, dist_yards, field_name, score_diff, clock_name, team=None):
    mask = ((frame.a['down'] == down - 1) & (frame.a['dist'] == distance_bucket(dist_yards))
            & (frame.a['field'] == FIELD_BUCKETS.index(field_name))
            & (frame.a['score'] == score_bucket(score_diff))
            & (frame.a['clock'] == CLOCK_BUCKETS.index(clock_name)))
    if team is not None:
        mask &= frame.a['team'] == frame.teams[team]
    return mask


def observed_counts(frame, down, dist_yards, field_name, score_diff, clock_name, team=None):
    """Observed historical frequency for an exact bucketed situation: plays, dropbacks, rate and seasons."""
    mask = situation_mask(frame, down, dist_yards, field_name, score_diff, clock_name, team)
    n = int(mask.sum())
    return {'plays': n, 'dropbacks': int(frame.a['y'][mask].sum()),
            'observed_dropback_rate': float(frame.a['y'][mask].mean()) if n else None,
            'seasons': sorted(int(s) for s in np.unique(frame.a['season'][mask])) if n else []}


def modelled_probability(design, prep_cols, beta, teams, down, dist_yards, field_name, score_diff, clock_name, team=None):
    """Modelled dropback probability for a situation. An unknown team adds no team effect (the league-average team), and a
    season is not given, so no season effect applies."""
    arrays = {'season': np.array([-1]), 'team': np.array([teams[team] if team in teams else -1]),
              'down': np.array([down - 1]), 'dist': np.array([distance_bucket(dist_yards)]),
              'field': np.array([FIELD_BUCKETS.index(field_name)]), 'score': np.array([score_bucket(score_diff)]),
              'clock': np.array([CLOCK_BUCKETS.index(clock_name)]), 'y': np.zeros(1, dtype=np.int64)}
    X = design.matrix(arrays)[:, prep_cols]
    return float(expit(X @ beta)[0])
