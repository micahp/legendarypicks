#!/usr/bin/env python3
"""One index of every 2026 regular-season game and every pregame snapshot it has. Read-only over the snapshot folders.

Snapshot sets read:
  cutoff    docs/research/cutoff-snapshots-2026/week-NN/<game_id>.json   (90-minute cutoff job on the fast host; copied here)
  model     docs/research/model-snapshots-2026/week-NN/<game_id>.json    (cutoff capture in the model format;
            cutoff_to_model_snapshot.py)
  walkforward docs/research/walkforward-2026/snapshots/wNN/<game_id>.json (model format, weeks 1-10 walk-forward build)
Each game's RUN ON column names the one model-format snapshot to run: model first, else walkforward, never a stale one.
A snapshot is STALE when a team's depth chart is more than 24 hours older than the snapshot cutoff
(pregame_snapshot.MAX_DEPTH_CHART_AGE). A game whose cutoff has passed is MISSING when it has no model-format snapshot that is not stale.

Writes docs/research/SNAPSHOT-INDEX-2026.md and .json. Exits 1 when any game is MISSING, so it cannot pass quietly.

Usage: python3 scripts/nfl_sequence/snapshot_index.py --games-csv games.csv [--now 2026-11-22T22:00:00Z]
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[2]
CUTOFF_DIR = ROOT / 'docs' / 'research' / 'cutoff-snapshots-2026'
MODEL_DIR = ROOT / 'docs' / 'research' / 'model-snapshots-2026'
WALKFORWARD_DIR = ROOT / 'docs' / 'research' / 'walkforward-2026' / 'snapshots'
OUT = ROOT / 'docs' / 'research' / 'SNAPSHOT-INDEX-2026'
MAX_AGE = timedelta(hours=24)
CUTOFF_BEFORE_KICKOFF = timedelta(minutes=90)


def utc(text):
    return datetime.fromisoformat(text.replace('Z', '+00:00'))


def kickoff(gameday, gametime):
    return datetime.fromisoformat(f'{gameday} {gametime}:00').replace(tzinfo=ZoneInfo('America/New_York')).astimezone(timezone.utc)


def cutoff_entry(path):
    d = json.loads(path.read_text())
    cut = utc(d['cutoff_utc'])
    versions = d['fields']['depth_chart_version']['value']
    age = max((cut - utc(v)).total_seconds() / 3600 for v in versions.values())
    labels = sorted({f['label'] for f in d['fields'].values()})
    return {'set': 'cutoff', 'path': str(path.relative_to(ROOT)), 'cutoff_utc': d['cutoff_utc'],
            'depth_age_hours': round(age, 1), 'stale': age > MAX_AGE.total_seconds() / 3600,
            'backfilled': 'backfilled' in d, 'labels': labels}


def model_entry(path, kind='model'):
    d = json.loads(path.read_text())
    d = d.get('pregame_snapshot', d)
    cut = utc(d['as_of'])
    age = max((cut - utc(d['rosters'][s]['snapshot_at'])).total_seconds() / 3600 for s in ('away', 'home'))
    return {'set': kind, 'path': str(path.relative_to(ROOT)), 'cutoff_utc': d['as_of'],
            'depth_age_hours': round(age, 1), 'stale': age > MAX_AGE.total_seconds() / 3600}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--games-csv', required=True, help='nflverse nfldata games.csv')
    ap.add_argument('--season', type=int, default=2026)
    ap.add_argument('--now', help='UTC time to judge which cutoffs have passed; default now')
    args = ap.parse_args(argv)
    now = utc(args.now) if args.now else datetime.now(timezone.utc)

    found = {}
    for path in sorted(CUTOFF_DIR.glob('week-*/*.json')):
        found.setdefault(path.stem, []).append(cutoff_entry(path))
    for path in sorted(MODEL_DIR.glob('week-*/*.json')):
        if path.name.endswith('.streak.json'):
            continue
        found.setdefault(path.stem, []).append(model_entry(path))
    for path in sorted(WALKFORWARD_DIR.glob('w*/*.json')):
        found.setdefault(path.stem, []).append(model_entry(path, 'walkforward'))

    games = []
    with open(args.games_csv, newline='') as handle:
        for r in csv.DictReader(handle):
            if r['season'] == str(args.season) and r['game_type'] == 'REG':
                kick = kickoff(r['gameday'], r['gametime'])
                games.append({'game_id': r['game_id'], 'week': int(r['week']), 'kickoff_utc': kick.strftime('%Y-%m-%dT%H:%MZ'),
                              'cutoff_passed': now >= kick - CUTOFF_BEFORE_KICKOFF})
    rows, missing = [], []
    for g in sorted(games, key=lambda g: (g['week'], g['kickoff_utc'], g['game_id'])):
        entries = found.pop(g['game_id'], [])
        usable = [e for kind in ('model', 'walkforward') for e in entries if e['set'] == kind and not e['stale']]
        run_on = usable[0]['path'] if usable else None
        if not g['cutoff_passed']:
            status = 'UPCOMING'
        elif usable:
            status = 'OK'
        else:
            status = 'MISSING'
            missing.append(g['game_id'])
        rows.append(dict(g, status=status, run_on=run_on, snapshots=entries))
    unknown = sorted(found)

    OUT.with_suffix('.json').write_text(json.dumps(
        {'generated_utc': now.strftime('%Y-%m-%dT%H:%M:%SZ'), 'max_depth_age_hours': 24, 'games': rows,
         'missing': missing, 'snapshots_for_games_not_in_schedule': unknown}, indent=1) + '\n')

    def cell(entries, kind):
        e = [x for x in entries if x['set'] == kind]
        if not e:
            return '-'
        x = e[0]
        tag = 'STALE ' if x['stale'] else ''
        extra = ' backfilled' if x.get('backfilled') else ''
        return f"{tag}[{x['depth_age_hours']}h{extra}]({Path(x['path']).relative_to('docs/research')})"

    counts = {s: sum(r['status'] == s for r in rows) for s in ('OK', 'MISSING', 'UPCOMING')}
    lines = ['# 2026 pregame snapshot index', '',
             f"Generated {now:%Y-%m-%d %H:%M} UTC by `scripts/nfl_sequence/snapshot_index.py`. Do not edit by hand.", '',
             f"Games: {counts['OK']} OK, {counts['MISSING']} MISSING, {counts['UPCOMING']} upcoming.", '',
             '- **cutoff**: the 90-minute cutoff job (`/root/cutoff-captures` on the fast host), copied to '
             '`cutoff-snapshots-2026/`. Backfilled ones were built after the game: their depth chart is the capture '
             'before the cutoff, but injury and roster data are `FETCHED_AFTER_CUTOFF`.',
             '- **RUN ON**: the model-format snapshot to run on for that game. Use this one.',
             '- **model**: `model-snapshots-2026/`, the cutoff snapshot turned into the model format by '
             '`cutoff_to_model_snapshot.py`, with RotoWire injuries published before the cutoff (weeks 9 on).',
             '- **walkforward**: `walkforward-2026/snapshots/`, the walk-forward build in the model format (weeks 1-10).',
             '- The number is the depth chart age at the cutoff. STALE means over 24 hours: do not run on it.', '',
             '| week | game | kickoff (UTC) | status | RUN ON | cutoff | model | walkforward |', '|---|---|---|---|---|---|---|---|']
    for r in rows:
        run_on = f"[{Path(r['run_on']).relative_to('docs/research')}]({Path(r['run_on']).relative_to('docs/research')})" if r['run_on'] else '-'
        lines.append(f"| {r['week']} | {r['game_id']} | {r['kickoff_utc']} | {r['status']} | {run_on} | "
                     f"{cell(r['snapshots'], 'cutoff')} | {cell(r['snapshots'], 'model')} | {cell(r['snapshots'], 'walkforward')} |")
    if unknown:
        lines += ['', 'Snapshots for game ids not in the schedule: ' + ', '.join(unknown)]
    OUT.with_suffix('.md').write_text('\n'.join(lines) + '\n')
    print(f"{counts['OK']} OK, {counts['MISSING']} MISSING, {counts['UPCOMING']} upcoming; "
          f"{len(unknown)} snapshots for unknown game ids; wrote {OUT}.md and .json")
    if missing:
        print('MISSING: ' + ', '.join(missing))
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
