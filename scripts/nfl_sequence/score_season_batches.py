#!/usr/bin/env python3
"""Score two arms of paired batch outputs against the 2026 results and apply the advance rule.

Each arm is a directory of simulate_pregame_batch.py outputs, one JSON file per game named <game_id>.json. Both arms must
hold the same games and the same seed lists. The win probability of a game is the share of its valid, untied simulated
seeds in which the home side wins. Results come from nfl_schedule (regular season, season 2026, weeks given).

Metrics per arm: winner Brier score and log loss, calibration by probability bin, and points CRPS for each team. The
paired difference (arm minus baseline) of the winner log loss and Brier score is reported with a 95% interval from a
game-clustered bootstrap, and the advance rule (owner, 2026-11-03) is applied once to the season total:
advance only if both mean log loss and mean Brier are lower than the baseline and the interval for the log-loss
difference is below zero.

Usage: python3 score_season_batches.py --baseline-dir DIR --candidate-dir DIR --weeks 1-8 --out REPORT.json
"""
import argparse
import json
import math
import random
import sqlite3
from pathlib import Path

DEFAULT_DB = '/root/legendarypicks/backend/data/picks.dev.db'
EPS = 1e-6
BOOTSTRAP_REPS = 10000
BOOTSTRAP_SEED = 20260103
BINS = [(0.0, 0.1), (0.1, 0.2), (0.2, 0.3), (0.3, 0.4), (0.4, 0.5), (0.5, 0.6), (0.6, 0.7), (0.7, 0.8), (0.8, 0.9), (0.9, 1.0001)]


def parse_weeks(text):
    low, high = (int(part) for part in text.split('-'))
    if low < 1 or high > 18 or low > high:
        raise ValueError(f'weeks must be within 1-18, got {text!r}')
    return list(range(low, high + 1))


def load_results(db, season, weeks):
    """{game_id: {'week', 'home', 'away', 'home_points', 'away_points'}} for final regular-season games in the weeks.

    A game is final only when both scores are present. nfl_schedule has no status column, so the score is the only
    finality signal this scorer has. A game without a final score is listed as unscored, never scored.
    """
    con = sqlite3.connect(f'file:{db}?mode=ro', uri=True, timeout=10)
    try:
        marks = ', '.join('?' for _ in weeks)
        rows = con.execute(
            f"SELECT game_id, week, home_team, away_team, home_score, away_score FROM nfl_schedule "
            f"WHERE season = ? AND game_type = 'REG' AND week IN ({marks})", (season, *weeks)).fetchall()
    finally:
        con.close()
    results, unscored = {}, []
    for game_id, week, home, away, home_score, away_score in rows:
        if home_score is None or away_score is None:
            unscored.append(game_id)
            continue
        results[game_id] = {'week': week, 'home': home, 'away': away,
                            'home_points': int(home_score), 'away_points': int(away_score)}
    return results, sorted(unscored)


def load_arm(directory):
    """{game_id: payload} for every batch JSON in a directory, plain or gzipped (<game_id>.json or <game_id>.json.gz).
    The file name must match the payload's game_id."""
    import gzip
    games = {}
    for path in sorted(list(Path(directory).glob('*.json')) + list(Path(directory).glob('*.json.gz'))):
        gz = path.suffix == '.gz'
        stem = path.name[:-len('.json.gz')] if gz else path.stem
        payload = json.loads(gzip.open(path, 'rt').read() if gz else path.read_text())
        if payload.get('game_id') != stem:
            raise ValueError(f'{path}: payload game_id {payload.get("game_id")!r} does not match the file name')
        if stem in games:
            raise ValueError(f'{path}: duplicate game {stem}')
        games[stem] = payload
    return games


SEED_RULES = {
    # A verified pregame snapshot and a complete, unblocked, legal game.
    'valid_full_game': 'valid_full_game',
    # A complete, unblocked, legal game. Archive reconstructions are never verified (their local capture time is not
    # established), so the engine never marks them valid_full_game; this rule scores them, and the report says so.
    'complete_game': 'complete_game',
}


def seed_outcomes(payload, rule='valid_full_game'):
    """(valid untied seed rows, seed numbers of every row) for one game."""
    rows = payload['summary']['outcomes']
    seeds = sorted(row['seed'] for row in rows)
    field = SEED_RULES[rule]
    valid = [row for row in rows if row.get(field) and row['home_points'] != row['away_points']]
    return valid, seeds


