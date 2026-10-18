"""NHL goalie adjustment: G1 (league-average goalie) vs G2 (regressed GSAx + expected starter).

Implements the pre-registration in
research/nhl/goalie-adjustment-pre-registration-2026-10-18.md exactly:

- G1: multiplicative Poisson rate model, rolling 10-game team GF/GA shrunk (w=5) toward the
  cumulative league mean, league-level home/away goal split. No goalie term.
- G2: G1 rate multiplied by exp(kappa * goalie_score) where goalie_score is the expected
  starter's regressed GSAx/shot rate (empirical-Bayes, k=1500 shots, trailing-3-season
  league mean). Fit on 2008-2022, validation 2023, test 2024-2025 walk-forward.
- Primary scored object: the PRE-confirmation forecast (predicted starter). The
  post-confirmation forecast (observed starter) is recorded for the movement comparison.
- Gates: paired game-clustered bootstrap on Brier and log loss; CRPS and midpoint-PIT KS.
"""
import json
import os
import numpy as np
import pandas as pd
from scipy.optimize import minimize_scalar
from scipy.stats import poisson, kstest

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, 'data')
OUT = os.path.join(HERE, 'results')
os.makedirs(OUT, exist_ok=True)

TRAIN_SEASONS = list(range(2008, 2023))   # 2008..2022
VAL_SEASON = 2023
TEST_SEASONS = [2024, 2025]
K_SHOTS = 1500          # pre-registered shrinkage constant (shots)
W_TEAM = 5              # G1 team-rate shrinkage weight (pseudo-games)
ROLL = 10               # G1 rolling window (games)
MAX_GOALS = 20          # support for Poisson CRPS / win prob
BOOT = 10000
RNG = np.random.default_rng(20261018)


def load():
    ledger = pd.read_parquet(os.path.join(DATA, 'ledger.parquet'))
    games = pd.read_parquet(os.path.join(DATA, 'games.parquet'))
    games = games.sort_values(['gameDate', 'game_id']).reset_index(drop=True)
    games['game_order'] = np.arange(len(games))
    ledger = ledger.merge(games[['season', 'game_id', 'game_order']], on=['season', 'game_id'], how='inner')
    return games, ledger


def trailing_league_gsax_mean(ledger, seasons=3):
    """league_mean_rate[season] = (sum xg - sum goals)/sum shots over the prior `seasons` seasons."""
    per_season = ledger.groupby('season').agg(shots=('shots_faced', 'sum'),
                                              xg=('xg_against', 'sum'),
                                              ga=('goals_against', 'sum'))
    per_season['gsax'] = per_season['xg'] - per_season['ga']
    per_season['rate'] = per_season['gsax'] / per_season['shots']
    out = {}
    all_seasons = sorted(per_season.index)
    for i, s in enumerate(all_seasons):
        window = [x for x in all_seasons if x < s][-seasons:]
        if not window:
            out[s] = 0.0
            continue
        gsax = sum(per_season.loc[x, 'gsax'] for x in window)
        shots = sum(per_season.loc[x, 'shots'] for x in window)
        out[s] = gsax / shots
    return out


