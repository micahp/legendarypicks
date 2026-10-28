"""Automatic onboarding takes a date of birth only when it has exactly one interpretation, and both publishers agree.

A page whose day and month can be read either way gives two readings. Nothing chooses between them. The identity goes
to review instead, and nobody is created on a guess.
"""
from test_mls_cutover_acceptance import D1, D2, World, _count
import mls_identity


def test_one_reading_from_each_publisher_that_agree_is_accepted():
    assert mls_identity.corroborated_dob(["1995-04-02"], ["1995-04-02"]) == ("1995-04-02", None)


def test_two_readings_from_one_publisher_are_ambiguous_even_when_one_matches():
    assert mls_identity.corroborated_dob(["1995-02-04", "1995-04-02"], ["1995-04-02"]) == (None, "dob_ambiguous")
    assert mls_identity.corroborated_dob(["1995-04-02"], ["1995-02-04", "1995-04-02"]) == (None, "dob_ambiguous")


def test_two_readings_that_match_neither_are_ambiguous_too():
    assert mls_identity.corroborated_dob(["1995-02-04", "1995-03-04"], ["1995-04-02"]) == (None, "dob_ambiguous")


def test_single_readings_that_differ_are_a_conflict():
    assert mls_identity.corroborated_dob(["1995-04-02"], ["1995-02-04"]) == (None, "dob_not_corroborated")


def test_a_missing_reading_is_missing():
    assert mls_identity.corroborated_dob([], ["1995-04-02"]) == (None, "dob_missing")
    assert mls_identity.corroborated_dob(["1995-04-02"], []) == (None, "dob_missing")


def test_a_reading_that_can_be_read_two_ways_is_queued_and_nobody_is_created():
    w = World()
    w.cycle(D1)
    w.add_pair("m9003", "f9003", "Two Readings", "Club04", dob="1995-04-02")
    w.dobs[("mlssoccer", "m9003")] = ["1995-02-04", "1995-04-02"]
    before = _count(w.con, "players")

    w.cycle(D2)

    assert _count(w.con, "players") == before, "an ambiguous date of birth never creates a person"
    assert w.bind_of("mlssoccer", "m9003") is None and w.bind_of("fotmob", "f9003") is None
    assert any(q["source_player_key"] == "m9003" and q["reason"] == "dob_ambiguous" for q in w.queue())
