"""nfl_score_dist.py -- joint home and away score distribution (SPEC A task 4.2).

Pre-registration, written 2026-10-11 BEFORE any run. Changing any rule below after seeing a
result is a new experiment and must be labelled as one in docs/.

WHAT THIS IS
For a game with v1 walk-forward expected points (eh, ea), draw realistic final scores: integers,
real football shapes, ties at the real rate. Win, spread, total and team-total probabilities all
come from these draws. Used by the season simulation (4.1 step 3) and market probabilities (4.5).

METHOD: NEAREST NEIGHBOURS, NO SCORE RESHAPING
Training pool = every REG game of the earlier seasons with (eh, ea, actual home score, actual away
score), where (eh, ea) is v1 walk-forward expected points (fit on earlier weeks of that season
only, never on the game itself).

For a target game: standardize (expected margin, expected total) by the training pool's standard
deviations of those two quantities (pool means subtracted, pool sds divided), take the K nearest
training games by Euclidean distance in that standardized space, and draw one of their actual
(home, away) score pairs uniformly with replacement. Scores are never shifted, rescaled or
rounded; the drawn pair is an actual NFL final score.

TRAINING AND TEST SEASONS
- Training seasons: 2010-2019.
- Test seasons: 2020-2025. Each test season uses training data from all earlier seasons only
  (2010..season-1), so 2020 trains on 2010-2019 and 2025 trains on 2010-2024.
- Leakage rule: the target season is never in its own neighbour pool, and the target game is never
  in its own pool. A test season's own games are also never in a later test season's pool except
  as allowed by the line above.

K GRID AND SELECTION RULE
- Grid: K in {25, 50, 100, 200}.
- Selection: lowest out-of-sample score-pair log loss over 2011-2019, walk-forward (season s is
  scored with pool = 2010..s-1), ties broken to the smaller K. 2010 is training data only: it has
  no earlier season, so it cannot be scored.
- 2020-2025 is never used to choose K.

SCORE-PAIR LOG LOSS, EXACTLY
The sampler is a discrete distribution over score pairs: P(pair) = (n_pair + 1) / (K + V), where
n_pair is the number of the K neighbours whose actual pair equals the pair, and V is the number of
distinct pairs among those K neighbours (add-one smoothing over the neighbours' pairs, so a pair
absent from the K neighbours is unlikely, not impossible, and the probabilities sum to one). The
floor 1/(K+V) is present for every K, so the comparison is driven by how often the actual pair is
among the K neighbours. Log loss is natural log, averaged over the scored games.

Correction, 2026-10-11, made while writing the tests and BEFORE reading the gate: the first
version of this paragraph defined V as the number of distinct pairs in the whole pool. With that
definition the probabilities do not sum to one, because the smoothing mass is spread over every
pool pair rather than over the neighbour pairs the sampler can draw. V is the neighbours' distinct
pairs, which makes the distribution proper and leaves the floor 1/(K+V) in place. The gate never
uses the log loss, so the gate result is unaffected by this correction; the K table is recomputed
and reported from the corrected loss.

GATE (ship or stop, decided before running)
The candidate is the K chosen above, applied to 2020-2025.
- Win Brier (decisive games only, ties excluded from the Brier and counted): candidate must be no
  worse than the current Normal(projected margin, sigma = 13.295) model. No worse means the
  candidate's Brier is less than or equal to the Normal's.
- Cover and over calibration: candidate's sum of squared bin errors (10% bins) for
  P(home covers spread_line) and for P(over total_line) must be lower than the comparator's. The
  comparator is the bivariate independent Normal: margin ~ N(proj_margin, sd_margin), total ~
  N(proj_total, sd_total), with sd_margin and sd_total fitted on the same training pool by the
  residual sds of actual minus expected margin and total. Bins with fewer than 20 games are
  reported but excluded from the squared-error sum.
- If the gate fails, report it and STOP. Do not tune K on 2020-2025. K is not re-chosen after
  the gate result.
Also reported (no gate): tie frequency predicted vs actual overall and for 2017+ (overtime was
shortened to 10 minutes in 2017), and a probability integral transform histogram of the actual
margin in 10 bins.

API
- sample(eh, ea, rng, n) -> list of (home, away) integer pairs.
- probabilities(eh, ea, spread, total, n=20000, rng) -> dict with p_home_win, p_tie, p_cover,
  p_push, p_over, and the counts they came from. p_home_win is conditional on a decisive result
  (ties excluded from its denominator), matching the published win probability in SPEC A 4.2.
"""
from __future__ import annotations

