"""MLS current-membership snapshots built from complete squads.

Development module. It is not wired into the roster job.

Inputs: the squads fetched in one run (FotMob and MLS Soccer) and the binds in player_source_ids.

Guarantees:
- Membership comes from the squads fetched in this run. It never reads published_roster, so stale
  roster rows cannot change a current membership decision.
- Identity is a lookup in existing binds. Nothing here creates a bind or a player.
- The prior state is read from the database. Callers cannot pass prior counts.
- Carry-forward keys are namespaced by source: (source, source_player_key).
- The population checksum excludes the fetch timestamp. An unchanged population refreshes the verification
  time of the current snapshot and creates no second membership set.
- Coverage is explicit. "verified" means every current member resolved and nothing was carried or
  unexplained. Anything else is "partial", with the measured reasons recorded in the payload.

Refused (nothing is published, the current snapshot stays): incomplete squads, identity conflicts, a club
count other than 30.
"""
from __future__ import annotations

import collections
import hashlib
import json
from dataclasses import dataclass, field
from typing import Dict, List, Mapping, Optional, Sequence, Tuple

import roster_membership as rm

LEAGUE = "mls"
SOURCE_LABEL = "fotmob+mlssoccer"
SOURCES = ("mlssoccer", "fotmob")  # the primary source for a person is mlssoccer when both list him
EXPECTED_CLUBS = 30
MIN_CLUB_SIZE = 20
CLUB_DROP_ABS = 3  # a club may lose this many players, or the fraction below, against the prior snapshot
CLUB_DROP_FRACTION = 0.20
TOTAL_DROP_FRACTION = 0.05


@dataclass
class Result:
    status: str  # "publish" or "refused"
    coverage: str = ""  # "verified" or "partial" when publishing
    memberships: List[dict] = field(default_factory=list)
    blockers: List[dict] = field(default_factory=list)  # keys with no known identity; excluded
    carried: List[dict] = field(default_factory=list)  # keys with a known person, kept from the prior snapshot
    departures: List[dict] = field(default_factory=list)  # confirmed: absent from every source they were in
    single_source_departures: List[dict] = field(default_factory=list)  # needs review
    bind_changed: List[dict] = field(default_factory=list)  # a current key now binds to someone else
    transfers: List[dict] = field(default_factory=list)  # same person, new club
    rekeys: List[dict] = field(default_factory=list)  # same person, a different key in one source
    conflicts: List[dict] = field(default_factory=list)
    reasons: List[str] = field(default_factory=list)
    payload: str = ""
    checksum: str = ""


# --- prior state, read from the database ---------------------------------------

def counts_from(memberships: Sequence[Mapping]) -> Dict[str, Dict[str, int]]:
    """Per-source, per-club player counts implied by a set of memberships."""
    counts = {source: collections.Counter() for source in SOURCES}
    for m in memberships:
        for source in m.get("keys", {}):
            counts[source][m["team"]] += 1
    return {source: dict(counter) for source, counter in counts.items()}


def prior_state(connection) -> Optional[dict]:
    row = connection.execute(
        "SELECT id, source_checksum, source_payload, captured_at FROM roster_snapshots "
        "WHERE league=? AND status='published'", (LEAGUE,)).fetchone()
    if not row:
        return None
    payload = json.loads(row[2])
    memberships = payload["memberships"]
    return {"snapshot_id": row[0], "checksum": row[1], "captured_at": row[3],
            "memberships": memberships, "counts": counts_from(memberships),
            "coverage": payload.get("coverage", {}).get("status")}


def binds_from_db(connection, leagues: Sequence[str] = ("mls", "lcup")) -> Dict[Tuple[str, str], int]:
    """(source, key) -> player_id from the database. Raises if one key points at two players."""
    binds: Dict[Tuple[str, str], int] = {}
    marks = ",".join("?" for _ in leagues)
    for source, key, player_id in connection.execute(
            "SELECT source, source_player_key, player_id FROM player_source_ids WHERE league IN (%s)" % marks,
            tuple(leagues)):
        identity = (source, str(key))
        if identity in binds and binds[identity] != player_id:
            raise ValueError("bind disagreement for %s %s: %s and %s" % (source, key, binds[identity], player_id))
        binds[identity] = player_id
    return binds


# --- completeness --------------------------------------------------------------

