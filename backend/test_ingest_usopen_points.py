import json
import sqlite3
import sys

import pytest

import ingest_usopen_points as mod


def capture_record(match_id, point_id, **extra):
    rec = {
        "MatchID": match_id,
        "PointID": point_id,
        "PointNumber": "1",
        "SetNo": "1",
        "GameNo": "1",
        "ServeNumber": "1",
        "Stage": "R128",
        "Sentence": "Player wins point",
        "PointWinner": "P1",
        "PointServer": "P1",
        "MatchWinner": "P1",
        "P1Score": "0",
        "P2Score": "0",
        "EpochTimeStart": "1000",
        "EpochTimeEnd": "1010",
        "ElapsedTime": "00:00:10",
    }
    rec.update(extra)
    return rec


@pytest.fixture
def sources(tmp_path, monkeypatch):
    # Capture: two real points and two non-point rows (blank PointID) for match 101, plus a trailing blank line.
    capture = tmp_path / "USOPEN_POINTS_test.jsonl"
    lines = [
        capture_record(101, "p1"),
        capture_record(101, "p2"),
        capture_record(101, ""),
        capture_record(101, ""),
    ]
    capture.write_text("\n".join(json.dumps(r) for r in lines) + "\n\n")
    # History: one file per match. Filenames sort numerically, so 2.json comes before 10.json.
    history = tmp_path / "history"
    history.mkdir()
    (history / "10.json").write_text(json.dumps([capture_record(203, "h3")]))
    (history / "2.json").write_text(json.dumps([capture_record(202, "h1"), capture_record(202, "h2")]))
    monkeypatch.setattr(mod, "CAPTURE", capture)
    monkeypatch.setattr(mod, "HISTORY_DIR", history)
    return capture, history


def run_main(monkeypatch, *args):
    monkeypatch.setattr(sys, "argv", ["ingest_usopen_points.py", *args])
    return mod.main()


def test_row_from_marks_blank_point_ids_as_non_points_and_strips_real_ones():
    real = mod.row_from("capture", "f", capture_record(101, " p1 "), "t")
    blank = mod.row_from("capture", "f", capture_record(101, "  "), "t")
    assert real[3] == "p1"
    assert real[4] == 1
    assert blank[3] == ""
    assert blank[4] == 0


def test_row_from_stringifies_the_match_id_and_keeps_the_raw_record():
    rec = capture_record(101, "p1")
    row = mod.row_from("capture", "f", rec, "t")
    assert row[2] == "101"
    assert json.loads(row[19]) == rec
    assert row[20] == "t"


def test_collect_reads_capture_first_then_history_in_numeric_order(sources):
    rows = mod.collect()
    assert [r[0] for r in rows] == ["capture"] * 4 + ["history"] * 3
    assert {r[1] for r in rows if r[0] == "capture"} == {"USOPEN_POINTS_test.jsonl"}
    assert [r[1] for r in rows if r[0] == "history"] == ["2.json", "2.json", "10.json"]
    assert [r[3] for r in rows if r[0] == "history"] == ["h1", "h2", "h3"]


def test_dry_run_counts_rows_and_writes_nothing(sources, tmp_path, monkeypatch, capsys):
    db = tmp_path / "picks.dev.db"
    assert run_main(monkeypatch, "--db", str(db)) == 0
    out = capsys.readouterr().out
    assert "rows to load: 7 (capture 4, history 3)" in out
    assert "real points: 5, non-point rows: 2" in out
    assert "distinct matches: 3" in out
    assert "dry run" in out
    assert not db.exists()


def test_apply_loads_every_row_with_the_expected_split(sources, tmp_path, monkeypatch):
    db = tmp_path / "picks.dev.db"
    assert run_main(monkeypatch, "--db", str(db), "--apply") == 0
    con = sqlite3.connect(db)
    try:
        assert con.execute("SELECT COUNT(*) FROM usopen_points").fetchone()[0] == 7
        assert con.execute("SELECT COUNT(*) FROM usopen_points WHERE is_point = 1").fetchone()[0] == 5
        assert con.execute(
            "SELECT source, COUNT(*) FROM usopen_points GROUP BY source ORDER BY source"
        ).fetchall() == [("capture", 4), ("history", 3)]
        assert con.execute("SELECT COUNT(DISTINCT match_id) FROM usopen_points").fetchone()[0] == 3
    finally:
        con.close()


def test_a_second_apply_refuses_to_insert_again(sources, tmp_path, monkeypatch):
    db = tmp_path / "picks.dev.db"
    run_main(monkeypatch, "--db", str(db), "--apply")
    with pytest.raises(SystemExit, match="already has 7 rows"):
        run_main(monkeypatch, "--db", str(db), "--apply")
    con = sqlite3.connect(db)
    try:
        assert con.execute("SELECT COUNT(*) FROM usopen_points").fetchone()[0] == 7
    finally:
        con.close()


def test_refuses_any_database_that_is_not_the_dev_db(sources, tmp_path, monkeypatch):
    db = tmp_path / "picks.db"
    with pytest.raises(SystemExit, match="not the dev database"):
        run_main(monkeypatch, "--db", str(db), "--apply")
    assert not db.exists()


def test_a_duplicate_real_point_aborts_the_whole_load(tmp_path, monkeypatch):
    capture = tmp_path / "dup.jsonl"
    capture.write_text(
        "\n".join(json.dumps(r) for r in [capture_record(101, "p1"), capture_record(101, "p1")]) + "\n"
    )
    history = tmp_path / "history"
    history.mkdir()
    monkeypatch.setattr(mod, "CAPTURE", capture)
    monkeypatch.setattr(mod, "HISTORY_DIR", history)
    db = tmp_path / "picks.dev.db"
    with pytest.raises(sqlite3.IntegrityError):
        run_main(monkeypatch, "--db", str(db), "--apply")
    con = sqlite3.connect(db)
    try:
        tables = [r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type = 'table'")]
        assert "usopen_points" not in tables or con.execute("SELECT COUNT(*) FROM usopen_points").fetchone()[0] == 0
    finally:
        con.close()
