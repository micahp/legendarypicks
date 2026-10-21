"""Step 11: the candidate's service path on the frozen 2025 holdout, with the holdout's frozen G2 offsets.

Fits on seasons before 2025 (as frozen_holdout does) and predicts 2025 with the ledger's elo_home_prob
as p_g2, the same test-row offsets the writer uses. Compares with the committed holdout file.
"""
import os
import sys

import pandas as pd

import common

sys.path.insert(0, common.CANDIDATE_BACKEND)
import fbs_model_service as service  # noqa: E402

F = common.make_frame("research")
ledger = pd.read_csv(os.path.join(common.FROZEN, "research/fbs/phase3-baseline/fbs_game_winner_holdout_2025_20261018.csv"),
                     usecols=["game_id", "elo_home_prob"], dtype={"game_id": str})
hold = pd.read_csv(os.path.join(common.FROZEN, "research/fbs/phase3-g/forecasts_holdout_2025.csv"), dtype={"game_id": str})
cutoff = F.loc[F.season == 2025, "utc_date"].min()
state = service.fit(F.copy(), cutoff)
test = (F[F.season == 2025].drop(columns=["p_g2"]).merge(ledger, on="game_id", how="inner")
        .rename(columns={"elo_home_prob": "p_g2"}))
pred = service.predict(F.copy(), state, test.copy())
m = hold.merge(pred[["game_id", "p_c2", "p_g2h"]], on="game_id", suffixes=("_c", "_r"))
lines = ["holdout rows committed=%d matched=%d train_games=%d cutoff=%s" % (len(hold), len(m), state["train_games"], cutoff.date())]
for col in ["p_c2", "p_g2h"]:
    d = (m[col + "_c"] - m[col + "_r"]).abs()
    lines.append("%s: max|dp|=%.3g rows>1e-6=%d of %d" % (col, d.max(), int((d > 1e-6).sum()), len(m)))
print("\n".join(lines))
open(os.path.join(common.HERE, "out", "holdout_candidate.txt"), "w").write("\n".join(lines) + "\n")
