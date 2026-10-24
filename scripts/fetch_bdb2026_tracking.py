#!/usr/bin/env python3
"""Download the NFL Big Data Bowl 2026 prediction training files used by the Phase 0 check.

Requires KAGGLE_API_TOKEN in the environment (not stored in this repo). The account that owns the token must have
accepted the competition rules on kaggle.com, or every download returns HTTP 403.
Writes outside git: /root/nfl-tracking-data/bdb2026-prediction/train/.
"""
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

COMP = 'nfl-big-data-bowl-2026-prediction'
OUT = '/root/nfl-tracking-data/bdb2026-prediction/train'


def fetch(token, name):
    dest = os.path.join(OUT, name)
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    url = f'https://www.kaggle.com/api/v1/competitions/data/download/{COMP}/' + urllib.parse.quote(name, safe='')
    req = urllib.request.Request(url, headers={'Authorization': f'Bearer {token}'})
    try:
        with urllib.request.urlopen(req, timeout=300) as r, open(dest + '.part', 'wb') as f:
            while chunk := r.read(1 << 20):
                f.write(chunk)
    except urllib.error.HTTPError as e:
        sys.exit(f'{name}: HTTP {e.code}; accept the competition rules for this account first')
    os.replace(dest + '.part', dest)
    print(name, os.path.getsize(dest), 'bytes')


if __name__ == '__main__':
    token = os.environ.get('KAGGLE_API_TOKEN')
    if not token:
        sys.exit('set KAGGLE_API_TOKEN in the environment')
    for week in range(1, 8):
        fetch(token, f'input_2023_w{week:02d}.csv')
        fetch(token, f'output_2023_w{week:02d}.csv')
