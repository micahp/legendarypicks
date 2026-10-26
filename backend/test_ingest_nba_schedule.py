import sqlite3

import pytest

import ingest_nba_schedule as sched


def _game(gid, code, status=1, home_score=None, away_score=None, label=""):
    date, teams = code.split("/")
    return {"gameId": gid, "gameCode": code, "gameStatus": status, "gameTimeUTC": f"{date[:4]}-{date[4:6]}-{date[6:]}T23:30:00Z",
            "gameLabel": label, "awayTeam": {"teamTricode": teams[:3], "teamName": "Pelicans", "score": away_score},
            "homeTeam": {"teamTricode": teams[3:], "teamName": "Heat", "score": home_score}}


def test_season_yy_is_start_year():
    assert sched.season_yy(2027) == "26"
    assert sched.season_yy(2000) == "99"


def test_parse_maps_nba_codes_to_ours_and_keeps_eastern_date():
    row = sched.parse_game(_game("0012600001", "20261008/NOPMIA", label="Preseason"), "0012600001", 2027)
    assert (row["away_team"], row["home_team"], row["game_date"], row["season_type"]) == ("NO", "MIA", "2026-10-08", "PRE")
    assert row["home_score"] is None and row["label"] == "Preseason"


def test_scores_only_when_final():
    row = sched.parse_game(_game("0022500001", "20251021/HOUOKC", status=3, home_score=125, away_score=124), "0022500001", 2026)
    assert (row["home_score"], row["away_score"]) == (125, 124)
    live = sched.parse_game(_game("0022500001", "20251021/HOUOKC", status=2, home_score=60, away_score=58), "0022500001", 2026)
    assert live["home_score"] is None


def test_page_echoing_another_id_is_fatal():
    with pytest.raises(sched.NBAScheduleError):
        sched.parse_game(_game("0012600002", "20261008/NOPMIA"), "0012600001", 2027)


def test_gamecode_disagreeing_with_teams_is_fatal():
    game = _game("0012600001", "20261008/NOPMIA")
    game["homeTeam"]["teamTricode"] = "TOR"
    with pytest.raises(sched.NBAScheduleError):
        sched.parse_game(game, "0012600001", 2027)


def test_non_nba_opponent_is_skipped_not_published():
    row = sched.parse_game(_game("0012600009", "20261005/MACPHI"), "0012600009", 2027)
    assert "skipped" in row


def test_walk_stops_after_miss_streak_and_skips_gaps():
    pages = {"0012600001": _game("0012600001", "20261008/NOPMIA"),
             "0012600003": _game("0012600003", "20261009/TORMIA")}
    asked = []

    def fetch(gid):
        asked.append(gid)
        return pages.get(gid)
    games, skipped, spend = sched.walk(2027, ("001",), fetch_game=fetch, log=lambda *a, **k: None)
    assert [g["game_id"] for g in games] == ["0012600001", "0012600003"]
    assert len(asked) == 3 + sched.MISS_STREAK and spend["requests"] == len(asked)


def test_three_consecutive_refusals_stop_the_walk():
    def fetch(gid):
        raise OSError("403")
    with pytest.raises(sched.NBAScheduleError, match="three consecutive"):
        sched.walk(2027, ("001",), fetch_game=fetch, log=lambda *a, **k: None)


def test_count_check_refuses_partial_regular_season_and_refusals():
    games = [{"season_type": "REG", "game_date": "2026-10-20", "home_team": "DET", "away_team": "BOS"}]
    assert any("1230" in f for f in sched.check_counts(games, []))
    assert any("refused" in f for f in sched.check_counts([], [{"game_id": "x", "skipped": "refused: 403"}]))


