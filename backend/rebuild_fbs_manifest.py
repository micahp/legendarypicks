#!/usr/bin/env python3
"""rebuild_fbs_manifest.py -- regenerate research/fbs/parquet/MANIFEST.jsonl from the files on disk.

The manifest is a statement of fact about the archive, not a log: one row per Parquet file with its
release, asset name, season, byte size, sha256, download url, fetch time and table kind. It carries
nothing else. This script rebuilds it from the files themselves, so a row exists only if the bytes do:

  * size and sha256 are recomputed from the file;
  * url and download time are recovered from the existing manifest where possible;
  * season comes from the file name, kind from the same mapping the fetcher uses.

Writes atomically. Never touches the Parquet files and never touches a database.

Usage: /root/legendarypicks/backend/venv/bin/python backend/rebuild_fbs_manifest.py
"""
from __future__ import annotations

import argparse
import datetime as dt
import glob
import hashlib
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from fetch_fbs_archive import kind_of, season_of  # noqa: E402


def sha256(path, chunk=1 << 20):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for b in iter(lambda: fh.read(chunk), b""):
            h.update(b)
    return h.hexdigest()


def prior_rows(path):
    out = {}
    if not os.path.exists(path):
        return out
    with open(path) as fh:
        for line in fh:
            try:
                r = json.loads(line)
            except ValueError:
                continue
            out[(r.get("release"), r.get("asset"))] = r
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--dir", default=os.path.join("research", "fbs", "parquet"))
    a = ap.parse_args(argv)
    manifest = os.path.join(a.dir, "MANIFEST.jsonl")
    old = prior_rows(manifest)
    rows, bytes_total = [], 0
    for path in sorted(glob.glob(os.path.join(a.dir, "*", "*.parquet"))):
        release = os.path.basename(os.path.dirname(path))
        asset = os.path.basename(path)
        size = os.path.getsize(path)
        prev = old.get((release, asset), {})
        rows.append({
            "release": release,
            "asset": asset,
            "season": season_of(asset),
            "bytes": size,
            "sha256": sha256(path),
            "url": prev.get("url", ""),
            "downloaded_at": prev.get("downloaded_at") or
            dt.datetime.fromtimestamp(os.path.getmtime(path), dt.timezone.utc)
            .replace(microsecond=0).isoformat(),
            "local_path": path,
            "kind": kind_of(release, asset),
        })
        bytes_total += size
    tmp = manifest + ".tmp"
    with open(tmp, "w") as fh:
        for r in rows:
            fh.write(json.dumps(r, sort_keys=True) + "\n")
    os.replace(tmp, manifest)
    print("wrote %s: %d files, %.1f MB, sha256 recomputed for every file"
          % (manifest, len(rows), bytes_total / 1e6))


if __name__ == "__main__":
    main()
