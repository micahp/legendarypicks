"""The game-type boundary: a foreign publisher's phase vocabulary -> ours.

Third sibling of `team_codes.normalize()` and `season_keys.normalize_season()`,
and it exists for the third instance of the same failure. A wrong team code does
not raise, it misses. A wrong season key does not raise, it misses. A **missing**
game type does not raise either — `AND game_type='REG'` over a column of NULLs
matches nothing, and `games_played` comes back 0 for a player who played every
game. `docs/DATA-COVERAGE-CONTRACT.md` §1 has the render: every NFL 2024 player
reading "missed 17" in amber, from a guard that checked the column *existed* and
then filtered on its *values*.

Ours is `PRE` | `REG` | `POST`, the vocabulary already in the column from the
nflverse NFL ingest.

**Measured, not assumed.** nhle.com publishes the phase as an integer with no
accompanying enum — `gameTypeId` in the game-log envelope, and nothing anywhere
that names 1, 2 and 3. So the correspondence below was established against the
dates the NHL *does* publish, at
`https://api.nhle.com/stats/rest/en/season?cayenneExp=id=20252026`:

    preseasonStartdate     2025-09-20     totalRegularSeasonGames  1312
    startDate              2025-10-07     totalPlayoffGames          82
    regularSeasonEndDate   2026-04-17
    endDate                2026-06-15

and against the game dates each `gameTypeId` actually returns: type 2 runs
2025-10-07..2026-04-16, inside the regular-season window; type 3 runs past
`regularSeasonEndDate` toward `endDate` (measured on 2024-25: first row
2025-06-17, a Stanley Cup Final game). `verify_nhl_phase()` below is that check,
kept runnable rather than written down, because a measurement recorded only in a
comment stops being a measurement the first time the publisher changes.
"""

from __future__ import annotations

import json
import urllib.request
from typing import Dict, Optional, Tuple

PRE, REG, POST = "PRE", "REG", "POST"
PHASES = (PRE, REG, POST)

# One entry per (source, league). Deliberately not a shared default: NHL's 1/2/3
# and ESPN's 1/2/3/4 agree by coincidence, not by standard, and a league that
# numbers its phases differently would inherit a silently wrong answer from any
# rule general enough to cover both.
_PUBLISHED: Dict[Tuple[str, str], Dict[str, str]] = {
    ("nhle.com", "nhl"): {"1": PRE, "2": REG, "3": POST},
}

_NHL_SEASON_DOC = "https://api.nhle.com/stats/rest/en/season?cayenneExp=id={season}"
_HDR = {"User-Agent": "Mozilla/5.0 (legendarypicks ingest)"}


def normalize_game_type(source: str, league: str, value) -> str:
    """Return our phase for a game type published by `source`.

    Raises ValueError rather than guessing. There is no safe fallback here: the
    plausible one — treating an unrecognised type as REG, since most games are
    regular-season games — would file preseason exhibitions as real games in the
    denominator of every per-game rate we serve.
    """
    src = str(source or "").strip().lower()
    lg = str(league or "").strip().lower()
    raw = str(value).strip() if value is not None else ""

    if not raw:
        raise ValueError(
            f"{src or '<no source>'}/{lg or '<no league>'} published no game type; "
            f"a NULL here is the defect this boundary exists to stop, not a value "
            f"to pass through"
        )

    # Already ours — from nflverse, or from a second pass over rows we wrote.
    if raw.upper() in PHASES:
        return raw.upper()

    table = _PUBLISHED.get((src, lg))
    if table is None:
        raise ValueError(
            f"no measured game-type correspondence for {src}/{lg}; read that "
            f"publisher's own phase dates and confirm which id falls in which "
            f"window before adding a case here — see backend/game_types.py"
        )
    try:
        return table[raw]
    except KeyError:
        raise ValueError(
            f"{src}/{lg} published game type {raw!r}, which is not one of the "
            f"values this boundary was measured against ({sorted(table)}). It may "
            f"be a phase we have never ingested; it is not REG by default."
        ) from None


# ---------------------------------------------------------------------------
#  Falsification — the mapping above, re-measured against the publisher
# ---------------------------------------------------------------------------


def nhl_season_window(season, *, timeout: int = 15) -> dict:
    """The NHL's own phase dates and game totals for one 8-digit season id.

    This is the published answer to "how many regular-season games are there",
    which is otherwise the kind of number that gets copied back off our own
    ingest and then used to check that same ingest.
    """
    url = _NHL_SEASON_DOC.format(season=str(season))
    req = urllib.request.Request(url, headers=_HDR)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        data = json.loads(r.read())
    rows = data.get("data") or []
    if not rows:
        raise ValueError(f"NHL publishes no season document for {season!r}")
    return rows[0]


def verify_nhl_phase(season, phase: str, dates, *, timeout: int = 15) -> Optional[str]:
    """None if every date sits in `phase`'s published window; else what is wrong.

    Call it with the game dates actually written, after an ingest. A stamp is a
    claim about which phase a row belongs to, and until something compares it to
    the publisher's calendar it is only the ingest repeating its own request
    parameter back.
    """
    dates = sorted(d for d in dates if d)
    if not dates:
        return None
    doc = nhl_season_window(season, timeout=timeout)
    day = lambda k: (doc.get(k) or "")[:10]  # noqa: E731 - published as ISO datetimes
    bounds = {
        PRE: (day("preseasonStartdate"), day("startDate")),
        REG: (day("startDate"), day("regularSeasonEndDate")),
        POST: (day("regularSeasonEndDate"), day("endDate")),
    }
    lo, hi = bounds[phase]
    if not lo or not hi:
        return f"NHL {season} publishes no window for {phase}"
    outside = [d for d in dates if d < lo or d > hi]
    if outside:
        return (
            f"{len(outside)} {phase} game dates outside the published "
            f"{lo}..{hi} window (e.g. {outside[:3]})"
        )
    return None
