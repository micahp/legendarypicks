"""Stage a narrow research extract of the nflverse play-by-play release (penalty and return fields only).

Source: https://github.com/nflverse/nflverse-data/releases/tag/pbp, file play_by_play_<season>.parquet.
Per season the raw file is downloaded to a scratch directory, hashed (sha256), read for the columns below, and the raw
file is deleted, so the disk is not filled. The extract and a manifest go to OUT_DIR, outside every production database.

Licence basis: the user's finding (2026-10-27) that the nflverse release terms allow this research use, with FTN-derived
content under CC BY-SA 4.0 and attribution. The nflverse-data README in the repo has no licence text, so the terms are
recorded as the user stated them. Attribution is written into the manifest. The extract is for internal research only.

Usage: python3 stage_nflverse_pbp.py [--seasons 2010 2011 ...]
"""
import argparse
import datetime
import hashlib
import json
import os
import urllib.request

import pyarrow.parquet as pq

BASE = 'https://github.com/nflverse/nflverse-data/releases/download/pbp/play_by_play_{season}.parquet'
OUT_DIR = '/root/lp-snapshots/nfl-backfill-2026-10-27'
SCRATCH = '/tmp/claude-0/-root/4a715766-ff4b-4980-99e5-dc209eaac7d4/scratchpad/nfl-splits/stage_tmp'
SEASONS = range(2010, 2027)
COLUMNS = ['game_id', 'play_id', 'season', 'season_type', 'week', 'home_team', 'away_team', 'posteam', 'defteam',
           'play_type', 'play_deleted', 'touchdown', 'fumble_lost', 'safety', 'penalty', 'penalty_type',
           'penalty_team', 'penalty_player_id', 'penalty_yards', 'first_down_penalty', 'return_team', 'return_yards',
           'return_touchdown', 'punt_attempt', 'kickoff_attempt', 'punt_blocked', 'touchback', 'punt_returner_player_id',
           'kickoff_returner_player_id']
ATTRIBUTION = ('Play-by-play data from the nflverse project (nflverse-data releases). Please credit nflverse. FTN-derived '
               'fields, if any, are CC BY-SA 4.0 and need FTN Data credited through nflverse.')


def fetch(season, path):
    req = urllib.request.Request(BASE.format(season=season), headers={'User-Agent': 'lp-research-staging'})
    with urllib.request.urlopen(req, timeout=300) as resp, open(path, 'wb') as out:
        while True:
            chunk = resp.read(1 << 20)
            if not chunk:
                break
            out.write(chunk)


def sha256(path):
    digest = hashlib.sha256()
    with open(path, 'rb') as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b''):
            digest.update(chunk)
    return digest.hexdigest()


def stage(season):
    os.makedirs(SCRATCH, exist_ok=True)
    os.makedirs(os.path.join(OUT_DIR, 'extract'), exist_ok=True)
    raw = os.path.join(SCRATCH, f'play_by_play_{season}.parquet')
    try:
        fetch(season, raw)
    except Exception as exc:  # a missing season is recorded, not hidden
        return dict(season=season, url=BASE.format(season=season), status=f'download failed: {exc}')
    digest, size = sha256(raw), os.path.getsize(raw)
    names = pq.read_schema(raw).names
    present = [c for c in COLUMNS if c in names]
    missing = [c for c in COLUMNS if c not in names]
    table = pq.read_table(raw, columns=present)
    out_path = os.path.join(OUT_DIR, 'extract', f'penalty_return_{season}.parquet')
    pq.write_table(table, out_path, compression='zstd')
    os.remove(raw)
    return dict(season=season, url=BASE.format(season=season), status='staged', raw_bytes=size, raw_sha256=digest,
                rows=table.num_rows, columns_kept=present, columns_missing=missing,
                extract=os.path.relpath(out_path, OUT_DIR), extract_sha256=sha256(out_path))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--seasons', nargs='+', type=int, default=list(SEASONS))
    args = ap.parse_args()
    os.makedirs(OUT_DIR, exist_ok=True)
    manifest_path = os.path.join(OUT_DIR, 'manifest.json')
    previous = {}
    if os.path.exists(manifest_path):
        previous = {r['season']: r for r in json.load(open(manifest_path))['files']}
    for season in args.seasons:
        previous[season] = stage(season)
        print(season, previous[season]['status'], previous[season].get('rows', ''), flush=True)
    manifest = dict(source='https://github.com/nflverse/nflverse-data/releases/tag/pbp',
                    staged_utc=datetime.datetime.utcnow().isoformat(timespec='seconds') + 'Z',
                    licence_basis=('User finding 2026-10-27: nflverse release terms permit this research use; FTN-derived '
                                   'content CC BY-SA 4.0. Not verified against the repo README, which has no licence text.'),
                    attribution=ATTRIBUTION, research_only=True, production_ingest=False,
                    files=[previous[s] for s in sorted(previous)])
    with open(manifest_path, 'w') as handle:
        json.dump(manifest, handle, indent=1)
    print('manifest', manifest_path)


if __name__ == '__main__':
    main()
