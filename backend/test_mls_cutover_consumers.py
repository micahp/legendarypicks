"""The MLS cutover reaches every consumer of stale observation rows, not only the props resolver.

With the cutover on, a departed person's observation row must not bind an identity (backfill) and must not copy a club
into players.team (refresh). With it off, each consumer behaves exactly as before.
"""
import sqlite3

import pytest

import mls_resolution
import published_roster
import refresh_soccer_player_teams as refresh
import test_mls_cutover_acceptance as acc
from backfill_from_published_roster import run as backfill_run


def _world_with_departed_person():
    w = acc.World()
    w.cycle(acc.D1)
    w.drop_person(5)          # person 5 has left both publishers
    w.cycle(acc.D2)
    # Their observation row from the earlier roster run is still in published_roster.
    w.con.execute("DELETE FROM player_source_ids WHERE player_id=5")  # no bind left to keep
    name = "Dara Quill"  # a distinctive name: the fold keeps letters only, so generated names would collide
    w.con.execute("UPDATE players SET name=? WHERE id=5", (name,))
    folded = published_roster.fold(name)  # the job's own fold, never a hand-written copy of it
    w.con.execute("INSERT INTO published_roster(league, source, source_player_key, name, name_folded, team, position, "
                  "position_group, team_code, updated_at, player_id) VALUES('mls','fotmob','f5',?,?,'Club01','M',"
                  "'midfield','CLB',?,5)", (name, folded, acc.D1))
    w.con.execute("INSERT INTO published_roster_name(league, source, source_player_key, name, name_folded) "
                  "VALUES('mls','fotmob','f5',?,?)", (name, folded))
    w.con.commit()
    return w


@pytest.fixture
def cutover_off(monkeypatch):
    monkeypatch.delenv(mls_resolution.CUTOVER_ENV, raising=False)


@pytest.fixture
def cutover_on(monkeypatch):
    monkeypatch.setenv(mls_resolution.CUTOVER_ENV, "1")


def _file_copy(w, tmp_path):
    path = str(tmp_path / "consumers.db")
    target = sqlite3.connect(path)
    w.con.backup(target)
    target.close()
    return path


def test_backfill_does_not_bind_a_departed_person_from_a_stale_row(tmp_path, cutover_on):
    w = _world_with_departed_person()
    path = _file_copy(w, tmp_path)
    backfill_run(path, ["mls"], apply_changes=True)
    con = sqlite3.connect(path)
    bound = con.execute("SELECT COUNT(*) FROM player_source_ids WHERE player_id=5").fetchone()[0]
    con.close()
    assert bound == 0, "a departed person is not re-bound from a stale observation row"


def test_backfill_with_the_cutover_off_binds_as_before(tmp_path, cutover_off):
    w = _world_with_departed_person()
    path = _file_copy(w, tmp_path)
    backfill_run(path, ["mls"], apply_changes=True)
    con = sqlite3.connect(path)
    bound = con.execute("SELECT COUNT(*) FROM player_source_ids WHERE player_id=5").fetchone()[0]
    con.close()
    assert bound >= 1, "the legacy behavior is unchanged while the cutover is off"


def test_refresh_never_copies_a_departed_persons_stale_club(cutover_on):
    w = _world_with_departed_person()
    changes, _ = refresh.plan(w.con)
    assert all(pid != 5 for pid, *_ in changes), "a departed person's stale roster row proposes no club"


def test_refresh_plans_mls_clubs_as_before_while_the_cutover_is_off(cutover_off):
    w = _world_with_departed_person()
    w.con.execute("UPDATE players SET team='WRONG' WHERE id=6")
    changes, _ = refresh.plan(w.con)
    assert any(pid == 5 for pid, *_ in changes), "the legacy plan still copies the stale club while the cutover is off"


def test_a_past_game_resolves_to_the_club_on_its_day_and_today_uses_the_current_membership(cutover_on):
    import datetime as dt
    import _core
    w = _world_with_departed_person()     # person 5 was on the squads on 2026-10-27 and left on 2026-10-28
    w.con.execute("CREATE TABLE IF NOT EXISTS prop_games(id INTEGER PRIMARY KEY, league TEXT, date TEXT, home TEXT, "
                  "away TEXT, start_time TEXT)")
    today = dt.date.today().isoformat()
    w.con.execute("INSERT INTO prop_games(id, league, date, home, away, start_time) VALUES(1,'mls','2026-10-27',"
                  "'Club01','Club02','2026-10-27T19:00:00+00:00')")
    w.con.execute("INSERT INTO prop_games(id, league, date, home, away, start_time) VALUES(2,'mls',?,'Club01','Club02',"
                  "?)", (today, today + "T19:00:00+00:00"))
    w.con.commit()
    name = "Dara Quill"
    past = _core._resolve_player_for_ingest(w.con, name, "Club01", "mls", game_id=1)
    now_ = _core._resolve_player_for_ingest(w.con, name, "Club01", "mls", game_id=2)
    assert past[0] == 5, "a game played while the person was on the club resolves to them, after they left"
    assert now_[0] is None, "a game today uses the current membership, which no longer has the person"


