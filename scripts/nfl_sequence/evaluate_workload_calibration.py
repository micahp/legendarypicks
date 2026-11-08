"""Which player-allocation model predicts real carries and targets best? (research, no game is simulated)

For every team-game of an evaluation season, each model predicts the split of the team's carries or targets across players, using only
data from before that game. The team's real total N is given to every model, so the test measures who gets the opportunities and not
how many there are. Models:

  A  position and usage rank   league-average share by position and prior-season usage rank (a proxy for the layers-off fallback;
                               depth charts are not available historically)
  B  fixed historical shares   pooled seasons from FIRST_SEASON up to the season before the evaluation, a multinomial
  C  current Dirichlet         previous-season shares, with the concentration fitted on the previous season
  D  in-season adaptive        previous-season shares blended with the team's own earlier games: w = N0 / (N0 + g)

All four see the same player set per team-game: players with any prior-season or earlier-this-season usage for that team. Real usage by
anyone else is pooled as OTHER. The primary metric is the Dirichlet-multinomial negative log-likelihood of the real counts given N.
Pregame injury and roster data are not used, so every result is exploratory. Games are resampled in clusters for the paired intervals.
"""
import argparse
import hashlib
import json
import math
import sqlite3
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import player_shares as ps  # noqa: E402
import share_distributions as sd  # noqa: E402

ROLES = {'receive': ('receiver_player_id', 'pass'), 'carry': ('rusher_player_id', 'run')}
MODELS = ('A', 'B', 'C', 'D')
FLOOR = ps.FLOOR
OTHER_WEIGHT = 0.02  # share of the Dirichlet mass kept for players nobody could name before the game; the same for every model
N0 = 4.0
MULTINOMIAL_PHI = 1e6
RANK_CAP = 6
INTERVAL_DRAWS = 300
BOOTSTRAP = 2000


def load_games(con, season, role, last_week=None):
    """[{game_id, week, team, counts}] for the regular season, with each team-game's per-player counts."""
    column, play_type = ROLES[role]
    sql = (f"SELECT game_id, week, posteam, {column}, COUNT(*) FROM nfl_pbp WHERE season = ? AND week <= ? AND play_type = ? "
           f"AND posteam IS NOT NULL AND {column} IS NOT NULL GROUP BY game_id, week, posteam, {column}")
    games = {}
    for game_id, week, team, player, n in con.execute(sql, (season, 18 if last_week is None else last_week, play_type)):
        row = games.setdefault((game_id, team), {'game_id': game_id, 'week': int(week), 'team': team, 'counts': {}})
        row['counts'][player] = n
    return sorted(games.values(), key=lambda r: (r['week'], r['game_id'], r['team']))


def team_totals(games):
    """{team: {player: count}} summed over the given team-games."""
    out = defaultdict(lambda: defaultdict(int))
    for game in games:
        for player, n in game['counts'].items():
            out[game['team']][player] += n
    return out


def shares(counts):
    total = sum(counts.values())
    return {p: n / total for p, n in counts.items()} if total else {}


def normalise(weights):
    total = sum(weights.values())
    return {p: w / total for p, w in weights.items()}


def rank_table(prior_games, positions):
    """League mean share by (position, usage rank within the team), from one prior season."""
    sums, counts = defaultdict(float), defaultdict(int)
    for team, players in team_totals(prior_games).items():
        total = sum(players.values())
        by_position = defaultdict(list)
        for player, n in players.items():
            by_position[positions.get(player, '?')].append(n / total)
        for position, values in by_position.items():
            for rank, value in enumerate(sorted(values, reverse=True), 1):
                key = (position, min(rank, RANK_CAP))
                sums[key] += value
                counts[key] += 1
    return {key: sums[key] / counts[key] for key in sums}


def predictions(game, earlier_games, prior_by_team, pooled_by_team, table_a, positions, phi_c):
    """Candidate players and each model's (shares, phi) for one team-game, using only earlier information."""
    team = game['team']
    prior = shares(prior_by_team.get(team, {}))
    pooled = shares(pooled_by_team.get(team, {}))
    current_counts = defaultdict(int)
    g = 0
    for earlier in earlier_games.get(team, ()):
        g += 1
        for player, n in earlier['counts'].items():
            current_counts[player] += n
    current = shares(current_counts)
    candidates = sorted(set(prior_by_team.get(team, {})) | set(pooled_by_team.get(team, {})) | set(current_counts))
    if not candidates:
        return None
    # A: league share by position and prior-season usage rank within the team
    ranked = defaultdict(list)
    for player in candidates:
        if player in prior:
            ranked[positions.get(player, '?')].append((-prior[player], player))
    rank_of = {player: min(rank, RANK_CAP) for items in ranked.values() for rank, (_, player) in enumerate(sorted(items), 1)}
    weights_a = {p: max(table_a.get((positions.get(p, '?'), rank_of[p]), FLOOR), FLOOR) if p in rank_of else FLOOR
                 for p in candidates}
    weights_b = {p: max(pooled.get(p, 0.0), FLOOR) for p in candidates}
    weights_c = {p: max(prior.get(p, 0.0), FLOOR) for p in candidates}
    w = N0 / (N0 + g)
    weights_d = {p: max(w * prior.get(p, 0.0) + (1 - w) * current.get(p, 0.0), FLOOR) for p in candidates}
    return candidates, {'A': (normalise(weights_a), phi_c), 'B': (normalise(weights_b), MULTINOMIAL_PHI),
                        'C': (normalise(weights_c), phi_c), 'D': (normalise(weights_d), phi_c)}