def build_goalie_features(games, ledger, league_mean_rate):
    """Per goalie cumulative prior stats and per (game, team) expected/observed starter scores."""
    ledger = ledger.sort_values(['goalie_id', 'game_order']).reset_index(drop=True)
    g = ledger.groupby('goalie_id', sort=False)
    ledger['cum_shots'] = g['shots_faced'].cumsum() - ledger['shots_faced']
    ledger['cum_xg'] = g['xg_against'].cumsum() - ledger['xg_against']
    ledger['cum_ga'] = g['goals_against'].cumsum() - ledger['goals_against']
    ledger['cum_gsax'] = ledger['cum_xg'] - ledger['cum_ga']
    # regressed GSAx/shot rate using only PRIOR shots (shifted cumsums above)
    ledger['league_mean'] = ledger['season'].map(league_mean_rate).fillna(0.0)
    ledger['goalie_score'] = (ledger['cum_gsax'] + K_SHOTS * ledger['league_mean']) / (ledger['cum_shots'] + K_SHOTS)
    # the current game's own stats, for identifying the observed starter
    ledger['own_shots'] = ledger['shots_faced']

    # observed starter per (game, team): the goalie who faced that side's first shot-against
    obs = (ledger[ledger['is_start']]
           .drop_duplicates(['game_order', 'goalie_team'], keep='first'))
    obs_map = {(int(r.game_order), r.goalie_team): r.goalie_id for r in obs.itertuples(index=False)}

    # team STARTS lists for the expected-starter heuristic (starts, not relief appearances)
    apps = {}
    for row in ledger[ledger['is_start']][['goalie_team', 'season', 'game_order', 'gameDate', 'goalie_id']].itertuples(index=False):
        apps.setdefault((row.goalie_team, row.season), []).append((row.game_order, row.gameDate, row.goalie_id))
    for key in apps:
        apps[key].sort()

    def expected_starter(team, season, game_order, date):
        """Predicted starter per the pre-registration: the goalie with the team's most recent
        prior START this season; on a back-to-back, the other goalie with a prior start this
        season. None if no candidates."""
        prior = [(o, d, gid) for (o, d, gid) in apps.get((team, season), []) if o < game_order]
        if not prior:
            return None
        primary = prior[-1]
        b2b = (date - primary[1]).days <= 1
        if b2b and len(prior) >= 2:
            return prior[-2][2]
        return primary[2]

    n = len(games)
    rows = []
    games_idx = games.set_index('game_order')
    for go in range(n):
        r = games_idx.loc[go]
        for side, team, opp in (('HOME', r['home_team'], r['away_team']),
                                ('AWAY', r['away_team'], r['home_team'])):
            exp_gid = expected_starter(team, r['season'], go, r['gameDate'])
            obs_gid = obs_map.get((go, team))
            rows.append({
                'game_order': go, 'season': r['season'], 'side': side,
                'team': team, 'opp': opp, 'home_goals': r['home_goals'], 'away_goals': r['away_goals'],
                'gameDate': r['gameDate'], 'home_won': r['home_won'],
                'exp_goalie': exp_gid, 'obs_goalie': obs_gid,
            })
    team_side = pd.DataFrame(rows)

    # attach goalie scores via an as-of lookup: for a target game_order, use the goalie's
    # cumulative stats through his most recent appearance STRICTLY BEFORE that game.
    ledger['own_gsax'] = ledger['xg_against'] - ledger['goals_against']
    ledger = ledger.sort_values(['goalie_id', 'game_order']).reset_index(drop=True)
    g2 = ledger.groupby('goalie_id', sort=False)
    ledger['cum_shots_after'] = g2['shots_faced'].cumsum()
    ledger['cum_gsax_after'] = g2['own_gsax'].cumsum()
    asof = {gid: (gdf['game_order'].values, gdf['cum_shots_after'].values, gdf['cum_gsax_after'].values)
            for gid, gdf in ledger.groupby('goalie_id')}

    def asof_score(gid, go, season):
        # no candidate or no prior appearance => zero prior shots => regressed rate = league mean
        if gid is None or (isinstance(gid, float) and np.isnan(gid)) or gid not in asof:
            n_shots, n_gsax = 0, 0.0
        else:
            orders, cs, cg = asof[gid]
            i = int(np.searchsorted(orders, go, side='left')) - 1
            if i < 0:
                n_shots, n_gsax = 0, 0.0
            else:
                n_shots, n_gsax = int(cs[i]), float(cg[i])
        L = league_mean_rate.get(season, 0.0)
        return (n_gsax + K_SHOTS * L) / (n_shots + K_SHOTS)

    team_side['score_pre'] = [asof_score(g, go, s) for g, go, s in
                              zip(team_side['exp_goalie'], team_side['game_order'], team_side['season'])]
    team_side['score_post'] = [asof_score(g, go, s) for g, go, s in
                               zip(team_side['obs_goalie'], team_side['game_order'], team_side['season'])]
    team_side['has_exp'] = team_side['exp_goalie'].notna().astype(int)
    return team_side


