"""Tests for the 2025 depth-chart snapshot adapter (SLC v2 research, owner ruling B).

Synthetic rows test each rule in isolation. The integration tests read the real publisher file and fail loudly if it is absent.
"""
import datetime as dt
import os
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import depth_adapter as da  # noqa: E402

RAW = '/root/gridiron-playbooks-research/data/raw'
DEPTH_FILE = os.path.join(RAW, 'depth_charts_2025.parquet')
PLAYERS_FILE = os.path.join(RAW, 'players.csv')
UTC = dt.timezone.utc


def ts(text):
    return dt.datetime.strptime(text, '%Y-%m-%dT%H:%M:%S').replace(tzinfo=UTC)


def row(snap, team='KC', espn='1', gsis='G1', grp='3WR 1TE', slot='QB', rank=1, name='Player'):
    return {'dt': ts(snap), 'team': team, 'player_name': name, 'espn_id': espn, 'gsis_id': gsis,
            'pos_grp': grp, 'pos_slot': slot, 'pos_rank': rank, 'pos_abb': slot, 'pos_name': slot,
            'source_sha256': 'synthetic'}


INDEX = da.identity_index(
    gsis_ids={'G1', 'G2', 'G3', 'G4'},
    espn_to_gsis={'1': {'G1'}, '2': {'G2'}, '3': {'G3', 'G9'}, '4': {'G4'}},
)


# Temporal selection

def test_latest_snapshot_is_latest_dt_at_or_before_cutoff():
    rows = [row('2025-09-01T10:00:00', gsis='G1'), row('2025-09-05T10:00:00', gsis='G2')]
    snap, staleness = da.latest_snapshot(rows, 'KC', ts('2025-09-06T00:00:00'))
    assert snap == ts('2025-09-05T10:00:00')
    assert staleness == dt.timedelta(hours=14)


def test_snapshot_exactly_at_cutoff_is_eligible():
    rows = [row('2025-09-05T10:00:00')]
    snap, staleness = da.latest_snapshot(rows, 'KC', ts('2025-09-05T10:00:00'))
    assert snap == ts('2025-09-05T10:00:00')
    assert staleness == dt.timedelta(0)


def test_no_snapshot_before_cutoff_gives_empty_state_not_a_later_one():
    rows = [row('2026-03-14T07:00:00')]
    state = da.depth_state(rows, 'KC', ts('2025-09-07T12:00:00'), INDEX, source_sha256='x')
    assert state['snapshot_dt'] is None
    assert state['entries'] == []
    assert state['reason'] == 'no_snapshot_before_cutoff'


def test_march_snapshot_never_describes_a_september_roster():
    rows = [row('2025-09-01T10:00:00', gsis='G1'), row('2026-03-14T07:00:00', gsis='G2')]
    state = da.depth_state(rows, 'KC', ts('2025-09-07T12:00:00'), INDEX, source_sha256='x')
    assert state['snapshot_dt'] == ts('2025-09-01T10:00:00')
    assert [e['gsis_id'] for e in state['entries']] == ['G1']


def test_team_change_visible_only_after_its_snapshot():
    rows = [
        row('2025-09-01T10:00:00', team='KC', espn='2', gsis='G2'),
        row('2025-09-08T10:00:00', team='BUF', espn='2', gsis='G2'),
    ]
    before = da.depth_state(rows, 'BUF', ts('2025-09-05T00:00:00'), INDEX, source_sha256='x')
    after = da.depth_state(rows, 'BUF', ts('2025-09-09T00:00:00'), INDEX, source_sha256='x')
    old_team = da.depth_state(rows, 'KC', ts('2025-09-09T00:00:00'), INDEX, source_sha256='x')
    assert before['entries'] == []
    assert [e['gsis_id'] for e in after['entries']] == ['G2']
    assert old_team['entries'] == [], 'the old team must not keep a player after the later snapshot'


def test_team_snapshot_behind_the_league_is_reported_not_used():
    rows = [row('2025-09-01T10:00:00', team='KC', gsis='G1'), row('2025-09-08T10:00:00', team='BUF', gsis='G2')]
    state = da.depth_state(rows, 'KC', ts('2025-09-09T00:00:00'), INDEX, source_sha256='x')
    assert state['reason'] == 'team_snapshot_behind_series'
    assert state['entries'] == []
    assert state['team_latest_dt'] == ts('2025-09-01T10:00:00')
    assert state['series_latest_dt'] == ts('2025-09-08T10:00:00')


# Staleness

def test_staleness_is_cutoff_minus_snapshot():
    rows = [row('2025-09-01T10:00:00')]
    state = da.depth_state(rows, 'KC', ts('2025-09-03T10:00:00'), INDEX, source_sha256='x')
    assert state['staleness_seconds'] == 2 * 24 * 3600


def test_staleness_is_never_negative():
    rows = [row('2025-09-01T10:00:00'), row('2025-09-20T10:00:00')]
    state = da.depth_state(rows, 'KC', ts('2025-09-10T00:00:00'), INDEX, source_sha256='x')
    assert state['staleness_seconds'] >= 0


# Identity

def test_gsis_match_when_present_and_verified():
    status, gsis = da.resolve_identity(row('2025-09-01T10:00:00', espn='1', gsis='G1'), INDEX)
    assert (status, gsis) == ('gsis', 'G1')