def dm_loglik(counts, total, alphas):
    a0 = sum(alphas.values())
    value = math.lgamma(total + 1) + math.lgamma(a0) - math.lgamma(a0 + total)
    for player, a in alphas.items():
        n = counts.get(player, 0)
        value += math.lgamma(n + a) - math.lgamma(a) - math.lgamma(n + 1)
    return value


def score_game(game, candidates, model_inputs, rng):
    """Per-model metrics for one team-game. Real counts of players outside `candidates` are pooled as OTHER."""
    counts = {p: game['counts'].get(p, 0) for p in candidates}
    other = sum(n for p, n in game['counts'].items() if p not in counts)
    total = sum(counts.values()) + other
    rows = {}
    for model, (share, phi) in model_inputs.items():
        mass = phi * (1 - OTHER_WEIGHT)
        alphas = {p: mass * share[p] for p in candidates}
        alphas['OTHER'] = phi * OTHER_WEIGHT
        observed = dict(counts, OTHER=other)
        nll = -dm_loglik(observed, total, alphas)
        names = list(alphas)
        p_vec = np.array([alphas[n] for n in names])
        if phi >= MULTINOMIAL_PHI:
            draws = rng.multinomial(total, p_vec / p_vec.sum(), size=INTERVAL_DRAWS)
        else:
            draws = np.array([rng.multinomial(total, rng.dirichlet(p_vec)) for _ in range(INTERVAL_DRAWS)])
        lo, hi = np.quantile(draws, 0.1, axis=0), np.quantile(draws, 0.9, axis=0)
        real = np.array([observed[n] for n in names])
        covered = (real >= lo) & (real <= hi)
        main = np.array([share.get(n, 0.0) >= 0.10 for n in names])  # players the model gives at least 10% of the opportunities
        mean_share = p_vec / p_vec.sum()
        abs_err = float(np.abs(real / total - mean_share)[:-1].mean()) if total else 0.0
        top_pred = max(candidates, key=lambda p: share[p])
        top_real = max(counts, key=lambda p: (counts[p], p)) if any(counts.values()) else None
        rows[model] = {'nll': nll, 'mean_abs_share_error': abs_err, 'top_player_hit': int(top_pred == top_real),
                       'interval_covered': int(covered.sum()), 'interval_players': len(names),
                       'main_covered': int((covered & main).sum()), 'main_players': int(main.sum())}
    return {'total': total, 'other': other, 'candidates': len(candidates), 'models': rows}


def cluster_bootstrap(per_game, rng, draws=BOOTSTRAP):
    """Mean and 95% interval of the sum of per-game differences, resampling games (a game holds two team-games)."""
    values = np.array(per_game)
    if len(values) == 0:
        return {'mean': None, 'lo': None, 'hi': None, 'games': 0}
    idx = rng.integers(0, len(values), size=(draws, len(values)))
    means = values[idx].mean(axis=1)
    return {'mean': float(values.mean()), 'lo': float(np.quantile(means, 0.025)), 'hi': float(np.quantile(means, 0.975)),
            'games': int(len(values))}


def evaluate(db, season, role, last_week=None, seed=0):
    con = sqlite3.connect(f'file:{db}?mode=ro', uri=True, timeout=10)
    try:
        games = load_games(con, season, role, last_week)
        prior_games = load_games(con, season - 1, role)
        pooled_games = [g for s in range(ps.FIRST_SEASON, season) for g in load_games(con, s, role)]
        positions = sd.player_positions(db)
    finally:
        con.close()
    if not games or not prior_games:
        raise ValueError(f'no {role} data for {season} or {season - 1}')
    prior_by_team = team_totals(prior_games)
    pooled_by_team = team_totals(pooled_games)
    fit = sd.fit_from_counts(*_fit_inputs(prior_games), season - 1)
    phi_c = fit['phi']
    table_a = rank_table(prior_games, positions)
    earlier = defaultdict(list)
    rng = np.random.default_rng(seed)
    results = []
    for game in games:
        made = predictions(game, earlier, prior_by_team, pooled_by_team, table_a, positions, phi_c)
        earlier_for_team = earlier[game['team']]
        if made is not None and sum(game['counts'].values()) > 0:
            candidates, inputs = made
            scored = score_game(game, candidates, inputs, rng)
            results.append({'game_id': game['game_id'], 'week': game['week'], 'team': game['team'], **scored})
        # a game becomes history only after it has been scored, and only for later weeks
        earlier_for_team.append(game)
        earlier_for_team.sort(key=lambda g: g['week'])
    # remove same-week information: predictions() above read `earlier` before the current team-game was added, but a team plays once a week
    return results, {'phi_c': phi_c, 'phi_interval': fit['phi_interval'], 'prior_team_games': fit['team_games']}


