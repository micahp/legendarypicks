"""Lock the SLC v1 Week 8 prospective forecasts and write the per-game readiness manifest (research, not adopted).

Reads each game's frozen snapshot and its batch output, computes the forecast summary, and writes one lock file and one manifest
row per game. The lock records the model commit, the play-call artifact hash, the snapshot hash, the SHA-256 of each batch
output, and the time the lock was written. The lock is locked only when this file is committed and pushed before kickoff; the
push time is the git commit time, not a field inside the file.

Usage: python3 slc_week8_lock.py --snapshots DIR --forecast DIR --model-commit SHA --out DIR
"""
import argparse
import hashlib
import json
import math
from datetime import datetime, timezone
from pathlib import Path

ARTIFACT = 'docs/research/SLC-PLAYCALL-ARTIFACT-v1.json'
MODEL_ID = 'slc_v1_incomplete'
CONNECTED = [
    'game-state reducer and legal transitions (reducer.py, game_state.py)',
    'E1 drive sampler with the live pre-play state (e1_drive.py, game_state.py)',
    'score-clock play-call layer, every scrimmage play chosen before its outcome (slc_playcall.py, slc_engine.py)',
    'E2 clock, scoring, possession and overtime rules (game_state.py)',
    'pregame depth roster used for participant usage (pregame_snapshot.py, game_state.participants_for)',
    'post-event player statistics as role allocations (game_stats.py)',
]
MISSING = [
    'team offense and defense splits: not integrated (only a team-by-down term inside the play-call artifact)',
    'team-specific playbooks: not integrated',
    'QB and role decision models: not integrated (decision_model.py is not imported at this commit)',
    'pre-event player selection: not integrated (participants are assigned after the outcome is drawn)',
    'injury report: captured, but not consumed by the engine',
    'kick and punt decisions: historical share fallback, labelled on every decision',
    'coaching: excluded from v1 by decision',
]


def _utc(text):
    return datetime.fromisoformat(text.replace('Z', '+00:00')).astimezone(timezone.utc)


def _sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def summarize(seed_rows):
    outcomes = [r['outcome'] for r in seed_rows if 'seed' in r]
    done = [o for o in outcomes if not o.get('error') and o.get('home_points') is not None]
    n = len(done)
    home_wins = sum(1 for o in done if o['home_points'] > o['away_points'])
    ties = sum(1 for o in done if o['home_points'] == o['away_points'])
    p = home_wins / n if n else None
    se = math.sqrt(p * (1 - p) / n) if n else None
    margins = [o['home_points'] - o['away_points'] for o in done]
    totals = [o['home_points'] + o['away_points'] for o in done]
    return {
        'seeds': len(outcomes), 'completed': n, 'errors': len(outcomes) - n,
        'valid_engine_games': sum(1 for o in done if o.get('valid_full_game')),
        'home_win_probability': round(p, 4) if p is not None else None,
        'home_win_probability_se': round(se, 4) if se is not None else None,
        'ties_at_regulation_end': ties,
        'mean_home_points': round(sum(o['home_points'] for o in done) / n, 2) if n else None,
        'mean_away_points': round(sum(o['away_points'] for o in done) / n, 2) if n else None,
        'mean_margin_home': round(sum(margins) / n, 2) if n else None,
        'mean_total': round(sum(totals) / n, 2) if n else None,
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--snapshots', type=Path, required=True)
    ap.add_argument('--forecast', type=Path, required=True)
    ap.add_argument('--model-commit', required=True)
    ap.add_argument('--out', type=Path, required=True)
    args = ap.parse_args()
    artifact_sha = json.loads(Path(ARTIFACT).read_text())['sha256']
    rows, games = [], []
    for snap_path in sorted(args.snapshots.glob('*.json')):
        snap = json.loads(snap_path.read_text())
        gid = snap['schedule']['game_id']
        batch = args.forecast / f'{gid}.json'
        seeds = args.forecast / f'{gid}.seeds.jsonl'
        summary = summarize([json.loads(line) for line in seeds.read_text().splitlines()]) if seeds.exists() else None
        rosters = snap['rosters']
        row = {
            'game_id': gid, 'week': snap['schedule']['week'], 'kickoff_utc': snap['schedule']['scheduled_kickoff_utc'],
            'as_of_cutoff_utc': snap['as_of'], 'snapshot_sha256': snap['snapshot_sha256'],
            'schedule_verified': snap['schedule']['availability_classification'] == 'captured_before_cutoff',
            'inputs_verified': snap['evaluation']['verified'],  # every input of the snapshot, the schedule and the depth rows
            'depth_snapshot_at': {side: rosters[side]['snapshot_at'] for side in rosters},
            'injury_report_available': {side: rosters[side]['injury_report']['available'] for side in rosters},
            'injury_rows': {side: rosters[side]['injury_report']['rows'] for side in rosters},
            'model_id': MODEL_ID, 'model_commit': args.model_commit, 'playcall_artifact_sha256': artifact_sha,
            'connected_layers': CONNECTED, 'missing_layers': MISSING,
            'evaluation_class': snap['evaluation']['class'],
            'forecast': summary,
            'batch_output_sha256': _sha(batch) if batch.exists() else None,
            'seed_ledger_sha256': _sha(seeds) if seeds.exists() else None,
        }
        rows.append(row)
        games.append(gid)
    lock = {'schema': 'lp-slc-week8-forecast-lock-1', 'model_id': MODEL_ID, 'model_commit': args.model_commit,
            'playcall_artifact_sha256': artifact_sha, 'evaluation_class': 'prospective_forecast',
            'written_at_utc': datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
            'note': 'locked only when committed and pushed before the game kickoff; the push time is the git commit time',
            'games': rows}
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / 'forecast-lock.json').write_text(json.dumps(lock, indent=1, sort_keys=True) + '\n')
    print(json.dumps({'games': len(games), 'forecasts': sum(1 for r in rows if r['forecast'])}))


if __name__ == '__main__':
    main()
