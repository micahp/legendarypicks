"""Step 8: 2x2 over every block, through the production FORECASTING path (service.fit / service.predict).

usage: 08_path_equivalence.py {research|production} BACKEND TAG
  inputs: research features or the BACKEND's build_frame features (WORK/data/prod pickle, see PROD_PICKLE)
  estimator: BACKEND's service.fit/predict as written, plus a research-standardized C2 candidate
Population fixed at the writer's 3,523 games.
"""
import os
import sys

import numpy as np
import pandas as pd

import common

variant, backend, tag = sys.argv[1], sys.argv[2], sys.argv[3]
common.use_production(backend)
import fbs_model_service as service  # noqa: E402
import fbs_phase3_increment as inc  # noqa: E402

F = common.make_frame(variant)
committed = pd.read_csv(common.COMMITTED_WF, dtype={"game_id": str}).set_index("game_id")
FEATS = common.FEATS


def cand_fit(train):
    mu, sd = train[FEATS].mean(), train[FEATS].std().replace(0, 1.0)
    X = np.column_stack([np.ones(len(train))] + [((train[c] - mu[c]) / sd[c]).to_numpy(float) for c in FEATS])
    return mu, sd, inc.fit_offset_logistic(X, train.y.to_numpy(float), inc.logit(train.p_g2.to_numpy(float)))


def cand_predict(state, rows):
    mu, sd, beta = state
    X = np.column_stack([np.ones(len(rows))] + [((rows[c] - mu[c]) / sd[c]).to_numpy(float) for c in FEATS])
    return inc.sigmoid(inc.logit(rows.p_g2.to_numpy(float)) + X @ beta)


rec = []
for block, idx in F.groupby("block", sort=True).groups.items():
    test = F.loc[np.asarray(idx)]
    cutoff = test.utc_date.min()
    train = F[F.utc_date < cutoff].dropna(subset=["p_g2", "y"] + FEATS)
    if len(train) < service.MIN_TRAIN_GAMES:
        rec += [(g, p, p, p) for g, p in zip(test.game_id, test.p_g2)]
        continue
    state = service.fit(F.copy(), cutoff)
    written = service.predict(F.copy(), state, test.copy())
    cand = cand_predict(cand_fit(train), test)
    rec += [(g, written["p_c2"].iloc[k], cand[k], written["p_g2h"].iloc[k]) for k, g in enumerate(test.game_id)]
r = pd.DataFrame(rec, columns=["game_id", "c2_as_written", "c2_candidate", "g2h_as_written"]).set_index("game_id")
r = r.join(committed[["season", "p_c2", "p_g2h"]])
r.to_csv(os.path.join(common.WORK, "path-%s.csv" % tag))
ev = r.season.between(2023, 2025)
lines = []
for name, col, ref in (("C2 as written", "c2_as_written", "p_c2"),
                       ("C2 research-standardized candidate", "c2_candidate", "p_c2"),
                       ("G2h as written", "g2h_as_written", "p_g2h")):
    d = (r[col] - r[ref]).abs()
    lines.append("%-38s inputs=%-10s backend=%s: 2023-25 max|dp|=%.3g, rows>1e-6=%d of %d" % (
        name, variant, tag, d[ev].max(), int((d[ev] > 1e-6).sum()), int(ev.sum())))
    print(lines[-1], flush=True)
open(os.path.join(common.HERE, "out", "path_%s_%s.txt" % (variant, tag)), "w").write("\n".join(lines) + "\n")
