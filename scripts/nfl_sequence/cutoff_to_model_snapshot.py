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
(membership from --weekly-roster, Out and inactive players excluded, the next eligible player promoted) and writes it into the snapshot as
roster_resolution; any preflight FAIL refuses the game. A game status from a team's previous game is not used. Writes docs/research/model-snapshots-2026/week-NN/<game_id>.json
and never overwrites one. Prints every refusal.

Usage: python3 scripts/nfl_sequence/cutoff_to_model_snapshot.py --db picks.dev.db --archive-schedule archive_schedule_2026.json
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'backend'), str(ROOT / 'scripts' / 'nfl_sequence'), str(ROOT)]
import oracle  # noqa: E402
import pregame_snapshot  # noqa: E402
import roster_preflight  # noqa: E402
from prop_identity import resolve_market_qbs, priced_qbs, validated_priced_qbs  # noqa: E402
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


BUILD_RUNTIME_READINESS = {'status': 'not_evaluated', 'required': 'model_specific_preflight_and_smoke'}


def write_runner_file(snap, streaks, out):
    """Write the pack runner's input: {pregame_snapshot, runtime_model_inputs} at `out`, and the streak source it hashes
    at <out stem>.streak.json. Refuses to overwrite either. Reloads and checks the file it wrote."""
    out.parent.mkdir(parents=True, exist_ok=True)
    streak_path = out.with_suffix('.streak.json')
    with streak_path.open('x') as handle:
        json.dump(streaks, handle, indent=1, sort_keys=True)
    slc_pregame_context.freeze_current_streak_context(streak_path, snap, StreakBuckets, nfl_team_codes)
    snap = pregame_snapshot.reseal(snap)
    inputs = slc_pregame_context.freeze_current_streak_model_inputs(streak_path, snap, StreakBuckets, nfl_team_codes)
    with out.open('x') as handle:
        json.dump({'pregame_snapshot': snap, 'runtime_model_inputs': inputs,
                   'runtime_readiness': BUILD_RUNTIME_READINESS}, handle, indent=1, sort_keys=True)
        handle.write('\n')
    loaded = pregame_snapshot.load_frozen_snapshot(str(out))
    slc_pregame_context.current_streaks_for_snapshot(loaded, nfl_team_codes, StreakBuckets, inputs)
    return loaded


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


def validate_capture(capture, game_id):
    if capture.get('game_id') != game_id:
        raise ValueError('CUTOFF_CAPTURE_GAME_ID_MISMATCH')
    cutoff, kickoff = (utc(capture[k]) for k in ('cutoff_utc', 'kickoff_utc'))
    if cutoff.tzinfo is None or kickoff.tzinfo is None or kickoff - cutoff != timedelta(minutes=90):
        raise ValueError('CUTOFF_CAPTURE_NOT_T90')
    away, home = nfl_team_codes.teams_from_game_id(game_id)
    if (nfl_team_codes.to_db(capture['away']), nfl_team_codes.to_db(capture['home'])) != (away, home):
        raise ValueError('CUTOFF_CAPTURE_TEAM_MISMATCH')
    fetched = utc(capture['fetched_at_utc'])
    if fetched.tzinfo is None:
        raise ValueError('CUTOFF_CAPTURE_FETCH_TIME_UNVERIFIED')
    return cutoff


