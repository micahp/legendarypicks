import sqlite3
from pathlib import Path
from unittest import mock

import pytest

import ingest_nhl_logs as ingest


GAME = {
    "game_id": "2026020001",
    "game_date": "2026-09-29",
    "game_state": "OFF",
    "away": "ANA",
    "home": "BOS",
}


def standings_row(team, rank, *, wins=1, losses=0, ot_losses=0):
    games = wins + losses + ot_losses
    return {
        "teamAbbrev": {"default": team},
        "teamName": {"default": f"{team} Club"},
        "seasonId": 20262027,
        "gameTypeId": 2,
        "date": "2026-09-29",
        "leagueSequence": rank,
        "gamesPlayed": games,
        "wins": wins,
        "losses": losses,
        "otLosses": ot_losses,
        "points": wins * 2 + ot_losses,
        "winPctg": wins / games if games else None,
        "pointPctg": (wins * 2 + ot_losses) / (games * 2) if games else None,
        "goalDifferential": wins - losses,
        "streakCode": "W" if wins else "L",
        "streakCount": 1 if games else 0,
        "l10GamesPlayed": games,
        "l10Wins": wins,
        "l10Losses": losses,
        "l10OtLosses": ot_losses,
        "conferenceName": "Eastern",
        "divisionName": "Atlantic",
    }


def schedule_game():
    return {
        "id": 2026020001,
        "gameDate": "2026-09-29",
        "gameState": "OFF",
        "gameType": 2,
        "awayTeam": {"abbrev": "ANA"},
        "homeTeam": {"abbrev": "BOS"},
    }


def test_schedule_population_is_proved_by_two_club_schedules():
    standings = {
        "standings": [
            standings_row("ANA", 1),
            standings_row("BOS", 2, wins=0, losses=1),
        ]
    }
    season = {"data": [{
        "id": 20262027,
        "numberOfGames": 1,
        "totalRegularSeasonGames": 1,
        "startDate": "2026-09-29T17:00:00",
        "regularSeasonEndDate": "2027-04-10T00:00:00",
    }]}

    def fake_get(url):
        if url == ingest.TEAM_DIRECTORY_URL:
            return standings
        if "stats/rest/en/season" in url:
            return season
        return {"currentSeason": 20262027, "games": [schedule_game()]}

    with mock.patch.object(ingest, "EXPECTED_TEAMS", 2), \
            mock.patch.object(ingest, "_get", fake_get):
        result = ingest.fetch_schedule(20262027)

    assert result["season"] == 2027
    assert result["scheduled_games"] == 1
    assert result["games_per_team"] == 1
    assert set(result["completed"]) == {"2026020001"}
    assert result["team_ids"] == {"ANA": "ANA", "BOS": "BOS"}
    assert result["standings"]["season_label"] == "2026-27"
    assert [row["abbrev"] for row in result["standings"]["teams"]] == ["ANA", "BOS"]


def test_schedule_refuses_a_game_missing_from_the_opponents_schedule():
    standings = {
        "standings": [
            standings_row("ANA", 1),
            standings_row("BOS", 2, wins=0, losses=1),
        ]
    }
    season = {"data": [{
        "id": 20262027,
        "numberOfGames": 1,
        "totalRegularSeasonGames": 1,
        "startDate": "2026-09-29T17:00:00",
        "regularSeasonEndDate": "2027-04-10T00:00:00",
    }]}

    def fake_get(url):
        if url == ingest.TEAM_DIRECTORY_URL:
            return standings
        if "stats/rest/en/season" in url:
            return season
        if "/ANA/" in url:
            return {"currentSeason": 20262027, "games": [schedule_game()]}
        other = dict(schedule_game(), id=2026020002)
        return {"currentSeason": 20262027, "games": [other]}

    with mock.patch.object(ingest, "EXPECTED_TEAMS", 2), \
            mock.patch.object(ingest, "_get", fake_get), \
            pytest.raises(ingest.NHLLogIngestError, match="unique games"):
        ingest.fetch_schedule(20262027)


