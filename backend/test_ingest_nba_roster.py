import datetime as dt
import pytest

import ingest_nba_roster as nba


def test_season_comes_from_the_published_span_never_the_bare_start_year():
    assert nba.season_from_span("2026-27") == 2027
    assert nba.season_from_span("1999-00") == 2000
    with pytest.raises(nba.NBARosterError):
        nba.season_from_span("2026")          # the bare SEASON value: refused, not passed through
    with pytest.raises(Exception):
        nba.season_from_span("2026-28")       # halves not consecutive


def test_acquired_from_reads_the_published_move():
    assert nba.acquired_from("Traded from DET on 07/07/25") == "DET"
    assert nba.acquired_from("Signed as free agent") is None
    assert nba.acquired_from(None) is None


def _row(pid, team, nba_id=None):
    return {"id": pid, "name": "Same Name", "team": team, "position": "G", "nba_id": nba_id}


def test_a_name_binds_only_with_team_or_acquired_from_evidence():
    member = {"team": "MIA", "how_acquired": "Traded from DET on 07/07/25"}
    assert nba._choose_unbound_candidate([_row(1, "MIA"), _row(2, "BOS")], member) == (_row(1, "MIA"), "matched_team")
    assert nba._choose_unbound_candidate([_row(3, "DET")], member) == (_row(3, "DET"), "matched_acquired_from")
    assert nba._choose_unbound_candidate([_row(4, "LAL")], member) == (None, "unverified_name")
    assert nba._choose_unbound_candidate([_row(5, "LAL"), _row(6, "BOS")], member) == (None, "ambiguous_name")


def test_a_same_name_row_already_tied_to_another_nba_person_is_a_different_person():
    assert nba._choose_unbound_candidate([_row(7, "MIA")], {"team": "MIA"}, bound=frozenset({7})) == (None, "insert")


def _page(team_id, abbr="MIA", span="2026-27", roster=None):
    return {"info": {"TEAM_ID": team_id, "TEAM_ABBREVIATION": abbr, "SEASON_YEAR": span},
            "roster": roster if roster is not None else [{"PLAYER_ID": team_id - 1610612000, "PLAYER": f"P{team_id}"}]}


ABBRS = ["ATL", "BOS", "CLE", "NOP", "CHI", "DAL", "DEN", "GSW", "HOU", "LAC", "LAL", "MIA", "MIL",
         "MIN", "BKN", "NYK", "ORL", "IND", "PHI", "PHX", "POR", "SAC", "SAS", "OKC", "TOR", "UTA",
         "MEM", "WAS", "DET", "CHA"]


def test_a_complete_population_validates_and_reports_spend():
    pages = {tid: _page(tid, abbr) for tid, abbr in zip(nba.TEAM_IDS, ABBRS)}
    season, rosters, spend = nba.fetch_population(lambda tid: pages[tid])
    assert season == 2027 and len(rosters) == 30 and spend["requests"] == 30


def test_a_page_echoing_another_team_id_fails_loudly():
    pages = {tid: _page(tid, abbr) for tid, abbr in zip(nba.TEAM_IDS, ABBRS)}
    pages[nba.TEAM_IDS[3]]["info"]["TEAM_ID"] = 1
    with pytest.raises(nba.NBARosterError, match="reports TEAM_ID"):
        nba.fetch_population(lambda tid: pages[tid])


def test_an_empty_roster_or_a_player_listed_twice_fails_loudly():
    pages = {tid: _page(tid, abbr) for tid, abbr in zip(nba.TEAM_IDS, ABBRS)}
    pages[nba.TEAM_IDS[0]]["roster"] = []
    with pytest.raises(nba.NBARosterError, match="empty roster"):
        nba.fetch_population(lambda tid: pages[tid])
    pages[nba.TEAM_IDS[0]]["roster"] = [{"PLAYER_ID": 1, "PLAYER": "A"}, {"PLAYER_ID": 1, "PLAYER": "A"}]
    with pytest.raises(nba.NBARosterError, match="listed twice"):
        nba.fetch_population(lambda tid: pages[tid])


