"""nfl_sim_scores.py -- real final scores for simulated NFL games: outcome first, scores from history.

Pre-registration, written 2026-10-13 BEFORE any run of this method. Changing any rule below after
seeing a result is a new experiment and must be labelled as one in docs/.

WHY
nfl_sim's placeholder splits a Normal margin around a fixed total of 40: non-integer scores, every
game totals 40, no ties, and every points tiebreaker runs on fake points. nfl_score_dist (A2) draws
real score pairs from nearest neighbours but failed its win-Brier gate (0.2355 vs 0.2285), so its
win probability must not replace the calibrated Normal one. This method keeps the Normal's win
probability and uses history only for the score that goes with the outcome.

METHOD
For an unplayed game with v1 expected points (eh, ea), expected margin e = eh - ea (after any hot
adjustment, see below) and expected total T = eh + ea:
1. Outcome. p = Phi(e / sigma), sigma = 13.295, the probability nfl_sim already uses. t = the
   historical tie rate. Split, proportional and symmetric:
       P(tie) = t,   P(home win) = (1 - t) * p,   P(away win) = (1 - t) * (1 - p).
   So P(home win | decisive) = p exactly: the win probability is the Normal's by construction.
   One uniform u in [0, 1): u < t is a tie; u < t + (1 - t) * p is a home win; else an away win.
   Stated side effect: expected win credit (W + T/2) is (1 - t) p + t / 2, which differs from p by
   t * (1/2 - p), at most t / 2 (about 0.0016) per game, toward .500.
2. Tie rate t for target season s = REG games with home_score = away_score divided by scored REG
   games, from nfl_schedule seasons 2010 .. s-1 (never the target season). Every season in that
   range must have scored REG games or the build raises.
3. Score. Pool = every REG game of seasons 2010 .. s-1 with v1 walk-forward expectations
   (nfl_backtest.backtest_season with half_life 6, cap 14, cap_points None, the same configuration
   and the same rows as nfl_score_dist.load_history; week 1 has no expectation and is absent), and
   its actual (home, away) final score. Coordinates are standardized exactly as nfl_score_dist
   does (the whole pool's means and population sds of expected margin and total), using
   ScoreDist.order. Restrict to the pool games whose actual outcome equals the drawn outcome
   (home win, away win, tie), take the K_o = min(K, class size) nearest, ties in distance broken by
   pool order (stable sort), and draw one of their actual pairs uniformly. Scores are never shifted,
   rescaled or rounded. An empty outcome class raises.
4. K. Grid {25, 50, 100, 200}. Chosen by the lowest walk-forward conditional score-pair log loss
   over seasons 2011-2019 (season y scored with pool 2010 .. y-1), decisive games only, ties broken
   to the smaller K: P(pair | outcome) = (n_pair + 1) / (K_o + V), V = distinct pairs among the
   K_o neighbours, a pair absent from them gets 1 / (K_o + V). Tie games are excluded from the
   selection because the tie class is smaller than 25 in every pool (13 REG ties 2010-2025 in
   nfl_schedule, fewer with week 1 removed), so every K draws from the whole tie class. 2020-2025
   is never used to choose K, and K is not re-chosen after the gate.
5. Hot updates (nfl_sim k > 0): the adjusted margin e' = e + delta_home - delta_away sets p and the
   neighbour coordinate (e', T); the total T is not adjusted. The residual is the integer drawn
   margin minus e'. With k = 0 the neighbour lists are computed once per game; with k > 0 they are
   recomputed at e' for every game of every run (slower, exact).

GATES (all must pass for "history" to become nfl_sim's default; otherwise placeholder stays)
Test seasons 2020-2025. "Test games" = REG games of those seasons with walk-forward expectations
(weeks 2+), each season sampled with pool 2010 .. s-1 and tie rate 2010 .. s-1.
G1 Outcome calibration. 20000 draws per test game, numpy seed 20261013 + season.
   (a) 10 bins of p (width 0.1): in every bin with at least 20000 decisive draws, the simulated
   P(home | decisive) is within 4 binomial standard errors of the mean p of those draws; the
   pooled tie rate of the draws is within 4 standard errors of the mean t.
   (b) Win Brier over decisive actual test games of p_hat (home draws / decisive draws per game)
   is at most the Normal's Brier (p) + 0.0005.
G2 Validity. Over every draw of G1 and every simulated game of the G5 history runs: integer,
   non-negative; the (home, away) pair, its total and its margin each appear among the actual
   REG finals of nfl_schedule seasons 2010 .. s-1 (read directly from nfl_schedule, not from the
   pool); the tie rate of the G5 simulated games is between 0.1% and 0.4%.
G3 Totals. From the G1 draws, against the actual totals of the same test games: |mean simulated
   total - mean actual total| <= 1.0 point; simulated sd / actual sd in [0.90, 1.10]; P(total >
   total_line) calibration SSE (10% bins, bins under 20 games excluded; the A2 harness functions)
   no worse than the A2 bivariate Normal comparator's on the same games.
G4 Season level. G5 history runs, cutoff week 5, seed A. Per season: real = each team's points per
   game in that season's games after week 5; simulated = the same per simulated season. Averaged
   over the six seasons: |simulated league ppg - real league ppg| <= 1.0; simulated across-team sd
   of ppg (mean over runs) / real across-team sd in [0.80, 1.25]. The across-runs sd of a team's
   ppg is reported, no gate.
G5 Playoff odds. nfl_sim backtest mode, seasons 2020-2025, cutoffs after week 5 and week 12,
   n = 2000, k = 0, both options, seed A = 1000 + week (as nfl_sim_backtest), seed B = 50000 +
   week. Truth from the published schedule: playoff teams = teams in WC/DIV/CON/SB games (14);
   division winners = WC home teams plus each conference's bye team (in DIV, not in WC) (8).
   Brier of p_playoffs and of p_division pooled over 12 (season, cutoff) x 32 teams. Noise N =
   max(|A - B| for history, |A - B| for placeholder). Pass: history(A) - placeholder(A) <=
   max(2 N, 0.001), for both Brier measures. Log loss (p clipped to [1/(2n), 1 - 1/(2n)]) and the
   largest per-team |change in p_playoffs| between options are reported.
G6 Ties. Over every G5 history simulated season (both seeds): no exception, and the seeding
   passes invariants in every season: each division winner has the best pct in its division,
   seeds 1-4 are the division winners in non-increasing pct, seeds 5+ are in non-increasing pct
   and each is at least the pct of every unseeded club of the conference. Reported: seasons with a
   simulated tie, and of those how many change a seed or the playoff field when each simulated tie
   (x, x) is replaced by (x + 1, x) or by (x, x + 1) (both seedings with rng=None, alphabetical
   coin, so only the tie differs).
"""
from __future__ import annotations