def build_g1_rates(team_side):
    """G1 multiplicative Poisson rates: rolling-10 GF/GA per team shrunk toward the
    cumulative league mean, with league-level home/away split. No goalie term."""
    ts = team_side.sort_values(['game_order', 'side']).reset_index(drop=True)
    # team-game long table: one row per (game, side) with GF = own goals, GA = opponent goals
    ts['gf'] = np.where(ts['side'] == 'HOME', ts['home_goals'], ts['away_goals'])
    ts['ga'] = np.where(ts['side'] == 'HOME', ts['away_goals'], ts['home_goals'])
    ts = ts.sort_values(['team', 'game_order']).reset_index(drop=True)
    g = ts.groupby('team', sort=False)
    ts['gf_roll'] = g['gf'].transform(lambda s: s.shift(1).rolling(ROLL, min_periods=1).sum()).fillna(0.0)
    ts['ga_roll'] = g['ga'].transform(lambda s: s.shift(1).rolling(ROLL, min_periods=1).sum()).fillna(0.0)
    ts['n_prior'] = g.cumcount()
    # cumulative league means up to (strictly before) each game
    ordered = ts.sort_values('game_order')
    cg = ordered.groupby('game_order', sort=False).agg(home_g=('home_goals', 'max'), away_g=('away_goals', 'max'))
    cg = cg.sort_index()
    cg['n'] = 1
    cum = cg.cumsum().shift(1).fillna(0.0)
    cum['L_home'] = cum['home_g'] / cum['n']
    cum['L_away'] = cum['away_g'] / cum['n']
    cum['L'] = (cum['home_g'] + cum['away_g']) / (2 * cum['n'])
    Lmap = cum[['L_home', 'L_away', 'L']]
    ts = ts.merge(Lmap, left_on='game_order', right_index=True, how='left')

    # shrunk attack/defence ratios
    ts['attack'] = (ts['gf_roll'] + W_TEAM * ts['L']) / ((np.minimum(ts['n_prior'], ROLL)) + W_TEAM) / ts['L']
    ts['defence'] = (ts['ga_roll'] + W_TEAM * ts['L']) / ((np.minimum(ts['n_prior'], ROLL)) + W_TEAM) / ts['L']
    ts['mu_g1'] = np.where(ts['side'] == 'HOME',
                           ts['L_home'] * ts['attack'] * ts['defence'],
                           ts['L_away'] * ts['attack'] * ts['defence'])
    return ts.sort_values('game_order').reset_index(drop=True)


def fit_kappa(ts, mask):
    """Fit the single goalie coefficient on the training rows via Poisson offset GLM."""
    sub = ts[mask].reset_index(drop=True)
    # each row: goals scored by this side's team, predicted from the OPPONENT's goalie score
    opp = ts.set_index(['game_order', 'side'])['score_pre']
    x = np.array([opp.loc[(go, 'AWAY' if s == 'HOME' else 'HOME')]
                  for go, s in zip(sub['game_order'], sub['side'])])
    y = sub['gf'].values
    offset = np.log(sub['mu_g1'].values)

    def nll(k):
        mu = np.exp(offset + k * x)
        return np.sum(mu - y * np.log(mu))

    res = minimize_scalar(nll, bounds=(-20, 20), method='bounded')
    return res.x, x, y, offset


def poisson_win_prob(mu_h, mu_a, p_home_so):
    """P(home win) from two independent Poissons, ties resolved with home shootout rate."""
    h = np.arange(MAX_GOALS + 1)
    M = np.outer(poisson.pmf(h, mu_h), poisson.pmf(h, mu_a))
    p_home_reg = float(np.triu(M, k=1).sum())
    p_tie = float(np.trace(M))
    return p_home_reg + p_tie * p_home_so


def crps_poisson(mu, y, support=MAX_GOALS):
    x = np.arange(support + 1)
    pmf = poisson.pmf(x, mu)
    cdf = np.cumsum(pmf)
    # E|X - y| for discrete X
    term1 = np.sum(pmf * np.abs(x - y))
    # E|X - X'| = 2 * sum_i pmf[i] * cdf[i]  (standard identity for discrete dists)
    term2 = 2 * np.sum(pmf * cdf)
    return term1 - 0.5 * term2


def midpoint_pit(mu, y, support=MAX_GOALS):
    pmf = poisson.pmf(np.arange(support + 1), mu)
    y = int(min(y, support))
    if y == 0:
        return 0.5 * pmf[0]
    return poisson.cdf(y - 1, mu) + 0.5 * pmf[y]


