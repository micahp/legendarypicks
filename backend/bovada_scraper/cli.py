"""cli — Bovada scraper cli layer."""
import re
import json
import os
import sys
import collections
import datetime as dt
import unicodedata
import urllib.request

import datetime as dt
import sys
from .config import API_BASE, LEAGUES, SCHEDULED_LEAGUES, _MINTED_PLAYERS, _RESTED_LEAGUES, _STALE_TEAM_TAGS, _UNMAPPED_PLAYER_MARKETS  # noqa: E402
from .backoff import _load_backoff, _record_result, _save_backoff, _should_fetch  # noqa: E402
from .client import fetch_events, parse_player_props  # noqa: E402
from .direct import _event_start_iso, _ufc_direct_ingest, _wc_direct_ingest, _wc_event_date  # noqa: E402
from .ingest import capture_snapshots, ingest_batch  # noqa: E402

def targets_for_request(league: str):
    """Select scheduled sources for ``all`` and retain explicit historical WC access."""
    if league == "all":
        return list(SCHEDULED_LEAGUES.items())
    if league in LEAGUES:
        return [(league, LEAGUES[league])]
    return None


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    league = sys.argv[1]
    do_ingest = "--ingest" in sys.argv
    do_capture = "--capture" in sys.argv

    targets = targets_for_request(league)
    if targets is None:
        print(f"Unknown league: {league}")
        sys.exit(1)

    all_props = []
    resolve_counts = {}
    today = dt.date.today().isoformat()

    backoff = _load_backoff()
    for key, (sport, lg) in targets:
        fetch, why = _should_fetch(key, backoff)
        if not fetch:
            print(f"Skipping {key.upper()} — {why}")
            _RESTED_LEAGUES.append(key)
            continue
        print(f"Fetching {key.upper()} from Bovada...")
        try:
            events = fetch_events(sport, lg)
        except Exception as e:
            print(f"  FAIL: {e}")
            continue

        _record_result(key, backoff, len(events))
        print(f"  {len(events)} events")

        for ev in events:
            props = parse_player_props(ev, key)
            if props:
                game_desc = ev.get("description", "?")
                print(f"  {game_desc}: {len(props)} props")
                all_props.extend(props)

    _save_backoff(backoff)
    print(f"\nTotal props scraped: {len(all_props)}")

    if all_props:
        # Show sample
        for p in all_props[:10]:
            line_str = f" {p['line']}" if p['line'] else ""
            print(f"  {p['player_name']} {p['side'].upper()}{line_str} {p['market']} ({p['odds']})")

        # Optionally ingest
        if do_ingest:
            # Route ingest PER PROP-LEAGUE (not the CLI arg) so `all --ingest` sends each league to the
            # right path: WC + UFC create their own players (direct DB), everything else goes through the
            # resolver API. The game date is derived from the Bovada startTime, not "today".
            by_league = {}
            for p in all_props:
                by_league.setdefault(p["league"], []).append(p)
            for lg, lprops in by_league.items():
                if lg == "wc":
                    print(f"\nDirect-ingesting WC props into DB...")
                    try:
                        print(f"  {_wc_direct_ingest(lprops, today)} props ingested")
                    except Exception as e:
                        print(f"  FAIL ingest (wc): {e}")
                elif lg == "ufc":
                    print(f"\nDirect-ingesting UFC props into DB...")
                    try:
                        print(f"  {_ufc_direct_ingest(lprops, today)} props ingested")
                    except Exception as e:
                        print(f"  FAIL ingest (ufc): {e}")
                else:
                    print(f"\nIngesting {lg.upper()} into {API_BASE}...")
                    by_game = {}
                    for p in lprops:
                        gkey = f"{p['league']}|{p['game_desc']}"
                        if gkey not in by_game:
                            by_game[gkey] = {
                                "league": p["league"],
                                "date": _wc_event_date(p, today, p["league"]),
                                "home": p["home_team"],
                                "away": p["away_team"],
                                "espn_event_id": "",
                                "start_time": _event_start_iso(p),
                                "props": []
                            }
                        by_game[gkey]["props"].append({
                            "player_name": p["player_name"],
                            "team": p["team"],
                            "market": p["market"],
                            "line": p["line"] or 0,
                            "side": p["side"],
                            "source": "bovada",
                            "odds": p.get("odds"),
                        })
                    lg_ingested = 0
                    lg_refreshed = 0
                    lg_unresolved = 0
                    lg_failed = 0
                    for batch in by_game.values():
                        try:
                            result = ingest_batch(batch)
                            lg_ingested += result.get("ingested") or 0
                            lg_refreshed += result.get("refreshed") or 0
                            lg_unresolved += result.get("unresolved") or 0
                            print(f"  {batch['away']} @ {batch['home']}: "
                                  f"{result['ingested']} new, {result.get('refreshed', 0)} refreshed")
                        except Exception as e:
                            lg_failed += 1
                            print(f"  FAIL ingest: {e}")
                    resolve_counts[lg] = {
                        "scraped": len(lprops),
                        "ingested": lg_ingested,
                        "refreshed": lg_refreshed,
                        "unresolved": lg_unresolved,
                        "games_failed": lg_failed,
                        "games": len(by_game),
                    }
        # Optionally capture snapshots
        if do_capture:
            print(f"\nCapturing odds snapshots...")
            try:
                result = capture_snapshots(all_props, league)
                print(f"  Snapshots: {result.get('snapshots',0)} written ({result.get('paired',0)} paired, {result.get('single',0)} single)")
            except Exception as e:
                print(f"  FAIL capture: {e}")
    else:
        print("  (no props found — games may not have started yet, or sport is out of season)")

    sys.exit(_run_report(resolve_counts, do_ingest))

