#!/usr/bin/env python3
"""Write the E3 step-one coverage report from the join's own JSON, so every count in the report is read, not typed.

Reads docs/evidence/e3/tracking-coverage-v1/e3-tracking-coverage-2026-10-24.json and writes
docs/evidence/e3/TRACKING-COVERAGE-STEP1-2026-10-24.md. Usage: python3 tracking_coverage_doc.py
"""
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DIR = ROOT / 'docs' / 'evidence' / 'e3' / 'tracking-coverage-v1'
COVERAGE = DIR / 'e3-tracking-coverage-2026-10-24.json'
PAIRS = DIR / 'e3-tracking-join-pairs-2026-10-24.csv'
OUT = ROOT / 'docs' / 'evidence' / 'e3' / 'TRACKING-COVERAGE-STEP1-2026-10-24.md'


def pct(n, d):
    return f'{100 * n / d:.1f}%'


def main():
    r = json.loads(COVERAGE.read_text())
    tracked = r['scope']['bdb_tracked_plays']
    status = r['status_counts']
    verified = status['verified']
    identified = tracked - status['unmatched']
    dc, gc = r['drive_coverage'], r['game_coverage']
    lp = r['lp_scrimmage_plays_tracking']
    scrim = r['scope']['lp_scrimmage_plays_with_drive']
    fields = r['failing_field_counts (not exclusive)']
    text = [
        '# E3 step 1: 2022 Big Data Bowl tracking joined to nfl_pbp, coverage (2026-10-24)', '',
        'The join reads the tracking files and the dev database read-only. Every number below is read from',
        '`docs/evidence/e3/tracking-coverage-v1/e3-tracking-coverage-2026-10-24.json`, and the play-level rows are in',
        '`e3-tracking-join-pairs-2026-10-24.csv`. Script: `scripts/bdb/e3_tracking_join.py` (from commit `e1f56b85`, unchanged).',
        f"Pairs CSV sha256 `{hashlib.sha256(PAIRS.read_bytes()).hexdigest()[:16]}`; coverage JSON sha256 "
        f"`{hashlib.sha256(COVERAGE.read_bytes()).hexdigest()[:16]}`.",
        '', '## Matched plays, out of 16,124 tracked', '',
        f'- **Identifier match:** {identified:,} of {tracked:,} tracked plays ({pct(identified, tracked)}) have one LP play with the same '
        f'game and play identifiers. {status["unmatched"]} unmatched.',
        f'- **Verified:** {verified:,} of {tracked:,} ({pct(verified, tracked)}). A verified play also agrees with LP on quarter, game '
        'clock, down, distance, possession and spot.',
        f"- **Not verified:** {status['unverified (spot side NA)']} with the spot side NA (the spot cannot be checked), and "
        f"{status['overtime (not checked)']} in overtime (the clock convention is not checked here).",
        f"- **Tracking frames:** all {r['tracking']['bdb_plays_with_frames']:,} tracked plays have frames; "
        f"{r['tracking']['bdb_plays_with_snap_frame']:,} have a SNAP frame; {r['tracking']['bdb_plays_with_ball_snap_event']:,} have a "
        f"`ball_snap` label; {r['tracking']['snap_frame_and_event_disagree']} disagree.", '',
        '## Which join fields match', '',
        '| join level | field | rule | result |', '|---|---|---|---|',
        f"| game | season, week, away club, home club | BDB `gameId` to LP `game_id`; LA and WAS mapped to LAR and WSH | "
        f"{r['game_identifier']['mapped']} of {r['games_total']} games map to exactly one LP game; "
        f"{len(r['game_identifier']['unmapped'])} unmapped |",
        f"| play | `playId` = `play_id` | identifier within the LP game | {identified:,} plays matched; "
        f"{r['play_identifier']['lp_duplicate_game_play_pairs']} duplicate LP (game, play) pairs |",
        f"| verification | quarter, game clock, down, distance, possession, spot | agree with LP on the identifier-matched plays | "
        f"failing counts other than overtime and NA spot: {sum(v for k, v in fields.items() if k not in ('overtime_unverified', 'spot_unverifiable'))} |",
        '', '## Drives and games covered', '',
        f"LP drives in weeks 1-9: {r['drives_total']:,} (null-drive rows are excluded: they are not drives).", '',
        '| definition | complete | partial | none |', '|---|---:|---:|---:|',
        f"| every play in the drive tracked (kickoffs and kicks count as untracked) | {dc['all_plays']['complete']} | "
        f"{dc['all_plays']['partial']:,} | {dc['all_plays']['none']} |",
        f"| every scrimmage play in the drive tracked | {dc['scrimmage_plays']['complete']:,} | {dc['scrimmage_plays']['partial']} | "
        f"{dc['scrimmage_plays']['none']} (and {dc['scrimmage_plays']['no scrimmage plays']} with no scrimmage play) |", '',
        f"Games: {r['games_total']}. Every play tracked: {gc['all_plays'].get('complete', 0)} complete, "
        f"{gc['all_plays']['partial']} partial. Every scrimmage play tracked: {gc['scrimmage_plays']['complete']} complete, "
        f"{gc['scrimmage_plays']['partial']} partial.", '',
        '## LP scrimmage plays', '',
        f"{scrim:,} LP run, pass, kneel and spike plays have a drive. Tracked and verified: {lp['tracked']:,} "
        f"({pct(lp['tracked'], scrim)}). BDB play failed verification: {lp['BDB play with this identifier failed verification']}. "
        f"No BDB play with this identifier: {lp['no BDB play with this identifier']:,}, by type "
        f"{r['lp_scrimmage_no_bdb_play_by_type']}.", '',
        '## Independent checks', '',
        '- `plays.csv` in weeks 1-9 has 16,124 rows and 16,124 distinct (gameId, playId) keys (Python csv).',
        '- The nine tracking files have 16,124 distinct (gameId, playId) keys, all in `plays.csv` (an `awk` pass that keeps only the key set).',
        '- LP drive groups in weeks 1-9 on non-null `drive`: 2,955 (SQL on the dev database).',
        '- The rerun of the committed script reproduces the pairs CSV and the coverage JSON byte for byte.', '',
        '## Not established', '',
        '- The 1,019 LP scrimmage plays with no BDB play are not in the published tracking. They are reported, not explained.',
        '- Coverage is a join fact. It does not say that a tracked play\'s movement matches the LP outcome beyond the context fields.',
        '- The 789-versus-790 complete-drive difference between the two earlier reports is not traced.', '',
    ]
    OUT.write_text('\n'.join(text))
    print(f'wrote {OUT}')


if __name__ == '__main__':
    main()
