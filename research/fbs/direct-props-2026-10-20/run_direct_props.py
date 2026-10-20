#!/usr/bin/env python3
"""run_direct_props.py -- FBS direct two-stage player-prop baseline.

Reproduces every number in RESULTS.md for four markets:
  pass_attempts, passing_yards, rush_attempts, rushing_yards.

Reads the read-only Phase-5 cache built by backend/fbs_phase5_data.py.
Writes only inside this directory: coverage.csv, scoring tables, frozen
per-player-game predictions, and RESULTS.md.

Design
------
Two-stage count model per market.
  Stage 1 (usage)      : per-player per-game count from historical logs, with
                         team + opponent context and shrinkage toward the
                         player's own trailing multi-game rate.
  Stage 2 (efficiency) : yards per attempt / per carry rate distribution.
  Yards markets        : product distribution = stage-1 count x stage-2 rate,
                         sampled by Monte Carlo. The count and rate are treated
                         as conditionally independent given pre-game info.

Baselines each market must beat:
  A) trailing-5-game mean with a fixed (pooled) spread.
  B) position-level league distribution.

Evaluation: tune on 2018-2024 (grid, selected on 2024), score 2025 out of
sample, and score the 2026 prop board at its real lines as a prospective check.

Phases 4-6 status is UNCHANGED by anything in this directory.
"""
from __future__ import annotations

import argparse
import json
import os
import warnings

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_CACHE = "/root/lp-fbs-archive/research/fbs/phase5/cache"

MARKETS = {
    "pass_attempts": dict(kind="count", col="pass_attempts", positions=["QB"],
                          real_line=34.5, label="passing attempts"),
    "passing_yards": dict(kind="yards", col="passing_yards", positions=["QB"],
                          denom="pass_attempts", real_line=249.5, label="passing yards"),
    "rush_attempts": dict(kind="count", col="rush_attempts", positions=["RB", "QB"],
                          real_line=14.5, label="rushing carries"),
    "rushing_yards": dict(kind="yards", col="rushing_yards", positions=["RB", "QB"],
                          denom="rush_attempts", real_line=59.5, label="rushing yards"),
}

WINDOW = 5
EFF_WINDOW = 15
TRAIN_SEASONS = list(range(2018, 2025))   # 2018..2024
VALID_SEASON = 2024
SCORE_SEASON = 2025
SEED = 20261020

TEAM_STATS = ["pass_attempts", "rush_plays", "pass_yards", "rush_yards"]


# =============================================================================
# frame building
# =============================================================================
def _excl_trailing(series, gid, w):
    """Exclusive trailing-window sum and non-null count within group gid."""
    inc = series.groupby(gid).cumsum()
    pref = inc.groupby(gid).shift(1).fillna(0.0)
    tsum = pref - pref.groupby(gid).shift(w).fillna(0.0)
    cnt = series.notna().astype(float)
    inc_c = cnt.groupby(gid).cumsum()
    pref_c = inc_c.groupby(gid).shift(1).fillna(0.0)
    tcnt = pref_c - pref_c.groupby(gid).shift(w).fillna(0.0)
    return tsum, tcnt


