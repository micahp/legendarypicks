"""The SLC v1 configuration, shared by the single-game runner and the batch runner (research, not adopted).

One place decides what an SLC game is: a pregame snapshot, a historical pool cut to the weeks before that game, and the frozen
score-clock play-call layer as the drive policy. The play-call artifact must have been fitted only on seasons before the game's
season. The runners call these functions rather than set the configuration themselves, so they cannot disagree about it.
A game without a snapshot is refused: the first-piece path has no pregame missed-kick return and no roster, so it would be a
different model under the SLC name.
"""
import copy
import hashlib
import json
import math
import sys
from collections.abc import Mapping
from collections import Counter, defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import e2_reference as er  # noqa: E402
import e0_single_play as e0  # noqa: E402
import game_state as gs  # noqa: E402
import playcall_model as pm  # noqa: E402
import pre_event  # noqa: E402
import slc_playcall as slc  # noqa: E402
import football_assertions  # noqa: E402

MODEL_ID = 'slc_v1_incomplete'
QB_DECISION_MODEL_ID = 'slc_v1_qb_decisions_research'
PLAYER_OUTCOME_MODEL_ID = 'slc_v1_player_outcomes_research'
COMBINED_PLAYER_MODEL_ID = 'slc_v1_qb_decisions_player_outcomes_research'


def _file_sha256(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def _stable_model_value(value):
    if isinstance(value, Mapping):
        entries = [(_stable_model_value(key), _stable_model_value(item)) for key, item in value.items()]
        entries.sort(key=lambda pair: json.dumps(pair[0], sort_keys=True, default=str))
        return {'__mapping__': entries}
    if isinstance(value, (tuple, list)):
        return [_stable_model_value(item) for item in value]
    if isinstance(value, (set, frozenset)):
        entries = [_stable_model_value(item) for item in value]
        return sorted(entries, key=lambda item: json.dumps(item, sort_keys=True, default=str))
    if hasattr(value, 'tolist'):
        return _stable_model_value(value.tolist())
    if hasattr(value, 'item'):
        try:
            return value.item()
        except (TypeError, ValueError):
            pass
    if hasattr(value, '__dict__'):
        return _stable_model_value(vars(value))
    return value


def _model_hash(value):
    encoded = json.dumps(_stable_model_value(value), sort_keys=True, separators=(',', ':'), default=str).encode()
    return hashlib.sha256(encoded).hexdigest()


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
                   player_outcomes_receiver_only=False, blocker_fixes=(), fg_ordinary_cutoff=60):
    """(Reference, excluded_kickoffs) for one snapshot. The play pool holds only prior seasons: no outcome from the game's own
    season is used, so a 2026 forecast draws on 2022 to 2025 and not on the 2026 results before it."""
    schedule = require_snapshot(snapshot)['schedule']
    season = int(schedule['season'])
    if player_outcomes_receiver_only and not player_outcomes:
        raise ValueError('receiver-only player outcomes require player_outcomes=True')
    check_artifact_cutoff(json.loads(Path(artifact_path).read_text()), season)
    fixes = er.normalize_blocker_fixes(blocker_fixes)
    run_scramble_backoff = 'run_scramble_backoff' in fixes
    ref, excluded = er.load(db, eligible_before=(season, 1), playcall_artifact=str(artifact_path),
                   playcall_teams=side_teams(snapshot), playcall_team_outcomes=team_outcomes,
                   playcall_formation=formation, playcall_player_shares=player_shares,
                   playcall_target_roles=target_roles, playcall_decision=decision,
                   playcall_exact_yardline=exact_yardline, playcall_coverage=coverage,
                   playcall_point_splits=point_splits, playcall_streak=streak, playcall_streak_league=streak_league,
                   playcall_qb_decisions=(qb_decisions or run_scramble_backoff),
                   playcall_player_outcomes=player_outcomes, blocker_fixes=fixes,
                   fg_ordinary_cutoff=fg_ordinary_cutoff)
    ref.pool, lateral_source_filter = exclude_unmodeled_lateral_rows(ref.pool, ref.participants)
    ref.pool_scope = dict(ref.pool_scope or {})
    ref.pool_scope['unmodeled_lateral_source_filter'] = lateral_source_filter
    sampler = ref.contextual_sampler
    sampler.source_cutoff = {'eligible_before': [season, 1]}
    sampler.optional_input_sha256 = {}
    if decision:
        import decision_layer as decision_inputs
        decision_paths = [Path(decision_inputs.PLAYERS_PARQUET)] + [
            Path(decision_inputs.PBP_PARQUET.format(season=year))
            for year in range(decision_inputs.FIRST_CHARTED_SEASON, season)
        ]
        for path in decision_paths:
            if not path.is_file():
                raise ValueError(f'decision-label source artifact is missing: {path}')
            sampler.optional_input_sha256[f'decision_source:{path.name}'] = _file_sha256(path)
    for name, value in (('point_splits_cache', point_splits), ('streak_splits_cache', streak),
                        ('streak_league_cache', streak_league)):
        if isinstance(value, str):
            sampler.optional_input_sha256[name] = _file_sha256(value)
    # These are independent research inputs. Each is fitted strictly before the target season.
    if qb_decisions or run_scramble_backoff or player_outcomes:
        if not source_commit:
            raise ValueError('QB decisions and player outcomes need a source commit for their model manifests')
    if qb_decisions or run_scramble_backoff:
        import qb_decisions as qb_model
        qb_table = qb_model.load(db, season)
        qb_table['scramble_cells'] = {
            qb_model.cell_of(row['down'], row['ydstogo'], row['yardline_100'])
            for cell in ref.pool.values() for _event, row, _runoff, _spot in cell
            if row.get('qb_scramble') == 1
        }
        qb_table['scramble_support'] = _scramble_support(qb_table, ref.pool)
        ref.contextual_sampler.qb_decision_table = qb_table
        ref.contextual_sampler.qb_decision_manifest = qb_model.manifest(qb_table, source_commit)
    if run_scramble_backoff:
        ref.contextual_sampler.source_pool = ref.pool
        ref.contextual_sampler.outcome_backoff_enabled = True
        ref.contextual_sampler.allow_sparse_cells = True
        ref.contextual_sampler.scramble_backoff_enabled = True
        ref.contextual_sampler.scramble_bounds = scramble_bounds_from_pool(ref.pool)
    ref.contextual_sampler.blocker_fixes = fixes
    ref.contextual_sampler.fg_ordinary_cutoff = float(fg_ordinary_cutoff)
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
        import glob
        from playbook_crosscheck import PLAYBOOKS
        paths = sorted(glob.glob(f'{PLAYBOOKS}/*-{int(schedule["season"]) - 1}.json'))
        if not paths:
            raise ValueError(f'no playbook source files for {int(schedule["season"]) - 1}')
        from playbook_crosscheck import TEAM_CODE
        available_teams = set()
        for path in paths:
            playbook_source = json.loads(Path(path).read_text())
            available_teams.add(TEAM_CODE.get(playbook_source.get('team_id'), playbook_source.get('team_id')))
            sampler.optional_input_sha256[f'playbook:{Path(path).name}'] = _file_sha256(path)
        required_teams = set((sampler.describe() or {}).get('side_teams', {}).values())
        missing_teams = sorted(required_teams - available_teams)
        if missing_teams:
            raise ValueError(f'playbook prior is missing target-game teams {missing_teams} for season {season - 1}')
    if streak_file is not None:  # each team's current streak as of the cutoff, from the verified records
        import json as _json
        import streak_splits as ss
        records = _json.loads(Path(streak_file).read_text())['teams']
        ref.contextual_sampler.current_streak = {team: ss.bucket_from_text(rec.get('streak', '')) for team, rec in records.items()}
        sampler.optional_input_sha256['current_streak_file'] = _file_sha256(streak_file)
    # Include every enabled model table and manifest in the reference identity. e2 computes an initial fingerprint before
    # these optional adapters are attached, so the final reference must be fingerprinted after all loading is complete.
    ref.model_inputs = er._reference_fingerprint(ref)
    return ref, excluded


