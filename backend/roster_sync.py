#!/usr/bin/env python3
"""
roster_sync.py — ensure every CURRENTLY-ROSTERED player exists in `players`, with
espn_id / team / position populated, and the `active` flag reflecting current rosters.

Why: the per-game-log ingests only resolve players who appeared in a game. Bench /
injured / just-signed players never log a row, so the roster is incomplete and the
`active` flag is stale (it was effectively "ever seen" = always 1). This walks every
team's ESPN roster, matches to existing players by normalized name (to avoid
duplicates), upserts, and rebuilds `active` per league.

Usage: python3 roster_sync.py [nfl nba nhl mlb]   (default: all four)
"""
import datetime as dt
import collections, sys, os, sqlite3
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import espn_client as espn
from audit_league_stats import _identity_name_key
from league_stats import queue_unresolved_player
from roster_membership import (
    normalized_source_payload,
    publish_roster_snapshot,
    require_roster_schema,
    roster_season,
)
from team_codes import (
    UnknownPositionCode,
    UnknownTeamCode,
    normalize,
    normalize_position_optional,
)

DB = os.environ.get("LP_DB_PATH") or os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "picks.db")

# Above this share of unidentifiable roster entries, stop and change nothing --
# something is wrong with the source, not with a player. Measured on real rosters
# the four leagues sit at 0.00%-0.08% (one or two players out of 700-3,000), so a
# 2% ceiling is ~25x the observed noise and still catches a source gone bad.
_MAX_UNRESOLVABLE_SHARE = float(os.environ.get("LP_ROSTER_MAX_UNRESOLVABLE", "0.02"))
_EXPECTED_TEAM_COUNTS = {"nfl": 32, "nba": 30, "nhl": 32, "mlb": 30}


def configure_espn():
    """Pacing, retries and the shared disk cache for this job's ESPN calls.

    This job is the heaviest ESPN caller in the repo -- one request per team, so
    ~32 per league and 128 for all four, which is what tripped the wall on
    2026-08-04 when they went out back to back. There is no bulk roster endpoint
    to collapse them into (checked: `byathlete` carries no team or position, and
    the `core` athlete lists are $ref stubs costing a request each), so the two
    levers are pacing the first run and not repeating it.

    `sync_league` calls this, not just `main`. On 2026-08-04 the prod run paid
    all 128 requests over again because the cache held no roster entries, and
    every caller that reaches this module by `import roster_sync; sync_league(...)`
    -- which is how both that night's runs were launched -- silently ran unpaced
    and uncached when the settings lived in `main` alone. Configuration that only
    applies when you enter through one door is configuration you do not have.
    """
    espn.set_retry_waits((5.0, 30.0, 120.0))
    espn.set_min_interval(float(os.environ.get("LP_ESPN_MIN_INTERVAL", "1.0")))
    espn.set_disk_cache(
        os.environ.get("LP_ESPN_CACHE_DIR")
        or os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "espn-cache"),
        ttl=float(os.environ.get("LP_ESPN_CACHE_TTL", "43200")),
    )


