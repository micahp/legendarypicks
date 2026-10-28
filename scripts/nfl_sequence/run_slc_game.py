"""Run one complete game with the SLC layers connected, and write its event trace and component manifest (research).

The reference is loaded with the frozen score-by-clock play-call layer as the drive-policy sampler. The historical pool is the 2022
to 2025 pool, so no 2026 outcome is used. Every scrimmage play's decision is recorded with the state before the play, the probability,
the chosen play type and the historical row it drew.

Usage: python3 run_slc_game.py --artifact JSON --seed N --home TEAM --away TEAM --out JSON
"""
import argparse
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import e1_drive as e1  # noqa: E402
import e2_reference as er  # noqa: E402
import game_state as gs  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--artifact', type=Path, required=True)
    ap.add_argument('--seed', type=int, required=True)
    ap.add_argument('--home', required=True)
    ap.add_argument('--away', required=True)
    ap.add_argument('--out', type=Path, required=True)
    ap.add_argument('--db', default=e1.DEFAULT_DB)
    ap.add_argument('--eligible-before', default='2025,18',
                    help='season,week cutoff: pool rows strictly before this week. The default excludes 2025 week 18 and keeps '
                         'the 2026 holdout out. The loader accepts weeks 1 to 18 only.')
    args = ap.parse_args()

    season, week = (int(part) for part in args.eligible_before.split(','))
    teams = {'A': args.away, 'B': args.home}
    ref, excluded = er.load(args.db, eligible_before=(season, week), playcall_artifact=str(args.artifact),
                            playcall_teams=teams)
    sampler = ref.contextual_sampler
    result = gs.play_game(args.seed, ref)
    decisions = sampler.decisions
    scrimmage = [d for d in decisions if d['intent'] != 'kick']
    trace = {
        'model_id': 'slc_v1_incomplete', 'components_connected': ['slc_playcall_v1 (score-by-clock play-call layer)'],
        'components_not_connected': ['team offense and defense splits', 'playbooks', 'QB and role decisions',
                                     'player opportunity selection', 'coaching (excluded from v1)'],
        'seed': args.seed, 'teams': teams, 'sampler': sampler.describe(),
        'decisions': len(decisions), 'scrimmage_decisions': len(scrimmage),
        'kick_decisions_fallback': sum(1 for d in decisions if d['intent'] == 'kick'),
        'excluded_kickoffs': excluded if isinstance(excluded, (int, float, str, dict, list)) else str(excluded),
        'contract': {
            'pregame_snapshot': None,
            'mode': result.get('mode'),
            'complete_game': result.get('complete_game'),
            'valid_full_game': result.get('valid_full_game'),
            'valid_full_game_requires': 'pregame_full_game mode with a verified pregame snapshot; none is supplied by this runner',
            'evaluation': 'exploratory smoke run',
            'cutoff_safe_backtest': False,
            'artifact_fit_seasons': sampler.layer.artifact['fit_seasons'],
            'artifact_note': 'the frozen play-call artifact is fit on every 2010 to 2025 primary play, so this run is not a '
                             'chronologically valid 2025 backtest',
            'player_stats': 'historical allocation from sampled historical participants; not a player projection and not the '
                            'roster of the simulated matchup',
        },
        'diagnosis': {
            'status': result.get('status'), 'blocker': result.get('blocker'),
            'regulation_end_reached': result.get('regulation_end_reached'),
            'unmodelled_transitions': result.get('unmodelled_transitions', []),
            'unsupported_rules': result.get('unsupported_rules', []),
            'scope_out': result.get('scope_out', []),
        },
        'result': result, 'event_trace': decisions,
    }
    args.out.write_text(json.dumps(trace, indent=1, sort_keys=True, default=str) + '\n')
    print(json.dumps({'decisions': len(decisions), 'scrimmage_decisions': len(scrimmage),
                      'result_keys': sorted(result) if isinstance(result, dict) else type(result).__name__}))


if __name__ == '__main__':
    main()
