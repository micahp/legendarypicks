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
    ap.add_argument('--coverage', action='store_true', help='SLC v1 research: defensive coverage priors and coverage-conditioned outcomes')
    ap.add_argument('--player-shares', action='store_true', help='SLC v1 research: prior-season player target and carry shares')
    ap.add_argument('--dirichlet-shares', action='store_true',
                    help='SLC v1 research: per-game Dirichlet target and carry shares (fitted on the prior season), drawn once per team '
                         'and game; implies the player-share adapter')
    ap.add_argument('--exact-yardline', action='store_true', help='SLC v1 research: condition red-zone outcome draws on exact yard line')
    ap.add_argument('--point-splits', action='store_true', help='SLC v1 research: team score-state play-call shifts')
    ap.add_argument('--streak-splits', action='store_true', help='SLC v1 research: team streak play-call shifts')
    ap.add_argument('--streak-league', action='store_true', help='SLC v1 research: league streak play-call and outcome shifts')
    ap.add_argument('--streak-file', type=Path, help='cutoff-safe team streak records for this pregame snapshot')
    ap.add_argument('--target-roles', action='store_true', help='SLC v1 research: team target-role priors by situation')
    ap.add_argument('--decision', action='store_true', help='SLC v1 research: decision labels, outcome lifts and optional row filter')
    ap.add_argument('--decision-unfiltered', action='store_true', help='disable the decision-label row filter while retaining outcome lifts')
    ap.add_argument('--playbook', action='store_true', help='SLC v1 research: use playbook priors for decision categories C, D and E')
    ap.add_argument('--qb-decisions', action='store_true',
                    help='SLC research: QB-specific target-role and scramble decisions from prior seasons')
    ap.add_argument('--player-outcomes', action='store_true',
                    help='SLC research: QB, receiver and rusher event, yardage and touchdown distributions; outcomes can change team scoring')
    ap.add_argument('--player-outcomes-receiver-only', action='store_true',
                    help='research ablation: apply player-conditioned event and result weights to receivers only; requires --player-outcomes')
    ap.add_argument('--seed', type=int, required=True)
    ap.add_argument('--db', default=e1.DEFAULT_DB)
    ap.add_argument('--out', type=Path, required=True)
    args = ap.parse_args(argv)
    if args.player_outcomes_receiver_only and not args.player_outcomes:
        ap.error('--player-outcomes-receiver-only requires --player-outcomes')
    if args.decision_unfiltered and not args.decision:
        ap.error('--decision-unfiltered requires --decision')
    return args


def player_shares_for(args):
    """The player-share adapter is on whenever the Dirichlet shares are: the shares are drawn over the adapter's players."""
    return bool(args.player_shares or args.dirichlet_shares)


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
                                                exact_yardline=args.exact_yardline, coverage=args.coverage,
                                                point_splits=args.point_splits, streak=args.streak_splits,
                                                streak_file=str(args.streak_file) if args.streak_file else None,
                                                streak_league=args.streak_league, target_roles=args.target_roles,
                                                decision=args.decision, decision_filter=not args.decision_unfiltered,
                                                dirichlet_shares=args.dirichlet_shares,
                                                qb_decisions=args.qb_decisions, player_outcomes=args.player_outcomes,
                                                player_outcomes_receiver_only=args.player_outcomes_receiver_only,
                                                playbook=args.playbook,
                                                source_commit=source_provenance['base_commit'])
    snapshot['model_reference']['observed_reference'] = ref.model_inputs
    snapshot['model_reference']['pool_scope'] = ref.pool_scope
    pregame_snapshot.reseal(snapshot)
    record, decisions = slc_engine.play(args.seed, ref, snapshot)
    gs.validate_game(record)

    schedule = snapshot['schedule']
    evaluation = snapshot.get('evaluation', {})  # the snapshot's own provenance result (pregame_snapshot.input_provenance)
    artifact = json.loads(args.artifact.read_text())
    playcall_layer = slc_engine.describe(ref) or {}
    feature_labels = {
        'score_clock_playcalling': 'score-clock play calling',
        'team_offense_defense_outcomes': 'team offense/defense outcomes',
        'formation_personnel_outcomes': 'formation/personnel outcomes',
        'defensive_coverage_outcomes': 'defensive coverage outcomes',
        'fixed_player_target_carry_shares': 'fixed player target/carry shares',
        'dirichlet_player_target_carry_shares': 'Dirichlet player target/carry shares',
        'qb_decisions': 'QB decisions',
        'player_conditioned_outcomes': 'player-conditioned outcomes',
        'target_role_priors': 'team target-role priors',
        'decision_labels': 'decision labels and outcome lifts',
        'playbook_priors': 'playbook priors',
        'point_splits': 'team point splits',
        'team_streak_splits': 'team streak splits',
        'league_streak_splits': 'league streak splits',
        'exact_yardline_outcomes': 'exact-yardline outcomes',
        'current_streak_context': 'current pregame streak context',
    }
    active = playcall_layer.get('enabled_layers', {})
    connected = [label for key, label in feature_labels.items() if active.get(key) is True]
    not_connected = [label for key, label in feature_labels.items() if active.get(key) is not True]
    not_connected.append('coaching tendencies (separate research)')
    trace = {
        'model_id': slc_engine.model_id(ref),
        'components_connected': connected,
        'components_not_connected': not_connected,
        'source': source_provenance,
        'seed': args.seed, 'team_outcomes': bool(args.team_outcomes), 'formation': bool(args.formation),
        'coverage': bool(args.coverage), 'player_shares': player_shares_for(args),
        'dirichlet_shares': bool(args.dirichlet_shares), 'exact_yardline': bool(args.exact_yardline),
        'point_splits': bool(args.point_splits), 'streak_splits': bool(args.streak_splits),
        'streak_league': bool(args.streak_league), 'target_roles': bool(args.target_roles),
        'decision': bool(args.decision), 'decision_filter': (not args.decision_unfiltered if args.decision else None),
        'playbook': bool(args.playbook),
        'qb_decisions': bool(args.qb_decisions), 'player_outcomes': bool(args.player_outcomes),
        'player_outcomes_receiver_only': bool(args.player_outcomes_receiver_only),
        'game': {'game_id': schedule['game_id'], 'season': schedule['season'], 'week': schedule['week'],
                 'side_teams': slc_engine.side_teams(snapshot)},
        'playcall_layer': playcall_layer,
        'snapshot': {'snapshot_sha256': snapshot['snapshot_sha256'], 'as_of': snapshot['as_of'],
                     'roster_snapshot_id': snapshot['roster_snapshot_id'],
                     'schedule_availability': schedule['availability_classification'],
                     'evaluation_class': evaluation.get('class'), 'inputs_verified': evaluation.get('verified')},
        'playcall': {'artifact_sha256': artifact['sha256'], 'fit_seasons': [min(artifact['fit_seasons']),
                                                                             max(artifact['fit_seasons'])],
                     'reference_season': artifact['reference_season'],
                     'summary': slc_engine.summary(decisions),
                     'player_share_distribution': (slc_engine.describe(ref) or {}).get('player_share_distribution'),
                     'qb_decision_model': (slc_engine.describe(ref) or {}).get('qb_decision_model'),
                     'player_outcome_model': (slc_engine.describe(ref) or {}).get('player_outcome_model')},
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
            'player_stats': ('participant-conditioned research distributions' if args.player_outcomes else
                             'historical allocation from sampled historical participants; not a player projection'),
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
