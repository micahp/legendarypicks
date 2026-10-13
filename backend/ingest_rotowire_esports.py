#!/usr/bin/env python3
"""ingest_rotowire_esports.py — CS2 + Valorant player props from the RotoWire relay.

Ingest only. Settlement/history is a separate phase: the codebase's own note in
routers/esports/pandascore.py says HLTV is the authoritative per-player stats source
for CS2, PandaScore for the rest -- neither is wired to grade a prop yet. This gets
real props flowing into the board first, matching the precedent already set for
UFC/ATP/WTA (priced before fully chartable), decided with Micah 2026-08-30.

## Market vocabulary (controlled -- never guess at a market)

Checked every archived rotowire-*.json.gz day, not just one snapshot (a single day's
absence proves nothing -- CONTEXT-2026-08-26 §1). 8 distinct esports marketIDs across
the whole archive, all Kills or Headshots at various map-count granularities:

    308 CS2 Map 1 Kills            313 CS2 Maps 1+2 Kills          315 CS2 Maps 1+2+3 Kills
    335 CS2 Map 1 Headshots        340 CS2 Maps 1+2 Headshots      342 CS2 Maps 1+2+3 Headshots
    368 Valorant Maps 1+2 Kills    370 Valorant Maps 1+2+3 Kills

## Game linking

Esports has no persisted scoreboard table the way MLB/NFL/NCAAF do (scoreboard_snapshots
only carries cod, per the distinct-leagues check 2026-08-30), so there is no independent
"did this game actually happen" source to check the relay against the way NCAAF's
fixture_scoreboard kind does. PandaScore fills that role here instead: `_fetch_ps()`
already gives (mostly) live schedule/opponent data for csgo and valorant, uncached calls
cost real PandaScore quota, so this borrows the router's own cache rather than calling the
API a second time. A relay event creates a `prop_games` row ONLY when both team names
match one PandaScore match on the same title within a time window -- the relay alone never
mints a game, same doctrine as every other league here.

Settlement (`detailed_stats` on the matched PandaScore match, and per-player stats) is
explicitly NOT read or stored by this script -- that field says whether PandaScore CAN
grade this specific match, and measuring it now would be recording a fact this script
throws away, which is the exact "measured the wrong thing" shape CONTEXT-2026-08-26 §1
warns about. Leave it for the settlement phase to measure when it actually reads it.

Usage: LP_DB_PATH=<db> ./venv/bin/python ingest_rotowire_esports.py [--dry-run]
"""
import argparse
import gzip
import json
import os
import re
import sqlite3
import sys
from contextlib import closing

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

MARKET_MAP = {
    308: ("CS2", "Map 1 Kills", "kills_map1"),
    313: ("CS2", "Maps 1+2 Kills", "kills_maps12"),
    315: ("CS2", "Maps 1+2+3 Kills", "kills_maps123"),
    335: ("CS2", "Map 1 Headshots", "headshots_map1"),
    340: ("CS2", "Maps 1+2 Headshots", "headshots_maps12"),
    342: ("CS2", "Maps 1+2+3 Headshots", "headshots_maps123"),
    368: ("Valorant", "Maps 1+2 Kills", "kills_maps12"),
    370: ("Valorant", "Maps 1+2+3 Kills", "kills_maps123"),
}
_SPORT_TO_LEAGUE = {"CS2": "cs2", "Valorant": "valorant"}
_SPORT_TO_PS_SLUG = {"CS2": "cs-go", "Valorant": "valorant"}

# PandaScore match time is a schedule estimate, not a lock -- relay eventTime and
# PandaScore begin_at have both been observed to disagree by minutes to a few hours
# around a delayed start. Wide enough to survive that, narrow enough that two
# different matches between the same rebooking-prone team names on the same day
# cannot both pass.
_MATCH_WINDOW_S = 6 * 3600


def _archive_path(day=None):
    import datetime as dt
    day = day or dt.datetime.now(dt.timezone.utc).date()
    return os.path.join(HERE, "data", "rotowire-archive", f"rotowire-{day.isoformat()}.json.gz")


def _latest_archive():
    """The newest rotowire-*.json.gz on disk, by the date in its filename -- never by
    mtime (a re-run touches the same day's file) and never a same-day intraday snapshot
    (rotowire-YYYY-MM-DD-snapHHMMSS.json.gz), which is a partial-day capture."""
    import glob
    day_files = glob.glob(os.path.join(HERE, "data", "rotowire-archive", "rotowire-????-??-??.json.gz"))
    if not day_files:
        return None
    return sorted(day_files)[-1]