def evaluate(ts, mask, kappa, p_home_so):
    """Brier / log loss / CRPS / PIT for G1 and G2 on the given games (pre-confirmation)."""
    sub = ts[mask]
    home = sub[sub['side'] == 'HOME'].sort_values('game_order').reset_index(drop=True)
    away = sub[sub['side'] == 'AWAY'].sort_values('game_order').reset_index(drop=True)
    assert (home['game_order'].values == away['game_order'].values).all()
    mu_h_g1 = home['mu_g1'].values
    mu_a_g1 = away['mu_g1'].values
    # the goalie facing this side's shots is the opponent's expected starter
    mu_h_g2 = mu_h_g1 * np.exp(kappa * away['score_pre'].values)
    mu_a_g2 = mu_a_g1 * np.exp(kappa * home['score_pre'].values)
    y = home['home_won'].values.astype(int)
    home_goals = home['home_goals'].values
    away_goals = away['away_goals'].values

    out = {}
    for name, mu_h, mu_a in (('G1', mu_h_g1, mu_a_g1), ('G2', mu_h_g2, mu_a_g2)):
        p = np.array([poisson_win_prob(h, a, p_home_so) for h, a in zip(mu_h, mu_a)])
        brier = float(np.mean((p - y) ** 2))
        eps = 1e-12
        ll = float(-np.mean(y * np.log(np.clip(p, eps, 1 - eps)) + (1 - y) * np.log(np.clip(1 - p, eps, 1 - eps))))
        crps_h = np.array([crps_poisson(h, yh) for h, yh in zip(mu_h, home_goals)])
        crps_a = np.array([crps_poisson(a, ya) for a, ya in zip(mu_a, away_goals)])
        crps = float(np.mean(np.concatenate([crps_h, crps_a])))
        pit_h = np.array([midpoint_pit(h, yh) for h, yh in zip(mu_h, home_goals)])
        pit_a = np.array([midpoint_pit(a, ya) for a, ya in zip(mu_a, away_goals)])
        ks_h = float(kstest(pit_h, 'uniform').statistic)
        ks_a = float(kstest(pit_a, 'uniform').statistic)
        out[name] = {'brier': brier, 'log_loss': ll, 'crps': crps,
                     'pit_ks_home': ks_h, 'pit_ks_away': ks_a}

    # paired game-clustered bootstrap on Brier and log loss differences (G1 - G2; positive = G2 better)
    p1 = np.array([poisson_win_prob(h, a, p_home_so) for h, a in zip(mu_h_g1, mu_a_g1)])
    p2 = np.array([poisson_win_prob(h, a, p_home_so) for h, a in zip(mu_h_g2, mu_a_g2)])
    d_brier = (p1 - y) ** 2 - (p2 - y) ** 2
    eps = 1e-12
    ll1 = -(y * np.log(np.clip(p1, eps, 1 - eps)) + (1 - y) * np.log(np.clip(1 - p1, eps, 1 - eps)))
    ll2 = -(y * np.log(np.clip(p2, eps, 1 - eps)) + (1 - y) * np.log(np.clip(1 - p2, eps, 1 - eps)))
    d_ll = ll1 - ll2
    n = len(d_brier)
    idx = RNG.integers(0, n, size=(BOOT, n))
    boot_b = d_brier[idx].mean(axis=1)
    boot_l = d_ll[idx].mean(axis=1)
    out['paired'] = {
        'brier_diff_mean': float(d_brier.mean()),
        'brier_ci': [float(np.percentile(boot_b, 2.5)), float(np.percentile(boot_b, 97.5))],
        'logloss_diff_mean': float(d_ll.mean()),
        'logloss_ci': [float(np.percentile(boot_l, 2.5)), float(np.percentile(boot_l, 97.5))],
        'n_games': int(n),
    }
    return out


