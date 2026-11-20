"""Pure NBA relationship graph: trades, team stints and shared tenure.

Input is a list of dict rows from `nba_player_movement` (see
`ingest_nba_player_movement.py`). Nothing here reads a database, the network or a
clock, so the same rows and the same `as_of` always give the same graph.

Rules this module keeps:

* Only a trade row with `direction_check == 'ok'` is used. Any other trade row is
  counted in `excluded_rows` and never reaches a movement or a stint.
* A multi-team trade is ONE `Transaction` (same GroupSort and date). Player
  movements and non-player assets (picks, cash, "draft consideration") stay on that
  one node. No one-for-one swap is invented between assets.
* Players are keyed on the NBA.com player id string, never on a name.
* Dates are effective dates. The file does not carry an agreement date.
* A stint whose beginning the file does not show has `start_covered=False`. A
  "re-signed" row proves the player was already on the team, so it never marks a
  start as covered. The file begins at `coverage_start`; nothing earlier is known.
* `as_of` keeps rows dated on or before that day. The caller chooses the day.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from ingest_nba_player_movement import SLUG_TO_CODE

_START_TYPES = {"Signing", "AwardOnWaivers"}


@dataclass(frozen=True)
class Movement:
    player_key: str
    from_team: str
    to_team: str
    date: str
    evidence_id: str


@dataclass
class Transaction:
    id: str
    effective_date: str
    movements: list = field(default_factory=list)
    other_assets: list = field(default_factory=list)   # evidence ids of non-player assets
    teams: set = field(default_factory=set)

    @property
    def player_keys(self):
        return {m.player_key for m in self.movements}


@dataclass
class Stint:
    team: str
    start: str | None
    start_covered: bool
    end: str | None
    start_evidence: list
    end_evidence: list


@dataclass(frozen=True)
class SharedStint:
    team: str
    start: str | None
    end: str | None
    complete: bool
    evidence: tuple


@dataclass(frozen=True)
class FormerTeam:
    team: str
    left_on: str | None
    evidence: tuple


def _eid(row) -> str:
    return "nba.com:player-movement:" + str(row["row_key"])


def _date(row) -> str:
    return str(row["transaction_date"])[:10]


class Graph:
    def __init__(self, rows, as_of=None):
        self.coverage_start = min((_date(r) for r in rows), default=None)
        self.excluded_rows = 0
        self.unmapped_team_rows = 0
        self.inconsistent_events = 0
        self.transactions: list[Transaction] = []
        self._stints: dict[str, list[Stint]] = {}
        used = [r for r in rows if as_of is None or _date(r) <= as_of]
        used.sort(key=lambda r: (_date(r), r["id"]))
        self._build_transactions(used)
        self._build_stints(used)

    # ---- construction -------------------------------------------------
    def _build_transactions(self, rows):
        nodes: dict = {}
        for row in rows:
            if row["transaction_type"] != "Trade":
                continue
            if row["direction_check"] != "ok":
                self.excluded_rows += 1
                continue
            date = _date(row)
            key = (row["group_sort"] or "row:" + str(row["row_key"]), date)
            node = nodes.get(key)
            if node is None:
                node = Transaction(id="nba:trade:%s:%s" % (key[0].replace(" ", "-"), date),
                                   effective_date=date)
                nodes[key] = node
                self.transactions.append(node)
            node.teams.update(t for t in (row["from_team"], row["to_team"]) if t)
            if row["asset_kind"] == "player" and row["nba_player_id"]:
                node.movements.append(Movement(str(row["nba_player_id"]), row["from_team"],
                                               row["to_team"], date, _eid(row)))
            else:
                node.other_assets.append(_eid(row))

    def _team(self, row):
        code = SLUG_TO_CODE.get(row["source_team_slug"] or "")
        if code is None:
            self.unmapped_team_rows += 1
        return code

    def _build_stints(self, rows):
        for row in rows:
            key = str(row["nba_player_id"] or "")
            if not key:
                continue
            kind, date, eid = row["transaction_type"], _date(row), _eid(row)
            stints = self._stints.setdefault(key, [])
            current = stints[-1] if stints and stints[-1].end is None else None
            if kind == "Trade":
                if row["direction_check"] != "ok" or row["asset_kind"] != "player":
                    continue
                if current is None:
                    stints.append(Stint(row["from_team"], None, False, date, [], [eid]))
                else:
                    if current.team != row["from_team"]:
                        self.inconsistent_events += 1
                    current.end, current.end_evidence = date, [eid]
                stints.append(Stint(row["to_team"], date, True, None, [eid], []))
                continue
            team = self._team(row)
            if team is None:
                continue
            if kind == "Waive":
                if current is not None and current.team == team:
                    current.end, current.end_evidence = date, [eid]
                elif current is None:
                    stints.append(Stint(team, None, False, date, [], [eid]))
                else:
                    self.inconsistent_events += 1
                continue
            reaffirm = "re-signed" in row["description"] or kind not in _START_TYPES
            if current is not None and current.team == team:
                current.start_evidence.append(eid)
                continue
            if current is not None:
                current.end, current.end_evidence = date, [eid]
            stints.append(Stint(team, date, not reaffirm, None, [eid], []))

    # ---- queries ------------------------------------------------------
    def movements(self):
        return [m for t in self.transactions for m in t.movements]

    def stints(self, player_key):
        return list(self._stints.get(str(player_key), []))

    def covers(self, date: str) -> bool:
        return self.coverage_start is not None and date >= self.coverage_start

    def former_teams(self, player_key, current_team):
        out = []
        for stint in self.stints(player_key):
            if stint.team != current_team:
                out.append(FormerTeam(stint.team, stint.end,
                                      tuple(stint.start_evidence + stint.end_evidence)))
        return out

    def shared_tenure(self, key_a, key_b):
        out = []
        for a in self.stints(key_a):
            for b in self.stints(key_b):
                if a.team != b.team:
                    continue
                start = max((s for s in (a.start, b.start) if s is not None), default=None)
                ends = [e for e in (a.end, b.end) if e is not None]
                end = min(ends) if ends else None
                if start is not None and end is not None and start >= end:
                    continue
                later, other = (a, b) if (a.start or "") >= (b.start or "") else (b, a)
                complete = later.start_covered and (
                    other.start_covered or (other.start is not None and other.start <= later.start))
                out.append(SharedStint(a.team, start, end, bool(complete),
                                       tuple(a.start_evidence + b.start_evidence)))
        return out


def build_graph(rows, as_of=None) -> Graph:
    return Graph(list(rows), as_of=as_of)


def reciprocal_players(transaction: Transaction, team_a: str, team_b: str):
    """Players each side sent the other in one transaction, or None if one way only."""
    a_to_b = {m.player_key for m in transaction.movements if m.from_team == team_a and m.to_team == team_b}
    b_to_a = {m.player_key for m in transaction.movements if m.from_team == team_b and m.to_team == team_a}
    if not a_to_b or not b_to_a:
        return None
    return {"%s_to_%s" % (team_a, team_b): a_to_b, "%s_to_%s" % (team_b, team_a): b_to_a}
