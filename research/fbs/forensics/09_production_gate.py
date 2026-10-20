"""Step 9: run the production parity gate function (runner.check_parity) on a backend's frame.

usage: 09_production_gate.py BACKEND FRAME_PICKLE TAG
Writes no certificate and enables nothing. It only reports what the gate would say.
"""
import json
import os
import sys

import pandas as pd

import common

backend, pickle, tag = sys.argv[1], sys.argv[2], sys.argv[3]
common.use_production(backend)
import fbs_model_runner as runner  # noqa: E402

frame = pd.read_pickle(pickle)
frame["game_id"] = frame["game_id"].astype(str)
result = runner.check_parity(frame)
json.dump(result, open(os.path.join(common.HERE, "out", "gate_%s.json" % tag), "w"), indent=1, default=float)
print(tag, json.dumps({m: {k: v[k] for k in ("brier", "max_abs_row_diff", "rows_over_1e-6", "ok")}
                       for m, v in result["models"].items()}, default=float), "ok=", result["ok"])
