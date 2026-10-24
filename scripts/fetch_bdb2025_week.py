#!/usr/bin/env python3
"""Stage one week of the 2025 Big Data Bowl data from a GitHub copy, verified against Git LFS pointers.

The competition data was removed from Kaggle. This copy is third-party and unofficial. The repository is Apache-2.0,
which covers its code, not the competition data; permitted use is user-reported and not verified here.
Pinned to commit e28d3b25725799ef2213680016db5325f6f90014. Files go outside git, under /root/nfl-tracking-data/bdb2025/.

Usage: python3 scripts/fetch_bdb2025_week.py tracking_week_1.csv games.csv plays.csv player_play.csv players.csv
"""
import hashlib
import json
import os
import sys
import urllib.request

REPO = 'b00nk3r/NFL-Big-Data-Bowl-2025'
COMMIT = 'e28d3b25725799ef2213680016db5325f6f90014'
OUT = '/root/nfl-tracking-data/bdb2025/code-data'


def pointer(name):
    url = f'https://raw.githubusercontent.com/{REPO}/{COMMIT}/code/data/{name}'
    fields = dict(line.split(' ', 1) for line in urllib.request.urlopen(url, timeout=60).read().decode().strip().splitlines())
    return fields['oid'].split(':', 1)[1], int(fields['size'])


def lfs_href(oid, size):
    body = json.dumps({'operation': 'download', 'transfers': ['basic'], 'objects': [{'oid': oid, 'size': size}]}).encode()
    req = urllib.request.Request(f'https://github.com/{REPO}.git/info/lfs/objects/batch', data=body,
                                 headers={'Accept': 'application/vnd.git-lfs+json', 'Content-Type': 'application/vnd.git-lfs+json'})
    obj = json.load(urllib.request.urlopen(req, timeout=60))['objects'][0]
    if 'error' in obj:
        sys.exit(f'LFS error for {oid}: {obj["error"]}')
    return obj['actions']['download']['href']


def fetch(name):
    oid, size = pointer(name)
    dest = os.path.join(OUT, name)
    os.makedirs(OUT, exist_ok=True)
    h, got = hashlib.sha256(), 0
    with urllib.request.urlopen(lfs_href(oid, size), timeout=600) as r, open(dest + '.part', 'wb') as f:
        while chunk := r.read(1 << 22):
            f.write(chunk)
            h.update(chunk)
            got += len(chunk)
    if h.hexdigest() != oid or got != size:
        os.remove(dest + '.part')
        sys.exit(f'{name}: MISMATCH (got {got} bytes, sha256 {h.hexdigest()}, expected {size} bytes, {oid})')
    os.replace(dest + '.part', dest)
    print(name, 'verified', got, 'bytes')


if __name__ == '__main__':
    for name in sys.argv[1:]:
        fetch(name)