def _scramble_support(qb_table, pool=None):
    """Cutoff-safe support by context, counting only scramble outcomes the engine can sample."""
    from collections import Counter
    counts = {name: {'scrambles': Counter(), 'dropbacks': Counter()}
              for name in ('exact_cell', 'down_field', 'down_distance', 'field_zone')}
    league_scrambles = league_dropbacks = 0
    for exact, outcomes in qb_table['league_cell'].items():
        down, distance, field = exact
        dropbacks = sum(outcomes.values())
        contexts = {'exact_cell': exact, 'down_field': (down, field), 'down_distance': (down, distance),
                    'field_zone': field}
        league_dropbacks += dropbacks
        for name, key in contexts.items():
            counts[name]['dropbacks'][key] += dropbacks
    if pool is None:
        # Compatibility for direct callers; SLC reference loading supplies the actual E1 sampling pool.
        for exact, outcomes in qb_table['league_cell'].items():
            down, distance, field = exact
            scrambles = outcomes.get('scramble', 0)
            league_scrambles += scrambles
            for name, key in {'exact_cell': exact, 'down_field': (down, field),
                              'down_distance': (down, distance), 'field_zone': field}.items():
                counts[name]['scrambles'][key] += scrambles
    else:
        for cell in pool.values():
            for event, row, _runoff, _spot in cell:
                if event != 'run' or row.get('qb_scramble') != 1:
                    continue
                exact = qb_decision_cell(row['down'], row['ydstogo'], row['yardline_100'])
                down, distance, field = exact
                league_scrambles += 1
                for name, key in {'exact_cell': exact, 'down_field': (down, field),
                                  'down_distance': (down, distance), 'field_zone': field}.items():
                    counts[name]['scrambles'][key] += 1
    if not league_scrambles:
        raise ValueError('run_scramble_backoff has no eligible historical QB scramble source rows')
    support = {name: {key: dict(counter) for key, counter in values.items()}
               for name, values in counts.items()}
    support['league_intent'] = {'scrambles': league_scrambles, 'dropbacks': league_dropbacks}
    return support


def qb_decision_cell(down, togo, yardline):
    import qb_decisions as qb_model
    return qb_model.cell_of(down, togo, yardline)


def scramble_bounds_from_pool(pool):
    """Observed maximum QB-scramble gain and loss, from eligible cutoff-safe source transitions."""
    rows = [row for cell in pool.values() for event, row, _runoff, _spot in cell
            if event == 'run' and row.get('qb_scramble') == 1
            and row.get('play_type') == 'run' and row.get('yards_gained') is not None
            and row.get('penalty') != 1 and row.get('two_point_attempt') != 1]
    if not rows:
        raise ValueError('run_scramble_backoff has no eligible historical QB scramble gains/losses')
    longest_gain = max(rows, key=lambda row: (int(row['yards_gained']), row['game_id'], int(row['play_id'])))
    longest_loss = min(rows, key=lambda row: (int(row['yards_gained']), row['game_id'], int(row['play_id'])))
    return {'max_gain_yards': max(0, int(longest_gain['yards_gained'])),
            'max_gain_source': {key: longest_gain[key] for key in ('game_id', 'play_id', 'season', 'week')},
            'max_loss_yards': max(0, -int(longest_loss['yards_gained'])),
            'max_loss_source': {key: longest_loss[key] for key in ('game_id', 'play_id', 'season', 'week')},
            'eligible_scramble_rows': len(rows), 'source_cutoff': 'target-season-before-week-1'}


def is_slc(ref):
    return isinstance(getattr(ref, 'contextual_sampler', None), slc.PlayCallSampler)