import math

import numpy as np

K_GRID = (25, 50, 100, 200)
SIGMA_NORMAL = 13.295
TRAIN_SEASONS = tuple(range(2010, 2020))
TEST_SEASONS = tuple(range(2020, 2026))
TUNE_SEASONS = tuple(range(2011, 2020))
CALIBRATION_MIN_N = 20
HIST_DIR = "/root/nfl-v1-rehearsal.d0IcMW/nflverse_2010_2023"
HIST_CSV = HIST_DIR + "/backtest_2010_2023_games.csv"
HIST_PARQUET = HIST_DIR + "/games.parquet"
DEV_DB = "/root/legendarypicks/backend/data/picks.dev.db"


def load_history(con=None, hist_csv=HIST_CSV, parquet=HIST_PARQUET):
    """Every REG game 2010-2025 with walk-forward v1 expectations and its actual scores.

    2010-2023 come from the rehearsal CSV, model == 'v1' rows only, joined to the nflverse parquet
    for the actual scores. Its proj_margin and proj_total are walk-forward v1 expectations (the fit
    uses earlier weeks of that season only), so eh = (total + margin) / 2 and ea = (total -
    margin) / 2. Week 1 games are absent from both sources: no earlier week to fit on, so they have
    no expectation and cannot be in the pool.

    2024-2025 come from nfl_backtest.backtest_season on the dev DB with the frozen v1
    configuration, same columns, weeks 2 to 18.

    Returns (rows, notes). A row is a dict: season, week, game_id, eh, ea, hs, as_.
    """
    import pandas as pd

    import nfl_backtest as bt

    notes = {}
    csv = pd.read_csv(hist_csv)
    csv = csv[csv["model"] == "v1"][["season", "week", "game_id", "proj_margin", "proj_total"]]
    games = pd.read_parquet(parquet)[["game_id", "home_score", "away_score", "spread_line",
                                     "total_line"]]
    merged = csv.merge(games, on="game_id", how="left")
    notes["hist_rows"] = int(len(csv))
    notes["hist_no_score"] = int(merged["home_score"].isna().sum())
    merged = merged.dropna(subset=["home_score", "away_score"])
    rows = []
    for row in merged.itertuples(index=False):
        margin = float(row.proj_margin)
        total = float(row.proj_total)
        rows.append({"season": int(row.season), "week": int(row.week), "game_id": row.game_id,
                     "eh": (total + margin) / 2.0, "ea": (total - margin) / 2.0,
                     "hs": int(round(float(row.home_score))),
                     "as_": int(round(float(row.away_score))),
                     "spread": None if pd.isna(row.spread_line) else float(row.spread_line),
                     "total": None if pd.isna(row.total_line) else float(row.total_line)})
    notes["db_rows"] = {}
    if con is not None:
        for season in (2024, 2025):
            got = bt.backtest_season(con, season,
                                     {"half_life": 6.0, "cap": 14.0, "cap_points": None})
            for r in got:
                am, at = float(r["actual_margin"]), float(r["actual_total"])
                rows.append({"season": season, "week": int(r["week"]), "game_id": r["game_id"],
                             "eh": (float(r["proj_total"]) + float(r["proj_margin"])) / 2.0,
                             "ea": (float(r["proj_total"]) - float(r["proj_margin"])) / 2.0,
                             "hs": int(round((at + am) / 2.0)),
                             "as_": int(round((at - am) / 2.0)),
                             "spread": r["spread_line"], "total": r["total_line"]})
            notes["db_rows"][season] = len(got)
    rows.sort(key=lambda r: (r["season"], r["week"], r["game_id"]))
    return rows, notes


