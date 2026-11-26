"""Compact, replayable evidence records for live GridIron executions."""
import hashlib
import json


def compact_live_execution(execution):
    """Keep deterministic replay inputs and compact integrity evidence for a live result."""
    if not isinstance(execution, dict):
        return execution
    compact = dict(execution)
    if compact.get('viewer') == 'gridiron_result.trajectory.frames':
        compact['viewer'] = 'rerun_stored_call_for_gridiron_result.trajectory.frames'
    call = execution.get('call')
    if isinstance(call, dict) and isinstance(call.get('player_profiles'), dict):
        profiles = call['player_profiles']
        compact_call = dict(call)
        compact_call.pop('player_profiles', None)
        compact_call['player_profile_ids'] = sorted(profiles)
        compact_call['player_profiles_sha256'] = hashlib.sha256(
            json.dumps(profiles, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
        special_ratings = {
            pid: {name: value for name, value in (profile.get('ratings') or {}).items()
                  if name in ('KPW', 'KAC')}
            for pid, profile in profiles.items()
            if any(name in (profile.get('ratings') or {}) for name in ('KPW', 'KAC'))
        }
        if special_ratings:
            compact_call['player_special_ratings'] = special_ratings
        compact['call'] = compact_call
    result = execution.get('result')
    if not isinstance(result, dict):
        return compact
    compact_result = dict(result)
    compact_result['replay_result_sha256'] = hashlib.sha256(
        json.dumps(result, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    # The call already lives on the outer execution record. Keeping its duplicate
    # inside the result is costly and adds no replay information.
    compact_result.pop('call', None)
    events = compact_result.pop('events', None)
    if isinstance(events, list):
        assignment_player_ids = sorted({
            event.get('player_id') for event in events
            if isinstance(event, dict) and event.get('type') == 'assignment_executed'
            and isinstance(event.get('player_id'), str)
        })
        event_types = {}
        for event in events:
            if isinstance(event, dict) and isinstance(event.get('type'), str):
                kind = event['type']
                event_types[kind] = event_types.get(kind, 0) + 1
        compact_result['event_summary'] = {
            'count': len(events),
            'types': dict(sorted(event_types.items())),
            'assignment_player_ids': assignment_player_ids,
            'sha256': hashlib.sha256(
                json.dumps(events, sort_keys=True, separators=(',', ':')).encode()).hexdigest(),
        }
    diagnostics = result.get('diagnostics')
    if isinstance(diagnostics, dict):
        compact_diagnostics = dict(diagnostics)
        if 'agent_decisions' in compact_diagnostics:
            compact_diagnostics['agent_decision_count'] = len(compact_diagnostics.pop('agent_decisions'))
        player_execution = compact_diagnostics.pop('player_execution', None)
        if isinstance(player_execution, list):
            compact_diagnostics['player_execution_count'] = len(player_execution)
            compact_diagnostics['player_execution_sha256'] = hashlib.sha256(
                json.dumps(player_execution, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
        compact_result['diagnostics'] = compact_diagnostics
    trajectory = result.get('trajectory')
    if isinstance(trajectory, dict) and isinstance(trajectory.get('frames'), list):
        compact_trajectory = {key: value for key, value in trajectory.items() if key != 'frames'}
        roster = compact_trajectory.pop('roster', None)
        if isinstance(roster, list):
            compact_trajectory['player_ids'] = sorted(
                row['id'] for row in roster if isinstance(row, dict) and isinstance(row.get('id'), str))
        compact_trajectory.update({'frame_count': len(trajectory['frames']),
                                   'frames_omitted': True,
                                   'replay_from_stored_call': True})
        compact_result['trajectory'] = compact_trajectory
    compact['result'] = compact_result
    provenance = execution.get('provenance')
    if isinstance(provenance, dict) and isinstance(provenance.get('player_rating_sources'), dict):
        compact_provenance = dict(provenance)
        sources = compact_provenance.pop('player_rating_sources')
        compact_provenance['player_rating_sources_summary'] = {
            'count': len(sources),
            'sha256': hashlib.sha256(json.dumps(
                sources, sort_keys=True, separators=(',', ':')).encode()).hexdigest(),
            'source_classes': sorted({(row.get('source_class'), row.get('evidence_source_class'))
                                      for row in sources.values()}),
        }
        compact['provenance'] = compact_provenance
    return compact
