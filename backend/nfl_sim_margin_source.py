"""nfl_sim_margin_source.py -- G4 follow-up: is the narrow team spread the margins' fault or the sampler's?

Pre-registration, written 2026-10-13 BEFORE any run of this experiment. Changing any rule below after
seeing a result is a new experiment and must be labelled as one in docs/.

BACKGROUND
The history score option (nfl_sim_scores) failed G4 (docs/RESULTS-nfl-sim-scores-2026-10-13.md):
across-team sd of simulated points per game after week 5 was 3.62 against 4.57 real, ratio 0.791 against
a floor of 0.80 (placeholder 0.653). Every other gate passed.

HYPOTHESIS H
The shortfall comes from the expected margins, because the v1 ratings regress toward the mean, and not
from the score sampler. H has two parts:
  H-A  a margin source whose expected points are spread wider across teams raises the G4 ratio;
  H-B  the sampler passes each team's expected points through without shrinking them.

MARGIN SOURCE "elo" (the lever)
538's NFL Elo as rebuilt in nfl_elo_replica (K 20, home 65, margin multiplier, tie multiplier 1.525,
2/3 carryover toward 1505, start from the nfl_elo_538 2010 ratings, all scored games, playoffs included).
  - Elo probability p_elo = 1 / (1 + 10^(-gap / 400)), gap = home - away rating + 65 unless neutral
    (nfl_elo_replica.prob; lock_nfl_elo.elo_gap applies the carryover for a team that has not yet
    played in the season).
  - Elo margin = 13.295 x PhiInverse(p_elo). With this conversion the outcome sampler's
    Phi(margin / 13.295) is exactly the Elo probability, so the sampler is unchanged and is fed the way
    the v1 margins are fed now.
  - The expected total stays v1's walk-forward expected total. eh = (total + margin) / 2,
    ea = (total - margin) / 2.
  - For pool games and test games (G1, G2, G3) the Elo margin uses the pre-game ratings of that game
    (walk-forward: only earlier games). For the season backtest (G4, G5, G6) at cutoff w of season s,
    ratings come from every scored game of earlier seasons plus season s REG weeks <= w. They are
    frozen for the remaining games, and the remaining games keep v1's expected totals.
  - Sampler: nfl_sim_scores unchanged, K = 25, tie rate as before. The pool is the same games with Elo
    coordinates (Elo margin, v1 total) in place of v1's, so queries and pool use one coordinate system.
Secondary source, measured in M1 only (no simulation): the v1 + Elo stack of lock_nfl_elo (fit_stack
for 2010..s-1, then b0 + b1 x v1 margin + b2 x Elo gap).

MEASUREMENTS (seasons 2020-2025, cutoff after week 5 unless stated)
M1 Input spread, no simulation. For each team, its expected points per game over its remaining games
   (weeks > 5) under a source. Then the across-team sd per season, averaged over the six seasons: S_v1,
   S_elo, S_stack. Compared with S_real, the across-team sd of actual points per game in the same
   games (4.57 in the G4 run).
M2 The same gate harness (backtest_nfl_sim_scores) with source "v1" and with source "elo", same seeds,
   n = 2000. G1 to G6 are judged under the thresholds pre-registered in nfl_sim_scores, unchanged. Two
   additions: (i) G4 is also computed for seed B, and the G4 noise N4 = max over sources of |ratio(A) -
   ratio(B)|; (ii) for the elo run, G1(b) is also scored against the v1 Normal Brier on the same games.
   That comparison is the win-calibration trade-off and is reported, not gated. G5 for the elo run
   compares elo-history with v1-placeholder, the current default.
M3 Sampler pass-through. In the seed-A week-5 runs, pooled over seasons, the OLS slope of each team's
   mean simulated ppg (mean over runs) on its expected ppg (M1, same source).
   Reported, no gate: the predicted simulated spread sqrt(S_x^2 + A_x^2) / S_real, where A_x is the mean
   across-runs sd of a team's ppg, against the observed G4 ratio.

DECISION RULE (fixed now)
- SUPPORTED if all hold: S_elo > 1.05 x S_v1; R_elo - R_v1 > 2 x N4 (R = G4 ratio, seed A); M3 slope
  in [0.9, 1.1] for both sources.
- REFUTED if S_elo > 1.05 x S_v1 and R_elo - R_v1 <= 2 x N4 (a wider input does not widen the output:
  H-A false), or if the M3 slope for v1 is below 0.9 (the sampler shrinks: H-B false).
- UNCLEAR otherwise, for example when S_elo <= 1.05 x S_v1, so the lever is too weak to test H-A.
Whatever the outcome, nothing becomes a default, and no threshold, K or constant changes.
"""
from __future__ import annotations