class ScoreDist:
    """Nearest neighbours over a fixed training pool of (expected margin, expected total) pairs."""

    def __init__(self, rows, k=K_GRID[0]):
        if not rows:
            raise ValueError("training pool is empty")
        if k not in K_GRID:
            raise ValueError("k %r is not in the pre-registered grid %r" % (k, K_GRID))
        self.k = int(k)
        self.rows = list(rows)
        self.eh = np.array([r["eh"] for r in self.rows], dtype=float)
        self.ea = np.array([r["ea"] for r in self.rows], dtype=float)
        self.hs = np.array([r["hs"] for r in self.rows], dtype=int)
        self.as_ = np.array([r["as_"] for r in self.rows], dtype=int)
        self.margin = self.eh - self.ea
        self.total = self.eh + self.ea
        self.m_mean = float(self.margin.mean())
        self.m_sd = float(self.margin.std(ddof=0))
        self.t_mean = float(self.total.mean())
        self.t_sd = float(self.total.std(ddof=0))
        if self.m_sd <= 0 or self.t_sd <= 0:
            raise ValueError("training pool has no spread in expected margin or total")
        self.zm = (self.margin - self.m_mean) / self.m_sd
        self.zt = (self.total - self.t_mean) / self.t_sd
        self.distinct_pairs = len(set(zip(self.hs.tolist(), self.as_.tolist())))
        self.actual_margin = self.hs - self.as_
        self.actual_total = self.hs + self.as_
        self.resid_margin_sd = float((self.actual_margin - self.margin).std(ddof=0))
        self.resid_total_sd = float((self.actual_total - self.total).std(ddof=0))

    def order(self, eh, ea):
        """Training rows nearest first for a target with expectations (eh, ea)."""
        zmt = ((eh - ea) - self.m_mean) / self.m_sd
        ztt = ((eh + ea) - self.t_mean) / self.t_sd
        d2 = (self.zm - zmt) ** 2 + (self.zt - ztt) ** 2
        return np.argsort(d2, kind="stable")

    def sample(self, eh, ea, rng, n):
        """n draws of (home, away) actual score pairs from the K nearest training games."""
        if n <= 0:
            raise ValueError("n must be > 0")
        idx = self.order(eh, ea)[: self.k]
        picks = rng.integers(0, len(idx), size=int(n))
        return [(int(self.hs[idx[i]]), int(self.as_[idx[i]])) for i in picks]

    def pair_probability(self, eh, ea):
        """The sampler's exact discrete distribution: {(home, away): p} over the K neighbours."""
        idx = self.order(eh, ea)[: self.k]
        counts = {}
        for i in idx:
            key = (int(self.hs[i]), int(self.as_[i]))
            counts[key] = counts.get(key, 0) + 1
        denom = float(self.k + len(counts))
        return {key: (c + 1.0) / denom for key, c in counts.items()}, denom

    def probabilities(self, eh, ea, spread=None, total=None, n=20000, rng=None):
        """Win, tie, cover, push and over probabilities from the draws.

        p_home_win and p_cover exclude ties and pushes from their denominator, as the published
        probabilities do; p_tie and p_push carry those rates. Counts are returned beside the rates.
        """
        if rng is None:
            raise ValueError("rng is required so a run can be reproduced")
        draws = self.sample(eh, ea, rng, n)
        home, away = zip(*draws)
        margins = [h - a for h, a in draws]
        totals = [h + a for h, a in draws]
        ties = sum(1 for m in margins if m == 0)
        decisive = n - ties
        out = {"n": int(n), "p_home_win": (sum(1 for m in margins if m > 0) / decisive)
               if decisive else None, "p_tie": ties / float(n), "ties": ties,
               "decisive": decisive}
        if spread is not None:
            covers = sum(1 for m in margins if m > spread)
            pushes = sum(1 for m in margins if m == spread)
            graded = n - pushes
            out["p_cover"] = covers / graded if graded else None
            out["p_push"] = pushes / float(n)
            out["pushes"] = pushes
        if total is not None:
            overs = sum(1 for t in totals if t > total)
            tpushes = sum(1 for t in totals if t == total)
            graded = n - tpushes
            out["p_over"] = overs / graded if graded else None
            out["p_total_push"] = tpushes / float(n)
        return out


def for_season(rows, season, k=K_GRID[0]):
    """A ScoreDist whose pool is every season strictly before `season` (never the target season)."""
    pool = [r for r in rows if r["season"] < season]
    if not pool:
        raise ValueError("no seasons before %d to train on" % season)
    return ScoreDist(pool, k=k)


def normal_probabilities(eh, ea, spread=None, total=None, sigma=SIGMA_NORMAL,
                         margin_sd=None, total_sd=None):
    """The comparator: win from Normal(margin, sigma), cover/over from the residual sds."""
    margin = eh - ea
    total_pts = eh + ea
    out = {"p_home_win": 0.5 * (1.0 + math.erf(margin / (sigma * math.sqrt(2.0))))}
    if spread is not None and margin_sd:
        out["p_cover"] = 1.0 - 0.5 * (1.0 + math.erf((spread - margin) / (margin_sd * math.sqrt(2.0))))
    if total is not None and total_sd:
        out["p_over"] = 1.0 - 0.5 * (1.0 + math.erf((total - total_pts) / (total_sd * math.sqrt(2.0))))
    return out
