"""The game-type boundary: a foreign publisher's phase vocabulary -> ours.

Third sibling of `team_codes.normalize()` and `season_keys.normalize_season()`,
and it exists for the third instance of the same failure. A wrong team code does
not raise, it misses. A wrong season key does not raise, it misses. A **missing**
game type does not raise either — `AND game_type='REG'` over a column of NULLs
matches nothing, and `games_played` comes back 0 for a player who played every
game. `docs/DATA-COVERAGE-CONTRACT.md` §1 has the render: every NFL 2024 player
reading "missed 17" in amber, from a guard that checked the column *existed* and
then filtered on its *values*.

Ours is `PRE` | `REG` | `POST` | `PLAYIN` | `ALLSTAR`. The first three are the
vocabulary already in the column from the nflverse NFL ingest; the last two were
added on 2026-08-02 because NBA publishes phases they are the only honest home
for, and the alternative was to file exhibitions as real games:

- **`PLAYIN`.** ESPN publishes the NBA play-in as its own season type (id 5,
  `play-in-season`, 2026-04-13..2026-04-18, 6 events), and our
  `team_game_results` for nba 2026 stops at 2026-04-13 with 82 games per team.
  Stamping those six games `REG` would give a participant 83 regular-season
  games against a team schedule of 82 — `games_played` exceeding the team's own
  game count. Kept distinct because that is the reversible direction: a caller
  who wants them in regular-season rates writes `game_type IN ('REG','PLAYIN')`,
  whereas collapsing them into `REG` cannot be undone from the data.
- **`ALLSTAR`.** ESPN files All-Star weekend *inside* type 2, Regular Season —
  `WORLD @ STARS` on 2026-02-15 publishes `season.type=2` exactly as opening
  night does. The only thing separating them is `competitions[0].type
  .abbreviation == "ALLSTAR"`. Taking the published phase at face value here
  puts three exhibitions into the denominator of every NBA per-game rate we
  serve, and accounts for the gap between ESPN's 1239 published type-2 events
  and the 1231 games `COV-nba` reconciles against.

The lesson generalises past basketball: **a publisher's phase field can be
right about the calendar and wrong about the question we are asking it.** NHL
needed only the id; NBA needs the id *and* the competition type.

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
PLAYIN, ALLSTAR = "PLAYIN", "ALLSTAR"
PHASES = (PRE, REG, POST, PLAYIN, ALLSTAR)

# One entry per (source, league). Deliberately not a shared default: NHL's 1/2/3
# and ESPN's 1/2/3/4 agree by coincidence, not by standard, and a league that
# numbers its phases differently would inherit a silently wrong answer from any
# rule general enough to cover both. NBA is the proof: it publishes a *fifth* id
# that NHL has no equivalent for, and files All-Star inside the second.
#
# Measured 2026-08-02 against
# `sports.core.api.espn.com/v2/sports/basketball/leagues/nba/seasons/2026`:
#     id=1 pre     Preseason        2025-10-01..2025-10-21    71 events
#     id=2 reg     Regular Season   2025-10-21..2026-04-13  1239 events
#     id=3 post    Postseason       2026-04-18..2026-06-27    85 events
#     id=4 off     Off Season       2026-06-27..2026-09-30     0 events
#     id=5 playin  Play-In Season   2026-04-13..2026-04-18     6 events
#
# Id 4 is absent on purpose. It publishes zero events, so a row claiming it is
# not a phase we failed to map — it is a row that should not exist, and the
# raise is the correct outcome.
_PUBLISHED: Dict[Tuple[str, str], Dict[str, str]] = {
    ("nhle.com", "nhl"): {"1": PRE, "2": REG, "3": POST},
    ("espn", "nba"): {"1": PRE, "2": REG, "3": POST, "5": PLAYIN},
}

# Competition-level phases: published on the competition, not the season, and
# overriding it. Keyed by (league, competitions[0].type.abbreviation).
_COMPETITION_PHASE: Dict[Tuple[str, str], str] = {
    ("nba", "ALLSTAR"): ALLSTAR,
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


def espn_event_phase(league: str, event) -> str:
    """Our phase for one normalized ESPN scoreboard event.

    `event` is a row from `espn_client.games()`, which carries `season_type` and
    `competition_type` straight off the envelope. Read it from there and not
    from the caller's own request parameters: an ingest that stamps the phase it
    *asked* for records its URL, not the game, and cannot notice the day the
    publisher files something somewhere else. That is the same discipline
    `ingest_nhl_logs.py` follows with `gameTypeId`.

    The competition type is checked first, because when the two disagree the
    competition is the more specific claim — NBA All-Star publishes
    `season.type=2` and `type.abbreviation="ALLSTAR"`, and the season field is
    the one that is wrong for our purposes.
    """
    lg = str(league or "").strip().lower()
    if not isinstance(event, dict):
        raise ValueError(f"espn_event_phase needs a normalized event dict, got {type(event).__name__}")

    competition_type = str(event.get("competition_type") or "").strip().upper()
    if competition_type:
        override = _COMPETITION_PHASE.get((lg, competition_type))
        if override:
            return override

    return normalize_game_type("espn", lg, event.get("season_type"))


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
