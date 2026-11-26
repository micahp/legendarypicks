#!/usr/bin/env python3
"""Print the full roster of each team in each pregame snapshot as plain text. Read-only.

Reads snapshot files in either format (a bare pregame snapshot, or the runner's {"pregame_snapshot": ...}). For each game:
the kickoff, the cutoff, and per team the depth chart capture time, then every player by position and depth rank with
the injury status known at the cutoff. Offense first, then defense, then special teams.

Usage: python3 scripts/nfl_sequence/print_snapshot_rosters.py SNAPSHOT_OR_DIR [...] [--out FILE]
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

ORDER = ['QB', 'RB', 'FB', 'WR', 'TE', 'LT', 'LG', 'C', 'RG', 'RT',
         'LDE', 'DE', 'DT', 'NT', 'RDE', 'LOLB', 'SLB', 'LILB', 'MLB', 'MIKE', 'RILB', 'WLB', 'ROLB', 'LB',
         'LCB', 'RCB', 'CB', 'NB', 'SS', 'FS', 'S', 'PK', 'K', 'P', 'H', 'LS', 'KR', 'PR']


def snapshots(paths):
    for p in paths:
        p = Path(p)
        files = sorted(f for f in p.glob('*.json') if not f.name.endswith('.streak.json') and f.name != 'manifest.json') \
            if p.is_dir() else [p]
        for f in files:
            data = json.loads(f.read_text())
            snap = data.get('pregame_snapshot', data)
            if 'rosters' in snap:
                yield f, snap


def render(path, snap):
    sched = snap['schedule']
    lines = [f"{sched['game_id']}  {sched['away_team']} at {sched['home_team']}",
             f"kickoff {sched.get('scheduled_kickoff_utc', sched.get('gameday'))}  cutoff {snap['as_of']}  file {path.name}"]
    for side in ('away', 'home'):
        roster = snap['rosters'][side]
        status = {p['gsis_id']: p['report_status'] for p in (roster.get('injury_report') or {}).get('players', [])}
        players = sorted(roster['players'], key=lambda p: (ORDER.index(p['pos_abb']) if p['pos_abb'] in ORDER else len(ORDER),
                                                            p['pos_abb'], p['pos_rank']))
        lines += ['', f"  {roster['team']} ({side})  depth chart {roster['snapshot_at']}  {len(players)} rows"]
        for p in players:
            note = f"  [{status[p['gsis_id']]}]" if p['gsis_id'] in status else ''
            lines.append(f"    {p['pos_abb']:<5} {p['pos_rank']:>2}  {p['player_name']:<28} {p['gsis_id']}{note}")
    return '\n'.join(lines)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('paths', nargs='+')
    ap.add_argument('--out')
    args = ap.parse_args(argv)
    found = sorted(snapshots(args.paths), key=lambda item: (item[1]['schedule'].get('scheduled_kickoff_utc', ''),
                                                            item[1]['schedule']['game_id']))
    if not found:
        raise SystemExit('no pregame snapshots found in ' + ', '.join(args.paths))
    text = ('\n\n' + '=' * 100 + '\n\n').join(render(f, s) for f, s in found) + '\n'
    if args.out:
        Path(args.out).write_text(text)
        print(f'wrote {len(found)} games to {args.out}')
    else:
        print(text, end='')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
