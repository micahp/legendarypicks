"""Download every parquet asset of every nflverse-data release, raw and pinned. Research only, no ingest.

Source: the GitHub releases of https://github.com/nflverse/nflverse-data (the list is fetched live and saved).
Format: parquet only. The csv, rds, qs and zip copies hold the same data and are not downloaded here.
Each file is written under RAW_DIR/<tag>/<name>, checked against the size GitHub reports, hashed (sha256), and recorded
in MANIFEST. The run is resumable: a file already on disk with the reported size and a manifest row is not fetched again.

Licence and attribution: see the manifest's licence_basis (the user's finding, 2026-10-27). FTN data is CC BY-SA 4.0.

Usage: python3 download_nflverse_raw.py [--tags pbp schedules ...]
"""
import argparse
import datetime
import hashlib
import json
import os
import time
import urllib.request

API = 'https://api.github.com/repos/nflverse/nflverse-data/releases?per_page=100'
ROOT = '/root/lp-snapshots/nfl-backfill-2026-10-27'
RAW_DIR = os.path.join(ROOT, 'raw')
MANIFEST = os.path.join(ROOT, 'raw_manifest.json')
LICENCE = ('User finding 2026-10-27: nflverse release terms permit this research use; FTN-derived content CC BY-SA 4.0 '
           'with attribution via nflverse. The repo README has no licence text, so the terms are recorded as the user '
           'stated them. Research use only, no redistribution, no production ingest.')
ATTRIBUTION = ('Data from the nflverse project (nflverse-data releases). Please credit nflverse. FTN charting data is '
               'CC BY-SA 4.0 and needs FTN Data credited through nflverse.')
RETRIES = 3


def fetch_json(url):
    req = urllib.request.Request(url, headers={'User-Agent': 'lp-research-download', 'Accept': 'application/json'})
    with urllib.request.urlopen(req, timeout=120) as resp:
        return json.loads(resp.read().decode('utf-8'))


def download(url, path, expected_size):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + '.part'
    last = None
    for attempt in range(1, RETRIES + 1):
        try:
            req = urllib.request.Request(url, headers={'User-Agent': 'lp-research-download'})
            with urllib.request.urlopen(req, timeout=600) as resp, open(tmp, 'wb') as out:
                while True:
                    chunk = resp.read(1 << 20)
                    if not chunk:
                        break
                    out.write(chunk)
            if os.path.getsize(tmp) != expected_size:
                raise IOError(f'size {os.path.getsize(tmp)} != {expected_size}')
            os.replace(tmp, path)
            return None
        except Exception as exc:  # recorded, retried, then reported
            last = str(exc)
            time.sleep(5 * attempt)
    if os.path.exists(tmp):
        os.remove(tmp)
    return last


def sha256(path):
    digest = hashlib.sha256()
    with open(path, 'rb') as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b''):
            digest.update(chunk)
    return digest.hexdigest()


def load_manifest():
    if os.path.exists(MANIFEST):
        return json.load(open(MANIFEST))
    return dict(licence_basis=LICENCE, attribution=ATTRIBUTION, research_only=True, production_ingest=False,
                source='https://github.com/nflverse/nflverse-data/releases', files=[])


def save_manifest(man):
    man['updated_utc'] = datetime.datetime.utcnow().isoformat(timespec='seconds') + 'Z'
    tmp = MANIFEST + '.tmp'
    with open(tmp, 'w') as handle:
        json.dump(man, handle, indent=1)
    os.replace(tmp, MANIFEST)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--tags', nargs='*', default=None, help='release tags to fetch (default: every release)')
    args = ap.parse_args()
    os.makedirs(RAW_DIR, exist_ok=True)
    releases = fetch_json(API)
    with open(os.path.join(RAW_DIR, 'releases.json'), 'w') as handle:
        json.dump(releases, handle)
    man = load_manifest()
    done = {(f['tag'], f['name']): f for f in man['files'] if f.get('status') == 'ok'}
    failures = []
    total = fetched = skipped = 0
    for rel in releases:
        tag = rel['tag_name']
        if args.tags and tag not in args.tags:
            continue
        for asset in rel.get('assets', []):
            name = asset['name']
            if not name.endswith('.parquet'):
                continue
            total += 1
            path = os.path.join(RAW_DIR, tag, name)
            key = (tag, name)
            if key in done and os.path.exists(path) and os.path.getsize(path) == asset['size']:
                skipped += 1
                continue
            err = download(asset['browser_download_url'], path, asset['size'])
            if err:
                failures.append((tag, name, err))
                man['files'] = [f for f in man['files'] if (f['tag'], f['name']) != key]
                man['files'].append(dict(tag=tag, name=name, status='failed', error=err))
            else:
                digest = sha256(path)
                row = dict(tag=tag, name=name, status='ok', url=asset['browser_download_url'], bytes=asset['size'],
                           sha256=digest, asset_updated_at=asset.get('updated_at'), release_published_at=rel.get('published_at'),
                           path=os.path.relpath(path, ROOT), downloaded_utc=datetime.datetime.utcnow().isoformat(timespec='seconds') + 'Z')
                man['files'] = [f for f in man['files'] if (f['tag'], f['name']) != key]
                man['files'].append(row)
                fetched += 1
            save_manifest(man)
            print(f"{tag:20s} {name:45s} {'ok' if not err else 'FAILED'}", flush=True)
    print(f"parquet assets {total}: fetched {fetched}, already present {skipped}, failed {len(failures)}", flush=True)
    for f in failures:
        print('FAILED', f, flush=True)


if __name__ == '__main__':
    main()