def test_under_the_gate_backfill_never_reads_an_observation_row(tmp_path, cutover_on, monkeypatch):
    import published_roster as pr

    def refuse(*args, **kwargs):
        raise AssertionError("backfill read an observation row while the cutover is on")

    monkeypatch.setattr(pr, "lookup", refuse)
    w = _world_with_departed_person()
    path = _file_copy(w, tmp_path)
    backfill_run(path, ["mls"], apply_changes=True)  # would raise if it consulted observation rows


def test_under_the_gate_spine_planning_never_reads_an_observation_row(cutover_on, monkeypatch):
    import published_roster as pr
    import spine_merge

    def refuse(*args, **kwargs):
        raise AssertionError("spine planning read an observation row while the cutover is on")

    monkeypatch.setattr(pr, "lookup", refuse)
    w = _world_with_departed_person()
    assert spine_merge._published_groups(w.con, "mls") == [], "no two current people share a publisher key"


def test_a_named_game_whose_day_cannot_be_established_fails_closed(cutover_on):
    import _core
    w = _world_with_departed_person()
    w.con.execute("CREATE TABLE IF NOT EXISTS prop_games(id INTEGER PRIMARY KEY, league TEXT, date TEXT, home TEXT, "
                  "away TEXT, start_time TEXT)")
    w.con.execute("INSERT INTO prop_games(id, league, date, home, away, start_time) VALUES(3,'mls',NULL,'Club01',"
                  "'Club02',NULL)")
    w.con.execute("INSERT INTO prop_games(id, league, date, home, away, start_time) VALUES(4,'mls','not-a-date',"
                  "'Club01','Club02',NULL)")
    w.con.commit()
    for game_id in (3, 4, 999):  # no date, an unreadable date, and a game that does not exist
        assert _core._resolve_player_for_ingest(w.con, "Dara Quill", "Club01", "mls", game_id=game_id) == (None, None), \
            "a named game whose day cannot be established must fail closed (game %s)" % game_id


def test_props_show_the_current_club_for_upcoming_games_and_the_stored_club_for_past_games(cutover_on):
    import mls_resolution as mr
    w = acc.World()
    w.cycle(acc.D1)
    w.move(6, "Club02")           # person 6 changed clubs; players.team keeps the old value
    w.cycle(acc.D2)
    w.con.execute("CREATE TABLE IF NOT EXISTS prop_games(id INTEGER PRIMARY KEY, league TEXT, date TEXT, home TEXT, "
                  "away TEXT, start_time TEXT)")
    w.con.execute("INSERT INTO prop_games VALUES(1,'mls','2026-10-27','Club01','Club03',NULL)")
    w.con.execute("INSERT INTO prop_games VALUES(2,'mls','2099-01-01','Club01','Club03',NULL)")
    expr = mr.club_now_sql("pl.id", "pl.league", "pl.team", "NULL", "pg.date >= date('now')")
    sql = "SELECT {} FROM players pl JOIN prop_games pg ON pg.id = ? AND pl.id = 6".format(expr)
    assert w.con.execute(sql, (2,)).fetchone()[0] == "Club02", "an upcoming game shows the current club"
    assert w.con.execute(sql, (1,)).fetchone()[0] == "Club01", "a past game keeps the club it was played for"


def test_player_stats_club_for_a_departed_mls_player_is_the_season_club_not_the_stale_stored_one(cutover_on):
    import mls_resolution as mr
    w = _world_with_departed_person()
    w.con.execute("CREATE TABLE IF NOT EXISTS player_stats(player_id INTEGER, league TEXT, team TEXT)")
    w.con.execute("INSERT INTO player_stats VALUES(5, 'mls', 'Season Club')")
    expr = mr.club_now_sql("ps.player_id", "p.league", "COALESCE(p.team, ps.team)", "ps.team")
    sql = "SELECT {} FROM player_stats ps JOIN players p ON p.id = ps.player_id".format(expr)
    assert w.con.execute(sql).fetchone()[0] == "Season Club", "a departed person's stored club is never shown as current"


def test_with_the_cutover_off_the_club_expressions_are_the_legacy_sql(cutover_off):
    import mls_resolution as mr
    assert mr.club_now_sql("pl.id", "pl.league", "pl.team", "NULL", "pg.date >= date('now')") == "pl.team"
    assert mr.club_now_sql("ps.player_id", "p.league", "COALESCE(p.team, ps.team)", "ps.team") == \
        "COALESCE(p.team, ps.team)"