def build_frames(cache):
    pg = pd.read_parquet(os.path.join(cache, "player_games.parquet"), columns=[
        "game_id", "team_id", "athlete_id", "athlete_name", "position",
        "position_abbreviation", "season", "pass_attempts", "passing_yards",
        "rush_attempts", "rushing_yards"])
    tg = pd.read_parquet(os.path.join(cache, "team_games.parquet"), columns=[
        "game_id", "team_id", "opp_id", "season", "week", "start_date",
        "pass_attempts", "rush_plays", "pass_yards", "rush_yards"])
    pr = pd.read_parquet(os.path.join(cache, "props_2026.parquet"))

    # Scope the population to QB/RB athletes (the four modelled markets).
    # Keep *all* rows for any athlete who is ever a QB or RB so trailing
    # windows still see their full history. Documented in RESULTS.md.
    keep_ath = pg.loc[pg.position_abbreviation.isin(["QB", "RB"]), "athlete_id"].unique()
    pg = pg[pg.athlete_id.isin(keep_ath)].reset_index(drop=True)
    print(f"player_games scoped to QB/RB athletes: {pg.shape}")

    tg["start_date"] = pd.to_datetime(tg["start_date"], errors="coerce")
    for c in TEAM_STATS:
        own = tg[c].fillna(0.0)
        tg[f"def_{c}"] = tg.groupby("game_id")[c].transform("sum").fillna(0.0) - own

    tg = tg.sort_values(["team_id", "start_date", "game_id"]).reset_index(drop=True)
    gid = tg["team_id"]
    tcols = []
    for c in TEAM_STATS:
        for base, col in (("t", c), ("d", f"def_{c}")):
            tsum, tcnt = _excl_trailing(tg[col].fillna(0.0), gid, WINDOW)
            tg[f"{base}_{c}_sum"] = tsum
            tg[f"{base}_{c}_cnt"] = tcnt
            tcols += [f"{base}_{c}_sum", f"{base}_{c}_cnt"]

    tctx = tg[["game_id", "team_id"] + tcols].copy()
    opp = tctx.rename(columns={"team_id": "opp_id", **{c: "o_" + c for c in tcols}})

    meta = ["game_id", "team_id", "week", "start_date", "opp_id"]
    meta = [c for c in meta if c in tg.columns]
    pg = pg.merge(tg[meta], on=["game_id", "team_id"], how="left")
    pg["start_date"] = pd.to_datetime(pg["start_date"], errors="coerce")
    pg = pg.sort_values(["athlete_id", "start_date", "game_id"]).reset_index(drop=True)

    agid = pg["athlete_id"]
    for c in ["pass_attempts", "passing_yards", "rush_attempts", "rushing_yards"]:
        tsum, tcnt = _excl_trailing(pg[c].fillna(0.0), agid, WINDOW)
        pg[f"{c}_tsum"] = tsum
        pg[f"{c}_tcnt"] = tcnt
        pg[f"{c}_tmean"] = np.where(tcnt > 0, tsum / np.where(tcnt > 0, tcnt, 1.0), np.nan)
    for mk in ("passing_yards", "rushing_yards"):
        d = MARKETS[mk]["denom"]
        pos = pg[d].fillna(0.0) > 0
        nsum, _ = _excl_trailing(pg[mk].fillna(0.0) * pos, agid, EFF_WINDOW)
        dsum, _ = _excl_trailing(pg[d].fillna(0.0) * pos, agid, EFF_WINDOW)
        pg[f"{mk}_enum"] = nsum
        pg[f"{mk}_eden"] = dsum

    pg = pg.merge(tctx, on=["game_id", "team_id"], how="left")
    pg = pg.merge(opp, on=["game_id", "opp_id"], how="left")
    return pg, tg, pr


def add_context_ratios(pg, tg):
    lm = {c: float(tg[tg.season.isin(TRAIN_SEASONS)][c].mean()) for c in TEAM_STATS}

    def ratio(num, den, key):
        return np.where(den > 0, num / np.where(den > 0, den, 1.0) / lm[key], 1.0)

    pg = pg.copy()
    pg["t_trail_ratio_pass"] = ratio(pg["t_pass_attempts_sum"].values, pg["t_pass_attempts_cnt"].values, "pass_attempts")
    pg["t_trail_ratio_rush"] = ratio(pg["t_rush_plays_sum"].values, pg["t_rush_plays_cnt"].values, "rush_plays")
    pg["o_trail_ratio_pass"] = ratio(pg["o_d_pass_attempts_sum"].values, pg["o_d_pass_attempts_cnt"].values, "pass_attempts")
    pg["o_trail_ratio_rush"] = ratio(pg["o_d_rush_plays_sum"].values, pg["o_d_rush_plays_cnt"].values, "rush_plays")
    return pg, lm


# =============================================================================
# priors / model means
# =============================================================================
def fit_league(pg, seasons):
    tr = pg[pg.season.isin(seasons)]
    L = {}
    for mk, cfg in MARKETS.items():
        col, pos = cfg["col"], cfg["positions"]
        d = tr[tr.position_abbreviation.isin(pos)]
        L[mk] = {
            "league_mean": float(d[col].mean()),
            "pos_mean": {p: float(d[d.position_abbreviation == p][col].mean()) for p in pos},
            "n": int(len(d)),
            "sd_fixed": float(np.nanstd((d[col] - d[f"{col}_tmean"]).values, ddof=1)),
            "pos_values": {p: d[d.position_abbreviation == p][col].astype(float).values for p in pos},
        }
        if cfg["kind"] == "yards":
            e = d[d[cfg["denom"]] > 0].copy()
            e["_r"] = e[col] / e[cfg["denom"]].clip(lower=1)
            L[mk]["league_eff"] = float(e[col].sum() / max(e[cfg["denom"]].sum(), 1))
            L[mk]["eff_sd"] = float(e["_r"].std(ddof=1))
    return L


