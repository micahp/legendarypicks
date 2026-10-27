"""MLS current-membership snapshots built from complete squads only.

Development module. It is not wired into the roster job.

Inputs: the squads fetched in one run (FotMob and MLS Soccer) and the existing player_source_ids binds.
Membership comes only from those squads. Identity is a lookup in the binds. This module never creates a
bind or a player, and it never reads published_roster for membership, so stale rows cannot change a
current membership decision.

Failure rules, all fail-closed:
- Incomplete squads (missing club, too few players, abnormal club drop, total drop): nothing is published,
  and the last published snapshot stays current.
- Conflicts (two keys from one source for one player, or sources disagreeing on a club): nothing is
  published. These need a person to decide.
- Unresolved keys (no bind) do not stop publication. They are reported as blockers. A key from the last
  published snapshot is carried forward with its player, so it is never deactivated silently.
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
SOURCES = ("mlssoccer", "fotmob")  # mlssoccer is the primary key when a player has both
EXPECTED_CLUBS = 30
MIN_CLUB_SIZE = 20
MAX_CLUB_DROP_ABS = 3  # a club may lose this many players, or the fraction below, between snapshots
MAX_CLUB_DROP_FRACTION = 0.20
MAX_TOTAL_DROP_FRACTION = 0.05


@dataclass
class Result:
    status: str  # "publish" or "refused"
    memberships: List[dict] = field(default_factory=list)
    blockers: List[dict] = field(default_factory=list)  # unresolved keys with no prior membership
    carried: List[dict] = field(default_factory=list)  # unresolved keys kept from the prior snapshot
    reasons: List[str] = field(default_factory=list)
    payload: str = ""
    checksum: str = ""


def check_completeness(squads: Mapping[str, Sequence[Mapping]],
                       prior_counts: Optional[Mapping[str, Mapping[str, int]]] = None) -> List[str]:
    """Reasons the fetched squads cannot be trusted. An empty list means complete."""
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
                drop = before - now
                if drop > max(MAX_CLUB_DROP_ABS, MAX_CLUB_DROP_FRACTION * before):
                    reasons.append("%s: %s fell from %d to %d" % (source, team, before, now))
            before_total, now_total = sum(prior.values()), len(members)
            if before_total and abs(now_total - before_total) / before_total > MAX_TOTAL_DROP_FRACTION:
                reasons.append("%s: total changed from %d to %d" % (source, before_total, now_total))
    return reasons


def resolve(squads: Mapping[str, Sequence[Mapping]],
            binds: Mapping[Tuple[str, str], int]) -> Tuple[List[dict], List[dict], List[dict]]:
    """Map current squad members to canonical players by lookup only.

    Returns (memberships, unresolved, conflicts). A membership is one row per player, keyed by the primary
    source's key. The other source's key contributes only its club, which must agree.
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
            "team": row["team"],
            "position": row.get("position"),
            "jersey": row.get("jersey"),
            "roster_status": "active",
            "display_name": row.get("name") or "",
        })
    return memberships, unresolved, conflicts


def build(squads: Mapping[str, Sequence[Mapping]],
          binds: Mapping[Tuple[str, str], int],
          prior_memberships: Sequence[Mapping] = (),
          prior_counts: Optional[Mapping[str, Mapping[str, int]]] = None,
          captured_at: str = "") -> Result:
    reasons = check_completeness(squads, prior_counts)
    if reasons:
        return Result(status="refused", reasons=reasons)

    memberships, unresolved, conflicts = resolve(squads, binds)
    if conflicts:
        return Result(status="refused", reasons=["%d identity conflicts" % len(conflicts)],
                      blockers=conflicts)

    teams = {m["team"] for m in memberships}
    if len(teams) != EXPECTED_CLUBS:
        return Result(status="refused", reasons=["%d clubs represented after resolve" % len(teams)])

    # Carry forward a prior membership whose key is unresolved now. Its player is known from the last
    # published snapshot, so it is kept rather than deactivated, and it is reported.
    prior_by_key = {}
    for m in prior_memberships:
        for key in set(m.get("keys", {}).values()) | {str(m["source_player_key"])}:
            prior_by_key[key] = m
    current_players = {m["player_id"] for m in memberships}
    carried, blockers = [], []
    for item in unresolved:
        prior = prior_by_key.get(item["source_player_key"])
        if prior is None:
            blockers.append(item)  # no known identity: a person has to decide
        elif prior["player_id"] in current_players:
            continue  # the same person is still resolved through another key this run
        else:
            memberships.append(dict(prior, roster_status="carried"))
            current_players.add(prior["player_id"])
            carried.append(item)

    memberships.sort(key=lambda m: m["player_id"])
    payload = json.dumps({
        "league": LEAGUE,
        "captured_at": captured_at,
        "sources": SOURCE_LABEL,
        "memberships": memberships,
        "unresolved_blockers": blockers,
        "carried_forward": carried,
    }, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    checksum = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    return Result(status="publish", memberships=memberships, blockers=blockers, carried=carried,
                  payload=payload, checksum=checksum)


def load_prior(connection) -> List[dict]:
    """Memberships of the current published snapshot, read from its payload (it keeps every key)."""
    row = connection.execute(
        "SELECT source_payload FROM roster_snapshots WHERE league=? AND status='published'",
        (LEAGUE,)).fetchone()
    if not row:
        return []
    return json.loads(row[0])["memberships"]


def publish(connection, result: Result, captured_at: str) -> Optional[int]:
    """Publish a built result. Returns the snapshot id, or None when nothing changed or nothing may publish."""
    if result.status != "publish":
        return None
    current = connection.execute(
        "SELECT source_checksum FROM roster_snapshots WHERE league=? AND status='published'",
        (LEAGUE,)).fetchone()
    if current and current[0] == result.checksum:
        return None  # repeated ingestion of the same verified population
    teams = len({m["team"] for m in result.memberships})
    return rm.publish_roster_snapshot(
        connection,
        league=LEAGUE,
        season=rm.roster_season(LEAGUE, captured_at),
        source=SOURCE_LABEL,
        captured_at=captured_at,
        source_payload=result.payload,
        team_count=teams,
        memberships=result.memberships,
    )
