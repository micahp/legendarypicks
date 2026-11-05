#!/usr/bin/env python3
"""Export the stored RotoWire payloads captured before a cutoff into a news capture directory.

The database's raw store (nfl_player_news_raw_polls, in legendarypicks) is the historical record. This writes each payload
that was acquired strictly before the cutoff into a capture directory, through news_evidence.capture, so the manifest and
file format are the ones news_evidence reads. Every stored payload is checked against its stored SHA-256 and byte count
before it is written, and a mismatch stops the export.

Nothing is chosen by hand: the directory holds every eligible poll, and news_evidence picks the latest version of each
update that was known at the cutoff.
"""
import argparse
import gzip
import hashlib
import sqlite3
import sys
from pathlib import Path

import news_evidence


def export(db_path, cutoff, out_dir):
    """Write every raw payload acquired strictly before the cutoff. Returns one dict per exported poll."""
    if (Path(out_dir) / 'manifest.json').exists():
        raise ValueError(f'{out_dir} already holds a capture manifest; export into an empty directory')
    con = sqlite3.connect(f'file:{db_path}?mode=ro', uri=True, timeout=30)
    try:
        rows = con.execute(
            """SELECT poll_id, polled_at_utc, source_url, payload_sha256, payload_bytes, payload_gzip
               FROM nfl_player_news_raw_polls ORDER BY polled_at_utc""").fetchall()
    finally:
        con.close()
    # Compare parsed times, not text: stored times end in +00:00 and the cutoff text ends in Z.
    rows = [row for row in rows if news_evidence._utc(row[1], f'poll {row[0]} polled_at') < cutoff]
    exported = []
    for poll_id, polled_at, url, digest, size, blob in rows:
        raw = gzip.decompress(blob)
        if hashlib.sha256(raw).hexdigest() != digest or len(raw) != size:
            raise ValueError(f'poll {poll_id}: stored payload does not match its stored hash and size')
        entry = news_evidence.capture(raw, out_dir, polled_at, url=url)
        exported.append({'poll_id': poll_id, 'name': entry['name'], 'sha256': entry['sha256'],
                         'acquired_at_utc': entry['acquired_at_utc'], 'updates': entry['updates']})
    return exported


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--db', required=True)
    ap.add_argument('--cutoff', required=True, help='UTC; payloads acquired at or after it are not exported')
    ap.add_argument('--out-dir', required=True)
    a = ap.parse_args(argv)
    cutoff = news_evidence._utc(a.cutoff, 'cutoff')
    exported = export(a.db, cutoff, a.out_dir)
    print(f'exported {len(exported)} stored payloads acquired before {a.cutoff} into {a.out_dir}')
    for item in exported:
        print(f"  poll {item['poll_id']} {item['acquired_at_utc']} {item['name']} sha256 {item['sha256'][:12]} "
              f"updates {item['updates']}")
    return 0


if __name__ == '__main__':
    sys.exit(main())