def check_completeness(squads: Mapping[str, Sequence[Mapping]],
                       prior_counts: Optional[Mapping[str, Mapping[str, int]]] = None) -> List[str]:
    reasons = []
    for source in SOURCES:
        members = list(squads.get(source) or [])
        if not members:
            reasons.append("%s: no members fetched" % source)
            continue
        per_club = collections.Counter(m["team"] for m in members)
        if len(per_club) != EXPECTED_CLUBS:
            reasons.append("%s: %d clubs, expected %d" % (source, len(per_club), EXPECTED_CLUBS))
        small = sorted(team for team, n in per_club.items() if n < MIN_CLUB_SIZE)
        if small:
            reasons.append("%s: clubs under %d players: %s" % (source, MIN_CLUB_SIZE, ", ".join(small)))
        keys = [str(m["source_player_key"]) for m in members]
        if len(set(keys)) != len(keys):
            reasons.append("%s: duplicate source keys in one fetch" % source)
        prior = (prior_counts or {}).get(source)
        if prior:
            for team in sorted(set(prior) | set(per_club)):
                before, now = prior.get(team, 0), per_club.get(team, 0)
                if before - now > max(CLUB_DROP_ABS, CLUB_DROP_FRACTION * before):
                    reasons.append("%s: %s fell from %d to %d" % (source, team, before, now))
            before_total, now_total = sum(prior.values()), len(members)
            if before_total and abs(now_total - before_total) / before_total > TOTAL_DROP_FRACTION:
                reasons.append("%s: total changed from %d to %d" % (source, before_total, now_total))
    return reasons


# --- resolution ----------------------------------------------------------------

def resolve(squads: Mapping[str, Sequence[Mapping]], binds: Mapping[Tuple[str, str], int]):
    """Map current squad members to people by lookup only.

    Returns (memberships, unresolved, conflicts). One membership per person. Each membership records every
    key that resolved to that person, by source, and the primary key is mlssoccer's when present.
    """
    grouped: Dict[int, dict] = {}
    unresolved, conflicts = [], []
    for source in SOURCES:
        for member in squads.get(source) or []:
            key = str(member["source_player_key"])
            player_id = binds.get((source, key))
            if player_id is None:
                unresolved.append({"source": source, "source_player_key": key,
                                   "name": member.get("name"), "team": member.get("team")})
                continue
            entry = grouped.setdefault(player_id, {"rows": {}})
            if source in entry["rows"]:
                conflicts.append({"player_id": player_id, "reason": "two keys from %s" % source,
                                  "keys": [entry["rows"][source]["source_player_key"], key]})
                continue
            entry["rows"][source] = dict(member, source_player_key=key)

    memberships = []
    for player_id, entry in sorted(grouped.items()):
        rows = entry["rows"]
        teams = {row["team"] for row in rows.values()}
        if len(teams) > 1:
            conflicts.append({"player_id": player_id, "reason": "sources disagree on club",
                              "teams": {s: r["team"] for s, r in rows.items()}})
            continue
        primary = "mlssoccer" if "mlssoccer" in rows else next(iter(rows))
        row = rows[primary]
        memberships.append({
            "player_id": player_id,
            "source_player_key": row["source_player_key"],
            "keys": {src: r["source_player_key"] for src, r in rows.items()},
            "team": teams.pop(),
            "position": row.get("position"),
            "jersey": row.get("jersey"),
            "roster_status": "active",
            "display_name": row.get("name") or "",
        })
    return memberships, unresolved, conflicts


def _classify(prior_memberships, memberships, unresolved, squads, binds):
    """Compare this run with the prior verified snapshot, person by person."""
    result = {"carried": [], "blockers": [], "departures": [], "single_source_departures": [],
              "bind_changed": [], "transfers": [], "rekeys": []}
    present = {m["player_id"]: m for m in memberships}
    squad_keys = {(src, str(m["source_player_key"])) for src in SOURCES for m in squads.get(src) or []}
    prior_index = {}
    for p in prior_memberships:
        for src, key in p.get("keys", {}).items():
            prior_index[(src, str(key))] = p

    for item in unresolved:
        prior = prior_index.get((item["source"], item["source_player_key"]))
        if prior is None:
            result["blockers"].append(item)
        elif prior["player_id"] in present:
            continue  # the same person is still resolved through another key this run
        else:
            present[prior["player_id"]] = dict(prior, roster_status="carried")
            result["carried"].append(item)

    for p in prior_memberships:
        pid = p["player_id"]
        if pid in present:
            member = present[pid]
            if member["team"] != p["team"] and member.get("roster_status") != "carried":
                result["transfers"].append({"player_id": pid, "from": p["team"], "to": member["team"]})
            for src, key in member["keys"].items():
                if src in p.get("keys", {}) and p["keys"][src] != key:
                    result["rekeys"].append({"player_id": pid, "source": src,
                                             "from": p["keys"][src], "to": key})
            continue
        # Not present and not carried: a departure, or a bind that moved. Check the squads.
        bound_elsewhere = [(src, key) for src, key in p.get("keys", {}).items()
                           if (src, str(key)) in squad_keys]
        if bound_elsewhere:
            result["bind_changed"].append({"player_id": pid, "keys": bound_elsewhere})
            continue
        if set(p.get("keys", {})) >= set(SOURCES):
            result["departures"].append({"player_id": pid, "keys": p["keys"]})
        else:
            result["single_source_departures"].append({"player_id": pid, "keys": p.get("keys", {})})
    return present, result


