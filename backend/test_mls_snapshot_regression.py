"""Regression: the 1,855 source records saved on 2026-10-27 must resolve to today's 1,040 people.

The fixture holds the saved squads and the bind rows that cover them. This test needs no database.
"""
import json
import os

import mls_snapshot as ms

FIXTURE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures", "mls_regression_2026-10-27.json")


def _load():
    fx = json.load(open(FIXTURE))
    binds = {}
    for source, key, player_id in fx["binds"]:
        binds[(source, key)] = player_id
    return fx["squads"], binds


def test_the_saved_squads_are_the_full_current_population():
    squads, _ = _load()
    assert len(squads["fotmob"]) == 900
    assert len(squads["mlssoccer"]) == 955
    assert len({m["team"] for m in squads["fotmob"]}) == 30
    assert len({m["team"] for m in squads["mlssoccer"]}) == 30


def test_the_saved_records_resolve_to_1040_people_with_no_blockers_or_conflicts():
    squads, binds = _load()
    memberships, unresolved, conflicts = ms.resolve(squads, binds)
    assert unresolved == []
    assert conflicts == []
    assert len(memberships) == 1040
    assert len({m["player_id"] for m in memberships}) == 1040
    assert len({m["team"] for m in memberships}) == 30


def test_the_saved_records_pass_completeness_and_build_a_publishable_snapshot():
    squads, binds = _load()
    result = ms.build(squads, binds, captured_at="2026-10-27T21:13:59+00:00")
    assert result.status == "publish"
    assert result.blockers == [] and result.carried == []
    assert len(result.memberships) == 1040