def is_pass_market(mk):
    return MARKETS[mk]["positions"] == ["QB"]


def means_for(mk, pg, L, k, alpha, beta):
    col = MARKETS[mk]["col"]
    raw = pg[f"{col}_tmean"].values.astype(float)
    n = pg[f"{col}_tcnt"].values.astype(float)
    pm = np.array([L[mk]["pos_mean"].get(p, L[mk]["league_mean"])
                   for p in pg.position_abbreviation], float)
    raw = np.where(np.isnan(raw), pm, raw)
    base = (n * raw + k * pm) / (n + k)
    tp, rp = ("t_trail_ratio_pass", "o_trail_ratio_pass") if is_pass_market(mk) else ("t_trail_ratio_rush", "o_trail_ratio_rush")
    tmult = pg[tp].fillna(1.0).values if tp in pg.columns else np.ones(len(pg))
    omult = pg[rp].fillna(1.0).values if rp in pg.columns else np.ones(len(pg))
    mu = base * np.power(tmult, alpha) * np.power(omult, beta)
    return np.clip(mu, 1e-6, None)


def eff_for(mk, pg, L, k2):
    col = MARKETS[mk]["col"]
    enum = pg[f"{mk}_enum"].values.astype(float)
    eden = pg[f"{mk}_eden"].values.astype(float)
    league = L[mk]["league_eff"]
    raw = np.where(eden > 0, enum / np.where(eden > 0, eden, 1.0), league)
    e = (eden * raw + k2 * league) / (eden + k2)
    return np.clip(e, -20.0, 30.0)


def fit_dispersion(y, mu):
    from scipy.optimize import minimize_scalar
    from scipy.special import gammaln
    y = np.asarray(y, float)
    mu = np.clip(np.asarray(mu, float), 1e-6, None)

    def nll(logr):
        r = np.exp(logr)
        p = r / (r + mu)
        ll = (gammaln(y + r) - gammaln(r) - gammaln(y + 1)
              + r * np.log(p + 1e-12) + y * np.log(1 - p + 1e-12))
        return -np.mean(ll)

    res = minimize_scalar(nll, bounds=(np.log(0.02), np.log(1000)), method="bounded")
    return float(np.exp(res.x))


# =============================================================================
# sampling / scoring
# =============================================================================
def nb_samples(mu, r, n, rng):
    p = (r / (r + np.clip(mu, 1e-9, None))).reshape(-1, 1)
    return rng.negative_binomial(np.asarray(r, float), p, size=(len(mu), n)).astype(float)


def sample_predictive(mk, cfg, mu, e, L, n, rng, r):
    if cfg["kind"] == "count":
        return nb_samples(mu, r, n, rng)
    c = nb_samples(mu, r, n, rng)
    rate = rng.normal(e[:, None], L[mk]["eff_sd"], size=c.shape)
    return np.clip(c * rate, 0.0, None)


def crps_from_samples(S, y):
    Ss = np.sort(S, axis=1)
    N = Ss.shape[1]
    t1 = np.abs(Ss - y[:, None]).mean(axis=1)
    w = 2.0 * np.arange(N) - N + 1.0
    return t1 - (w * Ss).sum(axis=1) / (N * N)


def logscore_kde(S, y):
    N = S.shape[1]
    sd = S.std(axis=1, ddof=1)
    iqr = np.quantile(S, 0.75, axis=1) - np.quantile(S, 0.25, axis=1)
    h = np.clip(0.9 * np.minimum(sd, iqr / 1.34) * N ** (-0.2), 1e-6, None)
    diff = (y[:, None] - S) / h[:, None]
    f = (np.exp(-0.5 * diff * diff) / (h[:, None] * np.sqrt(2 * np.pi))).mean(axis=1)
    return -np.log(np.clip(f, 1e-12, None))


