"""A bounded autonomous drive must preserve reducer state and caller clocks."""
from pathlib import Path

import pytest

import gridiron_bridge as bridge
import gridiron_drive as drive

ROOT = Path('/root')
SNAPSHOT = ROOT / 'lp-roster-preflight/docs/research/model-snapshots-2026/week-11/2026_11_MIN_SF.json'
FIELD = ROOT / 'lp-slc-v2/docs/research/participation-model-2026-11-02/outputs/field_v3_2022_2025.json'
BOOKS = ROOT / 'lp-snapshots/nfl-team-season-playbooks-2026-10-27-rev7'
ENGINE = ROOT / 'gridiron-slc-consolidation'
FIELD_HASH = 'a31fc7150c107b3c15b11e2e643ace88828c033f8da3576b51348e4b5a677107'
STATE = {'quarter': 1, 'clock': 600, 'offense': 'MIN', 'defense': 'SF', 'down': 1, 'togo': 10, 'yl': 50}


def test_empty_and_impossible_clocks_rejected_before_execution():
    with pytest.raises(ValueError, match='empty_plan'):
        drive.execute_drive(None, {}, STATE, [])
    with pytest.raises(ValueError, match='invalid_snap_clock'):
        drive.execute_drive(None, {}, STATE, [{'snap_clock': 601}])
    state = {**STATE, 'quarter': 2, 'clock': 125}
    with pytest.raises(ValueError, match='two_minute_boundary'):
        drive.execute_drive(None, {}, state, [{'snap_clock': 120}])


@pytest.mark.skipif(not all(p.exists() for p in (SNAPSHOT, FIELD, BOOKS, ENGINE)), reason='local pinned research artifacts unavailable')
def test_real_snapshot_consecutive_plays_to_turnover():
    call, _ = bridge.build_call(str(SNAPSHOT), str(FIELD), FIELD_HASH, str(BOOKS / 'MIN-2025.json'),
                                str(BOOKS / 'build_manifest.json'), seed=300001, family='pass', state=STATE)
    plan = [{'seed': 300001 + i, 'snap_clock': 600 - 30 * i, 'concept': 'slant_flat', 'coverage': 'zone'}
            for i in range(4)]
    with bridge.GridironSession(ENGINE) as session:
        result = drive.execute_drive(session, call, STATE, plan)
    assert result['status'] == 'terminal'
    assert result['terminal'] == 'turnover'
    assert len(result['plays']) == 3
    assert [p['reduction']['play']['event_type'] for p in result['plays']] == ['pass_incomplete', 'pass_incomplete', 'interception']
    assert [p['call']['situation']['down'] for p in result['plays']] == [1, 2, 3]
    assert result['end_state']['offense'] == 'SF'
    assert all(p['result']['trajectory']['frames'] is None for p in result['plays'])
    qb = next(p for p in result['player_statistics'] if p['player_id'] == call['offense']['lineup']['QB'])
    assert qb['passing']['att'] == 3
    assert qb['passing']['int'] == 1