def _legal_turnover_on_downs(play, outcome):
    before = play.get('state_before') or {}
    after = play.get('state_after') or {}
    return (
        outcome.get('turnover_on_downs') is True
        and outcome.get('turnover') is True
        and before.get('down') == 4
        and after.get('offense_team') == before.get('defense_team')
        and after.get('defense_team') == before.get('offense_team')
    )


def _decision_resolves_to_event(decision, event):
    expected_event = decision.get('event')
    if expected_event == event:
        return True
    return (
        (expected_event, event) in (('punt', 'blocked_punt'),
                                    ('field_goal_attempt', 'blocked_field_goal'))
        and decision.get('intent') == 'kick'
        and decision.get('outcome_intent') == 'kick'
    )


def play(seed, ref, snapshot, *, paired_randomness=False):
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
                                                    qb_decision_table=sampler.qb_decision_table,
                                                    scramble_backoff_enabled=sampler.scramble_backoff_enabled)
    try:
        record = gs.play_game(seed, ref, pregame_snapshot=copy.deepcopy(snapshot),
                              paired_randomness=paired_randomness)
    finally:
        sampler.participant_chooser = None
    decisions = list(sampler.decisions)
    sampler.decisions.clear()
    validate_decision_outcomes(record, decisions, seed=seed, snapshot=snapshot)
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


PASS_RESULT_EVENTS = {'pass_complete', 'pass_incomplete', 'interception'}
LATERAL_SOURCE_FIELDS = ('lateral_receiver_player_id', 'lateral_receiving_yards',
                         'lateral_rusher_player_id', 'lateral_rushing_yards')


def _has_lateral_source(sampled):
    for field in LATERAL_SOURCE_FIELDS:
        value = sampled.get(field)
        if value is None or value == '':
            continue
        try:
            if math.isnan(float(value)):
                continue
        except (TypeError, ValueError):
            pass
        if value != 0:
            return True
    return False


def exclude_unmodeled_lateral_rows(pool, participant_facts):
    """Remove aggregate-yardage outcomes with lateral transfers before SLC sampling.

    E1 source rows carry game and play IDs but omit lateral columns. Resolve those IDs through the participant facts, loaded
    from the same cutoff-safe ``nfl_pbp`` window, so a lateral cannot leak through an apparently clean E1 row.
    """
    kept_pool = {}
    excluded = Counter()
    for cell_key, samples in pool.items():
        kept = []
        for event, row, runoff, spot in samples:
            try:
                source_key = (row.get('game_id'), int(float(row.get('play_id'))))
            except (TypeError, ValueError):
                source_key = None
            if source_key is not None and _has_lateral_source(participant_facts.get(source_key, {})):
                excluded[event] += 1
            else:
                kept.append((event, row, runoff, spot))
        if kept:
            kept_pool[cell_key] = kept
    return kept_pool, {'policy': 'exclude_unmodeled_lateral_transfers',
                       'rows_excluded': sum(excluded.values()),
                       'rows_excluded_by_event': dict(sorted(excluded.items()))}


