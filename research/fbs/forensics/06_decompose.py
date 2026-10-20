"""Step 6: decompose the first divergent fitted block into feature vs estimator effects.

usage: 06_decompose.py BLOCK   (e.g. 2022-2022-09-25)
C2: research estimator on research features is the reference. Each alternative changes one factor.
G2h: the same class on both sides, so any difference is attributable to the inputs.
"""
import json
import os
import sys

import numpy as np
import pandas as pd

import common

BLOCK = sys.argv[1]
OUT = os.path.join(common.HERE, "out")
common.use_frozen_research()
os.chdir(common.FROZEN)
import fbs_phase3_hierarchical as hier_mod  # noqa: E402
import fbs_phase3_increment as inc  # noqa: E402
common.use_production(common.PROD_BACKEND)
import fbs_model_service as prod  # noqa: E402  (sha-identical research modules are already cached)

FR, FP = common.make_frame("research"), common.make_frame("production")
cutoff = FR.loc[FR.block == BLOCK, "utc_date"].min()
test_ids = FR.loc[FR.block == BLOCK, "game_id"].tolist()
committed = pd.read_csv(common.COMMITTED_WF, dtype={"game_id": str}).set_index("game_id")
blk_prod = pd.read_csv(os.path.join(common.WORK, "blk-production", "per_game.csv"),
                       dtype={"game_id": str}).set_index("game_id")


def objective(X, y, off, b, penalty_factor):
    p = inc.sigmoid(off + X @ b)
    eps = 1e-9
    nll = -np.sum(y * np.log(p + eps) + (1 - y) * np.log(1 - p + eps))
    return float(nll), float(penalty_factor * inc.RIDGE * np.sum(b[1:] ** 2))


def c2(F, mode):
    train = F[F.utc_date < cutoff].dropna(subset=["p_g2", "y"] + common.FEATS)
    test = F[F.block == BLOCK]
    y, off = train.y.to_numpy(float), inc.logit(train.p_g2.to_numpy(float))
    off_t = inc.logit(test.p_g2.to_numpy(float))
    info = {}
    if mode == "research_standardized":
        mu, sd = train[common.FEATS].mean(), train[common.FEATS].std().replace(0, 1.0)
        design = lambda d: np.column_stack([np.ones(len(d))] + [((d[c] - mu[c]) / sd[c]).to_numpy(float) for c in common.FEATS])  # noqa: E731
        X, Xt = design(train), design(test)
        b = inc.fit_offset_logistic(X, y, off)
        pf = 1.0
        info = {"mu": mu.round(6).to_dict(), "sd": sd.round(6).to_dict()}
    elif mode == "research_raw":
        X = np.column_stack([np.ones(len(train))] + [train[c].to_numpy(float) for c in common.FEATS])
        Xt = np.column_stack([np.ones(len(test))] + [test[c].to_numpy(float) for c in common.FEATS])
        b = inc.fit_offset_logistic(X, y, off)
        pf = 1.0
    else:  # production estimator as written: raw features, 0.5 penalty, solver options
        X = np.column_stack([np.ones(len(train))] + [train[c].to_numpy(float) for c in common.FEATS])
        Xt = np.column_stack([np.ones(len(test))] + [test[c].to_numpy(float) for c in common.FEATS])
        b = prod._fit_offset_logistic(X, y, off, ridge=prod.RIDGE)
        pf = 0.5
    p = inc.sigmoid(off_t + Xt @ b)
    nll, pen = objective(X, y, off, b, pf)
    return {"n_train": len(train), "beta": [round(v, 6) for v in b], "nll": nll, "penalty": pen,
            "objective": nll + pen, **info}, dict(zip(test.game_id, p))


out = {"block": BLOCK, "cutoff": str(cutoff.date()), "test_games": len(test_ids)}
ref = None
cases = [("C2 research estimator, research features (reference)", FR, "research_standardized"),
         ("C2 research estimator, production features", FP, "research_standardized"),
         ("C2 research objective, raw features, research features", FR, "research_raw"),
         ("C2 production estimator as written, production features", FP, "production_as_written"),
         ("C2 production estimator as written, research features", FR, "production_as_written")]
for label, F, mode in cases:
    params, preds = c2(F, mode)
    if ref is None:
        ref = preds
    params["max_diff_vs_research_reference"] = float(max(abs(preds[g] - ref[g]) for g in test_ids))
    params["max_diff_vs_committed"] = float(max(abs(preds[g] - committed.loc[g, "p_c2"]) for g in test_ids))
    out[label] = params
    print("%s | n_train %d | max|dp| vs reference %.4g | vs committed %.4g" % (
        label, params["n_train"], params["max_diff_vs_research_reference"], params["max_diff_vs_committed"]), flush=True)


def g2h(F):
    train = F[F.utc_date < cutoff].dropna(subset=["p_g2", "y"] + common.FEATS)
    model = hier_mod.HierarchicalLogistic(lam_team=9.0, lam_conf=156.0, ridge=1.0)
    model.fit(train, common.FEATS)
    test = F[F.block == BLOCK]
    return model, dict(zip(test.game_id, model.predict(test)))


mr, pr = g2h(FR)
mp, pp = g2h(FP)
out["G2h"] = {
    "n_train": int(len(FR[FR.utc_date < cutoff].dropna(subset=["p_g2", "y"] + common.FEATS))),
    "converged": [bool(mr.converged), bool(mp.converged)],
    "grad_norm": [float(mr.grad_norm), float(mp.grad_norm)],
    "n_iter": [int(mr.n_iter), int(mp.n_iter)],
    "max_abs_u_diff": float(np.max(np.abs(np.asarray(mr.u) - np.asarray(mp.u)))),
    "max_abs_m_diff": float(np.max(np.abs(np.asarray(mr.m) - np.asarray(mp.m)))),
    "mu_research": {c: round(float(mr.mu[c]), 6) for c in common.FEATS},
    "mu_production": {c: round(float(mp.mu[c]), 6) for c in common.FEATS},
    "sd_research": {c: round(float(mr.sd[c]), 6) for c in common.FEATS},
    "sd_production": {c: round(float(mp.sd[c]), 6) for c in common.FEATS},
    "max_diff_research_fit_vs_committed": float(max(abs(pr[x] - committed.loc[x, "p_g2h"]) for x in test_ids)),
    "max_diff_research_vs_production_features": float(max(abs(pr[x] - pp[x]) for x in test_ids)),
    "max_diff_production_fit_vs_block_file": float(max(abs(pp[x] - blk_prod.loc[x, "p_g2h"]) for x in test_ids)),
}
print("G2h", json.dumps({k: v for k, v in out["G2h"].items() if not k.startswith(("mu_", "sd_"))}, default=float), flush=True)
json.dump(out, open(os.path.join(OUT, "decompose_%s.json" % BLOCK), "w"), indent=1, default=float)
