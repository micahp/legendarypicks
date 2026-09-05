import datetime as dt

from routers.games import ufc_optimizer as pool


NOW = dt.datetime(2026, 9, 5, 12, 0, tzinfo=dt.timezone.utc)


def source(cancelled=False, lock="2026-09-05 14:00:00"):
    events = {}
    players = []
    projections = []
    event_ids = []
    for fight in range(4):
        event_id = str(100 + fight)
        event_ids.append(int(event_id))
        first, second = str(fight * 2 + 1), str(fight * 2 + 2)
        events[event_id] = {
            "eventDate": lock, "eventName": "UFC New Fighters",
            "status": "CANCELLED" if cancelled and fight == 0 else "SCHEDULED",
            "fighter1": {"id": first}, "fighter2": {"id": second},
        }
        for assignment, fighter_id in enumerate((first, second), start=fight * 2 + 10):
            players.append({
                "slateID": assignment, "rwID": int(fighter_id),
                "firstName": "Never", "lastName": f"Seen {fighter_id}",
                "salary": 7000 + assignment, "countryFlag": "Nowhere",
                "stats": {"record": "1-0-0"}, "odds": {},
            })
            projections.append({"slateID": assignment, "pts": "50.5"})
    slate = {"slateID": 77, "contestType": "Classic", "startDate": lock, "events": event_ids}

    def get_json(url):
        if url == pool.SLATES:
            return {"slates": [slate], "events": events}
        if "players.php" in url:
            return players
        if "projections.php" in url:
            return {"projections": projections}
        raise AssertionError(url)

    return get_json


def test_current_pool_accepts_fighters_not_in_the_local_spine():
    result = pool.build_current_pool(now=NOW, get_json=source())
    assert result["slate"]["fightCount"] == 4
    assert len(result["slate"]["fighters"]) == 8
    assert result["slate"]["fighters"][0]["name"] == "Never Seen 1"
    assert result["slate"]["fighters"][0]["opponentId"] == "rw:2"


def test_publisher_cancelled_fight_and_both_salary_rows_are_removed():
    result = pool.build_current_pool(now=NOW, get_json=source(cancelled=True))
    assert result["excluded_cancelled_fights"] == 1
    assert result["slate"]["fightCount"] == 3
    assert len(result["slate"]["fighters"]) == 6
    assert not {"rw:1", "rw:2"}.intersection(f["id"] for f in result["slate"]["fighters"])


def test_locked_pool_returns_unavailable_without_fetching_salary_rows():
    calls = []
    get_json = source(lock="2026-09-05 07:00:00")

    def tracked(url):
        calls.append(url)
        return get_json(url)

    result = pool.build_current_pool(now=NOW, get_json=tracked)
    assert result["slate"] is None
    assert result["reason"] == "no_unlocked_classic_pool"
    assert calls == [pool.SLATES]


def test_unexplained_missing_fighter_fails_closed():
    get_json = source()

    def missing(url):
        value = get_json(url)
        return value[:-1] if "players.php" in url else value

    try:
        pool.build_current_pool(now=NOW, get_json=missing)
    except RuntimeError as exc:
        assert "two fighters" in str(exc)
    else:
        raise AssertionError("one-sided active fight was accepted")
