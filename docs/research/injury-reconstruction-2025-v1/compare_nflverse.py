#!/usr/bin/env python3
"""compare_nflverse.py -- diagnostic only: compare extracted statuses with nflverse final report designations.

nflverse report_status is the final designation published after the pregame window, so it is not a pregame truth
source and is not used to tune or score the extractor. This prints how often the extractor's pregame statuses agree
with the final designation, and writes gold/nflverse_diagnostic.csv. The join is by GSIS id, week and team, and the
match count is printed so a silent miss shows up.
"""
import csv
import os
import sys

import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
GOLD = os.path.join(HERE, "gold")
INJURIES = "/root/lp-snapshots/nfl-backfill-2026-10-27/raw/injuries/injuries_2025.parquet"
MAP = {"Out": "OUT", "Doubtful": "DOUBTFUL", "Questionable": "QUESTIONABLE"}


def main(argv=None):
    nfl = pd.read_parquet(INJURIES, columns=["gsis_id", "week", "team", "report_status"])
    nfl = nfl[nfl.season_type == "REG"] if "season_type" in nfl.columns else nfl
    nfl["final"] = nfl.report_status.map(lambda s: MAP.get(s, "NONE") if isinstance(s, str) else "NONE")
    nfl = nfl.drop_duplicates(["gsis_id", "week", "team"])
    out = []
    for split in ("dev", "test"):
        path = os.path.join(GOLD, "extractions_%s.csv" % split)
        for r in csv.DictReader(open(path)):
            hit = nfl[(nfl.gsis_id == r["gsis_id"]) & (nfl.week == int(r["week"])) & (nfl.team == r["team"])]
            final = hit.final.iloc[0] if len(hit) else "not_listed"
            out.append(dict(item_id=r["item_id"], split=split, predicted=r["predicted"], gold=r["gold"],
                            nflverse_final=final))
    matched = sum(1 for o in out if o["nflverse_final"] != "not_listed")
    print("joined %d of %d items to nflverse injuries_2025 (gsis_id, week, team)" % (matched, len(out)))
    with open(os.path.join(GOLD, "nflverse_diagnostic.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(out[0].keys()))
        w.writeheader()
        w.writerows(out)
    for split in ("dev", "test"):
        rows = [o for o in out if o["split"] == split and o["predicted"] in ("OUT", "DOUBTFUL", "QUESTIONABLE")]
        agree = sum(1 for o in rows if o["predicted"] == o["nflverse_final"])
        print("%s: extractor designation vs nflverse final, agree %d of %d" % (split, agree, len(rows)))
        for o in rows:
            if o["predicted"] != o["nflverse_final"]:
                print("   %s predicted %-12s nflverse %s (gold %s)" % (o["item_id"], o["predicted"],
                                                                     o["nflverse_final"], o["gold"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
