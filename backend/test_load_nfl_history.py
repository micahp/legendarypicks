import os
import sqlite3

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

import load_nfl_history as L


def _inj(path, teams):
    cols = L.SOURCES["injuries"][1]
    data = {c: [None] * len(teams) for c in cols}
    data["season"] = [2015] * len(teams)
    data["week"] = [1] * len(teams)
    data["team"] = teams
    data["gsis_id"] = ["00-%07d" % i for i in range(len(teams))]
    pq.write_table(pa.table(data), path)


def _con(tmp_path):
    con = sqlite3.connect(str(tmp_path / "t.db"), isolation_level=None)
    L.migrate(con)
    return con


def test_rerun_replaces_and_maps_codes(tmp_path):
    f = str(tmp_path / "injuries_2015.parquet")
    _inj(f, ["STL", "SD", "WAS"])
    con = _con(tmp_path)
    L.load(con, "injuries", f, 2015)
    L.load(con, "injuries", f, 2015)
    rows = con.execute("SELECT team FROM nfl_hist_injuries ORDER BY team").fetchall()
    assert [r[0] for r in rows] == ["LAC", "LAR", "WSH"]
    assert con.execute("SELECT COUNT(*) FROM nfl_hist_loads").fetchone()[0] == 2


def test_unknown_team_raises_and_keeps_previous_rows(tmp_path):
    good = str(tmp_path / "good.parquet")
    bad = str(tmp_path / "bad.parquet")
    _inj(good, ["KC"])
    _inj(bad, ["KC", "XXX"])
    con = _con(tmp_path)
    L.load(con, "injuries", good, 2015)
    with pytest.raises(Exception):
        L.load(con, "injuries", bad, 2015)
    assert con.execute("SELECT COUNT(*) FROM nfl_hist_injuries").fetchone()[0] == 1


def test_wrong_season_in_file_raises(tmp_path):
    f = str(tmp_path / "x.parquet")
    _inj(f, ["KC"])
    con = _con(tmp_path)
    with pytest.raises(RuntimeError):
        L.load(con, "injuries", f, 2016)


def test_prod_db_refused(monkeypatch):
    monkeypatch.setenv("LP_DB_PATH", "/root/legendarypicks/backend/data/picks.db")
    with pytest.raises(SystemExit):
        L.main(["--migrate"])


def _part(path, game_ids):
    cols = [c for c in L.SOURCES["participation"][1] if c != "season"]
    data = {c: [None] * len(game_ids) for c in cols}
    data["nflverse_game_id"] = game_ids
    data["play_id"] = [float(i + 1) for i in range(len(game_ids))]
    data["possession_team"] = ["LA"] * len(game_ids)
    pq.write_table(pa.table(data), path)


def test_participation_season_comes_from_the_argument(tmp_path):
    f = str(tmp_path / "p.parquet")
    _part(f, ["2016_01_LA_SF", "2016_01_LA_SF"])
    con = _con(tmp_path)
    L.load(con, "participation", f, 2016)
    rows = con.execute("SELECT season, possession_team FROM nfl_hist_participation").fetchall()
    assert rows == [(2016, "LAR"), (2016, "LAR")]


def test_participation_game_id_from_another_season_raises(tmp_path):
    f = str(tmp_path / "p.parquet")
    _part(f, ["2016_01_LA_SF", "2017_01_LA_SF"])
    con = _con(tmp_path)
    with pytest.raises(RuntimeError):
        L.load(con, "participation", f, 2016)
    assert con.execute("SELECT COUNT(*) FROM nfl_hist_participation").fetchone()[0] == 0