def validate_decision_outcomes(record, decisions, *, seed, snapshot=None):
    """Refuse mismatches between a pre-outcome QB choice and the play/stat event it produced."""
    plays = [play for drive in record.get('drives', []) for play in drive.get('plays', [])]
    blocked_attempt = record.get('blocked_attempt') or {}
    partial_plays = blocked_attempt.get('plays_before_block') or []
    unrepresented_decisions = blocked_attempt.get('unrepresented_decisions') or []
    snapshot = snapshot or record.get('pregame_snapshot') or {}
    game_id = (snapshot.get('schedule') or {}).get('game_id') or record.get('game_id') or 'unknown'

    def fail(index, decision, play, reason, *, failure_class='ILLEGAL_STATE'):
        play = play or {}
        hashes = {
            'snapshot_sha256': snapshot.get('snapshot_sha256', 'unavailable'),
            'playcall_artifact_sha256': (decision or {}).get('artifact_sha256', 'unavailable'),
            'source': (decision or {}).get('source', 'unavailable'),
        }
        outcome = play.get('outcome') or {}
        detail = {
            'game_id': game_id, 'seed': seed, 'play_index': index,
            'state_before': play.get('state_before', 'unavailable'),
            'decision': decision or 'unavailable',
            'outcome': {'event_type': play.get('event_type'), 'yards_gained': outcome.get('yards_gained'),
                        'turnover': outcome.get('turnover'), 'touchdown': outcome.get('touchdown')},
            'state_after': play.get('state_after', 'unavailable'),
            'source_artifact_hashes': hashes,
        }
        raise football_assertions.FootballAssertionError(
            failure_class, reason, context=detail)

    expected_decisions = len(plays) + len(partial_plays) + len(unrepresented_decisions)
    if len(decisions) != expected_decisions:
        index = min(len(decisions), expected_decisions)
        evidence_play = (plays[index] if index < len(plays) else
                         partial_plays[index - len(plays)] if index - len(plays) < len(partial_plays) else None)
        fail(index, decisions[index] if index < len(decisions) else None, evidence_play,
             f'play-call decision count {len(decisions)} does not match {len(plays)} emitted and '
             f'{len(partial_plays)} blocked-attempt plays and {len(unrepresented_decisions)} unresolved decisions')
    if len(unrepresented_decisions) > 1:
        fail(len(plays) + len(partial_plays), unrepresented_decisions[0], None,
             f'blocked attempt contains {len(unrepresented_decisions)} unresolved play-call decisions; expected at most one')
    if unrepresented_decisions:
        unresolved = unrepresented_decisions[0]
        if not isinstance(unresolved, dict) or decisions[-1] != unresolved:
            fail(len(plays) + len(partial_plays), unresolved if isinstance(unresolved, dict) else None, None,
                 'unresolved blocked-attempt decision evidence does not match the final play-call decision')
        if (unresolved.get('decision_timing') != 'pre_outcome_sample'
                or unresolved.get('event') not in gs.reducer.EVENT_VOCABULARY):
            fail(len(plays) + len(partial_plays), unresolved, None,
                 'unresolved blocked-attempt decision has invalid timing or an unsupported event')

    for offset, (decision, play) in enumerate(zip(decisions[len(plays):], partial_plays), len(plays) + 1):
        event = play.get('event_type')
        if event not in gs.reducer.EVENT_VOCABULARY:
            fail(offset, decision, play, f'blocked-attempt play event {event!r} is outside the supported SLC rules vocabulary',
                 failure_class='UNSUPPORTED_RULE')
        if not _decision_resolves_to_event(decision, event):
            fail(offset, decision, play,
                 f'blocked-attempt decision event {decision.get("event")} disagrees with play event {event}')

    for index, (decision, play) in enumerate(zip(decisions, plays), 1):
        event = play.get('event_type')
        participants = play.get('participants') or {}
        selected = decision.get('participants') or {}
        outcome = play.get('outcome') or {}
        sampled = participants.get('sampled_play_context') or {}
        if record.get('pregame_snapshot'):
            decision_state = decision.get('state')
            allowed_state_fields = {
                'quarter', 'clock', 'down', 'togo', 'yardline_100', 'score_diff',
                'offense', 'defense', 'team',
            }
            if decision.get('decision_timing') != 'pre_outcome_sample' or not isinstance(decision_state, dict):
                fail(index, decision, play,
                     'SLC decision evidence must retain its pre-outcome state snapshot and timing boundary',
                     failure_class='NONCAUSAL_INFORMATION')
            if set(decision_state) != allowed_state_fields:
                fail(index, decision, play,
                     'SLC decision state contains missing or outcome-time fields',
                     failure_class='NONCAUSAL_INFORMATION')
            before = play.get('state_before') or {}
            offense_side = before.get('offense_team')
            if offense_side not in ('A', 'B'):
                fail(index, decision, play,
                     'SLC pre-outcome decision has no identifiable offense side',
                     failure_class='NONCAUSAL_INFORMATION')
            home_score, away_score = before.get('home_score'), before.get('away_score')
            if not isinstance(home_score, int) or not isinstance(away_score, int):
                fail(index, decision, play,
                     'SLC pre-outcome decision lacks the score available at the snap',
                     failure_class='NONCAUSAL_INFORMATION')
            expected_score_diff = home_score - away_score if offense_side == 'A' else away_score - home_score
            expected_state = {
                'quarter': before.get('quarter'), 'clock': before.get('clock_seconds'),
                'down': before.get('down'), 'togo': before.get('yards_to_go'),
                'yardline_100': before.get('yardline_100'), 'score_diff': expected_score_diff,
                'offense': before.get('offense_team'), 'defense': before.get('defense_team'),
            }
            mismatches = {key: (decision_state.get(key), value) for key, value in expected_state.items()
                          if decision_state.get(key) != value}
            if mismatches:
                fail(index, decision, play,
                     f'SLC decision used state that disagrees with the pre-snap game state: {mismatches}',
                     failure_class='NONCAUSAL_INFORMATION')
        called = decision.get('intent')
        outcome_intent = decision.get('outcome_intent', called)
        qb_action = decision.get('qb_action')
        if event not in gs.reducer.EVENT_VOCABULARY:
            fail(index, decision, play, f'play event {event!r} is outside the supported SLC rules vocabulary',
                 failure_class='UNSUPPORTED_RULE')
        if not _decision_resolves_to_event(decision, event):
            fail(index, decision, play, f'decision event {decision.get("event")} disagrees with play event {event}')

        if event in ('pass_complete', 'pass_incomplete', 'interception', 'run', 'fumble_lost') \
                and _has_lateral_source(sampled):
            fail(index, decision, play,
                 'lateral source outcomes are unsupported until every lateral player and yard is modeled',
                 failure_class='UNSUPPORTED_RULE')

        if (event in ('run', 'pass_complete', 'pass_incomplete', 'sack')
                and (outcome.get('turnover') or outcome.get('turnover_on_downs'))
                and not _legal_turnover_on_downs(play, outcome)):
            fail(index, decision, play,
                 'a scrimmage play turnover must be a legal fourth-down turnover on downs and transfer possession; '
                 'a lost fumble needs fumble_lost')

        realized_roles = {
            'pass_complete': ('passer', 'receiver'),
            'pass_incomplete': ('passer', 'receiver'),
            'interception': ('passer', 'receiver'),
            'sack': ('passer',),
            'run': ('rusher',),
        }.get(event)
        if qb_action == 'scramble' and event in PASS_RESULT_EVENTS:
            realized_roles = ()  # report the illegal play-type transition as ILLEGAL_STATE below
        if event == 'fumble_lost':
            realized_roles = tuple(
                role for role in ('passer', 'rusher', 'receiver')
                if participants.get(f'{role}_id') is not None
            )
        for role in realized_roles or ():
            chosen_id = selected.get(role)
            realized_id = participants.get(f'{role}_id')
            if chosen_id != realized_id:
                fail(index, decision, play,
                     f'pre-outcome {role} selection {chosen_id!r} disagrees with credited participant {realized_id!r}',
                     failure_class='STAT_ACCOUNTING')

        yards = outcome.get('yards_gained')
        if event == 'pass_incomplete':
            sampled_yards = [sampled.get(field) for field in ('passing_yards', 'receiving_yards')]
            if (yards != 0 or outcome.get('touchdown')
                    or any(value not in (None, 0, 0.0) for value in sampled_yards)):
                fail(index, decision, play,
                     'an incomplete pass must have zero gain, no score, and no credited pass or receiving yards')
        elif event == 'pass_complete':
            passing_yards, receiving_yards = sampled.get('passing_yards'), sampled.get('receiving_yards')
            if (passing_yards is not None and receiving_yards is not None
                    and passing_yards != receiving_yards):
                fail(index, decision, play,
                     'credited passing yards must equal the corresponding receiver yards on a completion')
            if outcome.get('touchdown'):
                before = play.get('state_before') or {}
                if (not isinstance(before.get('yardline_100'), int) or not isinstance(yards, int)
                        or yards < before['yardline_100'] or yards > before['yardline_100']):
                    fail(index, decision, play,
                         'a completed-pass touchdown must end at the goal line without exceeding credited yards')
                if outcome.get('scoring_team') not in (None, before.get('offense_team')):
                    fail(index, decision, play, 'a normal completed-pass touchdown must credit the offense')
        elif event == 'interception':
            if not outcome.get('turnover'):
                fail(index, decision, play, 'an interception must establish a change of possession')
            before = play.get('state_before') or {}
            after = play.get('state_after') or {}
            if (after.get('offense_team') != before.get('defense_team')
                    or after.get('defense_team') != before.get('offense_team')):
                fail(index, decision, play,
                     'an interception must transfer possession to the former defense')
            if outcome.get('touchdown'):
                fail(index, decision, play,
                     'interception-return touchdowns are outside the supported transition model',
                     failure_class='UNSUPPORTED_RULE')
            if any(sampled.get(field) not in (None, 0, 0.0)
                   for field in ('passing_yards', 'receiving_yards')):
                fail(index, decision, play,
                     'an interception cannot credit passing or receiving yards to the intended target')
        elif event == 'fumble_lost':
            if not outcome.get('turnover'):
                fail(index, decision, play, 'a fumble_lost event must establish a recovered change of possession')
            before = play.get('state_before') or {}
            after = play.get('state_after') or {}
            if (after.get('offense_team') != before.get('defense_team')
                    or after.get('defense_team') != before.get('offense_team')):
                fail(index, decision, play,
                     'a lost fumble must transfer possession to the classified recovery team')
            if outcome.get('touchdown'):
                fail(index, decision, play,
                     'fumble-return touchdowns are outside the supported transition model',
                     failure_class='UNSUPPORTED_RULE')
        elif event == 'sack':
            if isinstance(yards, (int, float)) and yards > 0:
                fail(index, decision, play, 'a sack cannot produce positive rushing or passing gain')
        elif event == 'run' and outcome.get('touchdown'):
            before = play.get('state_before') or {}
            if (not isinstance(before.get('yardline_100'), int) or not isinstance(yards, int)
                    or yards < before['yardline_100'] or yards > before['yardline_100']):
                fail(index, decision, play,
                     'a rushing touchdown must end at the goal line without exceeding credited yards')
            if outcome.get('scoring_team') not in (None, before.get('offense_team')):
                fail(index, decision, play, 'a normal rushing touchdown must credit the offense')

        if qb_action == 'scramble':
            passer = selected.get('passer')
            if (called != 'dropback' or outcome_intent != 'run' or event not in ('run', 'fumble_lost')
                    or not passer or selected.get('rusher') != passer or participants.get('rusher_id') != passer
                    or participants.get('receiver_id') is not None):
                fail(index, decision, play, 'a QB scramble must resolve as a QB rushing play without a pass target')
        elif called == 'dropback' and outcome_intent == 'run':
            fail(index, decision, play, 'a dropback cannot become a run without an explicit scramble decision')

        if event == 'sack':
            if (called != 'dropback' or qb_action == 'scramble' or not participants.get('passer_id')
                    or participants.get('receiver_id') is not None):
                fail(index, decision, play, 'a sack needs a passer, no target, and no pass-attempt credit')
        elif event in PASS_RESULT_EVENTS:
            if (called != 'dropback' or qb_action == 'scramble' or not participants.get('passer_id')
                    or not participants.get('receiver_id')
                    or participants.get('passer_id') == participants.get('receiver_id')):
                fail(index, decision, play, 'a pass result needs a dropback, passer and attributed target')
        elif event == 'run':
            if not participants.get('rusher_id'):
                fail(index, decision, play, 'a rushing outcome needs an attributed ball carrier')
            if called == 'dropback' and qb_action != 'scramble':
                fail(index, decision, play, 'a dropback cannot be relabeled as a designed run')

    for drive in record.get('drives', []):
        terminal = drive.get('terminal')
        if terminal not in ('touchdown', 'safety'):
            continue
        drive_plays = drive.get('plays') or []
        if not drive_plays and drive.get('observed_overtime_drive'):
            continue  # an observed overtime score has no play-level scorer to inspect
        if not drive_plays:
            fail(None, None, None, f'{terminal} drive has no scoring play')
        scoring_play = drive_plays[-1]
        index = next((position for position, row in enumerate(plays, 1) if row is scoring_play), None)
        decision = decisions[index - 1] if index is not None and index <= len(decisions) else None
        outcome = scoring_play.get('outcome') or {}
        event = scoring_play.get('event_type')
        before = scoring_play.get('state_before') or {}
        score_team = (drive.get('points_scored_on_drive') or {}).get('team')

        if terminal == 'touchdown':
            if not outcome.get('touchdown'):
                fail(index, decision, scoring_play, 'a touchdown terminal must be established by its final play')
            if event in ('run', 'pass_complete'):
                expected_scorer = drive.get('offense_team')
                if (drive.get('touchdown_scored_by') != expected_scorer
                        or (score_team is not None and score_team != expected_scorer)):
                    fail(index, decision, scoring_play,
                         'a normal rushing or receiving touchdown must credit the scoring offense')
            elif event in ('blocked_punt', 'blocked_field_goal'):
                expected_scorer = outcome.get('scoring_team')
                if (expected_scorer not in (before.get('offense_team'), before.get('defense_team'))
                        or drive.get('touchdown_scored_by') != expected_scorer
                        or (score_team is not None and score_team != expected_scorer)):
                    fail(index, decision, scoring_play,
                         'a blocked-kick touchdown scorer must match its classified recovery outcome')
            else:
                fail(index, decision, scoring_play,
                     f'touchdown event {event!r} has no supported scorer attribution',
                     failure_class='UNSUPPORTED_RULE')
        else:
            if event in ('run', 'pass_complete', 'sack'):
                yards = outcome.get('yards_gained')
                yardline = before.get('yardline_100')
                if (not outcome.get('safety') or not isinstance(yards, (int, float))
                        or not isinstance(yardline, int) or yardline - yards < 100):
                    fail(index, decision, scoring_play,
                         'a scrimmage safety requires the ball to become dead in the offense\'s own end zone')
                expected_scorer = before.get('defense_team')
                scoring_points = (drive.get('points_scored_on_drive') or {}).get('points')
                if score_team != expected_scorer or (scoring_points is not None and scoring_points != 2):
                    fail(index, decision, scoring_play, 'a scrimmage safety must credit the defense')
            elif event in ('blocked_punt', 'blocked_field_goal'):
                expected_scorer = outcome.get('scoring_team')
                if (not outcome.get('safety') or expected_scorer != before.get('defense_team')
                        or (score_team is not None and score_team != expected_scorer)):
                    fail(index, decision, scoring_play,
                         'a blocked-kick safety scorer must match its classified recovery outcome')
            else:
                fail(index, decision, scoring_play,
                     f'safety event {event!r} has no supported scoring transition',
                     failure_class='UNSUPPORTED_RULE')

    return {'status': 'passed', 'plays_checked': len(plays)}