def score_block(S, y, lines):
    out = {"n": int(len(y))}
    out["crps"] = float(np.mean(crps_from_samples(S, y)))
    out["logscore"] = float(np.mean(logscore_kde(S, y)))
    pit = (S < y[:, None]).mean(axis=1) + 0.5 * (S == y[:, None]).mean(axis=1)
    out["pit_mean"] = float(np.mean(pit))
    out["pit_abs_dev"] = float(np.mean(np.abs(pit - 0.5)))
    out["pit_hist"] = [int(x) for x in np.histogram(pit, bins=10, range=(0, 1))[0]]
    for q in (50, 80, 90):
        lo = np.quantile(S, (1 - q / 100) / 2, axis=1)
        hi = np.quantile(S, 1 - (1 - q / 100) / 2, axis=1)
        out[f"cov{q}"] = float(np.mean((y >= lo) & (y <= hi)))
    out["beyond_p99"] = float(np.mean(y > np.quantile(S, 0.99, axis=1)))
    for Lx in lines:
        p = (S > Lx).mean(axis=1)
        out[f"brier_{Lx}"] = float(np.mean((p - (y > Lx).astype(float)) ** 2))
    return out


def position_pool(mk, L):
    cfg = MARKETS[mk]
    return np.concatenate([L[mk]["pos_values"].get(p, np.array([0.0])) for p in cfg["positions"]])


# =============================================================================
# main
# =============================================================================
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cache", default=DEFAULT_CACHE)
    ap.add_argument("--out", default=HERE)
    ap.add_argument("--reuse-params", action="store_true")
    args = ap.parse_args()

    pg, tg, pr = build_frames(args.cache)
    pg, lm = add_context_ratios(pg, tg)
    L = fit_league(pg, TRAIN_SEASONS)
    print("frames", pg.shape, "| league means", {k: round(v, 3) for k, v in lm.items()})

    coverage = build_coverage(pg, pr)
    coverage.to_csv(os.path.join(args.out, "coverage.csv"), index=False)

    # ---- tuning --------------------------------------------------------------
    pjson = os.path.join(args.out, "params.json")
    if args.reuse_params and os.path.exists(pjson):
        params = json.load(open(pjson))
        print("reused params from params.json")
    else:
        params = tune(pg, L)
        json.dump(params, open(pjson, "w"), indent=2)
    print("params", json.dumps(params, indent=2, default=str))

    # ---- score 2025 + 2026 props --------------------------------------------
    scores, predictions = score_2025(pg, L, params)
    scores.to_csv(os.path.join(args.out, "scoring_2025.csv"), index=False)
    for mk, df in predictions.items():
        df.to_csv(os.path.join(args.out, f"predictions_{mk}.csv"), index=False)

    props = score_props_2026(pr, pg, L, params)
    if len(props):
        props.to_csv(os.path.join(args.out, "scoring_2026_props.csv"), index=False)

    write_results(args.out, coverage, scores, props, params, L)
    print("wrote results; predictions:", {m: len(d) for m, d in predictions.items()})


def tune(pg, L):
    grid = [dict(k=k, alpha=a, beta=b) for k in (2, 4, 8) for a in (0.0, 0.5) for b in (0.0, 0.5)]
    params = {}
    for mk, cfg in MARKETS.items():
        col, pos = cfg["col"], cfg["positions"]
        base = pg[pg.position_abbreviation.isin(pos) & (pg[f"{col}_tcnt"] >= 1)]
        tr = base[base.season.isin(TRAIN_SEASONS)]
        val = base[base.season == VALID_SEASON]
        yv = val[col].values.astype(float)
        best = None
        best_r = None
        for g in grid:
            mu_tr = means_for(mk, tr, L, g["k"], g["alpha"], g["beta"])
            r = fit_dispersion(tr[col].values, mu_tr)
            rng = np.random.default_rng(SEED)
            if cfg["kind"] == "count":
                S = nb_samples(means_for(mk, val, L, g["k"], g["alpha"], g["beta"]), r, 400, rng)
                crps = float(np.mean(crps_from_samples(S, yv)))
                cand = (crps, dict(**g, r=r, k2=None))
            else:
                mu_val = means_for(mk, val, L, g["k"], g["alpha"], g["beta"])
                for k2 in (10.0, 30.0, 60.0):
                    e = eff_for(mk, val, L, k2)
                    S = sample_predictive(mk, cfg, mu_val, e, L, 400, rng, r)
                    crps = float(np.mean(crps_from_samples(S, yv)))
                    cand = (crps, dict(**g, r=r, k2=k2))
                    if best is None or crps < best[0]:
                        best = cand
                continue
            if best is None or crps < best[0]:
                best = cand
        params[mk] = dict(best[1], val_crps=best[0])
    return params