import math

import numpy as np

import nfl_score_dist as nsd

FIRST_SEASON = 2010
K_GRID = nsd.K_GRID
TUNE_SEASONS = tuple(range(2011, 2020))
BACKTEST_CONFIG = {"half_life": 6.0, "cap": 14.0, "cap_points": None}
OUTCOMES = ("H", "A", "T")


def phi(x):
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def tie_rate(con, season):
    """(rate, ties, games) over scored REG games of seasons FIRST_SEASON .. season-1."""
    rows = con.execute(
        "SELECT season, COUNT(*), SUM(home_score = away_score) FROM nfl_schedule "
        "WHERE game_type = 'REG' AND season >= ? AND season < ? AND home_score IS NOT NULL "
        "AND away_score IS NOT NULL GROUP BY season", (FIRST_SEASON, season)).fetchall()
    have = {r[0] for r in rows if r[1]}
    missing = [s for s in range(FIRST_SEASON, season) if s not in have]
    if missing or not rows:
        raise ValueError("nfl_schedule has no scored REG games for seasons %s" % (missing or season))
    games = sum(r[1] for r in rows)
    ties = sum(r[2] for r in rows)
    return ties / float(games), ties, games


def pool_rows(con, seasons):
    """v1 walk-forward rows for the given seasons, the row shape of nfl_score_dist.load_history."""
    import nfl_backtest as bt
    out = []
    for season in seasons:
        got = bt.backtest_season(con, season, dict(BACKTEST_CONFIG))
        if not got:
            raise ValueError("no walk-forward rows for season %d" % season)
        for r in got:
            am, at = float(r["actual_margin"]), float(r["actual_total"])
            out.append({"season": season, "week": int(r["week"]), "game_id": r["game_id"],
                        "eh": (float(r["proj_total"]) + float(r["proj_margin"])) / 2.0,
                        "ea": (float(r["proj_total"]) - float(r["proj_margin"])) / 2.0,
                        "hs": int(round((at + am) / 2.0)), "as_": int(round((at - am) / 2.0)),
                        "spread": r["spread_line"], "total": r["total_line"]})
    out.sort(key=lambda r: (r["season"], r["week"], r["game_id"]))
    return out


def outcome_of(hs, as_):
    return "H" if hs > as_ else ("A" if hs < as_ else "T")


