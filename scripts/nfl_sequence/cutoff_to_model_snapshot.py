#!/usr/bin/env python3
"""Turn 90-minute cutoff captures into the pregame snapshot format the models read. Read-only over --db.

For each docs/research/cutoff-snapshots-2026/week-NN/<game_id>.json, pregame_snapshot.build runs with:
  - as_of = the capture's cutoff (kickoff minus 90 minutes)
  - depth chart = the capture's own depth chart version (the nflverse capture at or before the cutoff)
  - schedule = the database schedule version in force at the cutoff, else the newest dated nflverse archive before it
    (--archive-schedule, exported from /root/lp-snapshots/nflverse-archives-2026 on the fast host)
  - injuries = RotoWire news published before the cutoff (oracle.rotowire_injury_report), so they are pregame
  - win-loss streaks = results available by the cutoff (oracle.build_streaks), frozen with slc_pregame_context the way
    the portable pack runner checks them
The output is the file the pack runner reads: {"pregame_snapshot": ..., "runtime_model_inputs": ...}, plus the streak
source file it hashes, beside it as <game_id>.streak.json.
The 24-hour depth chart rule in pregame_snapshot.build applies. roster_preflight then resolves each team's playable roster
(Out and inactive players excluded, the next eligible player promoted) and writes it into the snapshot as
roster_resolution; any preflight FAIL refuses the game. A game status from a team's previous game is not used. Writes docs/research/model-snapshots-2026/week-NN/<game_id>.json
and never overwrites one. Prints every refusal.

Usage: python3 scripts/nfl_sequence/cutoff_to_model_snapshot.py --db picks.dev.db --archive-schedule archive_schedule_2026.json
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'backend'), str(ROOT / 'scripts' / 'nfl_sequence'), str(ROOT)]
import oracle  # noqa: E402
import pregame_snapshot  # noqa: E402
import roster_preflight  # noqa: E402
import slc_pregame_context  # noqa: E402
from scripts import nfl_team_codes  # noqa: E402

CUTOFF_DIR = ROOT / 'docs' / 'research' / 'cutoff-snapshots-2026'
OUT_DIR = ROOT / 'docs' / 'research' / 'model-snapshots-2026'
KICKOFF_SOURCE = 'https://github.com/nflverse/nfldata/raw/master/data/games.csv (gameday and gametime, US Eastern)'


def utc(text):
    return datetime.fromisoformat(text.replace('Z', '+00:00'))


class StreakBuckets:
    """The two names slc_pregame_context reads from the packs' streak_splits module, with the same rule: a streak of
    5 or more is W5+ or L5+, none is NONE."""
    BUCKETS = ('L5+', 'L4', 'L3', 'L2', 'L1', 'NONE', 'W1', 'W2', 'W3', 'W4', 'W5+')

    @staticmethod
    def bucket_from_text(text):
        if not text:
            return 'NONE'
        count = int(text[1:])
        side = text[0]
        return f'{side}5+' if count >= 5 else f'{side}{count}'


def depth_from_capture(capture):
    """{team: {version datetime: [row]}} with each team under its database and nflverse codes."""
    out = {}
    for team, version in capture['fields']['depth_chart_version']['value'].items():
        rows = [{'gsis_id': p['gsis_id'], 'player_name': p['player_name'], 'pos_abb': p['pos_abb'],
                 'pos_rank': int(p['pos_rank'])}
                for p in capture['players'] if p['team'] == team and p['gsis_id'] and p['pos_rank'] is not None]
        for code in {team, nfl_team_codes.to_db(team), nfl_team_codes.to_nflverse(team)}:
            out[code] = {utc(version): rows}
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--db', required=True)
    ap.add_argument('--archive-schedule', required=True, type=Path)
    ap.add_argument('--games', nargs='*')
    args = ap.parse_args(argv)
    archive = {g: [(utc(at), row) for at, row in obs] for g, obs in json.loads(args.archive_schedule.read_text()).items()}
    built, skipped, refused = 0, 0, []
    for path in sorted(CUTOFF_DIR.glob('week-*/*.json')):
        game_id = path.stem
        if args.games and game_id not in args.games:
            continue
        out = OUT_DIR / path.parent.name / path.name
        if out.exists():
            existing = json.loads(out.read_text())
            if 'pregame_snapshot' in existing:
                skipped += 1
                continue
            out.unlink()  # an earlier run of this script wrote the bare snapshot; rebuild it in the runner's format
        if out.with_suffix('.streak.json').exists():
            skipped += 1
            continue
        capture = json.loads(path.read_text())
        cutoff = utc(capture['cutoff_utc'])
        try:
            injury, _ = oracle.rotowire_injury_report(args.db, cutoff)
            snap = pregame_snapshot.build(args.db, game_id, capture['cutoff_utc'],
                                          kickoff_utc=utc(capture['kickoff_utc']).strftime('%Y-%m-%dT%H:%M:%SZ'),
                                          kickoff_source_url=KICKOFF_SOURCE, archive_schedule=archive,
                                          archive_depth=depth_from_capture(capture), injury_report=injury)
            streaks, _used = oracle.build_streaks(args.db, cutoff, game_id)
        except ValueError as exc:
            refused.append(f'{game_id}: {exc}')
            continue
        rows, resolved = roster_preflight.check(snap)
        bad = roster_preflight.failed(rows)
        if bad:
            refused.extend(f'{game_id}: {name}: {detail}' for name, _, detail in bad)
            continue
        snap['roster_resolution'] = resolved
        snap['cutoff_capture'] = {'path': str(path.relative_to(ROOT)), 'fetched_at_utc': capture['fetched_at_utc'],
                                  'backfilled': 'backfilled' in capture}
        out.parent.mkdir(parents=True, exist_ok=True)
        streak_path = out.with_suffix('.streak.json')
        with streak_path.open('x') as handle:
            json.dump(streaks, handle, indent=1, sort_keys=True)
        slc_pregame_context.freeze_current_streak_context(streak_path, snap, StreakBuckets, nfl_team_codes)
        snap = pregame_snapshot.reseal(snap)
        inputs = slc_pregame_context.freeze_current_streak_model_inputs(streak_path, snap, StreakBuckets, nfl_team_codes)
        with out.open('x') as handle:
            json.dump({'pregame_snapshot': snap, 'runtime_model_inputs': inputs}, handle, indent=1, sort_keys=True)
            handle.write('\n')
        loaded = pregame_snapshot.load_frozen_snapshot(str(out))
        slc_pregame_context.current_streaks_for_snapshot(loaded, nfl_team_codes, StreakBuckets, inputs)
        built += 1
    for line in refused:
        print('REFUSED', line)
    print(f'built {built}, already there {skipped}, refused {len(refused)}')
    return 1 if refused else 0


if __name__ == '__main__':
    raise SystemExit(main())
