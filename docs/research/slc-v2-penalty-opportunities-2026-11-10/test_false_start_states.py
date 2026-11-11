import pandas as pd

from audit_false_start_states import audit


def row(**changes):
    result = dict(game_id='game', play_id=1, order_sequence=1,
                  desc='PENALTY on AAA, False Start, 5 yards, enforced at AAA 30 - No Play.',
                  penalty=1, penalty_type='False Start', penalty_team='AAA', penalty_yards=5,
                  play_type='no_play', posteam='AAA', down=2, ydstogo=6, yardline_100=70,
                  qtr=1, game_seconds_remaining=3000, total_home_score=0, total_away_score=0)
    result.update(changes)
    return result


def test_matching_mismatching_and_half_distance():
    start = row()
    next_play = row(play_id=2, order_sequence=2, penalty=0, penalty_type=None,
                    down=2, ydstogo=11, yardline_100=75)
    good = audit(pd.DataFrame([start, next_play]))
    assert good['matching_expected_state'] == 1
    next_play['ydstogo'] = 6
    bad = audit(pd.DataFrame([start, next_play]))
    assert bad['nonmatching_expected_state'] == 1
    assert bad['nonmatching_examples'][0]['game_id'] == 'game'
    start['yardline_100'] = 95
    assert audit(pd.DataFrame([start, next_play]))['simple_false_start_candidates'] == 0


def test_duplicate_order_and_multiple_fouls_are_excluded():
    start = row(desc='PENALTY on AAA, False Start, enforced. PENALTY on BBB, declined.')
    following = row(play_id=2, order_sequence=2, penalty=0, penalty_type=None)
    assert audit(pd.DataFrame([start, following]))['simple_false_start_candidates'] == 0
    following['order_sequence'] = 1
    result = audit(pd.DataFrame([start, following]))
    assert result['duplicate_order_games_excluded'] == 1
    assert result['simple_false_start_candidates'] == 0
