import sqlite3

import settlement
from settlement.market_mapping import MARKET_ALIASES
from settlement.mlb_settle import _MLB_MARKET_MAP


def _connection():
    con = sqlite3.connect(":memory:")
    con.row_factory = sqlite3.Row
    con.executescript(
        """
        CREATE TABLE players(
          id INTEGER PRIMARY KEY, league TEXT, mlbam_id INTEGER
        );
        CREATE TABLE prop_results(
          prop_id INTEGER PRIMARY KEY, actual_value REAL, hit INTEGER,
          settled_at TEXT
        );
        INSERT INTO players VALUES(1,'mlb',101);
        INSERT INTO players VALUES(2,'mlb',202);
        """
    )
    return con


def _boxscore_with_plausible_walks_in_both_stat_groups():
    return {
        "teams": {
            "away": {
                "players": {
                    # The batter really walked twice, but also has a plausible
                    # pitching BB value. Picking the wrong group would not raise.
                    "ID101": {"stats": {
                        "batting": {"baseOnBalls": 2},
                        "pitching": {"baseOnBalls": 9},
                    }},
                    # The pitcher allowed three walks, while his batting line
                    # also contains a different plausible number.
                    "ID202": {"stats": {
                        "batting": {"baseOnBalls": 8},
                        "pitching": {"baseOnBalls": 3},
                    }},
                }
            },
            "home": {"players": {}},
        }
    }


def test_rotowire_222_batter_walks_never_grades_against_pitching_bb(monkeypatch):
    con = _connection()
    monkeypatch.setattr(settlement, "_fetch_mlb_gamepk", lambda *args, **kwargs: 99)
    monkeypatch.setattr(
        settlement, "_fetch_mlb_boxscore",
        lambda game_pk: _boxscore_with_plausible_walks_in_both_stat_groups(),
    )
    props = [
        {"id": 11, "market": "batter_walks", "line": 1.5, "side": "over",
         "player_id": 1},
        {"id": 12, "market": "walks", "line": 2.5, "side": "over",
         "player_id": 2},
    ]

    result = settlement._settle_mlb_props(
        con,
        {"date": "2026-08-23", "home": "San Diego Padres",
         "away": "Minnesota Twins", "start_time": "2026-08-23T20:10:00Z"},
        props,
    )

    actuals = dict(con.execute(
        "SELECT prop_id,actual_value FROM prop_results ORDER BY prop_id"
    ))
    assert result["settled"] == 2
    assert actuals == {11: 2.0, 12: 3.0}
    assert _MLB_MARKET_MAP["batter_walks"] == ("batting", "baseOnBalls")
    assert _MLB_MARKET_MAP["walks"] == ("pitching", "baseOnBalls")
    con.close()


def test_numeric_count_markets_are_not_aliased_to_anytime_markets():
    expected = {
        "doubles": ("batting", "doubles"),
        "home_runs": ("batting", "homeRuns"),
        "runs": ("batting", "runs"),
        "rbis": ("batting", "rbi"),
        "hits": ("batting", "hits"),
    }
    assert {key: _MLB_MARKET_MAP[key] for key in expected} == expected
    assert all(MARKET_ALIASES.get(key, key) == key for key in expected)
