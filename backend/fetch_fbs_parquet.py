#!/usr/bin/env python3
"""fetch_fbs_parquet.py -- download the SportsDataverse season Parquet releases
the FBS modeling track needs, into a local cache directory.

The FBS work needs a box-score authority that is NOT CFBD, so the two can be
reconciled against each other. The SportsDataverse releases are the open
alternative: they carry ESPN play-by-play, player box scores, game rosters,
team box scores, season rosters, the ESPN-native schedule, the all-division
schedule, and weekly poll history as plain files on public URLs, no API key and
no rate limit.

Why not the CFBD API: its free tier is 1,000 calls a month and the shared key
on this box has already exhausted this month's quota (measured 2026-10-16:
`HTTP 429 {"message":"Monthly call quota exceeded."}` on every endpoint). The
Parquet releases are the right bulk path for exactly that reason.

This script is a cache warmer, nothing more. It does not write to the database
and it does not change any schema. It only puts files on disk so the audit
scripts can measure them.

Idempotent: an existing file whose size matches the release asset is skipped.
Use --force to re-download. Downloads are resumable only in the sense that
`curl -C -` is not used; a partial file is overwritten on the next run.

Usage:
    /root/legendarypicks/backend/venv/bin/python fetch_fbs_parquet.py \
        --dir /root/lp-fbs-audit/research/fbs/parquet --seasons 2026

Environment:
    SDV_DATA_DIR  -- override the default cache directory.
"""
import argparse
import json
import os
import sys
import urllib.error
import urllib.request

RELEASES_BASE = "https://api.github.com/repos/sportsdataverse/sportsdataverse-data/releases"
DOWNLOAD_BASE = ("https://github.com/sportsdataverse/sportsdataverse-data"
                 "/releases/download")

DEFAULT_DIR = os.environ.get("SDV_DATA_DIR") or os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "research", "fbs", "parquet"
)

# tag -> {asset name template -> local file name}
# The template is formatted with the season year.
RELEASES = {
    "espn_cfb_pbp": {
        "pattern": "play_by_play_{year}.parquet",
        "local": "espn_pbp_{year}.parquet",
    },
    "ncaa_mfb_pbp_cfbfastr": {
        "pattern": "ncaa_mfb_pbp_cfbfastr_{year}.parquet",
        "local": "ncaa_mfb_pbp_cfbfastr_{year}.parquet",
    },
    "espn_cfb_player_box": {
        "pattern": "player_box_{year}.parquet",
        "local": "player_box_{year}.parquet",
    },
    "espn_cfb_game_rosters": {
        "pattern": "game_rosters_{year}.parquet",
        "local": "game_rosters_{year}.parquet",
    },
    "espn_cfb_team_box": {
        "pattern": "team_box_{year}.parquet",
        "local": "team_box_{year}.parquet",
    },
    "cfb_schedules": {
        "pattern": "cfb_schedules_{year}.parquet",
        "local": "cfb_schedules_{year}.parquet",
    },
    "cfb_team_info": {
        "pattern": "cfb_team_info_{year}.parquet",
        "local": "cfb_team_info_{year}.parquet",
    },
    "espn_cfb_schedules": {
        "pattern": "cfb_schedule_{year}.parquet",
        "local": "espn_schedule_{year}.parquet",
    },
    "cfb_poll_analytics": {
        "pattern": "cfb_poll_analytics_{year}.parquet",
        "local": "cfb_poll_analytics_{year}.parquet",
    },
    "espn_cfb_rosters": {
        "pattern": "cfb_rosters_{year}.parquet",
        "local": "rosters_{year}.parquet",
    },
    "espn_cfb_betting": {
        "pattern": "betting_{year}.parquet",
        "local": "betting_{year}.parquet",
    },
    "espn_cfb_injuries": {
        "pattern": "injuries_{year}.parquet",
        "local": "injuries_{year}.parquet",
    },
    "cfb_crosswalk": {
        "pattern": "cfb_rosters_crosswalk.parquet",
        "local": "crosswalk.parquet",
    },
}

UA = {"User-Agent": "lp-fbs-audit/1.0"}


def gh_json(url, timeout=60):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode())


def asset_size(release, asset_name):
    for a in release.get("assets") or []:
        if a["name"] == asset_name:
            return a["size"]
    return None


def main():
    ap = argparse.ArgumentParser(description="Fetch SportsDataverse FBS parquet releases")
    ap.add_argument("--dir", default=DEFAULT_DIR)
    ap.add_argument("--seasons", default="2022,2023,2024,2025,2026",
                    help="comma-separated seasons to fetch")
    ap.add_argument("--tags", default=",".join(RELEASES),
                    help="comma-separated release tags to fetch")
    ap.add_argument("--force", action="store_true", help="re-download existing files")
    args = ap.parse_args()

    os.makedirs(args.dir, exist_ok=True)
    seasons = [s.strip() for s in args.seasons.split(",") if s.strip()]
    tags = [t.strip() for t in args.tags.split(",") if t.strip()]

    # One call per tag, batched by the releases endpoint's pagination.
    releases = {}
    page = 1
    while True:
        batch = gh_json("%s?per_page=100&page=%d" % (RELEASES_BASE, page))
        if not batch:
            break
        for r in batch:
            releases[r["tag_name"]] = r
        page += 1
        if page > 8:
            break

    fetched = skipped = missing = failed = 0
    for tag in tags:
        spec = RELEASES.get(tag)
        if spec is None:
            print("unknown tag: %s" % tag)
            continue
        rel = releases.get(tag)
        if rel is None:
            print("release not found on GitHub: %s" % tag)
            missing += 1
            continue
        targets = [seasons] if "{year}" not in spec["pattern"] else seasons
        for year in targets:
            asset = spec["pattern"].format(year=year)
            local = spec["local"].format(year=year)
            path = os.path.join(args.dir, local)
            want = asset_size(rel, asset)
            if want is None:
                print("  %-24s %s: asset not in release (skipped)" % (tag, asset))
                missing += 1
                continue
            if os.path.exists(path) and not args.force:
                have = os.path.getsize(path)
                if have == want:
                    print("  %-24s %-34s cached (%d bytes)" % (tag, local, have))
                    skipped += 1
                    continue
                print("  %-24s %-34s size %d != %d, re-downloading"
                      % (tag, local, have, want))
            url = "%s/%s/%s" % (DOWNLOAD_BASE, tag, asset)
            print("  %-24s %-34s -> %s (%d bytes)"
                  % (tag, local, url.rsplit("/", 1)[-1], want))
            try:
                req = urllib.request.Request(url, headers=UA)
                with urllib.request.urlopen(req, timeout=600) as resp:
                    data = resp.read()
                with open(path, "wb") as fh:
                    fh.write(data)
                if len(data) != want:
                    print("     MISMATCH: wrote %d bytes, release says %d"
                          % (len(data), want))
                    failed += 1
                else:
                    fetched += 1
            except (urllib.error.URLError, OSError) as exc:
                print("     FAILED: %s" % exc)
                failed += 1

    print("")
    print("fetched %d, cached %d, missing %d, failed %d"
          % (fetched, skipped, missing, failed))
    print("cache dir: %s" % os.path.abspath(args.dir))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