def test_crosswalk_uses_stored_ids_only():
    games = [{"game_date": "2026-10-20", "home_team": "DET", "away_team": "BOS", "home_name": "Pistons", "away_name": "Celtics"},
             {"game_date": "2025-10-22", "home_team": "ATL", "away_team": "TOR", "home_name": "Hawks", "away_name": "Raptors"},
             {"game_date": "2026-10-08", "home_team": "MIA", "away_team": "NO", "home_name": "Heat", "away_name": "Pelicans"}]
    matched = sched.crosswalk(games, {("2025-10-22", "ATL", "TOR"): "401809935"},
                              [("2026-10-20", "Detroit Pistons", "Boston Celtics", "401909088")])
    assert matched == 2 and [g["espn"] for g in games] == ["401909088", "401809935", None]


def test_publish_upserts_and_keeps_known_espn(tmp_path):
    con = sqlite3.connect(tmp_path / "t.db")
    row = sched.parse_game(_game("0012600001", "20261008/NOPMIA"), "0012600001", 2027)
    row["espn"] = "401900001"
    sched.publish(con, [row], apply=True)
    row = dict(row, espn=None, status=3, home_score=110, away_score=100)
    sched.publish(con, [row], apply=True)
    assert con.execute("SELECT espn, status, home_score FROM nba_schedule").fetchall() == [("401900001", 3, 110)]


def test_undecided_cup_slot_is_kept_with_teams_pending():
    game = {"gameId": "0022601201", "gameCode": "", "gameStatus": 1, "gameStatusText": "TBD",
            "gameEt": "2026-12-04T00:00:00Z", "gameTimeUTC": "2026-12-04T05:00:00Z",
            "gameLabel": "Emirates NBA Cup", "gameSubLabel": "Quarterfinal",
            "homeTeam": {"teamId": 0, "teamTricode": ""}, "awayTeam": {"teamId": 0, "teamTricode": ""}}
    row = sched.parse_game(game, "0022601201", 2027)
    assert row["home_team"] is None and row["game_date"] == "2026-12-04" and row["sub_label"] == "Quarterfinal"
    assert sched.check_counts([row, row], []) == [
        f"2 regular-season games published + 0 unpublished; a full season is {sched.REGULAR_SEASON_GAMES}"]
    assert sched.crosswalk([row], {}, []) == 0


def test_walk_resumes_from_checkpoint_without_refetching(tmp_path):
    ck = str(tmp_path / "ck.jsonl")
    pages = {"0012600001": _game("0012600001", "20261008/NOPMIA"),
             "0012600002": _game("0012600002", "20261009/TORMIA")}
    sched.walk(2027, ("001",), fetch_game=pages.get, log=lambda *a, **k: None, checkpoint=ck)
    asked = []
    games, _, spend = sched.walk(2027, ("001",), fetch_game=lambda g: asked.append(g),
                                 log=lambda *a, **k: None, checkpoint=ck)
    assert asked == [] and [g["game_id"] for g in games] == ["0012600001", "0012600002"]


def test_unpublished_cup_ids_pass_but_holes_below_the_block_fail():
    reg = lambda n: {"season_type": "REG", "game_date": f"d{n}", "home_team": "DET", "away_team": "BOS"}
    games = [reg(n) for n in range(1206)]
    gap = [{"game_id": f"00226{n:05d}", "skipped": "unpublished"} for n in range(1205, 1229)]
    assert sched.check_counts(games, gap) == []
    hole = gap[:-1] + [{"game_id": "0022600500", "skipped": "unpublished"}]
    assert any("outside the Cup block" in f for f in sched.check_counts(games, hole))


def test_walk_reads_past_gaps_inside_the_regular_season(monkeypatch):
    monkeypatch.setattr(sched, "REGULAR_SEASON_GAMES", 12)
    pages = {f"00226{n:05d}": _game(f"00226{n:05d}", f"202610{n:02d}/BOSDET") for n in (1, 2, 11, 12)}
    games, skipped, _ = sched.walk(2027, ("002",), fetch_game=pages.get, log=lambda *a, **k: None)
    assert [g["game_id"][-2:] for g in games] == ["01", "02", "11", "12"]
    assert sum(1 for s in skipped if s["skipped"] == "unpublished") == 8


