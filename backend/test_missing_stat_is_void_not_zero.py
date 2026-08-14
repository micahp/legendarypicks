""""We could not find it" and "it genuinely happened zero times" are not the same
number, and grading them the same way always pays the UNDER.

Every prop in this repo is over/under a line, so a stat that reads 0 when it is
actually absent does not fail — it grades. The OVER loses and the UNDER cashes,
confidently, with a number in the column. This is the amplifier that turned a
wrong gamePk into 7,827 wrong grades on 2026-08-11 rather than 7,827 missing
ones: the unplayed game published a lineup, the lineup published no batting
lines, and `bat.get("hits", 0) or 0` read that as a hitless day.

Two sites, one rule — an absent stat is not zero and is not a terminal result:

  settlement._settle_mlb_props  compound `hits_runs_rbis` summed three `.get(x, 0)`
                                against a player with no batting object at all.
  settlement._find_player_stat  returned 0.0 after finding the athlete but not
                                the label — "this box score does not report TB"
                                became "he recorded 0 TB".

The distinction is available in both payloads. A player who really went 0-for-4
has a batting object with `hits: 0`; a player who did not bat has no batting
object. Read the difference instead of flattening it.
"""
import pytest

import settlement


# ── MLB Stats API path ─────────────────────────────────────────────────────────

class _Con:
    """Minimal stand-in that records the prop_results writes."""

    def __init__(self):
        self.rows = []

    def execute(self, sql, params=()):
        if "INSERT INTO prop_results" in sql:
            # A void is written as literal NULLs in the SQL, so normalise both
            # shapes to (prop_id, actual_value, hit).
            if "VALUES (?,NULL,NULL,?)" in sql:
                self.rows.append((params[0], None, None))
            else:
                self.rows.append(params[:3])
        return self

    def __iter__(self):
        return iter([])

    def commit(self):
        pass


def _prop(pid=1, market="total_hits,_runs_and_rbis", line=1.5, side="over"):
    return {"id": pid, "market": market, "line": line, "side": side,
            "player_id": 10, "player_name": "Austin Riley", "player_team": "ATL"}


def _run(monkeypatch, batting, prop=None, crosswalk=True):
    """Settle one hits+runs+RBIs prop against a player whose batting dict is `batting`."""
    con = _Con()
    monkeypatch.setattr(settlement, "_fetch_mlb_gamepk", lambda *a, **k: 825048)
    monkeypatch.setattr(settlement, "_fetch_mlb_boxscore", lambda pk: {
        "teams": {"home": {"players": {"ID12345": {"stats": {"batting": batting,
                                                             "pitching": {}}}}},
                  "away": {"players": {}}}})
    monkeypatch.setattr(con, "execute", con.execute)
    con.execute = con.execute  # keep the recorder

    class _C(_Con):
        def execute(self, sql, params=()):
            if sql.strip().upper().startswith("SELECT ID, MLBAM_ID"):
                return [{"id": 10, "mlbam_id": 12345}] if crosswalk else []
            return _Con.execute(self, sql, params)

    c = _C()
    out = settlement._settle_mlb_props(
        c, {"date": "2026-08-11", "home": "Atlanta Braves", "away": "San Francisco Giants",
            "start_time": "2026-08-11T01:40:00+00:00"}, [prop or _prop()])
    return out, c.rows


def test_a_player_with_no_batting_object_stays_pending(monkeypatch):
    """The 2026-08-11 case: an unplayed game's lineup carries no batting lines."""
    out, rows = _run(monkeypatch, {})
    assert out["settled"] == 0
    assert out["void"] == 0
    assert out["pending"] == 1
    assert rows == [], "absence must not create a terminal prop_results row"


def test_a_genuine_0_for_4_still_grades(monkeypatch):
    """The distinction has to cut both ways or it is just a different silence."""
    out, rows = _run(monkeypatch, {"hits": 0, "runs": 0, "rbi": 0, "atBats": 4})
    assert out["settled"] == 1
    assert rows[0][1] == 0.0 and rows[0][2] == 0, "0 < 1.5, so the OVER loses honestly"


