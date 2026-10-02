import datetime as dt
import json
import sqlite3
from unittest import mock

import pytest

import nhl_standings_store as store
from routers import games
from team_codes import CANONICAL


def published_document(*, source_season=20262027):
    rows = []
    for rank, team in enumerate(sorted(CANONICAL["nhl"]), 1):
        played = rank <= 2
        wins = 1 if rank == 1 else 0
        losses = 1 if rank == 2 else 0
        games = wins + losses
        rows.append({
            "teamAbbrev": {"default": team},
            "teamName": {"default": f"{team} Club"},
            "seasonId": source_season,
            "gameTypeId": 2,
            "date": "2026-10-01",
            "leagueSequence": rank,
            "gamesPlayed": games,
            "wins": wins,
            "losses": losses,
            "otLosses": 0,
            "points": wins * 2,
            "winPctg": wins / games if games else None,
            "pointPctg": wins / games if games else None,
            "goalDifferential": wins - losses,
            "streakCode": "W" if wins else ("L" if losses else ""),
            "streakCount": 1 if played else None,
            "l10GamesPlayed": games,
            "l10Wins": wins,
            "l10Losses": losses,
            "l10OtLosses": 0,
            "conferenceName": "Eastern" if rank <= 16 else "Western",
            "divisionName": "Test Division",
        })
    return {"standings": rows, "standingsDateTimeUtc": "2026-10-02T02:00:00Z"}


def connection(path):
    con = sqlite3.connect(path)
    con.row_factory = sqlite3.Row
    return con


def test_real_shape_names_current_season_and_preserves_published_nulls():
    snapshot = store.snapshot_from_document(
        published_document(), source_season=20262027
    )

    assert snapshot["season"] == 2027
    assert snapshot["season_label"] == "2026-27"
    assert snapshot["standings_date"] == "2026-10-01"
    assert len(snapshot["teams"]) == 32
    assert snapshot["teams"][0]["rank"] == 1
    unplayed = next(row for row in snapshot["teams"] if row["games_played"] == 0)
    assert unplayed["win_pct"] is None
    assert unplayed["last10"] is None


def test_partial_or_wrong_season_document_is_rejected():
    partial = published_document()
    partial["standings"].pop()
    with pytest.raises(store.NHLStandingsError, match="31 teams"):
        store.snapshot_from_document(partial, source_season=20262027)

    wrong = published_document(source_season=20252026)
    with pytest.raises(store.NHLStandingsError, match="!= 20262027"):
        store.snapshot_from_document(wrong, source_season=20262027)


def test_invalid_refresh_cannot_replace_last_good_snapshot(tmp_path):
    path = tmp_path / "standings.db"
    con = connection(path)
    store.ensure_table(con)
    good = store.snapshot_from_document(
        published_document(), source_season=20262027
    )
    store.publish_snapshot(
        con, good, captured_at=dt.datetime.now(dt.timezone.utc).isoformat()
    )
    con.commit()

    partial = published_document()
    partial["standings"].pop()
    with pytest.raises(store.NHLStandingsError):
        store.snapshot_from_document(partial, source_season=20262027)

    stored = store.read_snapshot(con, league="nhl")
    assert stored["season"] == 2027
    assert len(stored["teams"]) == 32
    con.close()


def test_route_reads_snapshot_without_calling_espn(tmp_path):
    path = tmp_path / "standings-route.db"
    con = connection(path)
    store.ensure_table(con)
    store.publish_snapshot(
        con,
        store.snapshot_from_document(
            published_document(), source_season=20262027
        ),
        captured_at="2026-10-02T02:00:00+00:00",
    )
    con.commit()
    con.close()

    with mock.patch.object(games, "_db", side_effect=lambda: connection(path)), \
            mock.patch.object(games.espn, "team_strength_standings") as upstream:
        response = games.get_standings("nhl")

    payload = json.loads(response.body)
    assert payload["season"] == 2027
    assert payload["season_label"] == "2026-27"
    assert payload["available_seasons"] == [2027]
    assert len(payload["teams"]) == 32
    assert response.headers["x-lp-data-source"] == "nhle.com:standings/now"
    upstream.assert_not_called()
