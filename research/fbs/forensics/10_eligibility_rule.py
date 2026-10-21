"""Step 10: is the EPA-availability exclusion reproducible from published play-by-play coverage?

For every frame game, compare the writer's epa_diff availability with whether each candidate
play-by-play source contains rows for that game. Reports disagreements and the games involved.
"""
import os
import pandas as pd
import pyarrow.parquet as pq

import common

PROD_DATA = os.environ.get("FBS_PROD_DATA", "/root/fbs-data/parquet")
OUT = os.path.join(common.HERE, "out")
R = pd.read_pickle(common.data_path("research_prefilter.pkl"))
R["game_id"] = R["game_id"].astype(str)
seasons = sorted(R.season.unique())


def covered(pattern):
    ids = set()
    for s in seasons:
        path = pattern % s
        if os.path.exists(path):
            ids |= set(pq.read_table(path, columns=["game_id"]).to_pandas().game_id.astype(str))
    return ids


sources = {
    "archive cfbfastR_cfb_pbp (the EP pipeline's source)": os.path.join(common.ARCHIVE_PBP, "cfbfastR_cfb_pbp", "play_by_play_%d.parquet"),
    "production espn_cfb_pbp (drive-feature source)": os.path.join(PROD_DATA, "espn_cfb_pbp", "play_by_play_%d.parquet"),
    "production ncaa_mfb_pbp_cfbfastr": os.path.join(PROD_DATA, "ncaa_mfb_pbp_cfbfastr_%d.parquet"),
}
lines = []
for name, pattern in sources.items():
    ids = covered(pattern)
    has = R.game_id.isin(ids)
    bad = R.loc[has != R.epa_present, ["game_id", "season", "utc_date", "home_team", "away_team"]]
    lines.append("%s: games with rows=%d of %d; disagreements with epa_diff availability=%d" % (
        name, int(has.sum()), len(R), len(bad)))
    if len(bad) and len(bad) < 10:
        lines.append("   " + bad.astype(str).to_string(index=False).replace("\n", "\n   "))
for line in lines:
    print(line)
open(os.path.join(OUT, "eligibility_rule.txt"), "w").write("\n".join(lines) + "\n")