def summary(decisions, record=None):
    target_decisions = [d for d in decisions if d.get('qb_target_role') is not None]
    fallbacks = Counter()
    situational_counts = Counter()
    for decision in decisions:
        state = decision.get('state') or {}
        if all(state.get(key) is not None for key in
               ('team', 'down', 'togo', 'yardline_100', 'score_diff', 'quarter', 'clock')):
            event = decision.get('event')
            if event in ('pass_complete', 'pass_incomplete', 'interception', 'sack', 'spike'):
                action = 'pass'
            elif event == 'run' or (event == 'fumble_lost' and decision.get('outcome_intent') == 'run'):
                action = 'run'
            elif event == 'fumble_lost':
                action = 'pass'
            elif event == 'punt' or event == 'blocked_punt':
                action = 'punt'
            elif event in ('field_goal_attempt', 'blocked_field_goal'):
                action = 'field_goal'
            else:
                action = 'other'
            distance = pm.DISTANCE_BUCKETS[pm.distance_bucket(int(state['togo']))][2]
            field = pm.FIELD_BUCKETS[pm.field_bucket(int(state['yardline_100']))]
            score = pm.SCORE_BUCKETS[pm.score_bucket(int(state['score_diff']))]
            clock = pm.CLOCK_BUCKETS[pm.clock_bucket(int(state['quarter']), int(state['clock']))]
            situational_counts[(str(state['team']), int(state['quarter']), int(state['down']), distance,
                                field, score, clock, action)] += 1
        if decision.get('fallback'):
            fallbacks[str(decision['fallback'])] += 1
        for key in ('qb_scramble_fallback', 'qb_target_role_fallback', 'qb_target_role_draw_fallback',
                    'exact_yardline_fallback', 'formation_fallback', 'coverage_fallback', 'streak_fallback'):
            if decision.get(key):
                fallbacks[str(decision[key])] += 1
        for category in decision.get('labels_unmatched', []):
            fallbacks[f'decision_row_missing_category_{category}'] += 1
        for fallback in decision.get('team_outcome_fallbacks', []):
            fallbacks[str(fallback)] += 1
        for category in (decision.get('participants') or {}).get('playbook_fallback', []):
            fallbacks[f'playbook_missing_category_{category}'] += 1
        for role, support in (decision.get('player_outcome_support') or {}).items():
            if not support:
                fallbacks[f'player_outcome_no_history_{role}'] += 1
    result = {'decisions': len(decisions),
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
            'player_outcome_zero_support_roles': sum(
                not support for d in decisions for support in (d.get('player_outcome_support') or {}).values()),
            'kick_fallback': sum(d['intent'] == 'kick' for d in decisions),
            'situational_decision_counts': [
                {'team': team, 'quarter': quarter, 'down': down, 'distance_bucket': distance,
                 'field_bucket': field, 'score_bucket': score, 'clock_bucket': clock,
                 'action': action, 'count': count}
                for (team, quarter, down, distance, field, score, clock, action), count
                in sorted(situational_counts.items())],
            'layer_execution': {
                'score_clock_playcalling': len(decisions),
                'team_offense_defense_outcomes': sum(bool(d.get('team_outcome_split')) for d in decisions),
                'formation_personnel_outcomes': sum(bool(d.get('formation_conditioned')) for d in decisions),
                'defensive_coverage_outcomes': sum(bool(d.get('coverage_conditioned')) for d in decisions),
                'fixed_player_target_carry_shares': sum(
                    (d.get('participants') or {}).get('participant_share_model') == 'fixed_player_share'
                    for d in decisions),
                'dirichlet_player_target_carry_shares': sum(
                    (d.get('participants') or {}).get('participant_share_model') == 'dirichlet_multinomial'
                    for d in decisions),
                'qb_decisions': sum(d.get('qb_action') is not None for d in decisions),
                'player_conditioned_outcomes': sum(bool(d.get('player_outcomes_conditioned')) for d in decisions),
                'target_role_priors': sum(bool((d.get('participants') or {}).get('target_role_prior_used'))
                                          for d in decisions),
                'decision_labels': sum(bool(d.get('labels_conditioned')) for d in decisions),
                'decision_row_filter': sum(bool(d.get('decision_row_filter_applied')) for d in decisions),
                'decision_row_filter_matches': sum(bool(d.get('labels_matched')) for d in decisions),
                'playbook_priors': sum(bool((d.get('participants') or {}).get('playbook_used')) for d in decisions),
                'point_splits_evaluated': sum(bool(d.get('point_split_applied')) for d in decisions),
                'point_splits_nonzero': sum(bool(d.get('point_shift')) for d in decisions),
                'team_streak_splits_evaluated': sum(bool(d.get('team_streak_split_applied')) for d in decisions),
                'team_streak_splits_nonzero': sum(bool(d.get('streak_shift')) for d in decisions),
                'league_streak_splits_evaluated': sum(bool(d.get('league_streak_split_applied')) for d in decisions),
                'league_streak_splits_nonzero': sum(bool(d.get('league_streak_shift')) for d in decisions),
                'exact_yardline_outcomes': sum(bool(d.get('exact_yardline_conditioned')) for d in decisions),
                'current_streak_context': sum(d.get('streak_bucket') is not None for d in decisions),
            },
            'fallback_events': dict(sorted(fallbacks.items()))}
    fixes = sorted({fix for decision in decisions for fix in decision.get('blocker_fixes', [])})
    if fixes:
        result['blocker_resolution'] = _blocker_resolution_summary(decisions, fixes, record)
    return result


