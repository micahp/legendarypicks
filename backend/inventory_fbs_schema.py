#!/usr/bin/env python3
"""inventory_fbs_schema.py -- what is actually in each release, column by column.

Writes research/fbs/archive-schema.json: for every release, the newest file, its row count, and every
column with its Arrow type. Also prints a leakage scan: columns whose name says the publisher computed
them from the game itself (EPA, win probability, FPI, ratings, spread, total, projections, percentiles).
Those columns are the evidence for the leakage register, so the doc cites names rather than opinion.

Reads Parquet footers only.

Usage: /root/legendarypicks/backend/venv/bin/python backend/inventory_fbs_schema.py
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import re

import pyarrow.parquet as pq

SCAN = re.compile(r"(^|_)(epa|wpa|wp|win_prob|win_probability|ep|ep_before|ep_after|fpi|sp|srs|rating|"
                  r"ratings|power_index|paper_index|percentile|projection|proj|spread|total|line|"
                  r"point_spread|over_under|win_prob|pred|elo|talent|rank)($|_)", re.I)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--dir", default=os.path.join("research", "fbs", "parquet"))
    ap.add_argument("--out", default=os.path.join("research", "fbs", "archive-schema.json"))
    a = ap.parse_args(argv)
    out, flagged = {}, []
    for rel_dir in sorted(glob.glob(os.path.join(a.dir, "*"))):
        if not os.path.isdir(rel_dir):
            continue
        rel = os.path.basename(rel_dir)
        files = sorted(glob.glob(os.path.join(rel_dir, "*.parquet")))
        if not files:
            continue
        newest = files[-1]
        pf = pq.ParquetFile(newest)
        cols = {f.name: str(f.type) for f in pf.schema_arrow}
        out[rel] = {"newest_file": os.path.basename(newest), "rows": pf.metadata.num_rows,
                    "columns": cols}
        hits = [c for c in cols if SCAN.search(c)]
        if hits:
            flagged.append((rel, len(cols), hits))
    with open(a.out, "w") as fh:
        json.dump(out, fh, indent=1, sort_keys=True)
    print("%d releases, schema written to %s" % (len(out), a.out))
    print("\ncolumns that look publisher-computed (leakage candidates):")
    for rel, n, hits in flagged:
        print("  %-42s %3d cols  %s" % (rel, n, ", ".join(hits[:12]) + (" ..." if len(hits) > 12 else "")))


if __name__ == "__main__":
    main()