def database(path: Path):
    connection = sqlite3.connect(path)
    connection.executescript(
        """
        CREATE TABLE players(id INTEGER PRIMARY KEY, league TEXT, nhl_id INTEGER);
        CREATE TABLE team_game_results(
          league TEXT, game_id TEXT, team TEXT, game_date TEXT, opponent TEXT,
          home_away TEXT, score_for REAL, score_against REAL, win INTEGER,
          season INTEGER, status TEXT, source TEXT, run_id TEXT,
          PRIMARY KEY(league,game_id,team)
        );
        CREATE TABLE team_game_stats(
          league TEXT, game_id TEXT, captured_at TEXT, team_abbrev TEXT,
          home_away TEXT, run_id TEXT, source TEXT, shots INTEGER,
          blocked_shots INTEGER, hits INTEGER, takeaways INTEGER,
          giveaways INTEGER, faceoff_pct REAL, powerplay_goals INTEGER,
          powerplay_opps INTEGER, shorthanded_goals INTEGER, penalty_min INTEGER,
          stats TEXT, UNIQUE(league,game_id,team_abbrev)
        );
        CREATE TABLE team_stats_coverage(
          run_id TEXT PRIMARY KEY, league TEXT, season INTEGER,
          season_start TEXT, season_end TEXT, status TEXT,
          expected_teams INTEGER, fetched_teams INTEGER, expected_games INTEGER,
          fetched_games INTEGER, paired_games INTEGER, paired_stat_games INTEGER,
          failure_count INTEGER, completed_at TEXT, source TEXT,
          checked_through TEXT
        );
        CREATE TABLE team_stats_team_inventory(
          run_id TEXT, team_id TEXT, team_abbrev TEXT,
          PRIMARY KEY(run_id,team_id)
        );
        CREATE TABLE team_stats_ingestion_failures(
          run_id TEXT, game_id TEXT, team TEXT, reason TEXT
        );
        """
    )
    connection.executemany(
        "INSERT INTO players VALUES(?,?,?)",
        [(1, "nhl", 101), (2, "nhl", 202)],
    )
    connection.commit()
    connection.close()


def publication():
    team_values = {
        "shots": 30, "blocked_shots": 10, "hits": 20, "takeaways": 5,
        "giveaways": 8, "faceoff_pct": 50.0, "powerplay_goals": 1,
        "powerplay_opps": 3, "shorthanded_goals": 0, "penalty_min": 4,
    }
    return {
        "source_season": 20262027,
        "season": 2027,
        "season_start": "2026-09-29",
        "season_end": "2027-04-10",
        "scheduled_games": 1,
        "games_per_team": 1,
        "teams": {"ANA": "ANA", "BOS": "BOS"},
        "team_ids": {"ANA": "1", "BOS": "2"},
        "standings": {
            "league": "nhl",
            "season": 2027,
            "source_season": 20262027,
            "season_label": "2026-27",
            "standings_date": "2026-09-29",
            "source": "nhle.com:standings/now",
            "teams": [
                {"rank": 1, "abbrev": "ANA", "name": "ANA Club"},
                {"rank": 2, "abbrev": "BOS", "name": "BOS Club"},
            ],
        },
        "completed": {GAME["game_id"]: GAME},
        "completed_games": 1,
        "checked_through": "2026-09-29",
        "player_rows": [
            {"player_id": 1, "source_player_key": "101", "game_id": GAME["game_id"],
             "game_date": GAME["game_date"], "team": "ANA", "opponent": "BOS",
             "home_away": "away", "stats": {"goals": 1, "shots": 3}},
            {"player_id": 2, "source_player_key": "202", "game_id": GAME["game_id"],
             "game_date": GAME["game_date"], "team": "BOS", "opponent": "ANA",
             "home_away": "home", "stats": {"saves": 29, "shotsAgainst": 30}},
        ],
        "result_rows": [
            {"game_id": GAME["game_id"], "game_date": GAME["game_date"],
             "team": "ANA", "opponent": "BOS", "home_away": "away",
             "score_for": 2, "score_against": 1, "win": 1},
            {"game_id": GAME["game_id"], "game_date": GAME["game_date"],
             "team": "BOS", "opponent": "ANA", "home_away": "home",
             "score_for": 1, "score_against": 2, "win": 0},
        ],
        "stat_rows": [
            {"game_id": GAME["game_id"], "team": "ANA", "home_away": "away",
             "values": dict(team_values)},
            {"game_id": GAME["game_id"], "team": "BOS", "home_away": "home",
             "values": dict(team_values)},
        ],
    }


