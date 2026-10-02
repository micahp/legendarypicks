import datetime as dt

from routers.games import ufc_optimizer as pool


NOW = dt.datetime(2026, 9, 5, 12, 0, tzinfo=dt.timezone.utc)


def source(cancelled=False, lock="2026-09-05 14:00:00", pool_only=False,
           unavailable=False):
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
        salaries = (9000 - fight * 200, 7200 + fight * 200)
        for offset, (assignment, fighter_id) in enumerate(
            zip(range(fight * 2 + 10, fight * 2 + 12), (first, second))
        ):
            players.append({
                "slateID": assignment, "rwID": int(fighter_id),
                "firstName": "Never", "lastName": f"Seen {fighter_id}",
                "salary": salaries[offset], "countryFlag": "Nowhere",
                "event": {"dateTime": lock},
                "stats": {"record": "1-0-0", "eventWeightClass": "Testweight"}, "odds": {},
            })
            projections.append({"slateID": assignment, "pts": "50.5"})
    if pool_only:
        for assignment, fighter_id, salary in ((90, 90, 9000), (91, 91, 7200)):
            players.append({
                "slateID": assignment, "rwID": fighter_id,
                "firstName": "Pool", "lastName": f"Only {fighter_id}",
                "salary": salary, "countryFlag": "Nowhere", "injuryStatus": None,
                "event": {"dateTime": lock},
                "stats": {"record": "1-0-0", "eventWeightClass": "Poolweight"}, "odds": {},
            })
            projections.append({"slateID": assignment, "pts": "60.5"})
    if unavailable:
        for assignment, fighter_id, salary in ((92, 92, 8500), (93, 93, 7700)):
            players.append({
                "slateID": assignment, "rwID": fighter_id,
                "firstName": "Unavailable", "lastName": str(fighter_id),
                "salary": salary, "countryFlag": "Nowhere", "injuryStatus": "Out",
                "event": {"dateTime": None},
                "stats": {"record": "1-0-0", "eventWeightClass": None}, "odds": {},
            })
            projections.append({"slateID": assignment, "pts": "0"})
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


def test_priced_fighters_in_no_published_bout_are_excluded_never_paired():
    """The salary feed keeps a replaced fighter. The event list is the matchup."""
    result = pool.build_current_pool(now=NOW, get_json=source(pool_only=True, unavailable=True))
    fighters = {fighter["id"]: fighter for fighter in result["slate"]["fighters"]}

    assert result["excluded_unmatched_fighters"] == 2
    assert result["excluded_unavailable_fighters"] == 2
    assert result["slate"]["fightCount"] == 4
    assert len(fighters) == 8
    assert not {"rw:90", "rw:91", "rw:92", "rw:93"}.intersection(fighters)
    assert result["slate"]["lockAt"] == "2026-09-05T18:00:00+00:00"


def test_bout_priced_on_one_side_is_dropped_whole_and_the_rest_still_serve():
    """A late replacement is in the bout before DraftKings prices him."""
    get_json = source()

    def missing(url):
        value = get_json(url)
        return value[:-1] if "players.php" in url else value

    result = pool.build_current_pool(now=NOW, get_json=missing)
    fighters = {fighter["id"]: fighter for fighter in result["slate"]["fighters"]}

    assert result["excluded_unpriced_fights"] == 1
    assert result["slate"]["fightCount"] == 3
    assert len(fighters) == 6
    # Both sides of the unpriced bout leave, so no half-bout reaches the board.
    assert not {"rw:7", "rw:8"}.intersection(fighters)
    for fighter in fighters.values():
        assert fighters[fighter["opponentId"]]["opponentId"] == fighter["id"]


def test_duplicate_pool_fighter_fails_closed():
    get_json = source()

    def duplicated(url):
        value = get_json(url)
        if "players.php" not in url:
            return value
        return list(value) + [dict(value[-1])]

    try:
        pool.build_current_pool(now=NOW, get_json=duplicated)
    except RuntimeError as exc:
        assert "duplicate" in str(exc)
    else:
        raise AssertionError("a duplicate priced fighter was accepted")


def test_slate_without_enough_whole_bouts_fails_closed():
    get_json = source()

    def thinned(url):
        value = get_json(url)
        return value[:5] if "players.php" in url else value

    try:
        pool.build_current_pool(now=NOW, get_json=thinned)
    except RuntimeError as exc:
        assert "fewer than six" in str(exc)
    else:
        raise AssertionError("a slate too thin to fill a lineup was accepted")


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
