"""Drive classification: one label per drive, from hand-built plays that stand for real and simulated snaps."""
from nfl_sequence.drive_eval import OUTCOMES, Play, build_drives, game_points, score_bin, field_bin


def snap(kind, drive=1, offense="BUF", defense="KC", down=1, ydstogo=10, yardline=70, yards=0, elapsed=30,
         clock=600, points_off=0, points_def=0, first_down=False, fumble=False, made=None, period=1, seq=0):
    return Play(source="sim", game="g", trial=0, seq=seq, drive=drive, kind=kind, offense=offense, defense=defense,
                period=period, clock=clock, down=down, ydstogo=ydstogo, yardline=yardline, yards=yards,
                elapsed=elapsed, fumble=fumble, touchback=False, made=made, first_down=first_down,
                points_off=points_off, points_def=points_def, points_off_before=0, points_def_before=0,
                kick_distance=None)


def kickoff(drive=1, offense="BUF", defense="KC", points_off=0, seq=0):
    return Play(source="sim", game="g", trial=0, seq=seq, drive=drive, kind="kickoff", offense=offense, defense=defense,
                period=1, clock=900, down=None, ydstogo=None, yardline=75, yards=0, elapsed=5, fumble=False,
                touchback=True, made=None, first_down=False, points_off=points_off, points_def=0,
                points_off_before=0, points_def_before=0, kick_distance=None)


def only_drive(plays):
    drives = build_drives(plays)
    assert len(drives) == 1, drives
    return drives[0]


def test_a_touchdown_drive_is_labelled_touchdown_with_its_points():
    d = only_drive([kickoff(seq=0), snap("run", seq=1, first_down=True, yards=12, yardline=70),
                    snap("pass", seq=2, yardline=58, down=1, ydstogo=10, yards=58, points_off=6)])
    assert d.outcome == "touchdown" and d.points_off == 6 and d.first_downs == 1 and d.red_zone_entry is False


def test_a_punt_drive_is_labelled_punt_and_a_missed_field_goal_is_not_a_punt():
    punt = only_drive([kickoff(seq=0), snap("run", seq=1), snap("punt", seq=2, down=4, yardline=60)])
    assert punt.outcome == "punt"
    missed = only_drive([kickoff(seq=0), snap("field_goal", seq=1, down=4, yardline=25, made=False)])
    assert missed.outcome == "field_goal_missed" and missed.fg_att == 1 and missed.fg_made == 0


def test_a_made_field_goal_scores_and_is_labelled_field_goal_made():
    d = only_drive([kickoff(seq=0), snap("field_goal", seq=1, yardline=22, made=True, points_off=3)])
    assert d.outcome == "field_goal_made" and d.points_off == 3 and d.fg_made == 1


def test_a_pick_six_is_a_defensive_touchdown_not_a_turnover():
    d = only_drive([kickoff(seq=0), snap("interception", seq=1, yardline=40, points_def=6)])
    assert d.outcome == "defensive_touchdown" and d.points_off == 0 and d.turnovers == 1


def test_a_plain_interception_is_a_turnover():
    d = only_drive([kickoff(seq=0), snap("pass", seq=1, yardline=40), snap("interception", seq=2, yardline=30, down=2)])
    assert d.outcome == "turnover" and d.turnovers == 1


def test_a_failed_fourth_down_run_is_turnover_on_downs():
    d = only_drive([kickoff(seq=0), snap("run", seq=1, down=4, ydstogo=3, yardline=45, yards=1)])
    assert d.outcome == "turnover_on_downs" and d.fourth_go_att == 1 and d.fourth_go_conv == 0


def test_a_drive_that_runs_out_the_half_is_clock_expiration_not_a_turnover():
    d = only_drive([kickoff(seq=0), snap("run", seq=1, elapsed=40, clock=40, yardline=50, yards=3)])
    assert d.outcome == "clock_expiration"


def test_a_drive_ended_by_a_kneel_is_kneel_end_game():
    d = only_drive([kickoff(seq=0), snap("kneel", seq=1, yards=-1, elapsed=40, clock=40, yardline=40)])
    assert d.outcome == "kneel_end_game"


def test_a_safety_against_the_offense_is_labelled_so():
    d = only_drive([kickoff(seq=0), snap("sack", seq=1, yardline=99, yards=-2, points_def=2)])
    assert d.outcome == "safety_against_offense"


def test_a_kickoff_with_no_snap_is_no_offensive_snap_and_a_return_touchdown_is_its_own_label():
    assert only_drive([kickoff(seq=0)]).outcome == "no_offensive_snap"
    assert only_drive([kickoff(seq=0, points_off=6)]).outcome == "kickoff_return_touchdown"


def test_a_red_zone_entry_and_its_touchdown_are_both_recorded():
    d = only_drive([kickoff(seq=0), snap("run", seq=1, yardline=18, yards=5),
                    snap("pass", seq=2, yardline=13, down=2, yards=13, points_off=6)])
    assert d.red_zone_entry and d.red_zone_td and d.outcome == "touchdown"


def test_points_reconcile_with_the_score_change_across_plays():
    plays = [kickoff(seq=0, offense="BUF", defense="KC"), snap("pass", seq=1, offense="BUF", defense="KC", points_off=6),
             snap("interception", seq=2, drive=2, offense="KC", defense="BUF", points_def=0)]
    assert game_points(plays) == {"BUF": 6, "KC": 0}


def test_every_drive_gets_one_known_label():
    plays = [kickoff(seq=0), snap("punt", seq=1), kickoff(drive=2, seq=2, offense="KC", defense="BUF"),
             snap("pass", drive=2, seq=3, offense="KC", defense="BUF", yardline=60, points_off=6)]
    labels = [d.outcome for d in build_drives(plays)]
    assert len(labels) == 2 and all(label in OUTCOMES for label in labels)


def test_bins_cover_the_field_and_the_score():
    assert field_bin(1) == "1-20" and field_bin(99) == "81-99"
    assert score_bin(-9) == "trail_9+" and score_bin(0) == "tied" and score_bin(9) == "lead_9+"
