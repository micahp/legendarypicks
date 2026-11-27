import pytest

import roster_resolution as rr
import roster_preflight
from v1_complete_roster import eligible_ids, eligible_rows, require_participants
import gridiron_bridge


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


def test_membership_only_players_supply_line_and_defensive_roles():
    def player(pid, pos, rank=None, eligible=True):
        return {'gsis_id': pid, 'name': pid, 'pos': pos, 'depth_rank': rank,
                'official_eligible': eligible, 'membership': 'ACTIVE_ROSTER',
                'exclusion_reason': None if eligible else 'injury_out'}
    offense = {'schema': 'lp-nfl-resolved-roster-2', 'blocks': [], 'roles': [], 'team': 'AAA',
               'players': [player('lt', 'LT', 1), player('lg', 'LG', 1), player('c', 'C', 1),
                           player('rg', 'RG', 1), player('backup', 'OL'), player('out', 'OL', eligible=False)]}
    rows = eligible_rows(offense)
    assert {r['gsis_id'] for r in rows} == {'lt', 'lg', 'c', 'rg', 'backup'}
    with pytest.raises(TypeError):
        rows[0]['team'] = 'BBB'
    assert gridiron_bridge._add_offensive_line({}, rows)['backup'] == 'RT'
    defense = {'schema': 'lp-nfl-resolved-roster-2', 'blocks': [], 'roles': [], 'team': 'BBB',
               'players': [player('dl' + str(i), 'DL') for i in range(4)]
                          + [player('lb' + str(i), 'LB') for i in range(2)]
                          + [player('db' + str(i), 'DB') for i in range(5)]}
    assert len(gridiron_bridge._defensive_lineup(defense, eligible_rows(defense))) == 11


def test_postflight_rejects_unknown_wrong_team_and_excluded_players():
    def team(name, qb, extra):
        return {'team': name, 'roles': [{'role': 'QB1', 'gsis_id': qb}], 'players': [
            {'gsis_id': qb, 'official_eligible': True, 'membership': 'ACTIVE_ROSTER', 'exclusion_reason': None},
            extra]}
    active = {'gsis_id': 'member', 'official_eligible': True, 'membership': 'ACTIVE_ROSTER', 'exclusion_reason': None}
    out = {'gsis_id': 'out', 'official_eligible': False, 'membership': 'ACTIVE_ROSTER', 'exclusion_reason': 'injury_out', 'name': 'Out'}
    resolved = {'home': team('AAA', 'qa', active), 'away': team('BBB', 'qb', out)}
    snapshot = {'rosters': {'home': {'team': 'AAA'}, 'away': {'team': 'BBB'}}}
    def row(pid, club, att=0):
        return {'player_id': pid, 'player_team': club, 'player_name': pid, 'passing': {'att': att}}
    players = [row('qa', 'AAA', 1), row('qb', 'BBB', 1), row('member', 'AAA')]
    assert not roster_preflight.failed(roster_preflight.postflight(snapshot, {'player_boxscores_by_seed': [{'players': players}]}, resolved))
    for bad in (row('unknown', 'AAA'), row('member', 'BBB'), row('out', 'BBB'), row('qa', 'OTHER')):
        checks = roster_preflight.postflight(snapshot, {'player_boxscores_by_seed': [{'players': players + [bad]}]}, resolved)
        assert any(name == 'player box scores belong to eligible team rosters' and status == 'FAIL'
                   for name, status, _ in checks)


@pytest.mark.parametrize(('schedule_team', 'roster_team', 'weekly_team'), [
    ('LA', 'LA', 'LA'), ('LAR', 'LAR', 'LA'), ('WAS', 'WAS', 'WAS'), ('WSH', 'WSH', 'WAS'),
])
def test_weekly_membership_attachment_normalizes_nflverse_aliases(schedule_team, roster_team, weekly_team):
    snapshot = {'schedule': {'week': 12, 'away_team': schedule_team, 'home_team': 'GB'}, 'rosters': {
        'away': {'team': roster_team, 'players': []},
        'home': {'team': 'GB', 'players': []},
    }}
    weekly = [{'team': weekly_team, 'week': 12, 'gsis_id': 'player-1', 'full_name': 'Player One',
               'position': 'WR', 'status': 'ACT', 'status_description_abbr': 'A01'},
              {'team': 'GB', 'week': 12, 'gsis_id': 'player-2', 'full_name': 'Player Two',
               'position': 'QB', 'status': 'ACT', 'status_description_abbr': 'A01'}]

    attached = roster_preflight.attach_membership(snapshot, weekly, 'weekly-rosters-test')

    assert attached['rosters']['away']['membership']['players'][0]['gsis_id'] == 'player-1'
    assert attached['rosters']['home']['membership']['players'][0]['gsis_id'] == 'player-2'
    assert attached['schedule']['away_team'] == schedule_team


def test_injury_report_capture_time_is_not_confused_with_row_publish_time():
    cutoff = roster_preflight._utc('2026-11-25T20:00:00Z')
    report = {'players': [{'gsis_id': 'p', 'report_status': 'Questionable'}],
              'source_timestamp_semantics': 'hash_pinned_source_capture',
              'source_available_utc': '2026-11-25T19:56:09Z', 'source_sha256': 'a' * 64}

    ok, count, missing, late, captured = roster_preflight._injury_report_applies(report, cutoff)

    assert (ok, count, missing, late, captured) == (
        True, 1, 1, 0, '2026-11-25T19:56:09Z')


def test_injury_report_capture_after_cutoff_is_rejected():
    cutoff = roster_preflight._utc('2026-11-25T20:00:00Z')
    report = {'players': [{'gsis_id': 'p', 'report_status': 'Questionable'}],
              'source_timestamp_semantics': 'hash_pinned_source_capture',
              'source_available_utc': '2026-11-25T20:00:01Z', 'source_sha256': 'a' * 64}

    assert roster_preflight._injury_report_applies(report, cutoff)[0] is False