def test_apply_publishes_logs_pairs_stats_and_manifest_together(tmp_path):
    path = tmp_path / "candidate.db"
    database(path)

    with mock.patch.object(ingest, "EXPECTED_TEAMS", 2):
        result = ingest.publish(str(path), publication(), apply=True)

    connection = sqlite3.connect(path)
    assert connection.execute(
        "SELECT COUNT(*) FROM player_game_logs WHERE season=2027"
    ).fetchone()[0] == 2
    assert connection.execute(
        "SELECT COUNT(*) FROM team_game_results WHERE season=2027"
    ).fetchone()[0] == 2
    assert connection.execute(
        "SELECT COUNT(*) FROM team_game_stats WHERE league='nhl'"
    ).fetchone()[0] == 2
    manifest = connection.execute(
        "SELECT status,expected_games,fetched_games,paired_games,paired_stat_games "
        "FROM team_stats_coverage WHERE season=2027"
    ).fetchone()
    assert manifest == ("complete", 1, 1, 1, 1)
    stored = connection.execute(
        "SELECT season,season_label,team_count,source FROM league_standings_snapshots"
    ).fetchone()
    assert stored == (2027, "2026-27", 2, "nhle.com:standings/now")
    assert result["status"] == "published"
    connection.close()


SEASON_LIST = {"seasons": [
    {"id": 20242025, "standingsStart": "2024-10-04", "standingsEnd": "2025-04-17"},
    {"id": 20252026, "standingsStart": "2025-10-07", "standingsEnd": "2026-04-17"},
    {"id": 20262027, "standingsStart": "2026-09-29", "standingsEnd": "2026-10-01"},
]}


def test_current_season_reads_standings_now():
    with mock.patch.object(ingest, "_get", return_value=SEASON_LIST):
        url, source = ingest.standings_endpoint(20262027)
    assert url == ingest.TEAM_DIRECTORY_URL
    assert source == "nhle.com:standings/now"


def test_completed_season_reads_its_own_published_end_date():
    """standings/now would answer for 20252026 with THIS season's table."""
    with mock.patch.object(ingest, "_get", return_value=SEASON_LIST):
        url, source = ingest.standings_endpoint(20252026)
    assert url == "https://api-web.nhle.com/v1/standings/2026-04-17"
    assert source == "nhle.com:standings/2026-04-17"
    # The source must say which endpoint answered, or two snapshots taken from
    # two different URLs are indistinguishable once stored.
    assert source != "nhle.com:standings/now"


def test_a_season_the_league_does_not_publish_fails_closed():
    with mock.patch.object(ingest, "_get", return_value=SEASON_LIST):
        with pytest.raises(ingest.NHLStandingsError, match="does not publish"):
            ingest.standings_endpoint(19992000)


def test_a_season_published_without_an_end_date_fails_closed():
    broken = {"seasons": [{"id": 20262027, "standingsEnd": "2026-10-01"},
                          {"id": 20252026, "standingsEnd": None}]}
    with mock.patch.object(ingest, "_get", return_value=broken):
        with pytest.raises(ingest.NHLStandingsError, match="standingsEnd"):
            ingest.standings_endpoint(20252026)
