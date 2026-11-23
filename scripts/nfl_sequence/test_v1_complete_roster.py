import pytest

import roster_resolution as rr
from v1_complete_roster import eligible_ids, require_participants


def test_resolved_eligibility_excludes_out_inactive_reserve_and_unelevated():
    def row(player_id, membership='ACTIVE_ROSTER', injury=None):
        return {'gsis_id': player_id, 'name': player_id, 'pos': 'WR', 'depth_rank': None,
                'membership': membership, 'injury': injury, 'observed_utc': '2026-11-21T12:00:00Z'}

    rows = [row('active'), row('out', injury='OUT'), row('inactive'), row('reserve', 'RESERVE'),
            row('practice', 'PRACTICE_SQUAD'), row('elevated', 'PRACTICE_SQUAD')]
    events = [{'id': 'elevate', 'gsis_id': 'elevated', 'kind': 'elevation',
               'observed_utc': '2026-11-22T10:00:00Z'}]
    result = rr.resolve_team('game', 'TEAM', '2026-11-22T16:00:00Z', rows, events, [], inactives=['inactive'])
    assert eligible_ids(result) == {'active', 'elevated'}
    require_participants(result, ['active', 'elevated'])
    for player in ('out', 'inactive', 'reserve', 'practice', 'unknown'):
        with pytest.raises(ValueError, match='v1_complete_roster_ineligible_participant'):
            require_participants(result, [player])


def test_projected_elevation_cannot_fill_a_required_role():
    rows = [{'gsis_id': 'pk', 'name': 'pk', 'pos': 'K', 'depth_rank': 1,
             'membership': 'PRACTICE_SQUAD', 'injury': None, 'observed_utc': '2026-11-21T12:00:00Z'}]
    roles = [{'role': 'PK', 'positions': ['K'], 'required': True, 'kind': 'PK'}]
    result = rr.resolve_team('game', 'TEAM', '2026-11-22T16:00:00Z', rows, [], roles)
    assert result['roles'][0]['status'] == 'PROJECTED'
    with pytest.raises(ValueError, match='v1_complete_roster_unresolved_role:PK'):
        eligible_ids(result)


def test_inconsistent_multiple_role_records_fail_closed():
    result = {'schema': 'lp-nfl-resolved-roster-2', 'blocks': [], 'roles': [], 'players': [
        {'gsis_id': 'p', 'official_eligible': True, 'membership': 'ACTIVE_ROSTER', 'exclusion_reason': None},
        {'gsis_id': 'p', 'official_eligible': False, 'membership': 'RESERVE', 'exclusion_reason': 'membership_reserve'}]}
    with pytest.raises(ValueError, match='v1_complete_roster_conflicting_eligibility'):
        eligible_ids(result)