def _run_report(resolve_counts: dict, did_ingest: bool) -> int:
    """Print what this run could NOT do, and return the process exit code.

    Every line here prints even when the count is zero (fail-loudly §3.7): a log that only
    speaks up on failure cannot tell "clean" from "never ran", which is the state the tennis
    ingest sat in for its whole existence -- 169 players rejected every 30 minutes behind a
    status line reading `0 ingested`.

    Exit 3 means the run wrote data AND found something a human needs to look at. It is
    deliberately not 0: a scrape that resolves none of what it scraped is a broken feed, and
    a systemd unit is the only thing that will ever notice.
    """
    problems = []

    print("\n--- run report ---")
    print(f"  leagues rested this run (no request made): {len(_RESTED_LEAGUES)}"
          + (" — " + ", ".join(_RESTED_LEAGUES) if _RESTED_LEAGUES else ""))
    print(f"  unmapped player markets: {len(_UNMAPPED_PLAYER_MARKETS)}")
    for (lg, group, desc), n in sorted(_UNMAPPED_PLAYER_MARKETS.items()):
        print(f"      UNMAPPED {lg} [{group}] {desc!r}"
              f" — {n['outcomes']} outcomes across {n['events']} events, NOT ingested")
        problems.append(f"unmapped market {lg}:{desc}")

    print(f"  players minted from a sportsbook name (no publisher id): "
          f"{len(_MINTED_PLAYERS)}")
    for league, name in _MINTED_PLAYERS[:20]:
        print(f"      MINTED {league} {name!r} — no espn_id, no game logs")
    if len(_MINTED_PLAYERS) > 20:
        print(f"      ... and {len(_MINTED_PLAYERS) - 20} more")

    print(f"  outcomes tagged with a club not in the fixture: {len(_STALE_TEAM_TAGS)}")
    for (name, code), game in sorted(_STALE_TEAM_TAGS.items()):
        print(f"      STALE TAG {name} ({code}) in {game} — team dropped, resolved on game_id")

    if did_ingest:
        for lg, c in sorted(resolve_counts.items()):
            resolved = c["ingested"] + c["refreshed"]
            print(f"  {lg}: resolved {resolved} of {c['scraped']} scraped"
                  f" ({c['ingested']} new, {c['refreshed']} refreshed,"
                  f" {c['unresolved']} unresolved) across {c['games']} games")
            if c["scraped"] and not resolved:
                print(f"      REJECTED all {c['scraped']} {lg} props —"
                      f" nothing in `players` matched. A count of zero is a finding.")
                problems.append(f"{lg} resolved 0 of {c['scraped']}")
            if c["games_failed"]:
                print(f"      {c['games_failed']} of {c['games']} {lg} games failed to POST")
                problems.append(f"{lg} {c['games_failed']} games failed to POST")

    if problems:
        print("\nEXIT 3 — " + "; ".join(problems))
        return 3
    print("  no problems found")
    return 0