def test_a_real_line_grades(monkeypatch):
    out, rows = _run(monkeypatch, {"hits": 2, "runs": 1, "rbi": 0})
    assert out["settled"] == 1
    assert rows[0][1] == 3.0 and rows[0][2] == 1


def test_a_partial_batting_line_is_not_padded_with_zeros(monkeypatch):
    """If the publisher reports hits but not RBI, we do not invent the RBI."""
    out, rows = _run(monkeypatch, {"hits": 2})
    assert out["void"] == 0
    assert out["pending"] == 1, "an incomplete sum is not a terminal result"
    assert rows == []


def test_a_missing_mlbam_crosswalk_stays_pending(monkeypatch):
    out, rows = _run(monkeypatch, {"hits": 2, "runs": 1, "rbi": 0},
                     crosswalk=False)
    assert out["pending"] == 1
    assert out["void"] == 0
    assert rows == []


def test_an_unsupported_mlb_market_stays_retryable(monkeypatch):
    out, rows = _run(
        monkeypatch, {"hits": 2, "runs": 1, "rbi": 0},
        prop=_prop(market="total_pitcher_walks"),
    )
    assert out["unmappable"] == 1
    assert rows == []


def test_a_malformed_published_value_stays_pending(monkeypatch):
    out, rows = _run(
        monkeypatch, {"hits": "not-a-number"},
        prop=_prop(market="total_hits"),
    )
    assert out["pending"] == 1
    assert rows == []


def test_an_invalid_mlb_side_stays_retryable(monkeypatch):
    out, rows = _run(
        monkeypatch, {"hits": 2},
        prop=_prop(market="total_hits", side="yes"),
    )
    assert out["unmappable"] == 1
    assert rows == []


# ── ESPN box score path ────────────────────────────────────────────────────────

def _espn_box(labels, stats):
    return {"players": [{
        "team": {"abbreviation": "ATL", "displayName": "Atlanta Braves"},
        "statistics": [{"name": "batting", "labels": labels,
                        "athletes": [{"athlete": {"displayName": "Austin Riley"},
                                      "stats": stats}]}],
    }]}


def test_espn_returns_none_when_the_label_is_absent():
    """Found the athlete, but this box score does not report that stat."""
    box = _espn_box(["AB", "R", "H", "RBI"], ["4", "1", "2", "0"])
    assert settlement._find_player_stat(box, "Austin Riley", "ATL", "batting", "SB") is None


def test_espn_still_reads_a_real_zero():
    box = _espn_box(["AB", "R", "H", "RBI"], ["4", "0", "0", "0"])
    assert settlement._find_player_stat(box, "Austin Riley", "ATL", "batting", "H") == 0.0


def test_espn_reads_a_real_value():
    box = _espn_box(["AB", "R", "H", "RBI"], ["4", "1", "2", "3"])
    assert settlement._find_player_stat(box, "Austin Riley", "ATL", "batting", "RBI") == 3.0


def test_an_empty_string_is_absent_not_zero():
    """ESPN publishes "" for a stat it is not reporting for that athlete."""
    box = _espn_box(["AB", "R", "H", "RBI"], ["4", "1", "2", ""])
    assert settlement._find_player_stat(box, "Austin Riley", "ATL", "batting", "RBI") is None


def test_a_compound_stat_needs_every_part():
    """_find_player_compound_stat summed whatever it found and called it a total —
    so H + (missing RBI) graded as H."""
    box = _espn_box(["AB", "R", "H"], ["4", "1", "2"])
    assert settlement._find_player_compound_stat(
        box, "Austin Riley", "ATL", ["batting", "batting", "batting"], ["H", "R", "RBI"]) is None


def test_a_complete_compound_stat_sums():
    box = _espn_box(["AB", "R", "H", "RBI"], ["4", "1", "2", "3"])
    assert settlement._find_player_compound_stat(
        box, "Austin Riley", "ATL", ["batting", "batting", "batting"], ["H", "R", "RBI"]) == 6.0
