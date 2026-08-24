"""Harvest the UFC spine from ESPN's published cards.

Why this exists. `load_targets` builds its work set from
`SELECT id, name, espn_id FROM players WHERE league='ufc'`, so the pipeline can only
ever see fighters it already has a row for. Nothing created those rows from a card, so
a fighter making a first appearance was invisible forever, no matter how many times we
fetched the card that named them. That is a one-way valve, not a missing data source.

Measured 2026-08-24 over ESPN's next 21 days of UFC cards:

    6 card days, 94 scheduled fighters, 0 without an ESPN athlete id,
    93 of 94 absent from the prod spine of 97

ESPN mints the athlete record when the fight is SCHEDULED, not when it is fought, so a
debut fighter arrives with a publisher id three weeks early. There is nothing to derive
and nothing to scrape: the identity is published, in a payload we already fetch.

One request for the whole window via `games_by_day`, not one per day. The budget skill's
first lever is issuing fewer requests, and a 21-day sweep is 21 requests for the same
answer.
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Sequence, Tuple

import espn_client as espn

LEAGUE = "ufc"

# ESPN files an unannounced opponent as a real athlete with a real id, and the same two
# ids recur on every card that has an open slot. Upserting them mints a fighter named
# "TBA" that every future placeholder bout then collides onto.
#
# Both conditions must hold, deliberately. Keying the skip on the id alone would drop a
# real fighter if ESPN ever reassigns one; keying it on the name alone would drop a real
# person actually named in a way that matches. Observed 2026-08-24 on the 2026-09-08 card.
PLACEHOLDER_ESPN_IDS = {"4402367", "2431356"}


def _is_placeholder(espn_id: str, name: str) -> bool:
    token = (name or "").strip().upper()
    looks_unnamed = token in ("TBA", "TBD", "OPPONENT TBA", "OPPONENT TBD", "OPPONENT")
    return espn_id in PLACEHOLDER_ESPN_IDS and looks_unnamed


@dataclass
class HarvestPlan:
    """What a card sweep would change. Built before any write, like the ingest plan."""

    new: List[dict] = field(default_factory=list)
    # A row we already hold under this exact name with NO publisher id. Binding the id to
    # it is a repair, where inserting beside it is a duplicate spine. Measured 2026-08-24:
    # harvesting without this produced 46 duplicate names on dev and then 49 ownership
    # CONFLICTs, because the resolver tried to give the old row an id the new row had
    # already taken. The harvest caused the conflict it then tripped over.
    adopt: List[Tuple[int, str, dict]] = field(default_factory=list)
    # The same name held by more than one id-less row. An ambiguous key must refuse, not
    # pick one: a wrong bind here is silent and permanent.
    ambiguous: List[Tuple[str, int]] = field(default_factory=list)
    already_known: int = 0
    placeholders: List[Tuple[str, str]] = field(default_factory=list)
    # An id we hold under a different spelling. Reported, never auto-renamed: our name may
    # be the sportsbook's vocabulary and is joined on elsewhere. A rename is a separate,
    # deliberate decision.
    name_drift: List[Tuple[str, str, str]] = field(default_factory=list)
    cards_read: int = 0
    days_with_cards: int = 0

    @property
    def mutations(self) -> int:
        return len(self.new) + len(self.adopt)


def fighters_from_games(games: Sequence[dict]) -> List[dict]:
    """Every named side of every fight on these cards, keyed by the publisher's id.

    Both sides, because a fight is the unit that identifies a fighter: the card names who
    is standing across from whom, and an id is a fact where a spelling is a vocabulary.
    """
    out: Dict[str, dict] = {}
    for game in games or []:
        for side, other in (("home", "away"), ("away", "home")):
            fighter = game.get(side) or {}
            opponent = game.get(other) or {}
            espn_id = str(fighter.get("id") or "")
            name = (fighter.get("name") or "").strip()
            if not espn_id or not name:
                continue
            # First card wins: the same fighter can appear on a rescheduled date.
            out.setdefault(espn_id, {
                "espn_id": espn_id,
                "name": name,
                "opponent": (opponent.get("name") or "").strip() or None,
                "event_id": str(game.get("event_id") or "") or None,
                "fight_id": str(game.get("game_id") or "") or None,
            })
    return list(out.values())


def build_harvest_plan(
    con,
    today: Optional[dt.date] = None,
    lookahead_days: int = 21,
    lookback_days: int = 14,
    emit: Callable[[str], None] = print,
    fetch: Optional[Callable[[str, str], Tuple[Dict[str, List[dict]], int]]] = None,
) -> HarvestPlan:
    """Read the card window and work out which fighters we do not hold.

    `fetch` is injectable so the plan is testable without a publisher.
    """
    today = today or dt.date.today()
    start = (today - dt.timedelta(days=lookback_days)).isoformat()
    end = (today + dt.timedelta(days=lookahead_days)).isoformat()
    fetch = fetch or (lambda s, e: espn.games_by_day(LEAGUE, s, e))

    by_day, raw_events = fetch(start, end)
    plan = HarvestPlan(cards_read=raw_events, days_with_cards=len(by_day))

    games: List[dict] = []
    for day_games in by_day.values():
        games.extend(day_games)

    known_by_id = {
        str(row[0]): row[1]
        for row in con.execute(
            "SELECT espn_id, name FROM players WHERE league=? AND NULLIF(espn_id,'') IS NOT NULL",
            (LEAGUE,),
        )
    }
    # Rows we hold with no publisher id, keyed by exact name. Exact only, and only within
    # this league: this is the same trust level as `resolve_from_card`'s exact ladder, and
    # deliberately NOT a fuzzy or surname match, which is what a two-publisher vocabulary
    # defeats (`Sergey Spivak` vs `Serghei Spivac`). A drifted spelling stays unadopted and
    # gets a row of its own, which the name-drift report then makes visible.
    unresolved_by_name: Dict[str, List[int]] = {}
    for row in con.execute(
        "SELECT id, name FROM players WHERE league=? AND NULLIF(espn_id,'') IS NULL",
        (LEAGUE,),
    ):
        unresolved_by_name.setdefault(row[1], []).append(row[0])

    for fighter in fighters_from_games(games):
        espn_id, name = fighter["espn_id"], fighter["name"]
        if _is_placeholder(espn_id, name):
            plan.placeholders.append((espn_id, name))
            continue
        held = known_by_id.get(espn_id)
        if held is None:
            candidates = unresolved_by_name.get(name) or []
            if len(candidates) == 1:
                plan.adopt.append((candidates[0], name, fighter))
            elif len(candidates) > 1:
                plan.ambiguous.append((name, len(candidates)))
            else:
                plan.new.append(fighter)
        else:
            plan.already_known += 1
            if held != name:
                plan.name_drift.append((espn_id, held, name))

    emit(
        "  card sweep {} to {}: {} raw cards over {} days, {} new, {} adopted, "
        "{} already held, {} placeholders skipped, {} name drift, {} ambiguous".format(
            start, end, plan.cards_read, plan.days_with_cards, len(plan.new),
            len(plan.adopt), plan.already_known, len(plan.placeholders),
            len(plan.name_drift), len(plan.ambiguous),
        )
    )
    for espn_id, name in plan.placeholders:
        emit("    PLACEHOLDER skipped {} {}".format(espn_id, name))
    for name, count in plan.ambiguous:
        emit("    AMBIGUOUS {!r}: {} id-less rows share this name, refusing to bind".format(
            name, count))
    for espn_id, held, published in plan.name_drift:
        emit("    NAME DRIFT {} we hold {!r}, ESPN publishes {!r}".format(espn_id, held, published))
    return plan


def apply_harvest(con, plan: HarvestPlan, now: Optional[str] = None) -> int:
    """Insert the new fighters. Identity comes from the publisher's id, never a name.

    `UNIQUE(espn_id, league)` makes this idempotent: a re-run of the same window is a
    no-op rather than a duplicate spine.
    """
    if not plan.mutations:
        return 0
    now = now or dt.datetime.now(dt.timezone.utc).isoformat()
    adopted = 0
    for player_id, _name, fighter in plan.adopt:
        # Guarded so it cannot bind twice or overwrite an id that arrived meanwhile.
        cur = con.execute(
            "UPDATE players SET espn_id=?, updated_at=? "
            "WHERE id=? AND league=? AND NULLIF(espn_id,'') IS NULL",
            (fighter["espn_id"], now, player_id, LEAGUE),
        )
        adopted += cur.rowcount
    rows = [
        # `team` carries the opponent for UFC rows, matching the existing spine's shape.
        (f["name"], f["opponent"], LEAGUE, f["espn_id"], 1, now)
        for f in plan.new
    ]
    if rows:
        con.executemany(
            "INSERT INTO players(name, team, league, espn_id, active, updated_at) "
            "VALUES(?,?,?,?,?,?) ON CONFLICT(espn_id, league) DO NOTHING",
            rows,
        )
    return len(rows) + adopted
