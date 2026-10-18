#!/usr/bin/env python3
"""fetch_fbs_archive.py -- acquire the complete college-football archive from SportsDataverse releases.

Every release whose tag starts with `cfb_`, `espn_cfb_` or `ncaa_mfb_` is a college-football dataset.
For each one this script downloads every `.parquet` asset (the analysis format; `.csv` and `.rds` are
the same data) into

    research/fbs/parquet/<release>/<asset>

and writes one manifest row per file:

    release, asset, season, bytes, sha256, url, downloaded_at, local_path, kind

`kind` is `raw` (one row per observed event), `reference` (identity/schedule/poll tables), `scored`
(the publisher's model output: EPA, FPI, Paper Index, ratings, projections) or `model_artifact`
(a serialised model, not a table). The distinction matters: a scored column is not an observation.

`season` is parsed from the asset name (`..._2024.parquet`). Assets with no year get season = null and
are still recorded.

The manifest carries access and integrity facts only: where the file came from, how big it is, its
sha256, when it was fetched, and what kind of table it is.

Never writes to a database. Never commits the files (research/fbs/parquet/*.parquet is gitignored).
Idempotent: an existing file with the same size is skipped; a size mismatch is re-downloaded.

Usage:
  backend/venv/bin/python backend/fetch_fbs_archive.py --dry-run
  backend/venv/bin/python backend/fetch_fbs_archive.py --workers 6
  backend/venv/bin/python backend/fetch_fbs_archive.py --releases cfb_schedules,espn_cfb_betting
"""
from __future__ import annotations

import argparse
import concurrent.futures as cf
import datetime as dt
import hashlib
import json
import os
import re
import sys
import urllib.error
import urllib.request

API = "https://api.github.com/repos/sportsdataverse/sportsdataverse-data/releases"
PREFIXES = ("cfb_", "espn_cfb_", "ncaa_mfb_", "cfbfastr_")   # cfbfastR_* has no underscore after cfb

KIND = {}
for tag in ("cfb_recruits", "cfbfastR_cfb_pbp", "espn_cfb_pbp", "espn_cfb_player_box",
            "espn_cfb_game_rosters", "espn_cfb_team_box", "espn_cfb_drives", "espn_cfb_linescores",
            "espn_cfb_play_participants", "espn_cfb_rosters", "espn_cfb_schedules",
            "espn_cfb_passing", "espn_cfb_rushing", "espn_cfb_receiving", "espn_cfb_injuries",
            "ncaa_mfb_pbp", "ncaa_mfb_pbp_cfbfastr", "ncaa_mfb_drives", "ncaa_mfb_linescore",
            "ncaa_mfb_player_stats", "ncaa_mfb_rosters", "ncaa_mfb_schedule", "ncaa_mfb_team_stats",
            "ncaa_mfb_teams", "ncaa_mfb_officials", "ncaa_mfb_qa"):
    KIND[tag] = "raw"
for tag in ("cfb_crosswalk", "cfb_groups", "cfb_schedules", "cfb_team_info", "cfb_team_portal",
            "espn_cfb_teams", "espn_cfb_schedules", "ncaa_mfb_schedule"):
    KIND[tag] = "reference"
for tag in ("cfb_model_artifacts", "espn_cfb_model_artifacts"):
    KIND[tag] = "model_artifact"
for tag in ("cfbfastr_cfb_pbp", "cfbfastR_cfb_pbp"):
    KIND[tag] = "raw"
KIND.setdefault("__default__", "scored")

def get(url, tries=4):
    last = None
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "lp-fbs-archive"})
            with urllib.request.urlopen(req, timeout=60) as r:
                return json.load(r)
        except (urllib.error.URLError, TimeoutError) as e:
            last = e
            import time
            time.sleep(2 + 3 * i)
    raise SystemExit("GitHub API failed after %d tries: %s" % (tries, last))


def releases(wanted=None):
    out, page = [], 1
    while True:
        batch = get("%s?per_page=100&page=%d" % (API, page))
        if not batch:
            break
        for r in batch:
            tag = r["tag_name"]
            if not tag.lower().startswith(PREFIXES):
                continue
            if wanted and tag not in wanted:
                continue
            out.append(r)
        page += 1
        if page > 6:
            break
    return out


