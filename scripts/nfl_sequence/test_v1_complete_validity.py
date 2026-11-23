import game_state as gs
from test_game_state import PERIOD_END_OVERTIME, StaticPool, kickoff_pool, ref


def test_complete_game_is_valid_when_snapshot_evidence_is_unverified():
    snapshot = {
        'snapshot_sha256': 'd' * 64, 'as_of': '2026-10-30T12:00:00Z', 'roster_snapshot_id': 'roster-1',
        'evaluation': {'verified': False},
        'rosters': {side: {'team': team, 'players': [{'gsis_id': team + '-RB', 'player_name': 'Runner',
                                                       'pos_abb': 'RB', 'pos_rank': 1}]}
                    for side, team in (('home', 'AAA'), ('away', 'BBB'))},
        'model_reference': {'observed_reference': {'runner_position_usage': {'shares': {'RB': 1.0}}}},
        'schedule': {'game_id': '2025_01_AAA_BBB', 'home_team': 'AAA', 'away_team': 'BBB',
                     'gameday': '2025-09-01', 'gametime': '12:00', 'gametime_timezone': 'America/Chicago',
                     'scheduled_kickoff_utc': '2025-09-01T17:00:00Z'},
    }
    reference = ref(StaticPool('run', 0, 20), kickoff_pool(), overtime_pool=[PERIOD_END_OVERTIME])
    game = gs.play_game(9, reference, winner_choice='receive', pregame_snapshot=snapshot)
    assert game['status'] == 'complete_overtime'
    assert game['valid_full_game'] is True
    assert game['snapshot_verified'] is False
    gs.validate_game(game)