import math
import statistics

import nfl_elo_replica as er
import nfl_sim as ns
import nfl_sim_scores as nss
import lock_nfl_elo as le

SIGMA = 13.295


def phi_inv(p):
    return statistics.NormalDist().inv_cdf(p)


def margin_from_gap(gap):
    return SIGMA * phi_inv(1.0 / (1.0 + 10.0 ** (-gap / 400.0)))


def _week_of(con):
    return {g: (int(s), t, int(w)) for g, s, t, w in con.execute(
        "SELECT game_id, season, game_type, week FROM nfl_schedule")}


def elo_pool_rows(con, rows):
    """The v1 pool rows with Elo coordinates: Elo margin from pre-game ratings, v1 total kept."""
    games = er.load_games(con)
    pre = er.run_elo(games, er.start_ratings(con))
    neutral = {g[0]: g[2] for g in games}
    out = []
    for r in rows:
        eh, ea = pre[r["game_id"]]
        m = margin_from_gap(eh - ea + (0.0 if neutral[r["game_id"]] else er.BASE["hfa"]))
        tot = r["eh"] + r["ea"]
        out.append(dict(r, eh=(tot + m) / 2.0, ea=(tot - m) / 2.0))
    return out


def elo_state_through(con, season, week):
    """Elo ratings after every scored game of earlier seasons and season REG weeks <= week."""
    wk = _week_of(con)
    games = [g for g in er.load_games(con)
             if wk[g[0]][0] < season or (wk[g[0]][0] == season and wk[g[0]][1] == "REG"
                                          and wk[g[0]][2] <= week)]
    _, rating, season_of = er.run_elo(games, er.start_ratings(con), return_state=True)
    return rating, season_of


def elo_inputs(con, inp, pool_elo):
    """A copy of nfl_sim inputs (backtest mode) whose remaining margins are Elo margins, totals v1,
    with a history sampler on the Elo-coordinate pool."""
    season, week = inp["season"], inp["through_week"]
    rating, season_of = elo_state_through(con, season, week)
    remaining = []
    for wk_, h, a, neutral, em in inp["remaining"]:
        gap = le.elo_gap(rating, season_of, season, h, a, neutral)
        remaining.append((wk_, h, a, neutral, margin_from_gap(gap)))
    out = dict(inp)
    out["remaining"] = remaining
    s = nss.build(con, season, ns.HISTORY_K, rows=pool_elo)
    out = ns.attach_history(out, s)
    return out


def stack_margins(con, inp):
    """Secondary source for M1: lock_nfl_elo's stack margin for each remaining game."""
    season, week = inp["season"], inp["through_week"]
    beta, _, _ = le.fit_stack(con, season)
    rating, season_of = elo_state_through(con, season, week)
    return [float(beta[0] + beta[1] * em + beta[2] * le.elo_gap(rating, season_of, season, h, a, n))
            for _, h, a, n, em in inp["remaining"]]


def expected_ppg(remaining, totals, margins=None):
    """team -> mean expected points per game over its remaining games."""
    pts, gp = {}, {}
    for i, (wk, h, a, neutral, em) in enumerate(remaining):
        m = em if margins is None else margins[i]
        for team, p in ((h, (totals[i] + m) / 2.0), (a, (totals[i] - m) / 2.0)):
            pts[team] = pts.get(team, 0.0) + p
            gp[team] = gp.get(team, 0) + 1
    return {t: pts[t] / gp[t] for t in pts}


def ols_slope(xs, ys):
    mx, my = statistics.fmean(xs), statistics.fmean(ys)
    sxx = sum((x - mx) ** 2 for x in xs)
    return sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / sxx if sxx else math.nan