def _blocker_resolution_summary(decisions, fixes, record=None):
    outcome_fallbacks = Counter(d.get('outcome_fallback') for d in decisions if d.get('outcome_fallback'))
    scramble_outcome_fallbacks = Counter(
        d.get('outcome_fallback') for d in decisions
        if d.get('outcome_class') == 'qb_scramble' and d.get('outcome_fallback'))
    scramble_decision_fallbacks = Counter(d.get('qb_scramble_fallback') for d in decisions
                                          if d.get('qb_scramble_fallback'))
    scramble_support_levels = Counter(d.get('scramble_support_level') for d in decisions
                                      if d.get('scramble_support_level'))
    fg_fallbacks = Counter(d.get('fg_fallback_level') for d in decisions if d.get('fg_fallback_level'))
    geometry_categories = Counter(d.get('blocked_kick_geometry_category') for d in decisions
                                  if d.get('blocked_kick_geometry_category'))
    period_expired_exclusions = Counter()
    for decision in decisions:
        period_expired_exclusions.update(decision.get('blocked_kick_period_expired_exclusions') or {})
    usage = defaultdict(lambda: {'count': 0, 'support': []})

    def add_usage(kind, level, decision, support):
        state = decision.get('state') or {}
        key = (kind, level, state.get('team'), state.get('down'),
               e0.ydstogo_bucket(state['togo']) if state.get('togo') is not None else None,
               e0.yardline_bucket(state['yardline_100']) if state.get('yardline_100') is not None else None)
        usage[key]['count'] += 1
        if support is not None:
            usage[key]['support'].append(int(support))

    for decision in decisions:
        if decision.get('outcome_fallback'):
            kind = 'scramble_outcome' if decision.get('outcome_class') == 'qb_scramble' else 'outcome'
            add_usage(kind, decision['outcome_fallback'], decision,
                      decision.get('outcome_fallback_support_n'))
        if decision.get('qb_scramble_fallback'):
            add_usage('scramble_decision', decision['qb_scramble_fallback'], decision,
                      decision.get('scramble_fallback_support_n'))
        if decision.get('fg_fallback_level'):
            add_usage('field_goal', decision['fg_fallback_level'], decision,
                      decision.get('fg_distribution_support_n'))
    usage_rows = []
    for key, value in sorted(usage.items(), key=lambda item: tuple('' if x is None else str(x) for x in item[0])):
        kind, level, team, down, distance, field = key
        supports = value['support']
        usage_rows.append({'kind': kind, 'level': level, 'team': team, 'down': down,
                           'distance_bucket': distance, 'field_zone_bucket': field, 'count': value['count'],
                           'support_n': ({'min': min(supports), 'mean': round(sum(supports) / len(supports), 2),
                                          'max': max(supports)} if supports else None)})
    kick_outcomes = [play.get('outcome', {}).get('blocked_kick')
                     or play.get('outcome', {}).get('kick_outcome') or {}
                     for drive in (record or {}).get('drives', []) for play in drive.get('plays', [])]
    audited_transitions = sum(bool(outcome.get('source_audit_ref')) for outcome in kick_outcomes)
    safety_kicks = sum(event.get('kind') == 'safety_free_kick' for event in (record or {}).get('kickoffs', []))
    return {
        'enabled_fixes': fixes,
        'outcome_fallback_level': dict(sorted(outcome_fallbacks.items())),
        'scramble_outcome_fallback_level': dict(sorted(scramble_outcome_fallbacks.items())),
        'scramble_decision_fallback_level': dict(sorted(scramble_decision_fallbacks.items())),
        'scramble_support_level': dict(sorted(scramble_support_levels.items())),
        'scramble_rejected_bounds': sum(int(d.get('scramble_rejected_bounds', 0)) for d in decisions),
        'scramble_eligible_candidates': sum(int(d.get('scramble_eligible_candidates', 0)) for d in decisions),
        'fg_rejected_distance': sum(bool(d.get('fg_rejected_distance')) for d in decisions),
        'fg_rejection_reason': dict(sorted(Counter(d['fg_rejection_reason'] for d in decisions
                                                     if d.get('fg_rejection_reason')).items())),
        'fg_long_range_exception': sum(bool(d.get('fg_long_range_exception')) for d in decisions),
        'fg_fallback_level': dict(sorted(fg_fallbacks.items())),
        'blocked_kick_geometry_categories': dict(sorted(geometry_categories.items())),
        'blocked_kick_period_expired_category_exclusions': dict(sorted(period_expired_exclusions.items())),
        'blocked_kick_geometry_rejected': sum(
            int(d.get('blocked_kick_geometry_candidates') == 0) for d in decisions
            if d.get('blocked_kick_geometry_category')),
        'blocked_kick_source_audit_transitions': audited_transitions,
        'safety_free_kicks': safety_kicks,
        'fallback_usage': usage_rows,
    }


