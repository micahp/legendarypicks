"""Run one SLC v1 game from a pregame snapshot, and write its trace and decision record (research, not adopted).

The configuration is slc_engine's, the same code the batch runner uses. The snapshot is built from the database as of --as-of, or
read from a hash-pinned --snapshot-file. A run without a snapshot is refused. Every scrimmage play's decision is recorded with the
state before the play, the probability, the chosen play type and the historical row it drew.

Usage: python3 run_slc_game.py --artifact JSON (--game-id ID --as-of TS | --snapshot-file JSON) --seed N --out JSON
"""
import argparse
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import e1_drive as e1  # noqa: E402
import simulate_pregame_game as game_cli  # noqa: E402
import game_state as gs  # noqa: E402
import pregame_snapshot  # noqa: E402
import slc_engine  # noqa: E402


def parse_args(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--artifact', type=Path, required=True, help='play-call artifact fitted before the game season')
    ap.add_argument('--snapshot-file', type=Path, help='hash-pinned pregame snapshot JSON')
    ap.add_argument('--game-id', help='published nfl_schedule game_id, when building the snapshot')
    ap.add_argument('--as-of', help='timezone-qualified ISO-8601 pregame cutoff, when building the snapshot')
    ap.add_argument('--kickoff-utc')
    ap.add_argument('--kickoff-source-url')
    ap.add_argument('--allow-unverified-current-schedule-exploratory', action='store_true',
                    help='historical games have no versioned schedule; use the current row, labelled unverified')
    ap.add_argument('--roster-snapshot')
    ap.add_argument('--roster-provenance')
    ap.add_argument('--team-outcomes', action='store_true',
                    help='SLC v1 research: prior-season team event splits within the play-call intent')
    ap.add_argument('--formation', action='store_true', help='SLC v1 research: pre-event formation and personnel, outcomes conditioned on formation')
    ap.add_argument('--dirichlet-shares', action='store_true',
                    help='SLC v1 research: per-game Dirichlet target and carry shares (fitted on the prior season), drawn once per team '
                         'and game; implies the player-share adapter')
    ap.add_argument('--seed', type=int, required=True)
    ap.add_argument('--db', default=e1.DEFAULT_DB)
    ap.add_argument('--out', type=Path, required=True)
    return ap.parse_args(argv)


def player_shares_for(args):
    """The player-share adapter is on whenever the Dirichlet shares are: the shares are drawn over the adapter's players."""
    return bool(args.dirichlet_shares)


def main():
    args = parse_args()
    source_provenance = game_cli.producer_source()

    if args.snapshot_file:
        snapshot = pregame_snapshot.load_frozen_snapshot(str(args.snapshot_file))
    elif args.game_id and args.as_of:
        snapshot = pregame_snapshot.build(args.db, args.game_id, args.as_of, args.kickoff_utc, args.kickoff_source_url,
                                          allow_unverified_current_schedule_exploratory=(
                                              args.allow_unverified_current_schedule_exploratory))
    else:
        raise SystemExit('SLC v1 needs a pregame snapshot: give --snapshot-file, or --game-id and --as-of')
    if bool(args.roster_snapshot) != bool(args.roster_provenance):
        raise SystemExit('--roster-snapshot and --roster-provenance must be supplied together')
    if args.roster_snapshot:
        pregame_snapshot.apply_full_depth_roster_snapshot(snapshot, args.roster_snapshot, args.roster_provenance)

    ref, excluded = slc_engine.load_reference(args.db, snapshot, args.artifact, team_outcomes=args.team_outcomes,
                                                formation=args.formation, player_shares=player_shares_for(args),
                                                dirichlet_shares=args.dirichlet_shares,
                                                source_commit=source_provenance['base_commit'])
    snapshot['model_reference']['observed_reference'] = ref.model_inputs
    snapshot['model_reference']['pool_scope'] = ref.pool_scope
    pregame_snapshot.reseal(snapshot)
    record, decisions = slc_engine.play(args.seed, ref, snapshot)
    gs.validate_game(record)

    schedule = snapshot['schedule']
    evaluation = snapshot.get('evaluation', {})  # the snapshot's own provenance result (pregame_snapshot.input_provenance)
    artifact = json.loads(args.artifact.read_text())
    connected = ['score-clock play-call layer (slc_playcall_v1)']
    not_connected = ['team offense and defense splits', 'playbooks', 'QB and role decisions',
                     'coaching (excluded from v1)']
    if args.dirichlet_shares:
        connected.append('pre-event player target and carry assignment (Dirichlet-multinomial shares)')
    else:
        not_connected.append('pre-event participant selection')
    trace = {
        'model_id': slc_engine.MODEL_ID,
        'components_connected': connected,
        'components_not_connected': not_connected,
        'source': source_provenance,
        'seed': args.seed, 'team_outcomes': bool(args.team_outcomes), 'formation': bool(args.formation),
        'game': {'game_id': schedule['game_id'], 'season': schedule['season'], 'week': schedule['week'],
                 'side_teams': slc_engine.side_teams(snapshot)},
        'snapshot': {'snapshot_sha256': snapshot['snapshot_sha256'], 'as_of': snapshot['as_of'],
                     'roster_snapshot_id': snapshot['roster_snapshot_id'],
                     'schedule_availability': schedule['availability_classification'],
                     'evaluation_class': evaluation.get('class'), 'inputs_verified': evaluation.get('verified')},
        'playcall': {'artifact_sha256': artifact['sha256'], 'fit_seasons': [min(artifact['fit_seasons']),
                                                                             max(artifact['fit_seasons'])],
                     'reference_season': artifact['reference_season'],
                     'summary': slc_engine.summary(decisions),
                     'player_share_distribution': (slc_engine.describe(ref) or {}).get('player_share_distribution')},
        'pool': {'eligible_before': [int(schedule['season']), int(schedule['week'])],
                 'excluded_kickoffs': excluded if isinstance(excluded, (int, float, str, dict, list)) else str(excluded)},
        'contract': {
            'mode': record.get('mode'),
            'complete_game': record.get('complete_game'),
            'valid_full_game_engine': record.get('valid_full_game'),
            'valid_full_game_claim': bool(record.get('valid_full_game') and evaluation.get('verified')),
            'valid_full_game_claim_requires': 'engine valid_full_game and every snapshot input verified (evaluation.verified)',
            'evaluation': 'exploratory single-game run',
            'cutoff_safe': True,
            'cutoff_safe_scope': 'the pool holds only plays before the game and the play-call artifact is fitted before its season',
            'player_stats': 'historical allocation from sampled historical participants; not a player projection',
        },
        'diagnosis': {
            'status': record.get('status'), 'blocker': record.get('blocker'),
            'regulation_end_reached': record.get('regulation_end_reached'),
            'unmodelled_transitions': record.get('unmodelled_transitions', []),
            'unsupported_rules': record.get('unsupported_rules', []),
            'scope_out': record.get('scope_out', []),
        },
        'result': record,
        'event_trace': decisions,
    }
    args.out.write_text(json.dumps(trace, indent=1, sort_keys=True, default=str) + '\n')
    print(json.dumps({'game_id': schedule['game_id'], 'seed': args.seed, 'status': record.get('status'),
                      'complete_game': record.get('complete_game'), 'valid_full_game_claim': trace['contract']['valid_full_game_claim'],
                      'decisions': len(decisions), 'points': record.get('points')}))


if __name__ == '__main__':
    main()
