"""The SLC v1 configuration, shared by the single-game runner and the batch runner (research, not adopted).

One place decides what an SLC game is: a pregame snapshot, a historical pool cut to the weeks before that game, and the frozen
score-clock play-call layer as the drive policy. The play-call artifact must have been fitted only on seasons before the game's
season. The runners call these functions rather than set the configuration themselves, so they cannot disagree about it.
A game without a snapshot is refused: the first-piece path has no pregame missed-kick return and no roster, so it would be a
different model under the SLC name.
"""
import copy
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import e2_reference as er  # noqa: E402
import game_state as gs  # noqa: E402
import pre_event  # noqa: E402
import slc_playcall as slc  # noqa: E402

MODEL_ID = 'slc_v1_incomplete'
QB_DECISION_MODEL_ID = 'slc_v1_qb_decisions_research'
PLAYER_OUTCOME_MODEL_ID = 'slc_v1_player_outcomes_research'
COMBINED_PLAYER_MODEL_ID = 'slc_v1_qb_decisions_player_outcomes_research'


def require_snapshot(snapshot):
    if not isinstance(snapshot, dict) or 'schedule' not in snapshot or 'rosters' not in snapshot:
        raise ValueError('SLC v1 needs a pregame snapshot; the first-piece path without one is not an SLC game')
    return snapshot


def side_teams(snapshot):
    """Offense side A is the home team and B the away team, as in the engine's team_identity (game_state.py)."""
    schedule = require_snapshot(snapshot)['schedule']
    return {'A': schedule['home_team'], 'B': schedule['away_team']}


def check_artifact_cutoff(artifact, season):
    """The layer may use only seasons before the game's season, and its recency reference is that season."""
    fit = sorted(int(s) for s in artifact['fit_seasons'])
    if int(artifact['reference_season']) != int(season):
        raise ValueError(f"play-call artifact reference season {artifact['reference_season']} is not the game season {season}")
    if not fit or fit[-1] >= int(season):
        raise ValueError(f"play-call artifact is fitted through {fit[-1] if fit else None}; a {season} game needs a fit "
                         f"that ends before {season}")


def load_reference(db, snapshot, artifact_path, team_outcomes=False, formation=False, player_shares=False,
                   exact_yardline=False, coverage=False, point_splits=False, streak=False, streak_file=None,
                   streak_league=False, target_roles=False, decision=False, decision_filter=True, dirichlet_shares=False,
                   playbook=False, source_commit=None, qb_decisions=False, player_outcomes=False,
                   player_outcomes_receiver_only=False):
    """(Reference, excluded_kickoffs) for one snapshot. The play pool holds only prior seasons: no outcome from the game's own
    season is used, so a 2026 forecast draws on 2022 to 2025 and not on the 2026 results before it."""
    schedule = require_snapshot(snapshot)['schedule']
    season = int(schedule['season'])
    if player_outcomes_receiver_only and not player_outcomes:
        raise ValueError('receiver-only player outcomes require player_outcomes=True')
    check_artifact_cutoff(json.loads(Path(artifact_path).read_text()), season)
    ref, excluded = er.load(db, eligible_before=(season, 1), playcall_artifact=str(artifact_path),
                   playcall_teams=side_teams(snapshot), playcall_team_outcomes=team_outcomes,
                   playcall_formation=formation, playcall_player_shares=(player_shares or dirichlet_shares),
                   playcall_target_roles=target_roles, playcall_decision=decision,
                   playcall_exact_yardline=exact_yardline, playcall_coverage=coverage,
                   playcall_point_splits=point_splits, playcall_streak=streak, playcall_streak_league=streak_league,
                   playcall_qb_decisions=qb_decisions, playcall_player_outcomes=player_outcomes)
    # These are independent research inputs. Each is fitted strictly before the target season.
    if qb_decisions or player_outcomes:
        if not source_commit:
            raise ValueError('QB decisions and player outcomes need a source commit for their model manifests')
    if qb_decisions:
        import qb_decisions as qb_model
        qb_table = qb_model.load(db, season)
        qb_table['scramble_cells'] = {
            qb_model.cell_of(row['down'], row['ydstogo'], row['yardline_100'])
            for cell in ref.pool.values() for _event, row, _runoff, _spot in cell
            if row.get('qb_scramble') == 1
        }
        ref.contextual_sampler.qb_decision_table = qb_table
        ref.contextual_sampler.qb_decision_manifest = qb_model.manifest(qb_table, source_commit)
    if player_outcomes:
        import player_outcomes as outcome_model
        outcome_table = outcome_model.load(db, season)
        ref.contextual_sampler.player_outcome_table = outcome_table
        ref.contextual_sampler.player_outcome_roles = ('receiver',) if player_outcomes_receiver_only else None
        ref.contextual_sampler.player_outcome_manifest = outcome_model.manifest(
            outcome_table, source_commit, enabled_roles=ref.contextual_sampler.player_outcome_roles)
    ref.contextual_sampler.decision_filter = decision_filter  # an experiment switch: False draws rows from the whole cell
    if dirichlet_shares:  # per-game Dirichlet target and carry shares, fitted on the season before the game season
        if not source_commit:
            raise ValueError('Dirichlet player shares need a source commit for their model manifest')
        import share_distributions
        table = share_distributions.load(db, season)
        ref.contextual_sampler.share_table = table
        ref.contextual_sampler.share_model_manifest = share_distributions.manifest(table, cutoff=season,
                                                                                    git_commit=source_commit)
    if playbook:  # the playbook files as the prior for pass depth, pass location and run gap; needs the decision labels on
        if not decision:
            raise ValueError('the playbook input replaces decision labels, so it needs decision=True')
        import playbook_prior
        ref.contextual_sampler.playbook_table = playbook_prior.load(int(schedule['season']))
    if streak_file is not None:  # each team's current streak as of the cutoff, from the verified records
        import json as _json
        import streak_splits as ss
        records = _json.loads(Path(streak_file).read_text())['teams']
        ref.contextual_sampler.current_streak = {team: ss.bucket_from_text(rec.get('streak', '')) for team, rec in records.items()}
    # Include every enabled model table and manifest in the reference identity. e2 computes an initial fingerprint before
    # these optional adapters are attached, so the final reference must be fingerprinted after all loading is complete.
    ref.model_inputs = er._reference_fingerprint(ref)
    return ref, excluded


