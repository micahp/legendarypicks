"""Step 4: run the FROZEN research walk-forwards on one feature source, recording every block.

usage: 04_block_forensics.py {research|production} OUT_DIR
Writes per_game.csv, blocks.csv (training membership and feature fingerprints) and diags_g2h.json.
"""
import hashlib
import json
import os
import sys

import numpy as np
import pandas as pd

import common

variant, out = sys.argv[1], sys.argv[2]
os.makedirs(out, exist_ok=True)
common.use_frozen_research()
os.chdir(common.FROZEN)
import fbs_phase3_increment as inc  # noqa: E402
import fbs_phase3_increment_g as incg  # noqa: E402

F = common.make_frame(variant)
print(variant, "frame", len(F), "eval", int(F.season.between(2023, 2025).sum()), flush=True)


def fingerprint(train):
    rows = ["%s|%s" % (rec.game_id, "|".join("%.17g" % getattr(rec, c)
                                            for c in ["y", "p_g2"] + common.FEATS))
            for rec in train.sort_values("game_id").itertuples(index=False)]
    return hashlib.sha256("\n".join(rows).encode()).hexdigest()[:16] if rows else ""


blocks = []
for block, idx in F.groupby("block", sort=True).groups.items():
    cutoff = F.loc[np.asarray(idx), "utc_date"].min()
    train = F[F["utc_date"] < cutoff].dropna(subset=["p_g2", "y"] + common.FEATS)
    blocks.append({"block": block, "cutoff": str(cutoff.date()), "n_test": len(idx),
                   "n_train": len(train),
                   "train_ids_sha": hashlib.sha256(",".join(sorted(train.game_id)).encode()).hexdigest()[:16],
                   "train_feat_sha": fingerprint(train)})
pd.DataFrame(blocks).to_csv(os.path.join(out, "blocks.csv"), index=False)

wf = inc.walk_forward(F.copy(), common.FEATS).set_index("game_id")
wf_h, diags = incg.hierarchical_walk_forward(F.copy(), common.FEATS, 9.0, 156.0)
wf_h = wf_h.set_index("game_id")
per = F[["game_id", "season", "utc_date", "block"]].copy()
per["p_c2"] = wf.loc[per.game_id, "p_b2"].to_numpy()
per["n_train_c2"] = wf.loc[per.game_id, "n_train"].to_numpy()
per["p_g2h"] = wf_h.loc[per.game_id, "p_h"].to_numpy()
per.to_csv(os.path.join(out, "per_game.csv"), index=False)
json.dump(diags, open(os.path.join(out, "diags_g2h.json"), "w"), default=float, indent=1)
print("done", variant, "blocks", len(blocks), flush=True)
