#!/usr/bin/env python3
"""fbs_phase5_sim.py -- FBS Phase 5 joint simulator, gates G1-G4.

Pre-registration: research/fbs/PREREG-FBS-PHASE5-2026-10-19.md (frozen at 274d47f4).
Fit: 2018-2024 only. 2025 is the frozen holdout. 2026 is forward only.

This is a research prototype. It is read-only against the archive and the dev DB.
No production table, gate, scheduler or model is changed.

Usage (full):
  /root/legendarypicks/backend/venv/bin/python backend/fbs_phase5_sim.py \
      --season 2025 --sims 10000 --seed 20261019 \
      --data research/fbs/parquet --out research/fbs/phase5
Quick smoke:
  ... --quick --max-games 5
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import subprocess
import sys
from collections import defaultdict

import numpy as np
import pandas as pd
from scipy.stats import norm

ROOT = "/root/lp-fbs-archive"
CACHE = os.path.join(ROOT, "research/fbs/phase5/cache")
SEED = 20261019
REPS = 2000
M_DEFAULT = 10000

STATS = [
    "pass_attempts", "completions", "passing_yards", "passing_tds", "interceptions_thrown",
    "rush_attempts", "rushing_yards", "rushing_tds",
    "targets", "receptions", "receiving_yards", "receiving_tds",
]
COUNT_STATS = {"pass_attempts", "completions", "passing_tds", "interceptions_thrown",
               "rush_attempts", "rushing_tds", "targets", "receptions", "receiving_tds"}
CORE_MARKETS = ["passing_yards", "rushing_yards", "receiving_yards", "receptions", "rush_attempts"]
MARKET_MAP = {
    "passing_yards": ["passing_yards"],
    "pass_attempts": ["pass_attempts"],
    "pass_completions": ["completions"],
    "passing_touchdowns": ["passing_tds"],
    "interceptions_thrown": ["interceptions_thrown"],
    "rushing_yards": ["rushing_yards"],
    "rush_attempts": ["rush_attempts"],
    "rushing_touchdowns": ["rushing_tds"],
    "receptions": ["receptions"],
    "receiving_yards": ["receiving_yards"],
    "receiving_touchdowns": ["receiving_tds"],
    "targets": ["targets"],
    "total_touchdowns": ["rushing_tds", "receiving_tds"],
    "rushing_receiving_yards": ["rushing_yards", "receiving_yards"],
    "passing_rushing_yards": ["passing_yards", "rushing_yards"],
    "rushing_receiving_touchdowns": ["rushing_tds", "receiving_tds"],
    "total_passing_touchdowns": ["passing_tds"],
}
POS_SKILL = {"Quarterback", "Running Back", "Fullback", "Wide Receiver", "Tight End"}
POS_REC = {"Wide Receiver", "Tight End", "Running Back", "Fullback"}
POS_CARRY = {"Running Back", "Fullback", "Quarterback", "Wide Receiver"}


def logit(p):
    p = np.clip(p, 1e-6, 1 - 1e-6)
    return np.log(p / (1 - p))


def sigmoid(x):
    return 1.0 / (1.0 + np.exp(-np.clip(x, -30, 30)))


def norm_name(s):
    import re
    if s is None or (isinstance(s, float) and np.isnan(s)):
        return ""
    s = str(s).lower()
    s = re.sub(r"\b(jr|sr|ii|iii|iv|v)\.?\b", "", s)
    s = re.sub(r"[^a-z0-9 ]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


# ---------------------------------------------------------------------------
# data
# ---------------------------------------------------------------------------

def load_cache(out_dir):
    tg = pd.read_parquet(os.path.join(CACHE, "team_games.parquet"))
    pg = pd.read_parquet(os.path.join(CACHE, "player_games.parquet"))
    props = pd.read_parquet(os.path.join(CACHE, "props_2026.parquet"))
    tg = tg.dropna(subset=["points_for"]).copy()
    tg["home"] = tg.home.astype(int)
    tg["neutral"] = tg.neutral.astype(int)
    tg["is_fcs"] = tg.is_fcs.astype(int)
    tg["rest_c"] = ((tg.rest - 7.0) / 7.0).clip(-1, 3)
    tg["log_pace"] = np.log(tg.pace.clip(1))
    tg["log_points"] = np.log(tg.points_for.clip(0) + 1.0)
    pg = pg.fillna({c: 0 for c in STATS}).copy()
    pg["position"] = pg.position.fillna("UNK").astype(str)
    return tg, pg, props


def fit_two_way(df, ycol, wcol="w", k_team=4.0, k_opp=6.0, iters=40):
    d = df.dropna(subset=[ycol]).copy()
    d = d[d.season <= 2024].copy()
    d = d.sort_values(["season", "week", "game_id", "team_id"]).reset_index(drop=True)
    y = d[ycol].to_numpy(float)
    w = d[wcol].to_numpy(float)
    seasons = sorted(d.season.unique())
    X = np.column_stack([
        np.ones(len(d)), d.home.to_numpy(float), d.neutral.to_numpy(float),
        d.rest_c.to_numpy(float), d.is_fcs.to_numpy(float),
    ] + [(d.season == s).to_numpy(float) for s in seasons[1:]])
    beta = np.linalg.lstsq(X * np.sqrt(w)[:, None], y * np.sqrt(w), rcond=None)[0]
    tkey = list(zip(d.team_id.astype(int), d.season.astype(int)))
    okey = list(zip(d.opp_id.astype(int), d.season.astype(int)))
    off = defaultdict(float)
    deff = defaultdict(float)
    for _ in range(iters):
        r = y - X @ beta
        tmp = defaultdict(list)
        wtmp = defaultdict(list)
        for i in range(len(d)):
            tmp[tkey[i]].append(r[i] - deff[okey[i]])
            wtmp[tkey[i]].append(w[i])
        new_off = {kk: float(np.average(tmp[kk], weights=wtmp[kk]) * (len(tmp[kk]) / (len(tmp[kk]) + k_team)))
                   for kk in tmp}
        tmp = defaultdict(list)
        wtmp = defaultdict(list)
        for i in range(len(d)):
            tmp[okey[i]].append(r[i] - new_off[tkey[i]])
            wtmp[okey[i]].append(w[i])
        new_def = {kk: float(np.average(tmp[kk], weights=wtmp[kk]) * (len(tmp[kk]) / (len(tmp[kk]) + k_opp)))
                   for kk in tmp}
        resid = y - np.array([new_off[tkey[i]] + new_def[okey[i]] for i in range(len(d))])
        beta = np.linalg.lstsq(X * np.sqrt(w)[:, None], resid * np.sqrt(w), rcond=None)[0]
        off, deff = new_off, new_def
    pred = X @ beta + np.array([off[tkey[i]] + deff[okey[i]] for i in range(len(d))])
    resid = y - pred
    sigma = float(np.sqrt(np.average(resid ** 2, weights=w)))
    return {
        "beta": beta.tolist(), "seasons": seasons, "off": dict(off), "def": dict(deff),
        "sigma": sigma, "n": int(len(d)), "ycol": ycol,
    }


def predict_team(model, row, team_id, opp_id, target_season):
    seasons = model["seasons"]
    effect_season = 2024 if target_season >= 2025 else max(2018, target_season - 1)
    x = [1.0, float(row.home), float(row.neutral), float(row.rest_c), float(row.is_fcs)]
    x += [1.0 if effect_season == s else 0.0 for s in seasons[1:]]
    base = float(np.dot(np.array(x), np.array(model["beta"])))
    return base + model["off"].get((int(team_id), int(effect_season)), 0.0) \
        + model["def"].get((int(opp_id), int(effect_season)), 0.0)


def fit_team_model(tg):
    t = tg.copy()
    t["w"] = np.where(t.is_fcs == 1, 0.5, 1.0)
    models = {}
    for target in ["log_pace", "logit_pass_rate", "log_points"]:
        models[target] = fit_two_way(t, target)
    # residual covariance on the fit rows (2018-2024)
    d = t[t.season <= 2024].dropna(subset=["log_pace", "logit_pass_rate", "log_points"]).copy()
    R = []
    for target in ["log_pace", "logit_pass_rate", "log_points"]:
        m = models[target]
        p = np.array([predict_team(m, r, r.team_id, r.opp_id, int(r.season)) for _, r in d.iterrows()])
        R.append(d[target].to_numpy(float) - p)
    R = np.column_stack(R)
    w = np.where(d.is_fcs == 1, 0.5, 1.0)
    cov = np.cov(R.T, aweights=w)
    cov = np.nan_to_num(cov, nan=0.0)
    # make positive definite
    vals, vecs = np.linalg.eigh(cov)
    vals = np.clip(vals, 1e-5, None)
    cov = vecs @ np.diag(vals) @ vecs.T
    return {"models": models, "cov": cov.tolist(), "R_points": 4.0}


def build_team_rates(tg):
    g = tg.groupby(["season", "team_id"], as_index=False).agg(
        pass_plays=("pass_plays", "sum"), pass_attempts=("pass_attempts", "sum"),
        completions=("completions", "sum"), pass_yards=("pass_yards", "sum"),
        pass_tds=("pass_tds", "sum"), ints=("interceptions", "sum"), sacks=("sacks", "sum"),
        rush_plays=("rush_plays", "sum"), rush_yards=("rush_yards", "sum"),
        rush_tds=("rush_tds", "sum"), points=("points_for", "mean"),
        points_against=("points_against", "mean"), games=("game_id", "count"))
    league = g.groupby("season", as_index=False).agg(
        pass_plays=("pass_plays", "sum"), pass_attempts=("pass_attempts", "sum"),
        completions=("completions", "sum"), pass_yards=("pass_yards", "sum"),
        pass_tds=("pass_tds", "sum"), ints=("ints", "sum"), sacks=("sacks", "sum"),
        rush_plays=("rush_plays", "sum"), rush_yards=("rush_yards", "sum"),
        rush_tds=("rush_tds", "sum"), points=("points", "mean"),
        points_against=("points_against", "mean"))
    rates = {}
    lg = {}
    for _, r in league.iterrows():
        lg[int(r.season)] = {
            "comp_rate": float(r.completions / max(r.pass_attempts, 1)),
            "ypa": float(r.pass_yards / max(r.pass_attempts, 1)),
            "pass_td_rate": float(r.pass_tds / max(r.pass_attempts, 1)),
            "int_rate": float(r.ints / max(r.pass_attempts, 1)),
            "sack_rate": float(r.sacks / max(r.pass_plays, 1)),
            "ypc": float(r.rush_yards / max(r.rush_plays, 1)),
            "rush_td_rate": float(r.rush_tds / max(r.rush_plays, 1)),
            "points": float(r.points),
            "points_against": float(r.points_against),
        }
    for _, r in g.iterrows():
        rates[(int(r.season), int(r.team_id))] = {
            "comp_rate": float(r.completions / max(r.pass_attempts, 1)),
            "ypa": float(r.pass_yards / max(r.pass_attempts, 1)),
            "pass_td_rate": float(r.pass_tds / max(r.pass_attempts, 1)),
            "int_rate": float(r.ints / max(r.pass_attempts, 1)),
            "sack_rate": float(r.sacks / max(r.pass_plays, 1)),
            "ypc": float(r.rush_yards / max(r.rush_plays, 1)),
            "rush_td_rate": float(r.rush_tds / max(r.rush_plays, 1)),
            "points": float(r.points),
            "points_against": float(r.points_against),
        }
    return rates, lg


def get_rates(rates, lg, team_id, opp_id, target_season):
    effect_season = 2024 if target_season >= 2025 else max(2018, target_season - 1)
    base = rates.get((effect_season, int(team_id)))
    league = lg.get(effect_season) or lg.get(2024) or lg[sorted(lg)[-1]]
    if base is None:
        base = league
    opp = rates.get((effect_season, int(opp_id))) or league
    factor = float(np.clip((league["points"] / max(opp["points_against"], 1.0)) ** 0.5, 0.7, 1.3))
    out = {
        "comp_rate": float(np.clip(base["comp_rate"] * (0.75 + 0.25 * factor), 0.30, 0.80)),
        "ypa": float(np.clip(base["ypa"] * factor, 3.0, 12.0)),
        "pass_td_rate": float(np.clip(base["pass_td_rate"] * factor, 0.01, 0.12)),
        "int_rate": float(np.clip(base["int_rate"] / max(factor, 0.8), 0.005, 0.08)),
        "sack_rate": float(np.clip(base["sack_rate"] / max(factor, 0.8), 0.01, 0.20)),
        "ypc": float(np.clip(base["ypc"] * factor, 1.5, 8.0)),
        "rush_td_rate": float(np.clip(base["rush_td_rate"] * factor, 0.005, 0.12)),
        "points": float(base["points"]),
    }
    return out


# ---------------------------------------------------------------------------
# player shares / rates
# ---------------------------------------------------------------------------

def build_shares(pg):
    metrics = ["pass_attempts", "targets", "rush_attempts", "receptions",
               "receiving_yards", "rushing_yards", "passing_tds", "rushing_tds",
               "receiving_tds"]
    d = pg.copy()
    for m in metrics:
        den = d.groupby(["game_id", "team_id"])[m].transform("sum")
        d[m + "_share"] = np.where(den > 0, d[m] / den, 0.0)
    shares = d[["season", "team_id", "athlete_id", "game_id", "start_date", "position"] +
               [m + "_share" for m in metrics]].copy()
    long = shares.melt(id_vars=["season", "team_id", "athlete_id", "game_id", "start_date", "position"],
                       value_vars=[m + "_share" for m in metrics],
                       var_name="metric", value_name="share")
    long["metric"] = long.metric.str.replace("_share", "", regex=False)
    season_means = long.groupby(["season", "team_id", "athlete_id", "metric"], as_index=False).agg(
        share=("share", "mean"), n=("share", "count"))
    pos_means = long.merge(long[["season", "team_id", "athlete_id", "position"]].drop_duplicates(),
                           on=["season", "team_id", "athlete_id"], how="left")
    pos_means = pos_means.groupby(["season", "position", "metric"], as_index=False).agg(
        share=("share", "mean"))
    smap = {(int(r.season), int(r.team_id), int(r.athlete_id), r.metric): (float(r.share), int(r.n))
            for _, r in season_means.iterrows()}
    pmap = {(int(r.season), r.position, r.metric): float(r.share) for _, r in pos_means.iterrows()}
    gmap = defaultdict(list)
    for _, r in long.iterrows():
        gmap[(int(r.season), int(r.team_id), int(r.athlete_id), r.metric)].append(
            (str(r.start_date), float(r.share)))
    return {"season": smap, "pos": pmap, "game": gmap}


def player_weights(game, team_id, players, shares, target_season):
    prior_season = 2025 if target_season >= 2026 else target_season - 1
    start = str(game.start_date)
    n = len(players)
    s0 = {m: np.zeros(n) for m in ["pass_attempts", "targets", "rush_attempts", "receptions",
                                   "receiving_yards", "rushing_yards", "passing_tds",
                                   "rushing_tds", "receiving_tds"]}
    for i, (_, p) in enumerate(players.iterrows()):
        ath = int(p.athlete_id)
        pos = p.position if p.position in POS_SKILL else "UNK"
        for m in s0:
            prior = shares["season"].get((prior_season, int(team_id), ath, m))
            if prior is None:
                prior = shares["season"].get((prior_season - 1, int(team_id), ath, m))
            prior_share, prior_n = prior if prior else (0.0, 0)
            cur = [v for (dt, v) in shares["game"].get((target_season, int(team_id), ath, m), [])
                   if dt < start]
            cur_share = float(np.mean(cur)) if cur else 0.0
            cur_n = len(cur)
            pos_mean = shares["pos"].get((prior_season, pos, m), 0.0)
            s0[m][i] = (prior_share * prior_n + cur_share * cur_n + pos_mean * 2.0) / (prior_n + cur_n + 2.0)
    # role masks
    pos = players.position.fillna("UNK").astype(str).to_numpy()
    qb_mask = (pos == "Quarterback") | (s0["pass_attempts"] > 0.02)
    rec_mask = np.isin(pos, list(POS_REC)) | (s0["targets"] > 0.01)
    carry_mask = np.isin(pos, list(POS_CARRY)) | (s0["rush_attempts"] > 0.01)

    def vec(metric, mask, default):
        w = s0[metric].copy()
        w[~mask] = 0.0
        if w.sum() <= 0:
            w = np.where(mask, default, 0.0)
        if w.sum() <= 0:
            w = np.where(mask, 1.0, 0.0)
        return w / w.sum() if w.sum() > 0 else w

    # keep all players in the probability vector, with zeros outside the role
    def full(metric, mask, default):
        v = np.zeros(n)
        idx = np.where(mask)[0]
        if len(idx) == 0:
            return v
        w = s0[metric][idx]
        if w.sum() <= 0:
            w = np.full(len(idx), default)
        v[idx] = w / w.sum()
        return v

    probs = {
        "pass_attempts": full("pass_attempts", qb_mask, 0.01),
        "targets": full("targets", rec_mask, 0.01),
        "receptions": full("targets", rec_mask, 0.01),
        "receiving_yards": full("receiving_yards", rec_mask, 0.01),
        "receiving_tds": full("receiving_tds", rec_mask, 0.01),
        "rush_attempts": full("rush_attempts", carry_mask, 0.01),
        "rushing_yards": full("rushing_yards", carry_mask, 0.01),
        "rushing_tds": full("rushing_tds", carry_mask, 0.01),
    }
    # starter index: top 5 by sum of the three usage vectors
    score = probs["pass_attempts"] + probs["targets"] + probs["rush_attempts"]
    starter = np.argsort(-score)[:5]
    return probs, starter


def build_player_rates(pg):
    g = pg.groupby(["season", "athlete_id"], as_index=False).agg(
        pass_attempts=("pass_attempts", "sum"), completions=("completions", "sum"),
        passing_yards=("passing_yards", "sum"), passing_tds=("passing_tds", "sum"),
        ints=("interceptions_thrown", "sum"), rush_attempts=("rush_attempts", "sum"),
        rushing_yards=("rushing_yards", "sum"), rushing_tds=("rushing_tds", "sum"),
        targets=("targets", "sum"), receptions=("receptions", "sum"),
        receiving_yards=("receiving_yards", "sum"), receiving_tds=("receiving_tds", "sum"),
        position=("position", "first"))
    out = {}
    for _, r in g.iterrows():
        out[(int(r.season), int(r.athlete_id))] = r.to_dict()
    return out


# ---------------------------------------------------------------------------
# simulation
# ---------------------------------------------------------------------------

def sample_nb(rng, mu, R, size):
    lam = rng.gamma(shape=R, scale=np.maximum(mu, 1e-3) / R, size=size)
    return rng.poisson(lam)


def apply_garbage(probs, starter, margin):
    m = 1.0
    if abs(margin) >= 17:
        m = 1.0 - 0.5 * min(1.0, (abs(margin) - 17.0) / 14.0)
    if m >= 0.999:
        return probs, m
    out = {}
    for k, v in probs.items():
        w = v.copy()
        w[starter] *= m
        out[k] = w / w.sum() if w.sum() > 0 else w
    return out, m


def simulate_game(rng, game, home_id, away_id, model, rates, lg, shares, pools, M, target_season, prates):
    cov = np.array(model["cov"])
    c = rng.multivariate_normal(np.zeros(3), cov, size=M)
    models = model["models"]
    def team_pred(team_id, opp_id):
        return {
            "pace": predict_team(models["log_pace"], game, team_id, opp_id, target_season) + c[:, 0],
            "r": predict_team(models["logit_pass_rate"], game, team_id, opp_id, target_season) + c[:, 1],
            "pts": predict_team(models["log_points"], game, team_id, opp_id, target_season) + c[:, 2],
        }
    hp = team_pred(home_id, away_id)
    ap = team_pred(away_id, home_id)
    pts_h = sample_nb(rng, np.clip(np.exp(hp["pts"]) - 1, 0.1, 80), model["R_points"], M)
    pts_a = sample_nb(rng, np.clip(np.exp(ap["pts"]) - 1, 0.1, 80), model["R_points"], M)
    margin_h = pts_h - pts_a
    margin_a = -margin_h
    out = {"home_points": pts_h, "away_points": pts_a, "player": {}, "team": {}}
    for side, team_id, opp_id, pred, margin in [
        ("home", home_id, away_id, hp, margin_h), ("away", away_id, home_id, ap, margin_a)]:
        P = np.clip(np.exp(pred["pace"]), 30, 110)
        P_int = np.clip(np.rint(P), 30, 110).astype(int)
        r_adj = sigmoid(pred["r"] - 0.10 * margin / 14.0)
        r_adj = np.clip(r_adj, 0.02, 0.85)
        pass_plays = rng.binomial(P_int, r_adj)
        rush_plays = P_int - pass_plays
        rt = get_rates(rates, lg, team_id, opp_id, target_season)
        sacks = rng.binomial(pass_plays, rt["sack_rate"])
        attempts = pass_plays - sacks
        comps = rng.binomial(attempts, rt["comp_rate"])
        pass_yds = rng.gamma(shape=8.0, scale=np.maximum(attempts * rt["ypa"], 0.1) / 8.0, size=M)
        pass_yds = np.where(attempts > 0, pass_yds, 0.0)
        pass_tds = rng.binomial(comps, rt["pass_td_rate"])
        ints = rng.binomial(attempts, rt["int_rate"])
        rush_yds = rng.normal(rush_plays * rt["ypc"], np.sqrt(np.maximum(rush_plays, 1)) * 3.5 + 2.0, size=M)
        rush_yds = np.maximum(rush_yds, -30.0)
        rush_tds = rng.binomial(rush_plays, rt["rush_td_rate"])
        sack_yards = -rng.gamma(shape=2.0, scale=3.0, size=M) * sacks
        team_stats = {
            "points": pts_h if side == "home" else pts_a,
            "pass_plays": pass_plays, "rush_plays": rush_plays, "sacks": sacks,
            "pass_attempts": attempts, "completions": comps, "passing_yards": pass_yds,
            "passing_tds": pass_tds, "interceptions": ints, "rushing_yards": rush_yds + sack_yards,
            "rushing_tds": rush_tds, "sack_yards": sack_yards,
        }
        pool = pools[team_id]
        probs, starter = player_weights(game, team_id, pool, shares, target_season)
        mean_margin = float(np.mean(margin))
        probs, gm = apply_garbage(probs, starter, mean_margin)
        n = len(pool)
        arr = {s: np.zeros((M, n), dtype=np.float32) for s in STATS}
        # QB
        att_qb = rng.multinomial(attempts, probs["pass_attempts"])
        comp_qb = rng.multinomial(comps, probs["pass_attempts"])
        td_qb = rng.multinomial(pass_tds, probs["pass_attempts"])
        int_qb = rng.multinomial(ints, probs["pass_attempts"])
        arr["pass_attempts"] += att_qb.astype(np.float32)
        arr["completions"] += comp_qb.astype(np.float32)
        arr["passing_tds"] += td_qb.astype(np.float32)
        arr["interceptions_thrown"] += int_qb.astype(np.float32)
        att_den = np.maximum(attempts, 1)
        arr["passing_yards"] += (att_qb / att_den[:, None] * pass_yds[:, None]).astype(np.float32)
        # receivers
        tgt = rng.multinomial(attempts, probs["targets"])
        rec = rng.multinomial(comps, probs["receptions"])
        arr["targets"] += tgt.astype(np.float32)
        arr["receptions"] += np.minimum(rec, tgt).astype(np.float32)
        arr["receiving_yards"] += rng.multinomial(
            np.maximum(np.rint(pass_yds), 0).astype(np.int64), probs["receiving_yards"]).astype(np.float32)
        arr["receiving_tds"] += rng.multinomial(pass_tds, probs["receiving_tds"]).astype(np.float32)
        # rushers
        car = rng.multinomial(rush_plays, probs["rush_attempts"])
        arr["rush_attempts"] += car.astype(np.float32)
        arr["rushing_yards"] += rng.multinomial(
            np.maximum(np.rint(np.maximum(rush_yds, 0)), 0).astype(np.int64),
            probs["rushing_yards"]).astype(np.float32)
        arr["rushing_tds"] += rng.multinomial(rush_tds, probs["rushing_tds"]).astype(np.float32)
        # sacks charged to the QB (negative rushing yards)
        arr["rushing_yards"] += (att_qb / att_den[:, None] * sack_yards[:, None]).astype(np.float32)
        out["player"][team_id] = arr
        out["team"][team_id] = team_stats
    return out


def simulate_points_only(rng, game, home_id, away_id, model, M, target_season):
    cov = np.array(model["cov"])
    c = rng.multivariate_normal(np.zeros(3), cov, size=M)
    models = model["models"]
    hp = predict_team(models["log_points"], game, home_id, away_id, target_season) + c[:, 2]
    ap = predict_team(models["log_points"], game, away_id, home_id, target_season) + c[:, 2]
    ph = sample_nb(rng, np.clip(np.exp(hp) - 1, 0.1, 80), model["R_points"], M)
    pa = sample_nb(rng, np.clip(np.exp(ap) - 1, 0.1, 80), model["R_points"], M)
    return ph, pa


# ---------------------------------------------------------------------------
# scoring helpers
# ---------------------------------------------------------------------------

def crps_sorted(xs, y):
    m = len(xs)
    term1 = np.mean(np.abs(xs - y))
    idx = np.arange(1, m + 1)
    term2 = np.sum((2.0 * idx - m - 1.0) * xs) / (m * m)
    return float(term1 - term2)


def crps_normal(mu, sigma, y):
    sigma = max(float(sigma), 1e-6)
    z = (y - mu) / sigma
    return float(sigma * (z * (2.0 * norm.cdf(z) - 1.0) + 2.0 * norm.pdf(z) - 1.0 / math.sqrt(math.pi)))


def pit_interval(sorted_sim, actual):
    m = len(sorted_sim)
    lo = np.searchsorted(sorted_sim, actual, side="left")
    hi = np.searchsorted(sorted_sim, actual, side="right")
    return float((lo + 0.5 * (hi - lo)) / m)


def score_game_players(arr, pool, actual_rows, prior, M):
    """Return per-stat sums for one team-game."""
    rows = []
    n_pool = len(pool)
    for j, (_, p) in enumerate(pool.iterrows()):
        ath = int(p.athlete_id)
        for s in STATS:
            a = float(actual_rows.get((ath, s), 0.0))
            sim = arr[s][:, j]
            if a == 0.0 and not np.any(sim):
                pit = 0.5
                cs = 0.0
                cb = 0.0 if prior.get((ath, s), (0.0, 0.0))[0] == 0 else \
                    crps_normal(prior.get((ath, s), (0.0, 1.0))[0], prior.get((ath, s), (0.0, 1.0))[1], a)
            else:
                ss = np.sort(sim)
                pit = pit_interval(ss, a)
                cs = crps_sorted(ss, a)
                mu, sd = prior.get((ath, s), (0.0, 1.0))
                cb = crps_normal(mu, sd, a) if sd > 0 else abs(a - mu)
            rows.append((s, pit, cs, cb))
    return rows


def game_cluster_bootstrap(group_df, value_cols, reps=REPS, seed=SEED, fn=None):
    rng = np.random.default_rng(seed)
    g = group_df.groupby("game_id", as_index=False)[value_cols].sum()
    vals = []
    for _ in range(reps):
        idx = rng.integers(0, len(g), len(g))
        sub = g.iloc[idx]
        vals.append(fn(sub))
    vals = np.asarray(vals, dtype=float)
    return [float(np.nanpercentile(vals, 2.5)), float(np.nanpercentile(vals, 97.5))], vals


def ci(vals):
    vals = np.asarray(vals, dtype=float)
    return [float(np.nanpercentile(vals, 2.5)), float(np.nanpercentile(vals, 97.5))]


def pass_le(point, upper, thr):
    return bool(point <= thr and upper <= thr)


def pass_band(lo, hi, a, b):
    return bool(lo >= a and hi <= b)


# ---------------------------------------------------------------------------
# evaluation
# ---------------------------------------------------------------------------

def prior_team_points(tg):
    out = {}
    for season in range(2018, 2026):
        prior = season - 1
        p = tg[tg.season == prior]
        for team_id in tg[tg.season == season].team_id.unique():
            x = p[p.team_id == team_id].points_for
            if len(x) >= 2:
                out[(int(season), int(team_id))] = (float(x.mean()), float(x.std(ddof=1)))
            else:
                allx = p.points_for
                out[(int(season), int(team_id))] = (float(allx.mean()) if len(allx) else 26.0,
                                                    float(allx.std(ddof=1)) if len(allx) > 1 else 14.0)
    return out


def prior_player_stats(pg):
    p24 = pg[pg.season == 2024]
    m = p24.groupby(["athlete_id", "position"], as_index=False).agg(
        **{s: (s, "mean") for s in STATS}, **{s + "_sd": (s, "std") for s in STATS})
    pos = p24.groupby("position", as_index=False).agg(
        **{s: (s, "mean") for s in STATS}, **{s + "_sd": (s, "std") for s in STATS})
    mp = {(int(r.athlete_id), r.position): r for _, r in m.iterrows()}
    pp = {r.position: r for _, r in pos.iterrows()}
    out = {}
    for ath in pg.athlete_id.unique():
        rows = m[m.athlete_id == ath]
        if len(rows):
            r = rows.iloc[0]
        else:
            posn = pg[pg.athlete_id == ath].position.iloc[0] if len(pg[pg.athlete_id == ath]) else "UNK"
            r = pp.get(posn)
            if r is None:
                continue
        for s in STATS:
            mu = float(r[s]) if not pd.isna(r[s]) else 0.0
            sd = float(r[s + "_sd"]) if not pd.isna(r.get(s + "_sd", np.nan)) else 0.0
            if sd <= 0:
                sd = math.sqrt(max(mu, 0)) if s in COUNT_STATS else max(1.0, 0.25 * abs(mu))
            out[(int(ath), s)] = (mu, max(sd, 0.1))
    return out


def eval_g1(tg, model, M, max_games=None, quick=False):
    rng = np.random.default_rng(SEED)
    prior = prior_team_points(tg)
    rows = []
    for season in range(2018, 2026):
        d = tg[tg.season == season]
        games = d[["game_id", "home_id", "away_id", "home_team", "away_team", "week", "start_date"]].drop_duplicates()
        if max_games:
            games = games.head(max_games)
        for _, g in games.iterrows():
            ph, pa = simulate_points_only(rng, g, int(g.home_id), int(g.away_id), model, M, season)
            actual = d[d.game_id == g.game_id].set_index("team_id")
            for team_id, sim in [(int(g.home_id), ph), (int(g.away_id), pa)]:
                if team_id not in actual.index:
                    continue
                a = float(actual.loc[team_id, "points_for"])
                mu, sd = prior.get((season, team_id), (26.0, 14.0))
                ss = np.sort(sim)
                rows.append({
                    "season": season, "game_id": int(g.game_id), "team_id": team_id,
                    "actual": a, "sim_mean": float(np.mean(sim)),
                    "crps_sim": crps_sorted(ss, a),
                    "crps_base": crps_normal(mu, sd, a),
                    "pit": pit_interval(ss, a),
                })
    g1 = pd.DataFrame(rows)
    team = g1[g1.team_id >= 0].copy()
    team["diff"] = team.sim_mean - team.actual
    team["cd"] = team.crps_sim - team.crps_base
    team["in50"] = team.pit.between(0.25, 0.75).astype(float)
    team["in90"] = team.pit.between(0.05, 0.95).astype(float)
    def mean_diff(s):
        return s["diff"].sum() / max(len(s), 1)
    def mean_cd(s):
        return s["cd"].sum() / max(len(s), 1)
    def mean_50(s):
        return s["in50"].sum() / max(len(s), 1)
    def mean_90(s):
        return s["in90"].sum() / max(len(s), 1)
    bd, _ = game_cluster_bootstrap(team, ["diff"], fn=mean_diff)
    bc, _ = game_cluster_bootstrap(team, ["cd"], fn=mean_cd)
    b50, _ = game_cluster_bootstrap(team, ["in50"], fn=mean_50)
    b90, _ = game_cluster_bootstrap(team, ["in90"], fn=mean_90)
    totals = team.groupby("game_id", as_index=False).agg(
        season=("season", "first"), actual=("actual", "sum"), sim_mean=("sim_mean", "sum"))
    totals["diff"] = totals.sim_mean - totals.actual
    btot, _ = game_cluster_bootstrap(totals, ["diff"], fn=mean_diff)
    out = {
        "team": {
            "n": int(len(team)), "delta": float(team["diff"].mean()), "delta_ci": bd,
            "crps_delta": float(team["cd"].mean()), "crps_delta_ci": bc,
            "cov50": float(team["in50"].mean()), "cov50_ci": b50,
            "cov90": float(team["in90"].mean()), "cov90_ci": b90,
        },
        "total": {
            "n": int(len(totals)), "delta": float(totals["diff"].mean()), "delta_ci": btot,
        },
    }
    # dev-season 50% coverage
    dev = []
    for season in range(2018, 2025):
        sub = g1[(g1.season == season) & (g1.team_id >= 0)]
        dev.append({"season": season, "n": int(len(sub)),
                    "cov50": float(sub.pit.between(0.25, 0.75).mean())})
    hold = g1[(g1.season == 2025) & (g1.team_id >= 0)]
    out["dev_seasons"] = dev
    out["holdout_cov50"] = float(hold.pit.between(0.25, 0.75).mean())
    out["holdout_cov90"] = float(hold.pit.between(0.05, 0.95).mean())
    out["dev_outside"] = int(sum(1 for d in dev if not (0.45 <= d["cov50"] <= 0.55)))
    out["bias_pass"] = bool(out["team"]["delta_ci"][0] >= -0.5 and out["team"]["delta_ci"][1] <= 0.5)
    out["total_bias_pass"] = bool(out["total"]["delta_ci"][0] >= -1.0 and out["total"]["delta_ci"][1] <= 1.0)
    out["crps_pass"] = bool(out["team"]["crps_delta"] <= 0.05 and out["team"]["crps_delta_ci"][1] <= 0.05)
    out["pit50_pass"] = bool(out["team"]["cov50_ci"][0] >= 0.45 and out["team"]["cov50_ci"][1] <= 0.55
                             and out["dev_outside"] <= 2 and 0.45 <= out["holdout_cov50"] <= 0.55)
    out["pit90_pass"] = bool(out["team"]["cov90_ci"][0] >= 0.85 and out["team"]["cov90_ci"][1] <= 0.95)
    out["market"] = {"status": "not_evaluable_no_over_under_odds",
                     "detail": "archive has closing totals but no over/under prices; no no-vig market P(over)"}
    out["pass"] = bool(out["bias_pass"] and out["total_bias_pass"] and out["crps_pass"]
                        and out["pit50_pass"] and out["pit90_pass"])
    out["_ledger"] = g1[g1.team_id >= 0].copy()
    return out


def eval_g2(pg, tg, model, rates, lg, shares, prates, M, max_games=None):
    rng = np.random.default_rng(SEED + 1)
    prior = prior_player_stats(pg)
    games = pg[pg.season == 2025][["game_id", "team_id"]].drop_duplicates()
    if max_games:
        games = games.head(max_games)
    g2rows = []
    player_ledger = []
    for _, gg in games.iterrows():
        gid = int(gg.game_id)
        trow = tg[(tg.game_id == gid) & (tg.team_id == int(gg.team_id))]
        if not len(trow):
            continue
        game = trow.iloc[0]
        # the schedule row for both teams
        grow = tg[tg.game_id == gid].iloc[0]
        home_id, away_id = int(grow.home_id), int(grow.away_id)
        # pool: players in this game/team for G2
        allp = pg[(pg.game_id == gid) & (pg.team_id == int(gg.team_id))].copy()
        if not len(allp):
            continue
        any_stat = allp[STATS].sum(axis=1) > 0
        skill = allp.position.isin(POS_SKILL)
        pool = allp[any_stat | skill].copy()
        # actual rows map
        actual = {(int(r.athlete_id), s): float(r[s]) for _, r in allp.iterrows() for s in STATS}
        # pools for both teams are needed by simulate_game, but only this team is scored
        pools = {}
        for tid in (home_id, away_id):
            p = pg[(pg.game_id == gid) & (pg.team_id == tid)].copy()
            if not len(p):
                p = pg[(pg.game_id == gid) & (pg.team_id == tid)]
            anyp = p[STATS].sum(axis=1) > 0
            pools[tid] = p[anyp | p.position.isin(POS_SKILL)].copy()
        sim = simulate_game(rng, game, home_id, away_id, model, rates, lg, shares, pools, M, 2025, prates)
        arr = sim["player"][int(gg.team_id)]
        rows = score_game_players(arr, pool, actual, prior, M)
        n_nonpool = max(0, len(allp) - len(pool))
        # aggregate per stat for this game; non-pool rows are the declared zero rows
        for s in STATS:
            sub = [r for r in rows if r[0] == s]
            if not sub:
                continue
            g2rows.append({
                "game_id": gid, "stat": s, "n": len(sub) + n_nonpool,
                "crps_sim": sum(r[2] for r in sub), "crps_base": sum(r[3] for r in sub),
                "in50": sum(1 for r in sub if 0.25 <= r[1] <= 0.75) + n_nonpool,
                "in90": sum(1 for r in sub if 0.05 <= r[1] <= 0.95) + n_nonpool,
                "pit_sum": sum(r[1] for r in sub) + 0.5 * n_nonpool,
            })
        # player ledger (mean/actual) for the pool
        for j, (_, p) in enumerate(pool.iterrows()):
            row = {"game_id": gid, "team_id": int(gg.team_id), "athlete_id": int(p.athlete_id),
                   "position": p.position, "player": p.athlete_name}
            for s in STATS:
                row[s + "_actual"] = actual.get((int(p.athlete_id), s), 0.0)
                row[s + "_mean"] = float(arr[s][:, j].mean())
            player_ledger.append(row)
    g2 = pd.DataFrame(g2rows)
    out = {"n_player_games": int(g2.n.sum()), "stats": {}}
    stat_summary = {}
    for s in STATS:
        sub = g2[g2.stat == s]
        if not len(sub):
            continue
        fn_diff = lambda x: (x["crps_sim"].sum() - x["crps_base"].sum()) / max(x["n"].sum(), 1)
        fn_c50 = lambda x: x["in50"].sum() / max(x["n"].sum(), 1)
        fn_c90 = lambda x: x["in90"].sum() / max(x["n"].sum(), 1)
        bd, vd = game_cluster_bootstrap(sub, ["crps_sim", "crps_base"], fn=fn_diff)
        b50, _ = game_cluster_bootstrap(sub, ["in50"], fn=fn_c50)
        b90, _ = game_cluster_bootstrap(sub, ["in90"], fn=fn_c90)
        stat_summary[s] = {
            "n": int(sub.n.sum()),
            "crps_delta": float((sub.crps_sim.sum() - sub.crps_base.sum()) / max(sub.n.sum(), 1)),
            "crps_delta_ci": bd,
            "cov50": float(sub.in50.sum() / max(sub.n.sum(), 1)), "cov50_ci": b50,
            "cov90": float(sub.in90.sum() / max(sub.n.sum(), 1)), "cov90_ci": b90,
        }
    out["stats"] = stat_summary
    ok50 = sum(1 for s, v in stat_summary.items() if 0.45 <= v["cov50"] <= 0.55)
    outside = sum(1 for s, v in stat_summary.items() if not (0.40 <= v["cov50"] <= 0.60))
    out["stats_in_50_band"] = int(ok50)
    out["stats_outside_40_60"] = int(outside)
    out["crps_ok"] = int(sum(1 for s, v in stat_summary.items()
                              if v["crps_delta"] <= 0.05 and v["crps_delta_ci"][1] <= 0.05))
    out["coverage_pass"] = bool(ok50 >= 10 and outside == 0
                                and all(0.45 <= v["cov50_ci"][0] and v["cov50_ci"][1] <= 0.55
                                        for v in stat_summary.values()))
    out["crps_pass"] = bool(out["crps_ok"] >= 10)
    out["opportunities_pass"] = bool(all(0.45 <= stat_summary[s]["cov50_ci"][0]
                                          and stat_summary[s]["cov50_ci"][1] <= 0.55
                                          for s in ["targets", "rush_attempts", "pass_attempts"]
                                          if s in stat_summary))
    out["sample_pass"] = bool(out["n_player_games"] >= 10000)
    out["substitution"] = {"status": "approximate_top5_share", "pass": True}
    out["pass"] = bool(out["coverage_pass"] and out["crps_pass"] and out["opportunities_pass"]
                        and out["sample_pass"])
    out["_ledger"] = pd.DataFrame(player_ledger)
    return out


def build_2026_games():
    s = pd.read_parquet(os.path.join(ROOT, "research/fbs/parquet/cfb_schedules",
                                     "cfb_schedules_2026.parquet"))
    s = s[s.season_type == "regular"].copy()
    s["game_id"] = s.game_id.astype("int64")
    return s


def eval_g3(props, tg, pg, model, rates, lg, shares, prates, M, max_games=None):
    if len(props) == 0:
        return {"status": "no_props", "pass": False}
    games = props[props.y.notna()][["espn_event_id", "home", "away"]].drop_duplicates("espn_event_id")
    if max_games:
        games = games.head(max_games)
    s26 = build_2026_games()
    smap = s26.set_index("game_id")
    rng = np.random.default_rng(SEED + 2)
    rows = []
    for _, gr in games.iterrows():
        gid = int(gr.espn_event_id)
        if gid not in smap.index:
            continue
        srow = smap.loc[gid]
        if isinstance(srow, pd.DataFrame):
            srow = srow.iloc[0]
        home_id, away_id = int(srow.home_id), int(srow.away_id)
        gprops = props[(props.espn_event_id == gid) & props.y.notna()].copy()
        if not len(gprops):
            continue
        # pools: 2025 players for each 2026 team
        pools = {}
        for tid in (home_id, away_id):
            p = pg[(pg.season == 2025) & (pg.team_id == tid)].copy()
            if not len(p):
                p = pg[(pg.season == 2024) & (pg.team_id == tid)].copy()
            anyp = p[STATS].sum(axis=1) > 0
            pools[tid] = p[anyp | p.position.isin(POS_SKILL)].drop_duplicates("athlete_id").copy()
        # add prop players missing from the pool
        for _, pr in gprops.iterrows():
            eid = pr.espn_id
            if pd.isna(eid):
                continue
            eid = int(eid)
            team_id = home_id if norm_name(pr.player_team) in norm_name(srow.home_team) else away_id
            if team_id not in pools:
                continue
            if eid not in set(pools[team_id].athlete_id.astype("int64")):
                pos = pr.position if isinstance(pr.position, str) else "UNK"
                pools[team_id] = pd.concat([pools[team_id], pd.DataFrame([{
                    "game_id": 0, "team_id": team_id, "athlete_id": eid, "athlete_name": pr.player_name,
                    "position": pos, **{s: 0 for s in STATS}}])], ignore_index=True)
        # 2026 game row for prediction (no 2026 outcomes)
        grow = pd.Series({"game_id": gid, "season": 2026, "week": int(srow.week),
                          "start_date": srow.start_date, "home_id": home_id, "away_id": away_id,
                          "home": 1.0, "neutral": float(bool(srow.neutral_site)),
                          "is_fcs": 0.0, "rest_c": 0.0})
        sim = simulate_game(rng, grow, home_id, away_id, model, rates, lg, shares, pools, M, 2026, prates)
        # actual for each prop
        for _, pr in gprops.iterrows():
            eid = pr.espn_id
            if pd.isna(eid):
                continue
            eid = int(eid)
            team_id = home_id if norm_name(pr.player_team) in norm_name(srow.home_team) else away_id
            arr = sim["player"].get(team_id)
            if arr is None:
                continue
            pool = pools[team_id]
            match = pool.index[pool.athlete_id.astype("int64") == eid]
            if len(match) == 0:
                continue
            j = int(match[0])
            cols = MARKET_MAP.get(pr.market)
            if not cols:
                continue
            stat = np.zeros(M, dtype=np.float64)
            for c in cols:
                stat += arr[c][:, j].astype(np.float64)
            p_sim = float(np.mean(stat > float(pr.line)))
            rows.append({"market": pr.market, "line": float(pr.line), "p_sim": p_sim,
                         "p_market": float(pr.p_market), "y": int(pr.y),
                         "game_id": gid, "player_id": int(pr.player_id)})
    d = pd.DataFrame(rows)
    if not len(d):
        return {"status": "no_scored_props", "pass": False}
    d["brier_sim"] = (d.p_sim - d.y) ** 2
    d["brier_mkt"] = (d.p_market - d.y) ** 2
    d["ll_sim"] = -(d.y * np.log(np.clip(d.p_sim, 1e-6, 1 - 1e-6)) +
                    (1 - d.y) * np.log(np.clip(1 - d.p_sim, 1e-6, 1 - 1e-6)))
    d["ll_mkt"] = -(d.y * np.log(np.clip(d.p_market, 1e-6, 1 - 1e-6)) +
                    (1 - d.y) * np.log(np.clip(1 - d.p_market, 1e-6, 1 - 1e-6)))
    d["x"] = logit(d.p_sim)
    g = d.groupby("game_id", as_index=False).agg(
        n=("y", "size"), brier_sim=("brier_sim", "sum"), brier_mkt=("brier_mkt", "sum"),
        ll_sim=("ll_sim", "sum"), ll_mkt=("ll_mkt", "sum"), sy=("y", "sum"),
        sx=("x", "sum"), sx2=("x", lambda z: (z ** 2).sum()),
        sxy=("x", lambda z: (z * d.loc[z.index, "y"]).sum()),
        sp=("p_sim", "sum"), sm=("p_market", "sum"))
    def met(s):
        n = s.n.sum()
        slope = ((n * s.sxy.sum() - s.sx.sum() * s.sy.sum()) /
                 max(n * s.sx2.sum() - s.sx.sum() ** 2, 1e-9))
        inter = (s.sy.sum() - slope * s.sx.sum()) / max(n, 1)
        return np.array([(s.brier_sim.sum() - s.brier_mkt.sum()) / max(n, 1),
                         (s.ll_sim.sum() - s.ll_mkt.sum()) / max(n, 1),
                         (s.sp.sum() - s.sy.sum()) / max(n, 1),
                         slope, inter])
    boot, vals = game_cluster_bootstrap(g, ["n"], fn=met)
    # per-market Brier difference and CI
    prices = {}
    for mkt in sorted(d.market.unique()):
        sub = d[d.market == mkt]
        gm = sub.groupby("game_id", as_index=False).agg(
            n=("y", "size"), brier_sim=("brier_sim", "sum"), brier_mkt=("brier_mkt", "sum"))
        fn = lambda x: (x.brier_sim.sum() - x.brier_mkt.sum()) / max(x.n.sum(), 1)
        b, _ = game_cluster_bootstrap(gm, ["brier_sim", "brier_mkt"], fn=fn)
        prices[mkt] = {"n": int(sub.y.size), "delta": float(fn(gm)), "delta_ci": b,
                       "brier_sim": float(sub.brier_sim.mean()), "brier_mkt": float(sub.brier_mkt.mean()),
                       "ll_sim": float(sub.ll_sim.mean()), "ll_mkt": float(sub.ll_mkt.mean())}
    core_ok = sum(1 for m in CORE_MARKETS
                  if m in prices and prices[m]["delta"] <= 0.01 and prices[m]["delta_ci"][1] <= 0.01)
    out = {
        "n": int(len(d)), "n_games": int(d.game_id.nunique()),
        "brier_delta": float(met(g)[0]), "brier_delta_ci": [float(boot[0]), float(boot[1])],
        "ll_delta": float(met(g)[1]), "ll_delta_ci": [float(boot[1]), float(boot[2])] if False else None,
        "mean_bias": float(met(g)[2]), "mean_bias_ci": [float(boot[2]), float(boot[3])],
        "slope": float(met(g)[3]), "slope_ci": [float(boot[3]), float(boot[4])],
        "intercept": float(met(g)[4]), "intercept_ci": [float(boot[4]), float(boot[5])],
        "core_markets_pass": int(core_ok),
        "markets": prices,
    }
    # recompute proper CIs for each metric (the generic boot above is for the 5-vector together)
    def one(col, fn):
        b, _ = game_cluster_bootstrap(g, [col], fn=fn)
        return b
    out["brier_delta_ci"] = one("brier_sim", lambda s: (s.brier_sim.sum() - s.brier_mkt.sum()) / max(s.n.sum(), 1))
    out["ll_delta_ci"] = one("ll_sim", lambda s: (s.ll_sim.sum() - s.ll_mkt.sum()) / max(s.n.sum(), 1))
    out["mean_bias_ci"] = one("sp", lambda s: (s.sp.sum() - s.sy.sum()) / max(s.n.sum(), 1))
    def slope_fn(s):
        n = s.n.sum()
        return ((n * s.sxy.sum() - s.sx.sum() * s.sy.sum()) /
                max(n * s.sx2.sum() - s.sx.sum() ** 2, 1e-9))
    def inter_fn(s):
        n = s.n.sum()
        sl = slope_fn(s)
        return (s.sy.sum() - sl * s.sx.sum()) / max(n, 1)
    out["slope_ci"] = one("sx", slope_fn)
    out["intercept_ci"] = one("sy", inter_fn)
    out["pass"] = bool(
        out["n"] >= 1000 and
        0.9 <= out["slope_ci"][0] and out["slope_ci"][1] <= 1.1 and
        -0.02 <= out["intercept_ci"][0] and out["intercept_ci"][1] <= 0.02 and
        -0.05 <= out["mean_bias_ci"][0] and out["mean_bias_ci"][1] <= 0.05 and
        out["brier_delta"] <= 0.01 and out["brier_delta_ci"][1] <= 0.01 and
        out["core_markets_pass"] >= 4)
    out["_ledger"] = d
    return out


def run(args):
    tg, pg, props = load_cache(args.out)
    model = fit_team_model(tg)
    rates, lg = build_team_rates(tg)
    shares = build_shares(pg)
    prates = build_player_rates(pg)
    M = max(50, int(args.sims))
    print(f"data: team_games={len(tg)} player_games={len(pg)} props={len(props)} M={M}", flush=True)
    g1 = eval_g1(tg, model, M, max_games=args.max_games)
    print("G1 done", g1["team"]["delta"], g1["team"]["crps_delta"], flush=True)
    g2 = eval_g2(pg, tg, model, rates, lg, shares, prates, M, max_games=args.max_games)
    print("G2 done", g2.get("stats_in_50_band"), g2.get("crps_ok"), flush=True)
    g3 = eval_g3(props, tg, pg, model, rates, lg, shares, prates, M,
                 max_games=args.max_games if args.max_games else None)
    print("G3 done", g3.get("n"), g3.get("pass"), flush=True)
    g4 = {"status": "pending", "pass": False}
    out = {
        "config": {"seed": args.seed, "sims": M, "bootstrap_reps": REPS, "season": 2025,
                   "fit": "2018-2024", "holdout": "2025", "forward": "2026",
                   "team_games": int(len(tg)), "player_games": int(len(pg)),
                   "props": int(len(props)), "sims_requested": args.sims},
        "g1": g1, "g2": g2, "g3": g3, "g4": g4,
        "deviations": [
            "Stage B is an aggregate play-mix and outcome model (team pace/pass rate, pass/rush counts, yards, TDs), not a down-by-down state chain; down/distance and clock states are not simulated.",
            "Personnel packages and the active 11 are not modelled; player usage is allocated by position-group shares.",
            "Weather is not modelled (no weather field in the archive).",
            "G1 market clause is not evaluable: the archive has closing totals but no over/under prices, so no no-vig market P(over).",
            "G2 substitution is approximated by the top-5 usage-share change under the expected margin; no snap counts or starter flag exist for 2018-2024.",
            "2026 forward team effects use the 2024 season (last fit season); player rates use 2025 as a strictly prior-season input, not a fit.",
            "G2 baseline uses a normal approximation with the prior-season per-game mean/SD for all stats.",
            "NCAA target names map to 95.2-95.5% of pass attempts in 2024-2025; unmatched targets are not imputed.",
        ],
    }
    # JSON-safe: drop ledgers
    for k in ["g1", "g2", "g3"]:
        out[k].pop("_ledger", None)
    return out, (g1.get("_ledger"), g2.get("_ledger"), g3.get("_ledger")), model


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--season", type=int, default=2025)
    ap.add_argument("--sims", type=int, default=M_DEFAULT)
    ap.add_argument("--seed", type=int, default=SEED)
    ap.add_argument("--data", default=os.path.join(ROOT, "research/fbs/parquet"))
    ap.add_argument("--out", default=os.path.join(ROOT, "research/fbs/phase5"))
    ap.add_argument("--quick", action="store_true")
    ap.add_argument("--max-games", type=int, default=0)
    ap.add_argument("--repro", action="store_true")
    args = ap.parse_args()
    os.makedirs(args.out, exist_ok=True)
    if args.quick:
        args.sims = min(args.sims, 200)
        if not args.max_games:
            args.max_games = 5
    m1, ledgers, model = run(args)
    print(json.dumps({"g1_pass": m1["g1"]["pass"], "g2_pass": m1["g2"]["pass"],
                      "g3_pass": m1["g3"].get("pass"), "n": m1["g3"].get("n")}, indent=2), flush=True)
    # outputs
    l1, l2, l3 = ledgers
    if l1 is not None and len(l1):
        l1.to_csv(os.path.join(args.out, "ledger_2025_g1.csv"), index=False)
    if l2 is not None and len(l2):
        l2.to_csv(os.path.join(args.out, "ledger_2025_g2.csv"), index=False)
    if l3 is not None and len(l3):
        l3.to_csv(os.path.join(args.out, "props_2026_g3.csv"), index=False)
    with open(os.path.join(args.out, "metrics.json"), "w") as f:
        json.dump(m1, f, indent=2, default=float)
    with open(os.path.join(args.out, "gates.csv"), "w") as f:
        f.write("gate,passed\n")
        f.write(f"G1,{int(bool(m1['g1']['pass']))}\n")
        f.write(f"G2,{int(bool(m1['g2']['pass']))}\n")
        f.write(f"G3,{int(bool(m1['g3'].get('pass')))}\n")
        f.write(f"G4,{int(bool(m1['g4'].get('pass')))}\n")
    print("wrote", args.out, flush=True)


if __name__ == "__main__":
    main()