def test_teams_disagreeing_on_the_season_fail_loudly():
    pages = {tid: _page(tid, abbr) for tid, abbr in zip(nba.TEAM_IDS, ABBRS)}
    pages[nba.TEAM_IDS[5]]["info"]["SEASON_YEAR"] = "2025-26"
    with pytest.raises(nba.NBARosterError, match="disagree on the season"):
        nba.fetch_population(lambda tid: pages[tid])


def test_a_dated_move_after_our_last_roster_explains_a_different_team():
    import datetime as dt
    since = dt.date(2026, 8, 4)
    moved = {"team": "DEN", "how_acquired": "Signed on 09/08/26"}
    assert nba._choose_unbound_candidate([_row(8, "CHI")], moved, known_since=since) == (_row(8, "CHI"), "matched_moved_since_snapshot")
    stale = {"team": "BKN", "how_acquired": "Signed on 10/15/25"}       # before our snapshot: a real conflict
    assert nba._choose_unbound_candidate([_row(9, "MIL")], stale, known_since=since) == (None, "unverified_name")
    two = {"team": "DEN", "how_acquired": "Signed on 09/08/26"}         # two candidates: still ambiguous
    assert nba._choose_unbound_candidate([_row(10, "CHI"), _row(11, "LAL")], two, known_since=since) == (None, "ambiguous_name")


def test_birth_date_breaks_a_sole_name_tie_and_a_mismatch_stays_unproven():
    import datetime as dt
    row = {"id": 12, "name": "Same Name", "team": "UTAH", "position": "C", "espn_id": 4432827, "nba_id": 4432827}
    member = {"team": "HOU", "how_acquired": "Signed on 07/24/26", "birth_date": "NOV 27, 1999"}
    since = dt.date(2026, 8, 4)                       # the move predates our snapshot: dates alone fail
    same = lambda espn_id: dt.date(1999, 11, 27)
    other = lambda espn_id: dt.date(2001, 1, 1)
    assert nba._choose_unbound_candidate([row], member, known_since=since, birth_date_of=same) == (row, "matched_birth_date")
    assert nba._choose_unbound_candidate([row], member, known_since=since, birth_date_of=other) == (None, "unverified_name")


def test_reviewed_birth_dates_are_read_from_checked_file(tmp_path):
    path = tmp_path / "reviewed.json"
    path.write_text('{"nba": {"1631131": {"espn_id": 4432827, "espn_birth_date": "1999-11-27"}}}')
    assert nba._reviewed_birth_dates(str(path)) == {"4432827": dt.date(1999, 11, 27)}
    assert nba._reviewed_birth_dates(str(tmp_path / "missing.json")) == {}


def test_shipped_reviewed_file_parses():
    assert len(nba._reviewed_birth_dates()) == 7


def test_last_logged_team_binds_a_stale_sole_candidate():
    import sqlite3
    con = sqlite3.connect(":memory:")
    con.row_factory = sqlite3.Row
    con.execute("CREATE TABLE p(id INT, name TEXT, team TEXT, espn_id TEXT, nba_id TEXT)")
    con.execute("INSERT INTO p VALUES (25589,'Bradley Beal','WSH',NULL,'6580')")
    row = con.execute("SELECT * FROM p").fetchone()
    member = {"team": "LAC", "how_acquired": "Signed on 07/18/25", "birth_date": "JUN 28, 1993"}
    since = nba.dt.date(2026, 8, 4)
    assert nba._choose_unbound_candidate([row], member, known_since=since)[1] == "unverified_name"
    got = nba._choose_unbound_candidate([row], member, known_since=since,
                                        last_logged_team=lambda pid: "LAC")
    assert got[1] == "matched_last_logged_team"
    assert nba._choose_unbound_candidate([row], member, known_since=since,
                                         last_logged_team=lambda pid: "PHX")[1] == "unverified_name"