def _norm_team(name):
    """Lowercase, strip punctuation/whitespace -- 'NEW VISION' == 'new-vision' == 'New Vision'."""
    return re.sub(r"[^a-z0-9]", "", (name or "").lower())


def _ps_matches_by_slug():
    """PandaScore's own cache, not a fresh call -- this borrows the router's cache
    rather than spending PandaScore quota a second time for the same schedule."""
    from routers.esports import pandascore as ps
    if not ps._ps_key():
        return {}
    matches = ps._fetch_ps(include_running=True)
    out = {}
    for m in matches:
        slug = (m.get("videogame") or {}).get("slug")
        if slug:
            out.setdefault(slug, []).append(m)
    return out


def _team_matches(relay_n, opp_n):
    """A publisher-vs-publisher name match, not an equality check: relay names an org
    "Fire Flux", PandaScore names the same match "Fire Flux Esports" -- measured
    2026-08-30, this exact pair was the only reason a real, verifiable match read as
    unverified. Containment either direction, guarded to >=4 normalized characters so
    a short name ("OG", "G2") cannot spuriously match inside an unrelated longer one;
    below that length the two normalized forms must match exactly. Both inputs are
    already `_norm_team`-normalized."""
    if not relay_n or not opp_n:
        return False
    if relay_n == opp_n:
        return True
    shorter = relay_n if len(relay_n) <= len(opp_n) else opp_n
    if len(shorter) < 4:
        return False
    return relay_n in opp_n or opp_n in relay_n


def _verify_fixture(ps_matches, slug, home, away, event_time_s):
    """A relay event is a real PandaScore match iff both team names match one
    PandaScore match on the same title within the time window. Returns the matched
    PandaScore match's own team names (its own spelling, not the relay's) or None."""
    home_n, away_n = _norm_team(home), _norm_team(away)
    if not home_n or not away_n:
        return None
    for m in ps_matches.get(slug, []):
        begin = m.get("begin_at") or (m.get("scheduled_at"))
        if not begin:
            continue
        try:
            import datetime as dt
            begin_s = dt.datetime.fromisoformat(begin.replace("Z", "+00:00")).timestamp()
        except Exception:
            continue
        if abs(begin_s - event_time_s) > _MATCH_WINDOW_S:
            continue
        home_opp = away_opp = None
        for o in m.get("opponents") or []:
            team = o.get("opponent") or {}
            candidates = [_norm_team(team.get(k)) for k in ("name", "acronym") if team.get(k)]
            if home_opp is None and any(_team_matches(home_n, c) for c in candidates):
                home_opp = team.get("name")
            elif away_opp is None and any(_team_matches(away_n, c) for c in candidates):
                away_opp = team.get("name")
        if home_opp and away_opp:
            return {
                "home": home_opp,
                "away": away_opp,
                "start_time": begin,
                "ps_match_id": m.get("id"),
            }
    return None


def _resolve_player(con, league, entity_id, name, team, dry_run):
    """rotowire entity id -> our players.id, via player_source_ids. Creates the
    identity if this is the first time we've seen this rotowire entity for this
    league -- the same shape as every other publisher-id resolver in this repo."""
    row = con.execute(
        "SELECT player_id FROM player_source_ids WHERE source='rotowire' AND league=? "
        "AND source_player_key=?", (league, str(entity_id))).fetchone()
    if row:
        return row[0]
    if dry_run:
        return None
    cur = con.execute(
        "INSERT INTO players(name, team, league, active) VALUES (?, ?, ?, 1)",
        (name, team, league))
    player_id = cur.lastrowid
    con.execute(
        "INSERT INTO player_source_ids(source, league, source_player_key, player_id, "
        "first_seen, last_seen) VALUES ('rotowire', ?, ?, ?, datetime('now'), datetime('now'))",
        (league, str(entity_id), player_id))
    return player_id