class HistorySampler:
    """Outcome from the calibrated probability, score from same-outcome nearest historical games."""

    def __init__(self, rows, k, tie_rate_value, sigma=nsd.SIGMA_NORMAL):
        if not 0.0 <= tie_rate_value < 1.0:
            raise ValueError("tie rate %r out of range" % tie_rate_value)
        self.dist = nsd.ScoreDist(rows, k=k)          # standardization, distance, K grid check
        self.k = self.dist.k
        self.t = float(tie_rate_value)
        self.sigma = float(sigma)
        am = self.dist.actual_margin
        self.masks = {"H": am > 0, "A": am < 0, "T": am == 0}
        for o, m in self.masks.items():
            if not m.any():
                raise ValueError("outcome class %s is empty in the pool" % o)

    def p_home(self, margin):
        return phi(margin / self.sigma)

    def outcome(self, p, u):
        if u < self.t:
            return "T"
        return "H" if u < self.t + (1.0 - self.t) * p else "A"

    def neighbours(self, margin, total, outcome):
        """Pool indices of the K_o nearest games with this outcome, nearest first."""
        order = self.dist.order((total + margin) / 2.0, (total - margin) / 2.0)
        return order[self.masks[outcome][order]][: self.k]

    def pairs(self, margin, total, outcome):
        idx = self.neighbours(margin, total, outcome)
        return [(int(self.dist.hs[i]), int(self.dist.as_[i])) for i in idx]

    def game_table(self, margin, total):
        """(p, {outcome: [pairs]}) for one game, computed once for cold runs."""
        return self.p_home(margin), {o: self.pairs(margin, total, o) for o in OUTCOMES}

    def draw(self, rng, p, table):
        """One (home, away) score. rng is a random.Random: one uniform, then one index."""
        pairs = table[self.outcome(p, rng.random())]
        return pairs[rng.randrange(len(pairs))]

    def cond_pair_probability(self, margin, total, outcome):
        """Pre-registered conditional score-pair distribution, add-one smoothed over neighbours."""
        counts = {}
        for pair in self.pairs(margin, total, outcome):
            counts[pair] = counts.get(pair, 0) + 1
        k_o = sum(counts.values())
        denom = float(k_o + len(counts))
        return {pair: (c + 1.0) / denom for pair, c in counts.items()}, denom


def select_k(rows, k_grid=K_GRID, seasons=TUNE_SEASONS):
    """Walk-forward conditional score-pair log loss per K over decisive games. Returns
    (chosen_k, {k: (mean log loss, games)})."""
    table = {}
    for k in k_grid:
        total, n = 0.0, 0
        for season in seasons:
            pool = [r for r in rows if r["season"] < season]
            s = _decisive_only(pool, k)
            for r in rows:
                if r["season"] != season or r["hs"] == r["as_"]:
                    continue
                probs, denom = s.cond_pair_probability(r["eh"] - r["ea"], r["eh"] + r["ea"],
                                                       outcome_of(r["hs"], r["as_"]))
                total += -math.log(probs.get((r["hs"], r["as_"]), 1.0 / denom))
                n += 1
        table[k] = (total / n, n)
    chosen = min(k_grid, key=lambda k: (table[k][0], k))
    return chosen, table


def _decisive_only(pool, k):
    """A sampler for K selection, which queries only the decisive classes; built without the
    empty-tie-class check because early pools (2011 trains on 2010) have no tie."""
    s = HistorySampler.__new__(HistorySampler)
    s.dist = nsd.ScoreDist(pool, k=k)
    s.k = s.dist.k
    s.t = 0.0
    s.sigma = nsd.SIGMA_NORMAL
    am = s.dist.actual_margin
    s.masks = {"H": am > 0, "A": am < 0, "T": am == 0}
    return s


def build(con, season, k, rows=None):
    """The sampler for a target season: pool and tie rate from seasons before it only.
    rows: optional precomputed pool_rows covering at least FIRST_SEASON .. season-1."""
    if rows is None:
        rows = pool_rows(con, range(FIRST_SEASON, season))
    pool = [r for r in rows if FIRST_SEASON <= r["season"] < season]
    have = {r["season"] for r in pool}
    missing = [s for s in range(FIRST_SEASON, season) if s not in have]
    if missing:
        raise ValueError("pool is missing seasons %s" % missing)
    rate, ties, games = tie_rate(con, season)
    s = HistorySampler(pool, k, rate)
    s.info = {"k": k, "tie_rate": rate, "ties": ties, "tie_games": games,
              "pool_games": len(pool), "pool_seasons": [FIRST_SEASON, season - 1],
              "pool_ties": int(s.masks["T"].sum())}
    return s
