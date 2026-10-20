"""Step 7: does the writer's epa_diff population filter change any scored prediction?

Adds the one epa-null game back (research features, zero-filled as the writer does) and refits the
frozen C2 and G2h walk-forwards. Reports the scored 2023-2025 rows whose probability changes.
"""
import os

import numpy as np
import pandas as pd

import common

OUT = os.path.join(common.HERE, "out")
common.use_frozen_research()
os.chdir(common.FROZEN)
import fbs_phase3_increment as inc  # noqa: E402
import fbs_phase3_increment_g as incg  # noqa: E402

base = common.make_frame("research")
R = pd.read_pickle(common.data_path("research_prefilter.pkl"))
R["game_id"] = R["game_id"].astype(str)
row = R[~R["epa_present"]].copy()
row["utc_date"] = pd.to_datetime(row["utc_date"])
row["has_drive_data"] = row[common.FEATS].notna().all(axis=1)
for c in common.FEATS:
    row[c] = row[c].fillna(0.0)
cols = [c for c in base.columns if c != "block"]
full = pd.concat([base[cols], row[cols]], ignore_index=True).sort_values(["utc_date", "game_id"]).reset_index(drop=True)
full["block"] = full["season"].astype(str) + "-" + full["utc_date"].astype(str)
ev = base.loc[base.season.between(2023, 2025), "game_id"]
lines = ["epa-null game(s): %s on %s" % (row.game_id.tolist(), row.utc_date.dt.date.astype(str).tolist())]
for label, fn, col in (("C2", inc.walk_forward, "p_b2"), ("G2h", incg.hierarchical_walk_forward, "p_h")):
    if label == "C2":
        w0 = fn(base.copy(), common.FEATS).set_index("game_id")
        w1 = fn(full.copy(), common.FEATS).set_index("game_id")
    else:
        w0 = fn(base.copy(), common.FEATS, 9.0, 156.0)[0].set_index("game_id")
        w1 = fn(full.copy(), common.FEATS, 9.0, 156.0)[0].set_index("game_id")
    d = (w1.loc[ev, col] - w0.loc[ev, col]).abs()
    changed = d[d > 1e-6].index
    dates = base.set_index("game_id").loc[changed, "utc_date"]
    lines.append("%s: scored 2023-25 rows changed (>1e-6) = %d of %d; max |dp| = %.3g; seasons %s; dates %s to %s" % (
        label, len(changed), len(ev), d.max(), sorted(set(base.set_index("game_id").loc[changed, "season"])) if len(changed) else [],
        dates.min() if len(changed) else None, dates.max() if len(changed) else None))
    print(lines[-1], flush=True)
open(os.path.join(OUT, "population_effect.txt"), "w").write("\n".join(lines) + "\n")