def _seed(path, games):
    rows = [sched.parse_game(_game(gid, code, status=status, home_score=home, away_score=away), gid, 2027)
            for gid, code, status, home, away in games]
    for row in rows:
        row.setdefault("espn", None)
    connection = sqlite3.connect(path)
    sched.publish(connection, rows, apply=True)
    connection.close()


def test_open_refresh_reads_only_games_that_can_still_move(tmp_path):
    db = tmp_path / "picks.dev.db"
    _seed(db, [
        ("0022600001", "20261025/PHIDET", 1, None, None),   # open, inside the window: read
        ("0022600002", "20261024/MINTOR", 3, 94, 117),      # final: never read again
        ("0022600003", "20261001/SACMEM", 1, None, None),   # open but a week older than the window
        ("0022600004", "20261029/BOSNYK", 1, None, None),   # open, three days ahead: read
    ])
    requested = []

    def fetch(game_id):
        requested.append(game_id)
        if game_id == "0022600001":
            return _game(game_id, "20261025/PHIDET", status=3, home_score=93, away_score=106)
        return _game(game_id, "20261029/BOSNYK", status=1)

    report = sched.refresh_open(str(db), apply=True, fetch_game=fetch, today="2026-10-26")
    assert requested == ["0022600001", "0022600004"]
    assert report["final_now"] == 1 and report["still_open"] == 1
    assert report["stale_unfetched"] == 1 and report["failures"]
    connection = sqlite3.connect(db)
    assert connection.execute("SELECT status, away_score, home_score FROM nba_schedule "
                              "WHERE game_id='0022600001'").fetchone() == (3, 106, 93)
    connection.close()


def test_a_stale_preseason_row_is_reported_not_failed(tmp_path):
    db = tmp_path / "picks.dev.db"
    _seed(db, [("0012600001", "20261005/PHIDET", 1, None, None)])
    connection = sqlite3.connect(db)
    connection.execute("UPDATE nba_schedule SET season_type='PRE'")
    connection.commit()
    connection.close()
    report = sched.refresh_open(str(db), apply=True, fetch_game=lambda gid: None, today="2026-10-26")
    assert report["preseason_unread"] == 1
    assert report["stale_unfetched"] == 0 and report["failures"] == []


def test_open_refresh_stops_after_three_refusals(tmp_path):
    db = tmp_path / "picks.dev.db"
    _seed(db, [(f"00226000{n:02d}", f"20261025/PHIDET", 1, None, None) for n in range(1, 6)])
    calls = []

    def refused(game_id):
        calls.append(game_id)
        raise OSError("403 Forbidden")

    with pytest.raises(sched.NBAScheduleError):
        sched.refresh_open(str(db), apply=True, fetch_game=refused, today="2026-10-26")
    assert len(calls) == 3


def test_open_refresh_dry_run_writes_nothing(tmp_path):
    db = tmp_path / "picks.dev.db"
    _seed(db, [("0022600001", "20261025/PHIDET", 1, None, None)])
    report = sched.refresh_open(str(db), apply=False,
                                fetch_game=lambda gid: _game(gid, "20261025/PHIDET", status=3,
                                                             home_score=93, away_score=106),
                                today="2026-10-26")
    assert report["status"] == "ready"
    connection = sqlite3.connect(db)
    assert connection.execute("SELECT status FROM nba_schedule").fetchone() == (1,)
    connection.close()


def test_open_refresh_refuses_an_empty_schedule(tmp_path):
    db = tmp_path / "picks.dev.db"
    sqlite3.connect(db).executescript(sched.SCHEMA)
    with pytest.raises(sched.NBAScheduleError):
        sched.refresh_open(str(db), apply=True, fetch_game=lambda gid: None, today="2026-10-26")