def score_2025(pg, L, params):
    rows, preds = [], {}
    for mk, cfg in MARKETS.items():
        col, pos = cfg["col"], cfg["positions"]
        p = params[mk]
        ev = pg[(pg.season == SCORE_SEASON) & pg.position_abbreviation.isin(pos)
                & (pg[f"{col}_tcnt"] >= 1)].copy()
        y = ev[col].values.astype(float)
        mu = means_for(mk, ev, L, p["k"], p["alpha"], p["beta"])
        rng = np.random.default_rng(SEED)
        if cfg["kind"] == "count":
            S_model = sample_predictive(mk, cfg, mu, None, L, 1000, rng, p["r"])
        else:
            e = eff_for(mk, ev, L, p["k2"])
            S_model = sample_predictive(mk, cfg, mu, e, L, 1000, rng, p["r"])
        tm = ev[f"{col}_tmean"].fillna(L[mk]["league_mean"]).values
        S_A = np.clip(rng.normal(tm[:, None], L[mk]["sd_fixed"], size=(len(ev), 1000)), 0, None)
        S_B = rng.choice(position_pool(mk, L), size=(len(ev), 1000))
        for name, S in (("model", S_model), ("baseline_A_trailing5_fixed", S_A),
                        ("baseline_B_position_league", S_B)):
            row = score_block(S, y, [cfg["real_line"]])
            row.update(market=mk, method=name, season=SCORE_SEASON)
            rows.append(row)
        pred = pd.DataFrame({
            "game_id": ev.game_id.values, "athlete_id": ev.athlete_id.values,
            "athlete_name": ev.athlete_name.values, "team_id": ev.team_id.values,
            "season": ev.season.values, "week": ev.week.values, "position": ev.position_abbreviation.values,
            "observed": y, "pred_mean": S_model.mean(axis=1), "pred_sd": S_model.std(axis=1),
            "q10": np.quantile(S_model, 0.10, axis=1), "q50": np.quantile(S_model, 0.50, axis=1),
            "q90": np.quantile(S_model, 0.90, axis=1),
            f"p_over_{cfg['real_line']}": (S_model > cfg["real_line"]).mean(axis=1),
        })
        preds[mk] = pred
    return pd.DataFrame(rows), preds