def test_gsis_not_in_index_is_unverified_and_keeps_the_raw_id():
    status, gsis = da.resolve_identity(row('2025-09-01T10:00:00', espn='1', gsis='G99'), INDEX)
    assert status == 'gsis_unverified'
    assert gsis is None


def test_missing_gsis_resolves_through_a_unique_espn_id():
    status, gsis = da.resolve_identity(row('2025-09-01T10:00:00', espn='2', gsis=None), INDEX)
    assert (status, gsis) == ('espn_unique', 'G2')


def test_ambiguous_espn_id_is_not_matched():
    status, gsis = da.resolve_identity(row('2025-09-01T10:00:00', espn='3', gsis=None), INDEX)
    assert status == 'ambiguous'
    assert gsis is None


def test_espn_id_absent_from_the_index_is_unmatched():
    status, gsis = da.resolve_identity(row('2025-09-01T10:00:00', espn='404', gsis=None), INDEX)
    assert status == 'unmatched'
    assert gsis is None


def test_name_alone_never_matches_a_player():
    named = row('2025-09-01T10:00:00', espn='404', gsis=None, name='G2 Named Player')
    status, gsis = da.resolve_identity(named, INDEX)
    assert status == 'unmatched'
    assert gsis is None


# Duplicates and roles

def test_duplicate_position_slot_is_flagged_and_both_rows_kept():
    rows = [
        row('2025-09-01T10:00:00', espn='1', gsis='G1', slot='QB', rank=1),
        row('2025-09-01T10:00:00', espn='2', gsis='G2', slot='QB', rank=1),
    ]
    state = da.depth_state(rows, 'KC', ts('2025-09-02T00:00:00'), INDEX, source_sha256='x')
    assert len(state['entries']) == 2
    assert state['counts']['duplicate_slot'] == 2


def test_same_player_in_two_slots_is_a_duplicate_identity():
    rows = [
        row('2025-09-01T10:00:00', espn='1', gsis='G1', slot='QB', rank=1),
        row('2025-09-01T10:00:00', espn='1', gsis='G1', slot='WR', rank=2),
    ]
    state = da.depth_state(rows, 'KC', ts('2025-09-02T00:00:00'), INDEX, source_sha256='x')
    assert state['counts']['duplicate_identity'] == 2


def test_blank_role_fields_are_kept_as_unknown():
    rows = [row('2025-09-01T10:00:00', grp='', slot='', rank=None)]
    state = da.depth_state(rows, 'KC', ts('2025-09-02T00:00:00'), INDEX, source_sha256='x')
    entry = state['entries'][0]
    assert entry['pos_grp'] == 'UNKNOWN'
    assert entry['pos_slot'] == 'UNKNOWN'
    assert entry['pos_rank'] is None


# Horizons

def test_early_and_final_horizons_are_ordered_and_before_kickoff():
    early, final = da.game_horizons('2025-09-07', '13:00')
    kickoff = dt.datetime(2025, 9, 7, 17, 0, tzinfo=UTC)
    assert early < final < kickoff
    assert final == kickoff - dt.timedelta(hours=1)


def test_early_horizon_is_a_tuesday_noon_eastern():
    early, _ = da.game_horizons('2025-09-07', '13:00')
    local = early.astimezone(dt.timezone(dt.timedelta(hours=-4)))
    assert local.weekday() == 1
    assert (local.hour, local.minute) == (12, 0)


def test_missing_kickoff_time_fails_loudly():
    with pytest.raises(ValueError):
        da.game_horizons('2025-09-07', None)


# Integration with the real publisher file

@pytest.fixture(scope='module')
def real_rows():
    assert os.path.exists(DEPTH_FILE), f'missing publisher file {DEPTH_FILE}'
    return da.load_snapshot_rows(DEPTH_FILE)


@pytest.fixture(scope='module')
def real_index():
    assert os.path.exists(PLAYERS_FILE), f'missing identity file {PLAYERS_FILE}'
    return da.identity_index_from_players(PLAYERS_FILE)


def test_real_file_has_32_teams_and_one_shared_snapshot_series(real_rows):
    teams = {r['team'] for r in real_rows}
    assert len(teams) == 32
    per_team = {t: {r['dt'] for r in real_rows if r['team'] == t} for t in list(teams)[:3]}
    series = list(per_team.values())
    assert all(s == series[0] for s in series)
    assert len(series[0]) == 221


def test_real_file_records_its_source_hash(real_rows):
    assert all(len(r['source_sha256']) == 64 for r in real_rows[:5])


def test_real_file_every_non_null_gsis_is_in_the_players_index(real_rows, real_index):
    gsis = [r['gsis_id'] for r in real_rows if r['gsis_id']]
    assert gsis and all(g in real_index['gsis'] for g in gsis)


def test_real_file_null_gsis_rows_are_partitioned_into_identity_statuses(real_rows, real_index):
    null_rows = [r for r in real_rows if not r['gsis_id']]
    statuses = [da.resolve_identity(r, real_index)[0] for r in null_rows]
    assert len(statuses) == 5577
    assert set(statuses) <= {'espn_unique', 'ambiguous', 'unmatched'}


def test_real_file_state_never_uses_a_later_snapshot(real_rows, real_index):
    cutoff = ts('2025-09-10T00:00:00')
    state = da.depth_state(real_rows, 'KC', cutoff, real_index, source_sha256=real_rows[0]['source_sha256'])
    assert state['snapshot_dt'] is not None
    assert state['snapshot_dt'] <= cutoff
    assert state['staleness_seconds'] >= 0