def is_slc(ref):
    return isinstance(getattr(ref, 'contextual_sampler', None), slc.PlayCallSampler)


def play(seed, ref, snapshot):
    """One SLC game. Returns (record, decisions): the engine record and this game's play-call decisions, in order."""
    if not is_slc(ref):
        raise ValueError('the reference was not loaded with the SLC play-call layer')
    sampler = ref.contextual_sampler
    sampler.decisions.clear()
    sampler.participant_chooser = pre_event.chooser(require_snapshot(snapshot), seed,
                                                    formation_priors=sampler.formation_priors,
                                                    player_shares=sampler.player_shares,
                                                    defense_priors=sampler.defense_priors,
                                                    role_table=sampler.role_table, decision_table=sampler.decision_table,
                                                    share_table=sampler.share_table, playbook_table=sampler.playbook_table,
                                                    qb_decision_table=sampler.qb_decision_table)
    try:
        record = gs.play_game(seed, ref, pregame_snapshot=copy.deepcopy(snapshot))
    finally:
        sampler.participant_chooser = None
    decisions = list(sampler.decisions)
    sampler.decisions.clear()
    if sampler.player_outcome_table is not None:
        roles = (sampler.player_outcome_manifest or {}).get('enabled_roles', ['qb', 'receiver', 'rusher'])
        role_text = ', '.join(roles)
        attribution = 'pregame_participant_and_conditioned_outcome_model'
        record['stats']['player_attribution'] = attribution
        for player_line in record['stats']['player']:
            player_line['attribution'] = attribution
        record['stats']['player_note'] = (
            f'Participants are selected from the frozen pregame roster before the outcome. {role_text} outcome rows are '
            'reweighted by cutoff-safe player distributions before the game-state transition. Box-score passing, '
            'receiving and rushing yards use their corresponding nflverse fields when present; the state transition uses '
            'yards_gained. This is a research projection layer; historical source outcomes and the current model do not '
            'establish calibrated forecasts.')
    return record, decisions


def summary(decisions):
    target_decisions = [d for d in decisions if d.get('qb_target_role') is not None]
    return {'decisions': len(decisions),
            'scrimmage': sum(d['intent'] != 'kick' for d in decisions),
            'dropback': sum(d['intent'] == 'dropback' for d in decisions),
            'run': sum(d['intent'] == 'run' for d in decisions),
            'qb_scramble': sum(d.get('qb_action') == 'scramble' for d in decisions),
            'qb_target_role_decisions': len(target_decisions),
            'qb_target_role_conditioned': sum(bool(d.get('qb_target_role_conditioned')) for d in target_decisions),
            'qb_target_role_fallbacks': sum(d.get('qb_target_role_fallback') is not None for d in target_decisions),
            'qb_target_role_draw_fallbacks': sum(d.get('qb_target_role_draw_fallback') is not None
                                                 for d in target_decisions),
            'qb_target_role_no_history': sum(d.get('qb_target_role_history_n') == 0 for d in target_decisions),
            'kick_fallback': sum(d['intent'] == 'kick' for d in decisions)}


def describe(ref):
    """The layer's manifest for a batch payload: None for the S0 control."""
    if not is_slc(ref):
        return None
    sampler = ref.contextual_sampler
    artifact = sampler.layer.artifact
    description = {'model_id': model_id(ref), 'artifact_id': artifact['artifact_id'], 'artifact_sha256': artifact['sha256'],
                   'fit_seasons': sorted(int(s) for s in artifact['fit_seasons']),
                   'reference_season': int(artifact['reference_season']), 'side_teams': sampler.describe().get('side_teams')}
    share_manifest = getattr(sampler, 'share_model_manifest', None)
    if share_manifest is not None:
        description['player_share_distribution'] = share_manifest
    qb_manifest = getattr(sampler, 'qb_decision_manifest', None)
    if qb_manifest is not None:
        description['qb_decision_model'] = qb_manifest
    outcome_manifest = getattr(sampler, 'player_outcome_manifest', None)
    if outcome_manifest is not None:
        description['player_outcome_model'] = outcome_manifest
    integration_hashes = sampler.describe().get('integration_code_sha256')
    if integration_hashes is not None:
        description['integration_code_sha256'] = integration_hashes
    return description


def model_id(ref):
    sampler = getattr(ref, 'contextual_sampler', None)
    if sampler is not None:
        qb = sampler.qb_decision_table is not None
        outcomes = sampler.player_outcome_table is not None
        if qb and outcomes:
            return COMBINED_PLAYER_MODEL_ID
        if qb:
            return QB_DECISION_MODEL_ID
        if outcomes:
            return PLAYER_OUTCOME_MODEL_ID
    return MODEL_ID