def season_of(name):
    """Season from a single-season file name; None for multi-season files.

    `cfb_model_pbp_2004_2025.parquet` covers 22 seasons, so it is NOT a 2025 file: a range name gets
    season = None. Mis-dating those files silently inflated one season's row count by 5.5M rows.
    """
    stem = name[:-8] if name.endswith(".parquet") else name
    if re.search(r"_\d{4}_\d{4}$", stem):
        return None
    m = re.search(r"(?:^|_)(\d{4})$", stem)
    return int(m.group(1)) if m else None


def kind_of(tag, asset):
    """A release can mix table types; the file name decides when it does."""
    if asset.startswith("rb_eval_"):
        return "model_artifact"
    if "train_full" in asset:
        return "training_matrix"
    return KIND.get(tag, KIND["__default__"])


def download(job, force=False):
    tag, asset, url, size, local, manifest_path = job
    os.makedirs(os.path.dirname(local), exist_ok=True)
    if os.path.exists(local) and not force:
        have = os.path.getsize(local)
        if have == size:
            sha = sha256(local)
            return {"release": tag, "asset": asset["name"], "season": season_of(asset["name"]),
                    "bytes": have, "sha256": sha, "url": url, "status": "skipped",
                    "local_path": local, "kind": kind_of(tag, asset["name"])}
    h = hashlib.sha256()
    tmp = local + ".part"
    with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "lp-fbs-archive"}),
                                timeout=120) as r, open(tmp, "wb") as fh:
        while True:
            chunk = r.read(1 << 20)
            if not chunk:
                break
            fh.write(chunk)
            h.update(chunk)
    got = os.path.getsize(tmp)
    if got != size:
        os.unlink(tmp)
        raise IOError("%s: size %d != asset %d" % (asset["name"], got, size))
    os.replace(tmp, local)
    return {"release": tag, "asset": asset["name"], "season": season_of(asset["name"]),
            "bytes": got, "sha256": h.hexdigest(), "url": url, "status": "downloaded",
            "local_path": local, "kind": kind_of(tag, asset["name"])}


def sha256(path, chunk=1 << 20):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for b in iter(lambda: fh.read(chunk), b""):
            h.update(b)
    return h.hexdigest()


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--dir", default=os.path.join("research", "fbs", "parquet"))
    ap.add_argument("--manifest", default=None, help="default <dir>/MANIFEST.jsonl")
    ap.add_argument("--releases", help="comma-separated tags; default every college release")
    ap.add_argument("--workers", type=int, default=5)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--force", action="store_true")
    a = ap.parse_args(argv)
    wanted = set(a.releases.split(",")) if a.releases else None
    rels = releases(wanted)
    jobs, total, by_rel = [], 0, []
    for r in rels:
        tag = r["tag_name"]
        n = sz = 0
        for asset in r["assets"]:
            if not asset["name"].endswith(".parquet"):
                continue
            url = asset["browser_download_url"]
            local = os.path.join(a.dir, tag, asset["name"])
            jobs.append((tag, asset, url, asset["size"], local, a.manifest))
            n += 1
            sz += asset["size"]
        total += sz
        by_rel.append((tag, n, sz))
    print("%d college releases, %d parquet assets, %.1f MB" % (len(rels), len(jobs), total / 1e6))
    for tag, n, sz in sorted(by_rel, key=lambda x: -x[2])[:15]:
        print("  %-44s %4d files %8.1f MB" % (tag, n, sz / 1e6))
    if a.dry_run:
        return
    manifest = a.manifest or os.path.join(a.dir, "MANIFEST.jsonl")
    os.makedirs(a.dir, exist_ok=True)
    done = errors = 0
    with cf.ThreadPoolExecutor(max_workers=a.workers) as ex:
        futs = {ex.submit(download, j, a.force): j for j in jobs}
        for fut in cf.as_completed(futs):
            j = futs[fut]
            try:
                row = fut.result()
                row["downloaded_at"] = dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()
                with open(manifest, "a") as fh:
                    fh.write(json.dumps(row, sort_keys=True) + "\n")
                done += 1
                if done % 100 == 0:
                    print("  %d/%d files" % (done, len(jobs)), flush=True)
            except Exception as e:  # keep going; the failure is recorded and reported
                errors += 1
                print("  FAILED %s/%s: %s" % (j[0], j[1]["name"], e), flush=True)
    print("finished: %d ok, %d failed; manifest %s" % (done, errors, manifest))
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main() or 0)