def _resolve_game(con, league, verified, dry_run):
    ps_match_id = verified["ps_match_id"]
    espn_event_id = f"ps-{ps_match_id}"
    row = con.execute(
        "SELECT id FROM prop_games WHERE league=? AND espn_event_id=?",
        (league, espn_event_id)).fetchone()
    if row:
        return row[0]
    if dry_run:
        return None
    date = verified["start_time"][:10]
    cur = con.execute(
        "INSERT INTO prop_games(league, date, home, away, espn_event_id, start_time) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (league, date, verified["home"], verified["away"], espn_event_id, verified["start_time"]))
    return cur.lastrowid


def run(payload_path=None, dry_run=False):
    payload_path = payload_path or _latest_archive()
    if not payload_path or not os.path.exists(payload_path):
        print("no rotowire archive found")
        return
    with gzip.open(payload_path) as f:
        payload = json.load(f)
    print(f"reading {os.path.basename(payload_path)}")

    markets = {m["marketID"]: m for m in payload.get("markets", [])}
    entities = {e["entityID"]: e for e in payload.get("entities", [])}
    events = {e["eventID"]: e for e in payload.get("events", [])}

    esports_props = [p for p in payload.get("props", []) if p.get("marketID") in MARKET_MAP]
    print(f"{len(esports_props)} esports props in payload across "
          f"{len({p['marketID'] for p in esports_props})} markets")

    ps_by_slug = _ps_matches_by_slug()
    if not ps_by_slug:
        print("PandaScore key not set or returned nothing -- no fixture can be verified, stopping")
        return

    db_path = os.environ.get("LP_DB_PATH") or os.path.join(HERE, "data", "picks.db")
    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row

    verified_cache = {}   # eventID -> verified dict or False
    game_cache = {}        # eventID -> prop_games.id or None
    written = updated = skipped_unverified = skipped_no_player = 0

    try:
        for prop in esports_props:
            sport, market_name, our_key = MARKET_MAP[prop["marketID"]]
            league = _SPORT_TO_LEAGUE[sport]
            slug = _SPORT_TO_PS_SLUG[sport]
            if len(prop.get("entities") or []) != 1:
                continue  # every esports market here is single-player; a multi-entity row is not one we mapped
            entity = entities.get(prop["entities"][0])
            if not entity:
                continue
            event = events.get(entity.get("eventID"))
            if not event:
                continue
            eid = event["eventID"]
            if eid not in verified_cache:
                verified_cache[eid] = _verify_fixture(
                    ps_by_slug, slug, event.get("homeTeam"), event.get("awayTeam"), event["eventTime"]
                ) or False
            verified = verified_cache[eid]
            if not verified:
                skipped_unverified += 1
                continue
            if eid not in game_cache:
                game_cache[eid] = _resolve_game(con, league, verified, dry_run)
            game_id = game_cache[eid]
            if game_id is None and not dry_run:
                continue

            player_id = _resolve_player(con, league, entity["entityID"], entity["name"],
                                        entity.get("team"), dry_run)
            if player_id is None and not dry_run:
                skipped_no_player += 1
                continue

            for line in prop.get("lines") or []:
                side_pairs = [("over", line.get("over")), ("under", line.get("under"))]
                for side, odds in side_pairs:
                    if odds is None:
                        continue
                    source = "rotowire:" + line.get("book", "unknown")
                    line_val = line.get("line")
                    if dry_run:
                        written += 1
                        continue
                    # props carries no unique constraint on (game_id, player_id, market,
                    # line, side, source) -- checked before insert here rather than
                    # relying on one, because a re-run of this script (which will happen
                    # on the same day's snapshot, refreshed odds included) DOUBLED every
                    # row the first time this was tried: 1282 -> 2564 with no guard.
                    existing = con.execute(
                        "SELECT id FROM props WHERE game_id=? AND player_id=? AND market=? "
                        "AND line=? AND side=? AND source=?",
                        (game_id, player_id, our_key, line_val, side, source)).fetchone()
                    if existing:
                        con.execute(
                            "UPDATE props SET odds=?, odds_captured_at=datetime('now') WHERE id=?",
                            (odds, existing[0]))
                        updated += 1
                        continue
                    con.execute(
                        "INSERT INTO props(game_id, player_id, market, line, side, source, "
                        "captured_at, odds, odds_captured_at) VALUES (?, ?, ?, ?, ?, ?, "
                        "datetime('now'), ?, datetime('now'))",
                        (game_id, player_id, our_key, line_val, side, source, odds))
                    written += 1

        if dry_run:
            con.rollback()
        else:
            con.commit()
    finally:
        con.close()

    verified_events = sum(1 for v in verified_cache.values() if v)
    print(f"events: {len(verified_cache)} seen, {verified_events} verified against PandaScore, "
          f"{len(verified_cache) - verified_events} unverified (no fixture match, not created)")
    print(f"props: {written} new, {updated} refreshed  (skipped: {skipped_unverified} "
          f"unverified fixture, {skipped_no_player} no player)")
    if dry_run:
        print("DRY RUN — nothing committed")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--payload", default=None, help="path to a specific rotowire-*.json.gz")
    args = ap.parse_args()
    run(payload_path=args.payload, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