def describe(ref):
    """The layer's manifest for a batch payload: None for the S0 control."""
    if not is_slc(ref):
        return None
    sampler = ref.contextual_sampler
    artifact = sampler.layer.artifact
    decision_enabled = bool(sampler.decision_outcomes)
    enabled_layers = {
        'score_clock_playcalling': True,
        'team_offense_defense_outcomes': sampler.team_outcomes is not None,
        'formation_personnel_outcomes': bool(sampler.formation_outcomes),
        'defensive_coverage_outcomes': bool(sampler.coverage_outcomes),
        'fixed_player_target_carry_shares': sampler.player_shares is not None,
        'dirichlet_player_target_carry_shares': sampler.share_table is not None,
        'qb_decisions': sampler.qb_decision_table is not None,
        'player_conditioned_outcomes': sampler.player_outcome_table is not None,
        'target_role_priors': sampler.role_table is not None,
        'decision_labels': decision_enabled,
        'decision_row_filter': bool(decision_enabled and sampler.decision_filter),
        'playbook_priors': sampler.playbook_table is not None,
        'point_splits': sampler.point_shifts is not None,
        'team_streak_splits': sampler.streak_shifts is not None,
        'league_streak_splits': sampler.streak_league is not None,
        'exact_yardline_outcomes': bool(sampler.exact_yardline),
        'current_streak_context': bool(sampler.current_streak),
    }
    reference_sha = (getattr(ref, 'model_inputs', None) or {}).get('sha256')
    component_values = {
        'score_clock_playcalling': {'artifact_sha256': artifact['sha256']},
        'team_offense_defense_outcomes': sampler.team_outcomes,
        'formation_personnel_outcomes': {'priors': sampler.formation_priors,
                                        'outcomes_enabled': sampler.formation_outcomes},
        'defensive_coverage_outcomes': {'priors': sampler.defense_priors,
                                      'outcomes_enabled': sampler.coverage_outcomes},
        'fixed_player_target_carry_shares': sampler.player_shares,
        'dirichlet_player_target_carry_shares': sampler.share_table,
        'qb_decisions': sampler.qb_decision_table,
        'player_conditioned_outcomes': {'table': sampler.player_outcome_table,
                                        'roles': sampler.player_outcome_roles},
        'target_role_priors': sampler.role_table,
        'decision_labels': {'table': sampler.decision_table, 'enabled': sampler.decision_outcomes,
                            'source_files': {key: value for key, value in sampler.optional_input_sha256.items()
                                             if key.startswith('decision_source:')}},
        'decision_row_filter': {'artifact_sha256': artifact['sha256'], 'enabled': bool(sampler.decision_filter)},
        'playbook_priors': {'table': sampler.playbook_table,
                            'files': {key: value for key, value in sampler.optional_input_sha256.items()
                                      if key.startswith('playbook:')}},
        'point_splits': sampler.point_shifts,
        'team_streak_splits': sampler.streak_shifts,
        'league_streak_splits': sampler.streak_league,
        'exact_yardline_outcomes': {'reference_sha256': reference_sha,
                                    'rule': 'exact yard line inside the 20 where source rows exist'},
        'current_streak_context': {'file_sha256': sampler.optional_input_sha256.get('current_streak_file'),
                                   'current_streak': sampler.current_streak},
    }
    layer_artifact_sha256 = {
        key: (_model_hash(value) if value is not None else None)
        for key, value in component_values.items()
    }
    layer_artifact_sha256['score_clock_playcalling'] = artifact['sha256']
    description = {'model_id': model_id(ref), 'artifact_id': artifact['artifact_id'], 'artifact_sha256': artifact['sha256'],
                   'fit_seasons': sorted(int(s) for s in artifact['fit_seasons']),
                   'reference_season': int(artifact['reference_season']), 'side_teams': sampler.describe().get('side_teams'),
                   'source_cutoff': getattr(sampler, 'source_cutoff', None), 'reference_sha256': reference_sha,
                   'layer_artifact_sha256': layer_artifact_sha256, 'enabled_layers': enabled_layers,
                   'optional_input_sha256': dict(sorted(getattr(sampler, 'optional_input_sha256', {}).items()))}
    if sampler.blocker_fixes:
        description['blocker_resolution'] = {
                       'enabled_fixes': sorted(sampler.blocker_fixes),
                       'fg_ordinary_cutoff_yards': sampler.fg_ordinary_cutoff,
                       'fg_distance_model': ref.kicks.get('field_goal_distance_model'),
                       'scramble_historical_bounds': sampler.scramble_bounds,
                       'blocked_kick_fixture_sha256': ref.blocked_kicks.get('sha256'),
                       'safety_kick_fixture_sha256': ref.safety_kick_sha256,
                   }
    share_manifest = getattr(sampler, 'share_model_manifest', None)
    if share_manifest is not None:
        description['player_share_distribution'] = share_manifest
    qb_manifest = getattr(sampler, 'qb_decision_manifest', None)
    if qb_manifest is not None:
        description['qb_decision_model'] = qb_manifest
    outcome_manifest = getattr(sampler, 'player_outcome_manifest', None)
    if outcome_manifest is not None:
        description['player_outcome_model'] = outcome_manifest
    integration_files = ('clock_d.py', 'e1_drive.py', 'e2_reference.py', 'game_state.py', 'game_stats.py', 'pre_event.py',
                         'playcall_model.py',
                         'team_tendency.py', 'formation_layer.py', 'defense_layer.py', 'point_splits.py',
                         'streak_splits.py', 'target_roles.py', 'decision_layer.py', 'player_shares.py',
                         'share_distributions.py', 'qb_decisions.py', 'player_outcomes.py', 'playbook_prior.py',
                         'paired_random_streams.py', 'run_slc_game.py', 'simulate_pregame_batch.py',
                         'slc_engine.py', 'slc_playcall.py')
    description['integration_code_sha256'] = {
        name: _file_sha256(HERE / name) for name in integration_files if (HERE / name).exists()
    }
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
