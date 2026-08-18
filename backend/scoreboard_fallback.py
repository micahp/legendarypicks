"""A scoreboard when ESPN will not answer.

ESPN's limit is a request COUNT per host, so the scoreboard is the surface that
loses it first — and when it does, `_games_from_db` has nothing either, because
we persist finished games, not live ones. The board goes blank. That happened on
2026-08-17 and it is what this exists for.

WHAT BOVADA ANSWERS — measured 2026-08-18:

    coupon listing (via bovada_scraper.fetch_events, the client that already
    handles this host)
        per event: `description`, `competitors[]` with home flags, `startTime`
        (epoch ms), `live`, `id`. No score.

    /services/sports/results/api/v1/scores/{eventId}
        `latestScore` {home, visitor}, `currentPeriodScore`, `clock`
        {period, periodNumber, gameTime, isTicking, numberOfPeriods},
        `gameStatus`, `sportDetails`, `lastUpdated`.

The second endpoint is the one that makes this a scoreboard rather than a slate.
It is easy to miss: the listing carries no score at all, and concluding from it
alone that "Bovada has no scores" is a statement about which endpoint was asked.

THE TRAP THIS CODE EXISTS AROUND. A PRE_GAME event returns `latestScore` 0-0
with a `lastUpdated` days old. That 0-0 is a placeholder, not a score, and it is
indistinguishable from a real 0-0 in a game that has started. So a score is only
ever read from an event Bovada says is under way, and anything else carries
`score: None` for the UI to render as a dash. A fabricated 0-0 on a live game is
worse than no board at all.

Cost: one listing request per league, plus one score request per event that is
actually live — on a host that is not ESPN.
"""
import datetime as dt
import json
import urllib.request

import bovada_scraper

# The MLS coupon path, kept here rather than in bovada_scraper.LEAGUES on
# purpose: that map drives PROP ingestion, and MLS was deliberately removed from
# it because Bovada prices only 2 of the 11 markets MLS needs. None of that
# applies to a scoreboard, which needs no markets at all — but re-adding it
# there would silently switch the props source back.
_EXTRA_PATHS = {"mls": ("soccer", "north-america/united-states/mls")}

_SCORES = "https://www.bovada.lv/services/sports/results/api/v1/scores"
_HDR = {"User-Agent": "Mozilla/5.0 (compatible; LegendaryPicks/1.0)"}
_TIMEOUT = 12

# Bovada's own words for a game in progress. Anything outside this set is not
# read for a score — see the module docstring.
_LIVE_STATUS = {"IN_PROGRESS", "IN_PLAY", "LIVE", "HALFTIME", "INTERMISSION", "DELAYED"}
_FINAL_STATUS = {"FINAL", "GAME_OVER", "COMPLETE", "COMPLETED", "ENDED"}


def league_path(league):
    """Bovada's (sport, path) for a league, or None if it does not carry it."""
    lg = (league or "").lower()
    return bovada_scraper.LEAGUES.get(lg) or _EXTRA_PATHS.get(lg)


def _score_int(value):
    """Bovada sends scores as strings. An unparseable one is absent, not zero."""
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


def event_scoreboard(event_id):
    """Live score + clock for one Bovada event, or None.

    Returns None rather than a zeroed record when the game is not under way, so
    a caller cannot accidentally publish a pre-game placeholder as a score.
    """
    try:
        request = urllib.request.Request(f"{_SCORES}/{event_id}", headers=_HDR)
        with urllib.request.urlopen(request, timeout=_TIMEOUT) as response:
            payload = json.loads(response.read().decode())
    except Exception as exc:
        print(f"[scores-fallback] bovada score unavailable event={event_id}: "
              f"{type(exc).__name__}: {exc}")
        return None

    status = (payload.get("gameStatus") or "").upper()
    clock = payload.get("clock") or {}
    ticking = bool(clock.get("isTicking"))
    under_way = status in _LIVE_STATUS or (ticking and status not in _FINAL_STATUS)
    final = status in _FINAL_STATUS
    if not under_way and not final:
        return None

    latest = payload.get("latestScore") or {}
    home = _score_int(latest.get("home"))
    away = _score_int(latest.get("visitor"))
    if home is None or away is None:
        return None

    period = clock.get("period") or ""
    game_time = clock.get("gameTime") or ""
    return {
        "home": home,
        "away": away,
        "state": "post" if final else "in",
        "completed": final,
        "status": "Final" if final else (period or "In progress"),
        "period": clock.get("periodNumber") or None,
        "clock": game_time or None,
        "status_detail": ("Final" if final
                          else " ".join(part for part in (period, game_time) if part) or "In progress"),
    }


def _team(competitor):
    return {
        "name": (competitor or {}).get("name") or "",
        "abbrev": (competitor or {}).get("shortName") or "",
        "score": None,   # absence, never zero
    }


def bovada_games(league, date=None, with_scores=True):
    """Bovada's slate for `date`, with live scores attached where they exist.

    Never raises: this is the fallback, and a path that is already degraded must
    not be handed a second failure.
    """
    lg = (league or "").lower()
    path = league_path(lg)
    if not path:
        return []
    sport, coupon = path
    try:
        events = bovada_scraper.fetch_events(sport, coupon)
    except Exception as exc:
        print(f"[scores-fallback] bovada listing unavailable league={lg}: "
              f"{type(exc).__name__}: {exc}")
        return []

    try:
        target = dt.date.fromisoformat(date) if date else dt.datetime.now(dt.timezone.utc).date()
    except ValueError:
        target = dt.datetime.now(dt.timezone.utc).date()

    games = []
    for event in events:
        if event.get("type") != "GAMEEVENT":
            continue
        start_ms = event.get("startTime")
        if not isinstance(start_ms, (int, float)):
            continue
        start = dt.datetime.fromtimestamp(start_ms / 1000, dt.timezone.utc)
        if start.date() != target:
            continue
        competitors = event.get("competitors") or []
        home = next((c for c in competitors if c.get("home")), None)
        away = next((c for c in competitors if not c.get("home")), None)
        if not home or not away:
            continue

        game = {
            # Namespaced so it can never be mistaken for an ESPN event id by
            # anything that later tries to look one up.
            "game_id": f"bovada-{event.get('id')}",
            "date": start.isoformat().replace("+00:00", "Z"),
            "state": "in" if event.get("live") else "pre",
            "completed": False,
            "status": "In progress" if event.get("live") else "Scheduled",
            "period": None,
            "clock": None,
            "status_detail": "In progress" if event.get("live") else "Scheduled",
            "season_type": None,
            "season_slug": None,
            "competition_type": None,
            "home": _team(home),
            "away": _team(away),
            "source": "bovada",
        }

        # One extra request, and only for a game the listing says is live.
        if with_scores and event.get("live"):
            live = event_scoreboard(event.get("id"))
            if live:
                game["home"]["score"] = live["home"]
                game["away"]["score"] = live["away"]
                game.update({key: live[key] for key in
                             ("state", "completed", "status", "period", "clock", "status_detail")})

        games.append(game)

    games.sort(key=lambda game: game["date"])
    return games