def home_win_probability(valid):
    return sum(1 for row in valid if row['home_points'] > row['away_points']) / len(valid)


def crps(samples, observed):
    """Continuous ranked probability score of the sample distribution against one observation (lower is better)."""
    xs = sorted(samples)
    n = len(xs)
    mean_abs_to_obs = sum(abs(x - observed) for x in xs) / n
    # Mean over all ordered pairs of |X - X'|, computed from the sorted sample in O(n).
    mean_abs_pairs = 2 * sum(x * (2 * i - (n - 1)) for i, x in enumerate(xs)) / (n * n)
    return mean_abs_to_obs - 0.5 * mean_abs_pairs


def log_loss(p, y):
    p = min(max(p, EPS), 1 - EPS)
    return -(y * math.log(p) + (1 - y) * math.log(1 - p))


def brier(p, y):
    return (p - y) ** 2


def bin_index(p):
    for index, (low, high) in enumerate(BINS):
        if low <= p < high:
            return index
    raise ValueError(f'probability outside [0, 1]: {p}')


def arm_metrics(rows):
    """Season and per-week metrics for one arm, from its per-game rows."""
    def summarise(group):
        count = len(group)
        return {
            'games': count,
            'brier': sum(r['brier'] for r in group) / count,
            'log_loss': sum(r['log_loss'] for r in group) / count,
            'crps_home_points': sum(r['crps_home'] for r in group) / count,
            'crps_away_points': sum(r['crps_away'] for r in group) / count,
        }
    calibration = []
    for index, (low, high) in enumerate(BINS):
        group = [r for r in rows if bin_index(r['p_home']) == index]
        calibration.append({
            'bin': [low, min(high, 1.0)], 'games': len(group),
            'mean_forecast': (sum(r['p_home'] for r in group) / len(group)) if group else None,
            'observed_home_win_rate': (sum(r['home_won'] for r in group) / len(group)) if group else None,
        })
    weeks = sorted({r['week'] for r in rows})
    return {'season': summarise(rows), 'calibration': calibration,
            'by_week': {str(week): summarise([r for r in rows if r['week'] == week]) for week in weeks}}


def bootstrap_interval(values, rng):
    """95% percentile interval of the mean of `values`, resampling games with replacement."""
    n = len(values)
    means = []
    for _ in range(BOOTSTRAP_REPS):
        means.append(sum(values[rng.randrange(n)] for _ in range(n)) / n)
    means.sort()
    return means[int(0.025 * BOOTSTRAP_REPS)], means[int(0.975 * BOOTSTRAP_REPS) - 1]


ADVANCE_RULE = ('advance only if mean log loss and mean Brier are both lower than baseline and the 95% interval for the '
                'log-loss difference is below zero')


def label_for(weeks):
    return 'retrospective-exposure' if max(weeks) <= 8 else 'prospective (weeks 9 onward are prospective)'


def not_scored(weeks, accounting, seed_rule):
    """The report when no game can be scored. It estimates nothing, and nothing advances."""
    reasons = sorted(set(accounting['excluded'].values())) or ['the arms hold no games']
    return {'label': label_for(weeks), 'weeks': weeks, 'games_scored': 0, 'accounting': accounting,
            'seed_rule': seed_rule, 'baseline': None, 'candidate': None, 'paired': None,
            'advance_rule': {'rule': ADVANCE_RULE, 'advance': False, 'verdict': 'NOT SCORED',
                             'reason': '; '.join(reasons)}}


