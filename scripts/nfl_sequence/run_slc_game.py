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
import slc_config  # noqa: E402
import historical_archive  # noqa: E402
import e2_reference as er  # noqa: E402


def parse_args(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--artifact', type=Path, required=True, help='play-call artifact fitted before the game season')
    ap.add_argument('--slc-profile', choices=('custom', 'v1_full_stack'), default='custom',
                    help='named fail-closed SLC configuration')
    ap.add_argument('--slc-disable-layer', action='append', default=[],
                    help='controlled ablation; repeat to disable multiple optional layers')
    ap.add_argument('--snapshot-file', type=Path, help='hash-pinned pregame snapshot JSON')
    ap.add_argument('--historical-archive-reconstruction', action='store_true',
                    help='explicitly run verified archived inputs as retrospective, never prospective')
    ap.add_argument('--readiness-matrix', type=Path)
    ap.add_argument('--archive-manifest', type=Path)
    ap.add_argument('--archive-root', type=Path)
    ap.add_argument('--historical-streak-file', type=Path)
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
    ap.add_argument('--qb-run-role-style', action='store_true',
                    help='SLC research ablation: adjust QB run-role selection using prior non-scramble run tendency; requires --qb-decisions')
    ap.add_argument('--player-outcomes', action='store_true',
                    help='SLC research: QB, receiver and rusher event, yardage and touchdown distributions; outcomes can change team scoring')
    ap.add_argument('--player-outcomes-receiver-only', action='store_true',
                    help='research ablation: apply player-conditioned event and result weights to receivers only; requires --player-outcomes')
    ap.add_argument('--slc-blocker-fix', action='append', choices=er.BLOCKER_FIXES, default=[],
                    help='opt-in SLC research blocker fix; repeat to enable multiple fixes')
    ap.add_argument('--slc-fg-ordinary-cutoff', type=float, default=60.0,
                    help='ordinary field-goal decision maximum in yards when long_field_goal_feasibility is enabled')
    ap.add_argument('--seed', type=int, required=True)
    ap.add_argument('--db', default=e1.DEFAULT_DB)
    ap.add_argument('--out', type=Path, required=True)
    args = ap.parse_args(argv)
    if args.player_outcomes_receiver_only and not args.player_outcomes:
        ap.error('--player-outcomes-receiver-only requires --player-outcomes')
    if args.decision_unfiltered and not args.decision:
        ap.error('--decision-unfiltered requires --decision')
    if args.slc_blocker_fix and not args.artifact:
        ap.error('--slc-blocker-fix requires --artifact')
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
    archive_validation = None
    archive_block = snapshot.get('archive_reconstruction')
    retrospective_marker = (snapshot.get('evaluation', {}).get('class') == historical_archive.MODE
                             or snapshot.get('schedule', {}).get('availability_classification') == historical_archive.MODE)
    if args.historical_archive_reconstruction:
        if not args.snapshot_file:
            raise ValueError('historical archive reconstruction requires a frozen --snapshot-file')
        if not (args.readiness_matrix and args.archive_manifest and args.archive_root):
            raise ValueError('historical archive reconstruction requires readiness, archive manifest, and archive root')
        if args.roster_snapshot:
            raise ValueError('archival reconstruction snapshot is already frozen; later roster overrides are refused')
        streak_path = args.historical_streak_file
        if not streak_path:
            relative = (archive_block or {}).get('streak_context', {}).get('file')
            if relative:
                streak_path = (args.snapshot_file.resolve().parent / relative).resolve()
        archive_validation = historical_archive.validate_snapshot(
            snapshot, readiness_matrix=args.readiness_matrix, archive_manifest=args.archive_manifest,
            archive_root=args.archive_root, streak_file=streak_path,
            expected_game_id=snapshot['schedule']['game_id'])
        if args.slc_profile == 'v1_full_stack' and not args.streak_file:
            args.streak_file = Path(streak_path)
    elif archive_block:
        raise ValueError('archival reconstruction snapshot requires explicit --historical-archive-reconstruction mode')
    elif retrospective_marker:
        raise ValueError('retrospective snapshot classification requires explicit --historical-archive-reconstruction mode')
    elif args.historical_streak_file:
        raise ValueError('--historical-streak-file is only valid in historical archive reconstruction mode')

    supplied = {
        'playcall_team_outcomes': bool(args.team_outcomes), 'playcall_formation': bool(args.formation),
        'playcall_coverage': bool(args.coverage), 'playcall_player_shares': bool(args.player_shares),
        'playcall_dirichlet_shares': bool(args.dirichlet_shares), 'playcall_qb_decisions': bool(args.qb_decisions),
        'playcall_qb_run_role_style': bool(args.qb_run_role_style),
        'playcall_player_outcomes': bool(args.player_outcomes), 'playcall_target_roles': bool(args.target_roles),
        'playcall_decision': bool(args.decision), 'playcall_playbook': bool(args.playbook),
        'playcall_point_splits': bool(args.point_splits), 'playcall_streak_splits': bool(args.streak_splits),
        'playcall_streak_league': bool(args.streak_league), 'playcall_exact_yardline': bool(args.exact_yardline),
    }
    if args.decision_unfiltered:
        supplied['playcall_decision_unfiltered'] = True
    resolved_profile = slc_config.resolve_profile(
        args.slc_profile, options=supplied, artifact_path=args.artifact,
        streak_file=args.streak_file, disable_layers=args.slc_disable_layer,
        decision_filter=not args.decision_unfiltered)
    if args.slc_profile == 'v1_full_stack' and args.player_outcomes_receiver_only:
        raise ValueError('v1_full_stack requires all configured player-outcome roles; receiver-only is an ablation')
    if args.slc_profile == 'v1_full_stack':
        for option, value in resolved_profile['options'].items():
            name = option[len('playcall_'):] if option.startswith('playcall_') else option
            setattr(args, name, value)
        args.player_shares = resolved_profile['options'].get('playcall_player_shares', False)
        args.decision_unfiltered = not resolved_profile['decision_filter']
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
                                                qb_run_role_style=args.qb_run_role_style,
                                                player_outcomes_receiver_only=args.player_outcomes_receiver_only,
                                                playbook=args.playbook,
                                                source_commit=source_provenance['base_commit'],
                                                blocker_fixes=args.slc_blocker_fix,
                                                fg_ordinary_cutoff=args.slc_fg_ordinary_cutoff)
    playcall_layer = slc_engine.describe(ref)
    slc_config.validate_engine_layers(resolved_profile, playcall_layer)
    snapshot['model_reference']['observed_reference'] = ref.model_inputs
    snapshot['model_reference']['pool_scope'] = ref.pool_scope
    pregame_snapshot.reseal(snapshot)
    record, decisions = slc_engine.play(args.seed, ref, snapshot)
    gs.validate_game(record)

    schedule = snapshot['schedule']
    evaluation = snapshot.get('evaluation', {})  # the snapshot's own provenance result (pregame_snapshot.input_provenance)
    artifact = json.loads(args.artifact.read_text())
    playcall_layer = playcall_layer or {}
    input_provenance = {
        'mode': 'retrospective_archive_reconstruction' if archive_validation else 'prospective_snapshot',
        'snapshot_sha256': snapshot['snapshot_sha256'], 'recorded_cutoff_utc': snapshot['as_of'],
        'snapshot_evaluation': snapshot.get('evaluation'), 'archive_validation': archive_validation,
    }
    profile_manifest = slc_config.build_manifest(resolved_profile, playcall_layer, snapshot, input_provenance)
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
        'model_id': profile_manifest['model_id'],
        'slc_profile_manifest': profile_manifest,
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
        'historical_archive_reconstruction': archive_validation,
        'playcall': {'artifact_sha256': artifact['sha256'], 'fit_seasons': [min(artifact['fit_seasons']),
                                                                             max(artifact['fit_seasons'])],
                     'reference_season': artifact['reference_season'],
                     'summary': slc_engine.summary(decisions, record),
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
            'evaluation': profile_manifest['evaluation_class'],
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
