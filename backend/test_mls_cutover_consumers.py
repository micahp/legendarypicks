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
    monkeypatch.setattr(mls_resolution, "CUTOVER_ENABLED", False)


@pytest.fixture
def cutover_on(monkeypatch):
    monkeypatch.setattr(mls_resolution, "CUTOVER_ENABLED", True)


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