# --- build and publish ----------------------------------------------------------

def build(connection, squads: Mapping[str, Sequence[Mapping]], binds: Mapping[Tuple[str, str], int],
          captured_at: str = "") -> Result:
    prior = prior_state(connection)
    prior_counts = prior["counts"] if prior else None
    reasons = check_completeness(squads, prior_counts)
    if reasons:
        return Result(status="refused", reasons=reasons)

    memberships, unresolved, conflicts = resolve(squads, binds)
    if conflicts:
        return Result(status="refused", reasons=["%d identity conflicts" % len(conflicts)], conflicts=conflicts)
    if len({m["team"] for m in memberships}) != EXPECTED_CLUBS:
        return Result(status="refused", reasons=["club count after resolve is not %d" % EXPECTED_CLUBS])

    prior_memberships = prior["memberships"] if prior else []
    present, c = _classify(prior_memberships, memberships, unresolved, squads, binds)
    final = sorted(present.values(), key=lambda m: m["player_id"])

    if c["bind_changed"] or c["blockers"] or c["carried"] or c["single_source_departures"]:
        status = "partial"
    else:
        status = "verified"
    coverage = {
        "status": status,
        "blockers": len(c["blockers"]),
        "carried": len(c["carried"]),
        "departures_confirmed": len(c["departures"]),
        "single_source_departures": len(c["single_source_departures"]),
        "bind_changed": len(c["bind_changed"]),
        "transfers": len(c["transfers"]),
        "rekeys": len(c["rekeys"]),
        "memberships": len(final),
    }
    # The payload holds the population and its coverage, never the fetch time. Every list is sorted, so the
    # fetch order of the providers cannot change the checksum.
    def stable(items):
        return sorted(items, key=lambda x: json.dumps(x, sort_keys=True, ensure_ascii=False))

    payload = json.dumps({"league": LEAGUE, "sources": SOURCE_LABEL, "memberships": final,
                          "coverage": coverage, "blockers": stable(c["blockers"]),
                          "carried": stable(c["carried"]), "departures": stable(c["departures"]),
                          "single_source_departures": stable(c["single_source_departures"]),
                          "bind_changed": stable(c["bind_changed"]), "transfers": stable(c["transfers"]),
                          "rekeys": stable(c["rekeys"])},
                         sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return Result(status="publish", coverage=status, memberships=final,
                  blockers=c["blockers"], carried=c["carried"], departures=c["departures"],
                  single_source_departures=c["single_source_departures"], bind_changed=c["bind_changed"],
                  transfers=c["transfers"], rekeys=c["rekeys"], payload=payload,
                  checksum=hashlib.sha256(payload.encode("utf-8")).hexdigest())


def publish(connection, result: Result, captured_at: str) -> Tuple[str, Optional[int]]:
    """Returns (outcome, snapshot_id). Outcome is 'refused', 'unchanged' or 'published'.

    'unchanged' refreshes the verification time of the current snapshot and creates no second membership
    set. Callers must run inside a transaction.
    """
    if result.status != "publish":
        return "refused", None
    current = connection.execute(
        "SELECT id, source_checksum FROM roster_snapshots WHERE league=? AND status='published'",
        (LEAGUE,)).fetchone()
    if current and current[1] == result.checksum:
        connection.execute("UPDATE roster_snapshots SET captured_at=? WHERE id=?", (captured_at, current[0]))
        return "unchanged", current[0]
    teams = len({m["team"] for m in result.memberships})
    snapshot_id = rm.publish_roster_snapshot(
        connection,
        league=LEAGUE,
        season=rm.roster_season(LEAGUE, captured_at),
        source=SOURCE_LABEL,
        captured_at=captured_at,
        source_payload=result.payload,
        team_count=teams,
        memberships=result.memberships,
    )
    return "published", snapshot_id


def health(connection) -> Optional[dict]:
    """What the current snapshot says about itself, for monitoring. None when nothing is published."""
    row = connection.execute(
        "SELECT id, captured_at, player_count, team_count, source_payload FROM roster_snapshots "
        "WHERE league=? AND status='published'", (LEAGUE,)).fetchone()
    if not row:
        return None
    coverage = json.loads(row[4]).get("coverage", {})
    return {"snapshot_id": row[0], "verified_at": row[1], "players": row[2], "clubs": row[3],
            "coverage": coverage.get("status"), "blockers": coverage.get("blockers"),
            "carried": coverage.get("carried")}