def validate_existing(out, capture, provenance, game_id):
    snap = pregame_snapshot.load_frozen_snapshot(str(out))
    payload = json.loads(out.read_text())
    if 'pregame_snapshot' not in payload or not isinstance(payload.get('runtime_model_inputs'), dict):
        raise ValueError('EXISTING_SNAPSHOT_NOT_RUNNER_FORMAT')
    if payload.get('runtime_readiness', BUILD_RUNTIME_READINESS) != BUILD_RUNTIME_READINESS:
        raise ValueError('EXISTING_SNAPSHOT_UNSUPPORTED_READINESS_CLAIM')
    schedule = snap['schedule']
    if (schedule['game_id'] != game_id or utc(snap['as_of']) != utc(capture['cutoff_utc'])
            or utc(schedule['scheduled_kickoff_utc']) != utc(capture['kickoff_utc'])):
        raise ValueError('EXISTING_SNAPSHOT_CUTOFF_OR_IDENTITY_MISMATCH')
    if snap.get('cutoff_capture') != provenance:
        raise ValueError('EXISTING_SNAPSHOT_PROVENANCE_MISMATCH')
    if not snap.get('roster_resolution'):
        raise ValueError('EXISTING_SNAPSHOT_ROSTER_RESOLUTION_MISSING')
    rows, resolved = roster_preflight.check(snap, validated_priced_qbs(snap))
    if snap['roster_resolution'].get('content_hash') != resolved['content_hash']:
        raise ValueError('EXISTING_SNAPSHOT_ROSTER_RESOLUTION_MISMATCH')
    if roster_preflight.failed(rows + [roster_preflight.exclusions_applied(snap, resolved)]):
        raise ValueError('EXISTING_SNAPSHOT_ROSTER_PREFLIGHT_FAILED')
    expected = slc_pregame_context.freeze_current_streak_model_inputs(
        out.with_suffix('.streak.json'), snap, StreakBuckets, nfl_team_codes)
    if payload['runtime_model_inputs'] != expected:
        raise ValueError('EXISTING_SNAPSHOT_RUNTIME_INPUT_MISMATCH')
    slc_pregame_context.current_streaks_for_snapshot(snap, nfl_team_codes, StreakBuckets, expected)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--db', required=True)
    ap.add_argument('--props-db', help='separate prop database, defaults to --db')
    ap.add_argument('--archive-schedule', required=True, type=Path)
    ap.add_argument('--weekly-roster', required=True, type=Path,
                    help='nflverse roster_weekly_<season>.parquet: membership for the preflight (no publish time; record when fetched)')
    ap.add_argument('--games', nargs='*')
    args = ap.parse_args(argv)
    import pandas as pd
    weekly_roster = pd.read_parquet(args.weekly_roster).to_dict('records')
    roster_source = f'{args.weekly_roster.name} sha256 {hashlib.sha256(args.weekly_roster.read_bytes()).hexdigest()}'
    archive_bytes = args.archive_schedule.read_bytes()
    archive_sha = hashlib.sha256(archive_bytes).hexdigest()
    archive = {g: [(utc(at), row) for at, row in obs] for g, obs in json.loads(archive_bytes).items()}
    built, skipped, refused = 0, 0, []
    for path in sorted(CUTOFF_DIR.glob('week-*/*.json')):
        game_id = path.stem
        if args.games and game_id not in args.games:
            continue
        out = OUT_DIR / path.parent.name / path.name
        try:
            raw = path.read_bytes()
            capture = json.loads(raw)
            cutoff = validate_capture(capture, game_id)
            provenance = {'path': str(path.relative_to(ROOT)), 'sha256': hashlib.sha256(raw).hexdigest(),
                          'fetched_at_utc': capture['fetched_at_utc'], 'backfilled': 'backfilled' in capture,
                          'weekly_roster_source': roster_source, 'archive_schedule_sha256': archive_sha}
            if out.exists():
                validate_existing(out, capture, provenance, game_id)
                skipped += 1
                continue
            if out.with_suffix('.streak.json').exists():
                raise ValueError('ORPHAN_STREAK_FILE: preserve and inspect before rebuilding')
            injury, _ = oracle.rotowire_injury_report(args.db, cutoff)
            snap = pregame_snapshot.build(args.db, game_id, capture['cutoff_utc'],
                                          kickoff_utc=utc(capture['kickoff_utc']).strftime('%Y-%m-%dT%H:%M:%SZ'),
                                          kickoff_source_url=KICKOFF_SOURCE, archive_schedule=archive,
                                          archive_depth=depth_from_capture(capture), injury_report=injury)
            streaks, _used = oracle.build_streaks(args.db, cutoff, game_id)
        except (ValueError, KeyError, TypeError, OSError) as exc:
            refused.append(f'{game_id}: {exc}')
            continue
        try:
            roster_preflight.attach_membership(snap, weekly_roster, roster_source)
        except ValueError as exc:
            refused.append(f'{game_id}: {exc}')
            continue
        try:
            schedule_row = snap['schedule']
            observed = [row for at, row in archive.get(game_id, []) if at <= cutoff]
            event_id = schedule_row.get('espn') or (observed[-1].get('espn') if observed else None)
            evidence = resolve_market_qbs(args.props_db or args.db, game_id, schedule_row['gameday'], event_id, cutoff)
            snap['market_qb_evidence'] = evidence
        except (ValueError, KeyError) as exc:
            refused.append(f'{game_id}: {exc}')
            continue
        rows, resolved = roster_preflight.check(snap, priced_qbs(evidence))
        bad = roster_preflight.failed(rows)
        if bad:
            refused.extend(f'{game_id}: {name}: {detail}' for name, _, detail in bad)
            continue
        try:
            snap = oracle.finalize_model_snapshot(snap, priced_qbs(evidence))
        except ValueError as exc:
            refused.append(f'{game_id}: {exc}')
            continue
        snap['cutoff_capture'] = provenance
        write_runner_file(snap, streaks, out)
        built += 1
    for line in refused:
        print('REFUSED', line)
    print(f'built {built}, already there {skipped}, refused {len(refused)}; model readiness NOT_EVALUATED')
    return 1 if refused else 0


if __name__ == '__main__':
    raise SystemExit(main())