def score(baseline_dir, candidate_dir, db, weeks, season=2026, seed_rule='valid_full_game'):
    results, unscored = load_results(db, season, weeks)
    baseline, candidate = load_arm(baseline_dir), load_arm(candidate_dir)
    if set(baseline) != set(candidate):
        raise ValueError(f'arms hold different games: only baseline {sorted(set(baseline) - set(candidate))}, '
                         f'only candidate {sorted(set(candidate) - set(baseline))}')
    accounting = {'results_in_weeks': len(results), 'unscored_in_weeks': unscored, 'arm_games': len(baseline),
                  'excluded': {}}
    rows = {'baseline': [], 'candidate': []}
    for game_id in sorted(baseline):
        if game_id not in results:
            accounting['excluded'][game_id] = 'no final score in nfl_schedule for the requested weeks'
            continue
        result = results[game_id]
        base_valid, base_seeds = seed_outcomes(baseline[game_id], seed_rule)
        cand_valid, cand_seeds = seed_outcomes(candidate[game_id], seed_rule)
        if base_seeds != cand_seeds:
            raise ValueError(f'{game_id}: arms do not share a seed list')
        if not base_valid or not cand_valid:
            accounting['excluded'][game_id] = 'no valid untied seeds in an arm'
            continue
        y = 1 if result['home_points'] > result['away_points'] else 0
        for name, valid, payload in (('baseline', base_valid, baseline[game_id]),
                                     ('candidate', cand_valid, candidate[game_id])):
            p = home_win_probability(valid)
            home_samples = [row['home_points'] for row in valid]
            away_samples = [row['away_points'] for row in valid]
            rows[name].append({
                'game_id': game_id, 'week': result['week'], 'p_home': p, 'home_won': y,
                'brier': brier(p, y), 'log_loss': log_loss(p, y), 'valid_seeds': len(valid),
                'crps_home': crps(home_samples, result['home_points']),
                'crps_away': crps(away_samples, result['away_points']),
            })
    if not rows['baseline']:
        return not_scored(weeks, accounting, seed_rule)
    games = [g for g in sorted({r['game_id'] for r in rows['baseline']})]
    base_by_game = {r['game_id']: r for r in rows['baseline']}
    cand_by_game = {r['game_id']: r for r in rows['candidate']}
    d_ll = [cand_by_game[g]['log_loss'] - base_by_game[g]['log_loss'] for g in games]
    d_brier = [cand_by_game[g]['brier'] - base_by_game[g]['brier'] for g in games]
    rng = random.Random(BOOTSTRAP_SEED)
    ll_low, ll_high = bootstrap_interval(d_ll, rng)
    brier_low, brier_high = bootstrap_interval(d_brier, rng)
    mean_d_ll = sum(d_ll) / len(d_ll)
    mean_d_brier = sum(d_brier) / len(d_brier)
    advance = mean_d_ll < 0 and mean_d_brier < 0 and ll_high < 0
    return {
        'label': label_for(weeks),
        'weeks': weeks, 'games_scored': len(games), 'accounting': accounting, 'seed_rule': seed_rule,
        'baseline': arm_metrics(rows['baseline']), 'candidate': arm_metrics(rows['candidate']),
        'paired': {'mean_log_loss_difference': mean_d_ll, 'log_loss_difference_95ci': [ll_low, ll_high],
                   'mean_brier_difference': mean_d_brier, 'brier_difference_95ci': [brier_low, brier_high],
                   'bootstrap_reps': BOOTSTRAP_REPS, 'bootstrap_seed': BOOTSTRAP_SEED},
        'advance_rule': {'rule': ADVANCE_RULE, 'advance': advance, 'verdict': 'PASS' if advance else 'FAIL'},
    }


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--baseline-dir', type=Path, required=True)
    ap.add_argument('--candidate-dir', type=Path, required=True)
    ap.add_argument('--weeks', type=parse_weeks, required=True, help='e.g. 1-8')
    ap.add_argument('--season', type=int, default=2026)
    ap.add_argument('--db', default=DEFAULT_DB)
    ap.add_argument('--out', type=Path, required=True)
    ap.add_argument('--seed-rule', choices=sorted(SEED_RULES), default='valid_full_game',
                    help='which seeds count: valid_full_game (verified snapshots only) or complete_game')
    args = ap.parse_args(argv)
    report = score(args.baseline_dir, args.candidate_dir, args.db, args.weeks, season=args.season,
                   seed_rule=args.seed_rule)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=1, sort_keys=True) + '\n')
    print(f"games scored {report['games_scored']}, excluded {len(report['accounting']['excluded'])}")
    if report['games_scored'] == 0:
        print(f"advance rule: NOT SCORED ({report['advance_rule']['reason']})")
        print(f'wrote {args.out}')
        return
    base, cand, paired = report['baseline']['season'], report['candidate']['season'], report['paired']
    print(f"brier   baseline {base['brier']:.4f}  candidate {cand['brier']:.4f}")
    print(f"logloss baseline {base['log_loss']:.4f}  candidate {cand['log_loss']:.4f}")
    print(f"mean log-loss difference {paired['mean_log_loss_difference']:+.4f}  95% interval "
          f"[{paired['log_loss_difference_95ci'][0]:+.4f}, {paired['log_loss_difference_95ci'][1]:+.4f}]")
    print(f"advance rule: {report['advance_rule']['verdict']}  ({report['label']})")
    print(f'wrote {args.out}')


if __name__ == '__main__':
    main()