def sync_league(con: sqlite3.Connection, league: str) -> dict:
    # Idempotent, and it must run before the first `espn.` call below -- see the
    # docstring: entering here directly is the normal case, not the exception.
    configure_espn()
    # Schema changes are explicit, backup-first migrations. Do not make source
    # calls or touch compatibility fields until the roster schema is present.
    require_roster_schema(con)
    teams = list(dict.fromkeys(
        t.get("abbrev") for t in espn.team_strength(league) if t.get("abbrev")
    ))
    expected_teams = _EXPECTED_TEAM_COUNTS.get(league, len(teams))
    if not teams or len(teams) != expected_teams:
        active_now = con.execute(
            "SELECT COUNT(*) FROM players WHERE league=? AND active=1", (league,)
        ).fetchone()[0]
        return {
            "status": "incomplete",
            "teams": len(teams),
            "expected_teams": expected_teams,
            "matched": 0,
            "inserted": 0,
            "espn_id_filled": 0,
            "active_now": active_now,
            "verified_at": None,
            "failures": [{
                "team": None,
                "reason": f"expected {expected_teams} teams, got {len(teams)}",
            }],
        }
    # Fetch the complete population before mutating active flags. A partial
    # upstream response must not deactivate an entire missing team's roster or
    # stamp the league as freshly verified.
    rosters = {}
    failures = []
    for abbr in teams:
        try:
            roster = espn.roster(league, abbr)
        except Exception as exc:
            failures.append({"team": abbr, "reason": str(exc)})
            continue
        if not roster:
            failures.append({"team": abbr, "reason": "empty roster"})
            continue
        try:
            team = normalize(league, abbr)
            normalized_roster = []
            for player in roster:
                normalized = dict(player)
                if league == "nfl":
                    normalized["position"] = normalize_position_optional(
                        "nfl", player.get("position")
                    )
                normalized_roster.append(normalized)
        except (UnknownTeamCode, UnknownPositionCode) as exc:
            failures.append({"team": abbr, "reason": str(exc)})
            continue
        rosters[team] = normalized_roster

    if failures or len(rosters) != expected_teams:
        active_now = con.execute(
            "SELECT COUNT(*) FROM players WHERE league=? AND active=1", (league,)
        ).fetchone()[0]
        return {
            "status": "incomplete",
            "teams": len(rosters),
            "expected_teams": expected_teams,
            "matched": 0,
            "inserted": 0,
            "espn_id_filled": 0,
            "active_now": active_now,
            "verified_at": None,
            "failures": failures,
        }

    # Plan every identity before mutating active flags. A single ambiguous
    # crosswalk leaves the previous verified roster intact.
    # Bucket by the IDENTITY key, not a plain normalize: 'Max P. Muncy' and
    # 'Max Muncy' must land in the SAME bucket so the team-narrowing ladder
    # below can separate them. A plain normalize keeps the middle-initial
    # spelling in its own bucket, the ESPN entry (plain 'Max Muncy') finds
    # only one candidate, and the wrong player silently gets the match.
    name_to_rows = {}
    eid_to_ids = {}
    for r in con.execute(
        "SELECT id,name,team,espn_id FROM players WHERE league=?",
        (league,),
    ):
        if r["name"]:
            name_to_rows.setdefault(
                _identity_name_key(r["name"]), []
            ).append(r)
        if r["espn_id"]:
            eid_to_ids.setdefault(str(r["espn_id"]), []).append(r["id"])

    verified_at = dt.datetime.now(dt.timezone.utc).isoformat()
    planned = []
    identity_failures = []
    # Trades resolved by the roster rather than blocked on -- reported so a
    # surprising number of them is visible instead of silent.
    team_changes = []
    seen_roster_ids = set()
    for abbr, roster in rosters.items():
        for p in roster:
            name = p.get("name")
            if not name:
                identity_failures.append({
                    "team": abbr,
                    "name": "<missing>",
                    "source_player_key": p.get("player_id"),
                    "reason": "missing_display_name",
                })
                continue
            raw_eid = p.get("player_id")
            eid = str(raw_eid).strip() if raw_eid is not None else None
            if eid in ("", "0", "None", "null"):
                eid = None
            pos = p.get("position")
            if not eid:
                identity_failures.append({
                    "team": abbr,
                    "name": name,
                    "source_player_key": None,
                    "reason": "missing_espn_id",
                })
                continue
            if eid in seen_roster_ids:
                identity_failures.append({
                    "team": abbr,
                    "name": name,
                    "source_player_key": eid,
                    "reason": "duplicate_source_roster_id",
                })
                continue
            seen_roster_ids.add(eid)
            exact_ids = eid_to_ids.get(eid, [])
            if len(exact_ids) > 1:
                identity_failures.append({
                    "team": abbr,
                    "name": name,
                    "source_player_key": eid,
                    "reason": "duplicate_spine_espn_id",
                })
                continue
            if exact_ids:
                planned.append({
                    "action": "update",
                    "player_id": exact_ids[0],
                    "name": name,
                    "team": abbr,
                    "position": pos,
                    "jersey": p.get("jersey"),
                    "source_player_key": eid,
                })
                continue

            candidates = name_to_rows.get(_identity_name_key(name), [])
            if not candidates:
                planned.append({
                    "action": "insert",
                    "player_id": None,
                    "name": name,
                    "team": abbr,
                    "position": pos,
                    "jersey": p.get("jersey"),
                    "source_player_key": eid,
                })
                continue
            # Two different people can share a name -- there are two Max
            # Muncys -- and a bare name collision used to fail the whole
            # league. The roster publishes which team this one plays for, so
            # narrow on that before giving up. Narrowing can only ever shrink
            # the candidate set, so it cannot introduce a match that the name
            # alone did not already support.
            if len(candidates) > 1:
                narrowed = [
                    c for c in candidates
                    if c["espn_id"] and str(c["espn_id"]) == eid
                ]
                if len(narrowed) != 1:
                    narrowed = [
                        c for c in candidates
                        if str(c["team"] or "").upper() == abbr
                    ]
                if len(narrowed) == 1:
                    candidates = narrowed

            if len(candidates) != 1:
                reason = "ambiguous_normalized_name"
            else:
                candidate = candidates[0]
                candidate_eid = (
                    str(candidate["espn_id"])
                    if candidate["espn_id"] else None
                )
                candidate_team = str(candidate["team"] or "").upper()
                if candidate_eid and candidate_eid != eid:
                    reason = "name_match_conflicting_espn_id"
                else:
                    # A team mismatch on a name that is unique in this league
                    # is a trade, and the published roster is the newer truth.
                    # This used to fail the league, which made the sync unable
                    # to do the one thing it exists for: a player changing
                    # teams blocked every other player's update. The evidence
                    # standard is unchanged -- unique name, no conflicting
                    # espn_id -- it is only the conclusion that was wrong.
                    if candidate_team and candidate_team != abbr:
                        team_changes.append({
                            "name": name, "from": candidate_team, "to": abbr,
                        })
                    planned.append({
                        "action": "update",
                        "player_id": candidate["id"],
                        "name": name,
                        "team": abbr,
                        "position": pos,
                        "jersey": p.get("jersey"),
                        "source_player_key": eid,
                    })
                    continue
            identity_failures.append({
                "team": abbr,
                "name": name,
                "source_player_key": eid,
                "reason": reason,
            })

    # A player we cannot identify is a fact about THAT player. Failing the league
    # over it is the same over-correction the name/trade cases were: on 2026-08-04
    # one Connor Ungar blocked all 32 NHL teams and one Max Muncy blocked all 30
    # MLB ones, so neither league had a team or an espn_id populated at all.
    #
    # The protection that matters is against SYSTEMIC breakage -- a roster fetch
    # that silently returns junk would deactivate a league, since apply resets
    # active=0 first. So keep blocking on that, and only on that:
    #   * any team that produced no usable entry at all, and
    #   * an unresolvable share above a floor, which no per-player oddity reaches.
    # Below the floor the players are queued for review, exactly as before, and
    # the other ~1,300 get the team and espn_id this job exists to give them.
    planned_by_team = collections.Counter(item["team"] for item in planned)
    empty_teams = sorted(set(rosters) - set(planned_by_team))
    total_seen = len(planned) + len(identity_failures)
    unresolvable_share = (len(identity_failures) / total_seen) if total_seen else 1.0
    systemic = bool(empty_teams) or unresolvable_share > _MAX_UNRESOLVABLE_SHARE

    if identity_failures and systemic:
        for failure in identity_failures:
            queue_unresolved_player(
                con,
                source="espn_roster",
                raw_name=failure["name"],
                league=league,
                team=failure["team"],
                source_player_key=failure["source_player_key"],
                reason=failure["reason"],
            )
        con.commit()
        active_now = con.execute(
            "SELECT COUNT(*) FROM players WHERE league=? AND active=1",
            (league,),
        ).fetchone()[0]
        return {
            "status": "identity_incomplete",
            "teams": len(rosters),
            "expected_teams": expected_teams,
            "matched": 0,
            "inserted": 0,
            "espn_id_filled": 0,
            "active_now": active_now,
            "verified_at": None,
            "failures": identity_failures,
            "empty_teams": empty_teams,
            "unresolvable_share": round(unresolvable_share, 4),
            "team_changes": team_changes,
        }

    source_payload = normalized_source_payload(league, rosters)
    matched = inserted = updated_espn = 0
    memberships = []
    snapshot_id = None
    try:
        con.execute("BEGIN IMMEDIATE")
        # Under the floor: queue the odd players for review and carry on. Inside
        # this transaction so the queue and the apply commit or roll back together
        # -- a review row for a sync that never landed would be a lie. They are
        # reported as `unresolved` rather than `failures` so "we skipped two
        # people" cannot be read as "the league synced cleanly".
        for failure in identity_failures:
            queue_unresolved_player(
                con,
                source="espn_roster",
                raw_name=failure["name"],
                league=league,
                team=failure["team"],
                source_player_key=failure["source_player_key"],
                reason=failure["reason"],
            )
        # Reset active only after every team supplied a non-empty roster and
        # every source identity has an unambiguous application plan.
        #
        # FANTASY ENTITIES ARE NOT ROSTER MEMBERS. A D/ST row is one team's
        # whole defence -- a fantasy construct that shares this table with real
        # humans. It will never appear on an ESPN roster, so a blanket
        # deactivation permanently marks all 32 inactive and nothing ever turns
        # them back on. That is not a cosmetic flag: `ingest_nfl_adp.py:227`
        # builds its team->player_id map from `position='DEF' AND active=1`,
        # so on 2026-08-04 this deactivation (22:37) silently killed every
        # later ADP run, and with it `injury_status` and `last_news_date` for
        # all 6,486 NFL players -- a fail-closed D/ST preflight aborting the
        # whole ingest over rows that were never its business.
        #
        # `active` for a D/ST means "this team exists", not "this player is
        # rostered", so this job has no opinion to offer about it. Excluded
        # here, at the write, rather than by teaching every reader to special-
        # case it -- the same reason season keys are normalised at the ingest.
        con.execute(
            "UPDATE players SET active=0, updated_at=? "
            "WHERE league=? AND COALESCE(position,'') != 'DEF'",
            (verified_at, league),
        )

        for item in planned:
            if league == "mlb":
                # MLB is the exception, and only MLB. ESPN's roster
                # `position` is a ROLE, not a position: it splits pitchers
                # SP/RP and spells hitters coarser than MLB does (and it is
                # the source of the two-vocabularies-in-one-column defect).
                # MLB publishes the real position itself with the group
                # (ingest_mlb_spine_identity.py writes primaryPosition
                # abbreviation -> `position` and type -> `position_group`),
                # so ESPN's value must never overwrite `players.position`.
                # The one fact ESPN carries that MLB does not is the
                # starter/reliever split: that goes to `pitcher_role`, and
                # only when it is SP or RP -- a hitter role is discarded,
                # MLB publishes hitters better.
                # NFL/NBA/NHL are untouched by this branch: ESPN is their
                # only publisher of position, and breaking them to fix MLB
                # would be a worse outcome than the defect itself.
                pitcher_role = (
                    item["position"]
                    if item["position"] in ("SP", "RP") else None
                )
                if item["action"] == "update":
                    before_eid = con.execute(
                        "SELECT espn_id FROM players WHERE id=?",
                        (item["player_id"],),
                    ).fetchone()["espn_id"]
                    con.execute(
                        """UPDATE players
                           SET active=1,team=?,
                               espn_id=COALESCE(espn_id,?),
                               pitcher_role=?,updated_at=?
                           WHERE id=?""",
                        (
                            item["team"],
                            item["source_player_key"], pitcher_role,
                            verified_at, item["player_id"],
                        ),
                    )
                    matched += 1
                    if not before_eid:
                        updated_espn += 1
                else:
                    cursor = con.execute(
                        """INSERT INTO players(
                             name,league,team,espn_id,pitcher_role,
                             active,updated_at
                           ) VALUES(?,?,?,?,?,1,?)""",
                        (
                            item["name"], league, item["team"],
                            item["source_player_key"], pitcher_role,
                            verified_at,
                        ),
                    )
                    item["player_id"] = int(cursor.lastrowid)
                    inserted += 1
            elif item["action"] == "update":
                before_eid = con.execute(
                    "SELECT espn_id FROM players WHERE id=?",
                    (item["player_id"],),
                ).fetchone()["espn_id"]
                con.execute(
                    """UPDATE players
                       SET active=1,team=?,position=COALESCE(?,position),
                           espn_id=COALESCE(espn_id,?),updated_at=?
                       WHERE id=?""",
                    (
                        item["team"], item["position"],
                        item["source_player_key"], verified_at,
                        item["player_id"],
                    ),
                )
                matched += 1
                if not before_eid:
                    updated_espn += 1
            else:
                cursor = con.execute(
                    """INSERT INTO players(
                         name,league,team,position,espn_id,active,updated_at
                       ) VALUES(?,?,?,?,?,1,?)""",
                    (
                        item["name"], league, item["team"],
                        item["position"], item["source_player_key"],
                        verified_at,
                    ),
                )
                item["player_id"] = int(cursor.lastrowid)
                inserted += 1
            memberships.append({
                "player_id": item["player_id"],
                "source_player_key": item["source_player_key"],
                "team": item["team"],
                "position": item["position"],
                "jersey": item["jersey"],
                "roster_status": "active",
                "display_name": item["name"],
            })

        snapshot_id = publish_roster_snapshot(
            con,
            league=league,
            season=roster_season(league, verified_at),
            source="espn_site_roster",
            captured_at=verified_at,
            source_payload=source_payload,
            team_count=expected_teams,
            memberships=memberships,
        )
        con.commit()
    except Exception:
        con.rollback()
        raise
    active_now = con.execute("SELECT COUNT(*) FROM players WHERE league=? AND active=1", (league,)).fetchone()[0]
    return {"status": "complete", "teams": len(rosters), "expected_teams": expected_teams,
            "matched": matched, "inserted": inserted,
            "espn_id_filled": updated_espn, "active_now": active_now,
            "verified_at": verified_at, "snapshot_id": snapshot_id,
            "failures": [], "unresolved": identity_failures,
            "team_changes": team_changes}


def main(leagues):
    configure_espn()
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    for lg in leagues:
        print(f"Syncing {lg} rosters...")
        s = sync_league(con, lg)
        print(f"  {lg}: {s['status']} | {s['teams']}/{s['expected_teams']} teams "
              f"| matched {s['matched']} | inserted {s['inserted']} new "
              f"| espn_id filled {s['espn_id_filled']} | now {s['active_now']} active")
        if s["failures"]:
            print(f"    NOT APPLIED — incomplete roster population: {s['failures']}")
        for u in s.get("unresolved") or []:
            print(f"    queued for review ({u['reason']}): {u['name']} [{u['team']}]")
    con.close()


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if a in ("nfl", "nba", "nhl", "mlb")]
    main(args or ["nfl", "nba", "nhl", "mlb"])