def main():
    games, ledger = load()
    # binary outcome (home won, shootout included) from the shots table's homeTeamWon
    con = __import__('duckdb').connect('/root/nhl_database_2025-26-playoffs.duckdb', read_only=True)
    hw = con.execute("""
      SELECT season, game_id, MAX(homeTeamWon)::INT AS home_won FROM shots WHERE isPlayoffGame=0 GROUP BY 1,2
    """).fetchdf()
    games = games.merge(hw, on=['season', 'game_id'], how='left')
    assert games['home_won'].notna().all()

    league_mean_rate = trailing_league_gsax_mean(ledger)
    team_side = build_goalie_features(games, ledger, league_mean_rate)
    ts = build_g1_rates(team_side)
    ts.to_parquet(os.path.join(OUT, 'ts.parquet'))

    # home shootout win rate from the training window (ties only)
    train_games = games[games['season'].isin(TRAIN_SEASONS)]
    ties = train_games[train_games['home_goals'] == train_games['away_goals']]
    p_home_so = float(ties['home_won'].mean())

    train_mask = ts['season'].isin(TRAIN_SEASONS)
    val_mask = ts['season'] == VAL_SEASON
    test_mask = ts['season'].isin(TEST_SEASONS)

    kappa, x_fit, y_fit, offset_fit = fit_kappa(ts, train_mask)
    print(f"kappa = {kappa:.4f}")

    from datetime import datetime, timezone
    run_utc = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
    results = {'kappa': float(kappa), 'p_home_so': p_home_so,
               'run_utc': run_utc,
               'forecast_as_of_note': ('both pre- and post-confirmation forecasts were generated by this '
                                       'run at the recorded run_utc; this is a retrospective '
                                       'reconstruction, not a prospective lock'),
               'train_seasons': TRAIN_SEASONS, 'val_season': VAL_SEASON, 'test_seasons': TEST_SEASONS}
    for label, mask in (('validation', val_mask), ('test', test_mask)):
        results[label] = evaluate(ts, mask, kappa, p_home_so)
        r = results[label]
        print(f"{label}: n={r['paired']['n_games']} G1 brier={r['G1']['brier']:.5f} G2 brier={r['G2']['brier']:.5f} "
              f"diff={r['paired']['brier_diff_mean']:.6f} ci={r['paired']['brier_ci']}")
        print(f"          G1 ll={r['G1']['log_loss']:.5f} G2 ll={r['G2']['log_loss']:.5f} "
              f"diff={r['paired']['logloss_diff_mean']:.6f} ci={r['paired']['logloss_ci']}")
        print(f"          G1 crps={r['G1']['crps']:.5f} G2 crps={r['G2']['crps']:.5f} "
              f"KS home {r['G1']['pit_ks_home']:.4f}->{r['G2']['pit_ks_home']:.4f} "
              f"away {r['G1']['pit_ks_away']:.4f}->{r['G2']['pit_ks_away']:.4f}")

    # goalie-start counts in the test window
    test_ts = ts[test_mask]
    n_starts = int((test_ts['obs_goalie'].notna()).sum())
    results['test_goalie_starts'] = n_starts

    # pre- vs post-confirmation movement on the test window
    th = test_ts[test_ts['side'] == 'HOME'].sort_values('game_order').reset_index(drop=True)
    ta = test_ts[test_ts['side'] == 'AWAY'].sort_values('game_order').reset_index(drop=True)
    mu_h_pre = th['mu_g1'].values * np.exp(kappa * ta['score_pre'].values)
    mu_a_pre = ta['mu_g1'].values * np.exp(kappa * th['score_pre'].values)
    mu_h_post = th['mu_g1'].values * np.exp(kappa * ta['score_post'].values)
    mu_a_post = ta['mu_g1'].values * np.exp(kappa * th['score_post'].values)
    p_pre = np.array([poisson_win_prob(h, a, p_home_so) for h, a in zip(mu_h_pre, mu_a_pre)])
    p_post = np.array([poisson_win_prob(h, a, p_home_so) for h, a in zip(mu_h_post, mu_a_post)])
    results['confirmation_movement'] = {
        'n_games': int(len(th)),
        'home_rate_mean_delta': float(np.mean(mu_h_post - mu_h_pre)),
        'away_rate_mean_delta': float(np.mean(mu_a_post - mu_a_pre)),
        'win_prob_mean_abs_delta': float(np.mean(np.abs(p_post - p_pre))),
        'win_prob_max_abs_delta': float(np.max(np.abs(p_post - p_pre))),
        'starter_prediction_accuracy': float(np.mean(th['obs_goalie'].values == th['exp_goalie'].values)),
    }
    print("confirmation movement:", results['confirmation_movement'])

    # κ sanity diagnostic
    q = test_ts['score_pre']
    results['kappa_diagnostic'] = {
        'kappa': float(kappa),
        'score_pre_quantiles': {str(p): float(np.quantile(q, p)) for p in (0.05, 0.25, 0.5, 0.75, 0.95)},
        'ga_swing_at_q05': float(np.exp(kappa * np.quantile(q, 0.05))),
        'ga_swing_at_q95': float(np.exp(kappa * np.quantile(q, 0.95))),
        # pre-reg-as-written check (kappa > 0) recorded alongside the corrected-convention
        # check: the pre-reg prose contradicts its own GSAx definition (xG - goals against,
        # positive = above-average goalie), under which goaltending requires kappa < 0.
        'sign_correct_pre_reg_as_written': bool(kappa > 0),
        'sign_correct_under_corrected_convention': bool(kappa < 0),
    }
    print("kappa diagnostic:", results['kappa_diagnostic'])

    with open(os.path.join(OUT, 'results.json'), 'w') as f:
        json.dump(results, f, indent=2, default=str)
    print("saved", os.path.join(OUT, 'results.json'))


if __name__ == '__main__':
    main()
