#!/usr/bin/env python3
"""smoke_fbs_archive.py -- prove every release is readable, not just present.

Opening a Parquet footer proves the file is not truncated; it does not prove the columns decode.
This reads the first rows of the newest file in every release and reports the column count and a
non-null count, so a release that is structurally broken shows up here rather than in a model run.

Exit code 1 if any release fails.

Usage: /root/legendarypicks/backend/venv/bin/python backend/smoke_fbs_archive.py
"""
from __future__ import annotations

import argparse
import glob
import os
import sys

import pyarrow.parquet as pq


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--dir", default=os.path.join("research", "fbs", "parquet"))
    ap.add_argument("--rows", type=int, default=5)
    a = ap.parse_args(argv)
    ok = bad = 0
    failures = []
    for rel_dir in sorted(glob.glob(os.path.join(a.dir, "*"))):
        if not os.path.isdir(rel_dir):
            continue
        files = sorted(glob.glob(os.path.join(rel_dir, "*.parquet")))
        if not files:
            continue
        try:
            t = pq.read_table(files[-1]).slice(0, a.rows)
            vals = t.to_pylist()
            if not vals:
                raise ValueError("no rows")
            non_null = sum(1 for v in vals[0].values() if v is not None)
            ok += 1
            print("%-42s %3d cols %4d/%d non-null in row 1" % (
                os.path.basename(rel_dir), t.num_columns, non_null, t.num_columns))
        except Exception as e:
            bad += 1
            failures.append((os.path.basename(rel_dir), str(e)))
            print("FAIL %-37s %s" % (os.path.basename(rel_dir), e))
    print("\n%d readable, %d failed" % (ok, bad))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main() or 0)
