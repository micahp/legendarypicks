"""espn_client.config -- hosts, league registry, and the shared fetcher.

The league table, the ESPN host templates, the process-wide paced_http Fetcher
(which owns pacing, the per-host budget and the disk cache), and the small
config/setter functions that used to open `espn_client.py`. Everything here
is a leaf: nothing in this module imports the rest of the package, so it is
safe to import first.

The module used to be one file; it is now a package whose __init__ re-exports
the names below, so `import espn_client as espn; espn.games(...)` and
`monkeypatch.setattr(espn_client, "_get", fake)` keep working unchanged.
"""
import os

import paced_http

LEAGUES = {  # our key -> (espn "sport/league" path, regulation periods)
    "nba":  ("basketball/nba", 4),
    "wnba": ("basketball/wnba", 4),
    "nhl":  ("hockey/nhl", 3),
    "mlb":  ("baseball/mlb", 9),
    "nfl":  ("football/nfl", 4),
    "ncaaf": ("football/college-football", 4),
    "atp":  ("tennis/atp", 3),
    "wta":  ("tennis/wta", 3),
    "ufc":  ("mma/ufc", 3),
    "wc":   ("soccer/fifa.world", 2),
    "lcup": ("soccer/concacaf.leagues.cup", 2),
    "mls":  ("soccer/usa.1", 2),
}

# These were both `site.api.espn.com`, which refused this box for a full day on
# 2026-08-04 and took the live scores page and every standings tab down with it
# -- a 403 here surfaces as a 500 and the page says "No data available", which
# blames our data for an upstream refusal.
#
# `site.web.api.espn.com` serves the identical paths. Verified across all four
# leagues, both shapes (`/scoreboard` and `/standings`, the only two used):
# 8 of 8 return 200 while site.api returns 403 for the same request. Same
# publisher, same payload shape, a host that answers.
_SITE = "https://site.web.api.espn.com/apis/site/v2/sports/{path}"
_CORE = "https://site.web.api.espn.com/apis/v2/sports/{path}"
_COMMON = "https://site.web.api.espn.com/apis/common/v3/sports/{path}"
_SPORTS_CORE = "https://sports.core.api.espn.com/v2/sports/{sport}"
_HDRS = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/124 Safari/537.36"}

# Pacing, the per-host budget and the disk cache all live in `paced_http`, which
# exists because SIX modules had each written their own copy of them and this one
# -- the module every serving path and the heaviest batch job go through -- had
# none. That asymmetry is what let `roster_sync.py` fire 128 requests back to
# back and trip ESPN's wall on 2026-08-04.
#
# The defaults here do nothing on purpose: a page load must not pause and must
# not answer from an hours-old payload. Only a caller that knows it is about to
# iterate opts in, via set_min_interval() / set_disk_cache().
# retry_waits is EMPTY by default, for the same reason the interval is 0: a page
# load must not sit through a 155s ladder while somebody waits. Waiting out a
# refusal is a batch job's move, so batch callers opt in via set_retry_waits().
# on_exhausted="refuse": this module is what the request handlers call, and the
# budget's default answer to exhaustion is `time.sleep(60)`. Measured on prod
# 2026-08-18, that produced 46 minute-long pauses inside 46 minutes of uptime and
# was the actual reason the scoreboard read as broken -- not an ESPN refusal.
# A batch job opts back into waiting by constructing its own Fetcher or calling
# set_host_budget on a client it owns; a page load never waits.
_FETCHER = paced_http.Fetcher(min_interval=0.0, retry_waits=(),
                              headers=_HDRS, timeout=20, on_exhausted="refuse",
                              cache_dir=os.environ.get("LP_ESPN_CACHE_DIR") or "",
                              cache_ttl=float(os.environ.get("LP_ESPN_CACHE_TTL",
                                                             "43200") or 0))


def set_min_interval(seconds):
    """Space subsequent requests by at least `seconds`. Returns the previous value."""
    prev = _FETCHER.min_interval
    _FETCHER.min_interval = float(seconds or 0)
    return prev


def set_disk_cache(directory, ttl=None):
    """Persist payloads under `directory` and re-serve them for `ttl` seconds.

    Returns the previous directory. Pass "" to disable.
    """
    prev = _FETCHER.cache_dir
    _FETCHER.cache_dir = directory or ""
    if ttl is not None:
        _FETCHER.cache_ttl = float(ttl or 0)
    if _FETCHER.cache_dir:
        os.makedirs(_FETCHER.cache_dir, exist_ok=True)
    return prev


def set_retry_waits(waits):
    """Wait out an upstream refusal on this ladder. Returns the previous one."""
    prev = _FETCHER.retry_waits
    _FETCHER.retry_waits = tuple(waits or ())
    return prev


def set_on_exhausted(mode):
    """'"sleep" or "refuse" when the per-host count is spent. Returns the previous.

    The module default is "refuse" because the request handlers import this
    module directly. A batch job that enters through the same module (every
    ingest does) says so explicitly, since waiting out a cooldown is exactly
    what a job with nobody watching should do.
    """
    prev = _FETCHER.on_exhausted
    _FETCHER.on_exhausted = mode
    return prev


def set_host_budget(budget, cooldown=None):
    """Requests allowed per host before a cooldown. 0 disables the budget."""
    prev = _FETCHER.host_budget
    _FETCHER.host_budget = int(budget)
    if cooldown is not None:
        _FETCHER.host_cooldown = float(cooldown)
    return prev


# The in-memory cache is the Fetcher's dict, exposed under the name this module
# has always used. Callers and tests that reach for `espn_client._CACHE` are
# asserting prod behaviour and should not have to know where the mechanism moved.
_CACHE = _FETCHER._memory


def _get(url, ttl=30):
    return _FETCHER.json(url, ttl=ttl)


def _check(league):
    league = (league or "").lower()
    if league not in LEAGUES:
        raise ValueError(f"unsupported league {league!r}; supported: {sorted(LEAGUES)}")
    return league, LEAGUES[league][0]