def score_props_2026(pr, pg, L, params):
    last = pg.sort_values(["athlete_id", "start_date"]).groupby("athlete_id").tail(1).set_index("athlete_id")
    keep = ["position_abbreviation"]
    for mk, cfg in MARKETS.items():
        keep += [f"{cfg['col']}_tmean", f"{cfg['col']}_tcnt"]
        if cfg["kind"] == "yards":
            keep += [f"{mk}_enum", f"{mk}_eden"]
    keep += ["t_trail_ratio_pass", "t_trail_ratio_rush"]
    last = last[keep]
    rows = []
    for mk, cfg in MARKETS.items():
        col, pos = cfg["col"], cfg["positions"]
        p = params[mk]
        s = pr[(pr.market == mk) & pr.y.notna() & pr.espn_id.notna()].copy()
        if not len(s):
            continue
        s["athlete_id"] = s.espn_id.astype("int64")
        s = s.merge(last, left_on="athlete_id", right_index=True, how="left")
        s = s[s[f"{col}_tcnt"].notna() & (s[f"{col}_tcnt"] >= 1)].copy()
        if not len(s):
            continue
        posn = s["position_abbreviation"].fillna(pos[0]).values
        raw = s[f"{col}_tmean"].values.astype(float)
        n = s[f"{col}_tcnt"].values.astype(float)
        pm = np.array([L[mk]["pos_mean"].get(x, L[mk]["league_mean"]) for x in posn])
        base = (n * raw + p["k"] * pm) / (n + p["k"])
        tmul = (s["t_trail_ratio_pass"] if is_pass_market(mk) else s["t_trail_ratio_rush"]).fillna(1.0).values
        mu = np.clip(base * np.power(tmul, p["alpha"]), 1e-6, None)  # opponent not identifiable for 2026
        rng = np.random.default_rng(SEED)
        if cfg["kind"] == "count":
            Sm = sample_predictive(mk, cfg, mu, None, L, 1000, rng, p["r"])
        else:
            enum = s[f"{mk}_enum"].values.astype(float)
            eden = s[f"{mk}_eden"].values.astype(float)
            league = L[mk]["league_eff"]
            rawe = np.where(eden > 0, enum / np.where(eden > 0, eden, 1.0), league)
            e = np.clip((eden * rawe + p["k2"] * league) / (eden + p["k2"]), -20, 30)
            Sm = sample_predictive(mk, cfg, mu, e, L, 1000, rng, p["r"])
        tm = s[f"{col}_tmean"].fillna(L[mk]["league_mean"]).values
        Sa = np.clip(rng.normal(tm[:, None], L[mk]["sd_fixed"], size=(len(s), 1000)), 0, None)
        Sb = rng.choice(position_pool(mk, L), size=(len(s), 1000))
        line = s.line.values.astype(float)
        y = s.y.values.astype(float)
        obs_line = s.actual_value.values.astype(float)
        for name, S in (("model", Sm), ("baseline_A_trailing5_fixed", Sa),
                        ("baseline_B_position_league", Sb)):
            rows.append(dict(
                market=mk, method=name, n=len(s),
                brier_actual_line=float(np.mean(((S > line[:, None]).mean(axis=1) - y) ** 2)),
                brier_realistic_line=float(np.mean(((S > cfg["real_line"]).mean(axis=1) - (obs_line > cfg["real_line"]).astype(float)) ** 2)),
                mean_line=float(np.mean(line)),
            ))
    return pd.DataFrame(rows)


def build_coverage(pg, pr):
    rows = []
    for mk, cfg in MARKETS.items():
        col, pos = cfg["col"], cfg["positions"]
        d = pg[pg.position_abbreviation.isin(pos)]
        nz = d[d[col] > 0]
        props = pr[pr.market == mk]
        rows.append(dict(
            market=mk, label=cfg["label"], positions="|".join(pos),
            seasons=f"{int(pg.season.min())}-{int(pg.season.max())}",
            player_games=len(d), player_games_gt0=len(nz),
            distinct_players=int(d.athlete_id.nunique()),
            distinct_games=int(d.game_id.nunique()),
            mean=round(float(d[col].mean()), 3), median=float(d[col].median()),
            sd=round(float(d[col].std(ddof=1)), 3),
            props_2026=int(len(props)), props_2026_settled=int(props.y.notna().sum()),
        ))
    return pd.DataFrame(rows)


def write_results(out, coverage, scores, props, params, L):
    def md(df):
        try:
            return df.to_markdown(index=False)
        except Exception:
            return df.to_string(index=False)
    L_ = ["# FBS direct player-prop baseline -- RESULTS\n",
          "Direct two-stage count model (usage x efficiency), independent of the",
          "Phase 4/5 play-by-play simulator. **Phases 4-6 status is UNCHANGED**: this is a",
          "new parallel prototype and claims nothing about phases 4, 5 or 6.\n",
          "## Coverage (data honesty)\n", md(coverage), "",
          "## Tuned parameters (grid on 2018-2024, selected on 2024 CRPS)\n"]
    for mk, p in params.items():
        L_.append(f"- `{mk}`: k={p['k']}, alpha={p['alpha']}, beta={p['beta']}, r={p['r']:.3f}, k2={p['k2']}, 2024 CRPS={p['val_crps']:.4f}")
    L_ += ["", "## 2025 out-of-sample scoring\n", md(scores), ""]
    if props is not None and len(props):
        L_ += ["## 2026 prop board (real lines)\n", md(props), ""]
    with open(os.path.join(out, "RESULTS.md"), "w") as f:
        f.write("\n".join(L_))


if __name__ == "__main__":
    main()
