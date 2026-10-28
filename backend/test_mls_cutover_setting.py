"""The MLS cutover switch is a runtime setting, LP_MLS_CUTOVER, and it is off unless set.

Production runs with the variable unset. These tests pin the default, the accepted values, and the one behavior change
the switch makes: a departed person stops resolving.
"""
import pytest

import _core
import mls_resolution
from test_mls_cutover_acceptance import D1, D2, World

LEGACY_CLUB = "pl.team"


def test_the_switch_is_off_when_the_variable_is_unset(monkeypatch):
    monkeypatch.delenv(mls_resolution.CUTOVER_ENV, raising=False)
    assert mls_resolution.cutover_enabled() is False
    assert mls_resolution.club_now_sql("pl.id", "pl.league", LEGACY_CLUB, "NULL") == LEGACY_CLUB


@pytest.mark.parametrize("value", ["1", "true", "YES", " on "])
def test_affirmative_values_turn_the_switch_on(monkeypatch, value):
    monkeypatch.setenv(mls_resolution.CUTOVER_ENV, value)
    assert mls_resolution.cutover_enabled() is True
    assert "roster_snapshots" in mls_resolution.club_now_sql("pl.id", "pl.league", LEGACY_CLUB, "NULL")


@pytest.mark.parametrize("value", ["", "0", "false", "off", "no", "2", "enabled"])
def test_anything_else_leaves_the_switch_off(monkeypatch, value):
    monkeypatch.setenv(mls_resolution.CUTOVER_ENV, value)
    assert mls_resolution.cutover_enabled() is False
    assert mls_resolution.club_now_sql("pl.id", "pl.league", LEGACY_CLUB, "NULL") == LEGACY_CLUB


def test_the_switch_is_read_on_every_call(monkeypatch):
    monkeypatch.delenv(mls_resolution.CUTOVER_ENV, raising=False)
    assert mls_resolution.cutover_enabled() is False
    monkeypatch.setenv(mls_resolution.CUTOVER_ENV, "1")
    assert mls_resolution.cutover_enabled() is True
    monkeypatch.delenv(mls_resolution.CUTOVER_ENV, raising=False)
    assert mls_resolution.cutover_enabled() is False


def test_enabled_and_disabled_differ_only_for_a_departed_person(monkeypatch):
    monkeypatch.delenv(mls_resolution.CUTOVER_ENV, raising=False)
    w = World()
    w.cycle(D1)
    name, club = w.name_of(3), w.team_of(3)
    w.drop_person(3)
    w.cycle(D2)

    assert _core._resolve_player_for_ingest(w.con, name, club, "mls")[0] == 3, \
        "switch off: the legacy resolver still answers for a departed person"

    monkeypatch.setenv(mls_resolution.CUTOVER_ENV, "1")
    assert _core._resolve_player_for_ingest(w.con, name, club, "mls")[0] is None, \
        "switch on: the membership answers, and a departed person does not resolve"
    current, current_club = w.name_of(4), w.team_of(4)
    assert _core._resolve_player_for_ingest(w.con, current, current_club, "mls")[0] == 4, \
        "switch on: a current member still resolves"