def _fit_inputs(prior_games):
    games = defaultdict(lambda: defaultdict(dict))
    season_counts = defaultdict(lambda: defaultdict(int))
    for game in prior_games:
        games[game['team']][game['game_id']] = dict(game['counts'])
        for player, n in game['counts'].items():
            season_counts[game['team']][player] += n
    return games, season_counts


def summarise(results, seed=0):
    rng = np.random.default_rng(seed)
    out = {'team_games': len(results), 'models': {}, 'paired_nll_vs_C': {}}
    for model in MODELS:
        rows = [r['models'][model] for r in results]
        n = len(rows)
        main_players = sum(r['main_players'] for r in rows)
        out['models'][model] = {
            'mean_nll_per_team_game': sum(r['nll'] for r in rows) / n,
            'mean_abs_share_error': sum(r['mean_abs_share_error'] for r in rows) / n,
            'top_player_hit_rate': sum(r['top_player_hit'] for r in rows) / n,
            'interval_80_coverage_all_players': sum(r['interval_covered'] for r in rows) / sum(r['interval_players'] for r in rows),
            'interval_80_coverage_main_players': (sum(r['main_covered'] for r in rows) / main_players) if main_players else None}
    by_game = defaultdict(list)
    for r in results:
        by_game[r['game_id']].append(r)
    for model in MODELS:
        if model == 'C':
            continue
        diffs = [sum(r['models'][model]['nll'] - r['models']['C']['nll'] for r in rows) / len(rows) for rows in by_game.values()]
        out['paired_nll_vs_C'][model] = cluster_bootstrap(diffs, rng)  # positive: model worse than C
    out['other_share_of_opportunities'] = sum(r['other'] for r in results) / sum(r['total'] for r in results)
    return out


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument('--db', default='/root/legendarypicks/backend/data/picks.dev.db')
    ap.add_argument('--season', type=int, required=True)
    ap.add_argument('--role', choices=tuple(ROLES), required=True)
    ap.add_argument('--last-week', type=int, default=None)
    ap.add_argument('--seed', type=int, default=0)
    ap.add_argument('--out-prefix', required=True)
    args = ap.parse_args(argv)
    results, fit = evaluate(args.db, args.season, args.role, args.last_week, args.seed)
    summary = summarise(results, args.seed)
    commit = subprocess.run(['git', '-C', str(HERE), 'rev-parse', 'HEAD'], capture_output=True, text=True).stdout.strip()
    manifest = {'season': args.season, 'role': args.role, 'last_week': args.last_week, 'seed': args.seed,
                'label': 'exploratory: no pregame injury or roster data; players are those with earlier usage for the team',
                'parameters': {'FLOOR': FLOOR, 'OTHER_WEIGHT': OTHER_WEIGHT, 'N0': N0, 'RANK_CAP': RANK_CAP,
                               'INTERVAL_DRAWS': INTERVAL_DRAWS, 'BOOTSTRAP': BOOTSTRAP, 'first_pooled_season': ps.FIRST_SEASON},
                'fit': fit, 'database': args.db, 'script_sha256': sha256(__file__), 'git_commit': commit}
    Path(f'{args.out_prefix}.json').write_text(json.dumps({'manifest': manifest, 'summary': summary}, indent=1, sort_keys=True) + '\n')
    with open(f'{args.out_prefix}.csv', 'w') as handle:
        handle.write('game_id,week,team,model,total,other,candidates,nll,mean_abs_share_error,top_player_hit,interval_covered,interval_players\n')
        for r in results:
            for model in MODELS:
                m = r['models'][model]
                handle.write(f"{r['game_id']},{r['week']},{r['team']},{model},{r['total']},{r['other']},{r['candidates']},"
                             f"{m['nll']:.4f},{m['mean_abs_share_error']:.5f},{m['top_player_hit']},{m['interval_covered']},{m['interval_players']}\n")
    print(json.dumps(summary, indent=1, sort_keys=True))


if __name__ == '__main__':
    main()
