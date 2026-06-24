#!/usr/bin/env python3
"""
bovada_scraper.py — scrape player props from Bovada's open API.

Usage:
  python3 bovada_scraper.py mlb     # scrape MLB player props
  python3 bovada_scraper.py nba     # NBA (when in season)
  python3 bovada_scraper.py nfl     # NFL
  python3 bovada_scraper.py nhl     # NHL
  python3 bovada_scraper.py all     # all available
  python3 bovada_scraper.py mlb --ingest   # scrape + POST to ingest API

Source: Bovada's internal API — no auth, no Cloudflare, live odds.
"""
import sys, json, os, urllib.request, datetime as dt

API_BASE = os.environ.get("LP_API_BASE", "http://localhost:8000")
BOVADA = "https://www.bovada.lv/services/sports/event/coupon/events/A/description"

LEAGUES = {
    "mlb":  ("baseball", "mlb"),
    "nba":  ("basketball", "nba"),
    "nfl":  ("football", "nfl"),
    "nhl":  ("hockey", "nhl"),
    "wnba": ("basketball", "wnba"),
}

HDR = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/131 Safari/537.36"}

# Map Bovada market descriptions → our canonical market names
MARKET_MAP = {
    # Pitcher props (with lines)
    "total strikeouts": "strikeouts",
    "total hits allowed": "hits_allowed",
    "total pitcher outs": "outs",
    "total earned runs": "earned_runs",
    "total walks": "walks",
    # Player props with lines (points/rebounds etc for NBA/NFL)
    "total points": "points",
    "total rebounds": "rebounds",
    "total assists": "assists",
    "total threes": "threes",
    "total blocks": "blocks",
    "total steals": "steals",
    "total turnovers": "turnovers",
    "passing yards": "passing_yards",
    "passing tds": "passing_tds",
    "rushing yards": "rushing_yards",
    "receiving yards": "receiving_yards",
    "receptions": "receptions",
    "total tackles": "tackles",
    "total sacks": "sacks",
    "total shots": "shots",
    "total saves": "saves",
    "total goals": "goals",
    # Yes/no props (no line, just odds)
    "player to hit a home run": "home_run_any",
    "player to hit 2+ home runs": "home_runs_2plus",
    "player to record a hit": "hit_any",
    "player to record 2+ hits": "hits_2plus",
    "player to record a run": "run_any",
    "player to record 2+ runs": "runs_2plus",
    "player to record a rbi": "rbi_any",
    "player to record 2+ rbis": "rbis_2plus",
    "player to record a stolen base": "stolen_base_any",
    "player to record a double": "double_any",
    "player to record a triple": "triple_any",
}


def fetch_events(sport: str, league: str) -> list:
    url = f"{BOVADA}/{sport}/{league}"
    req = urllib.request.Request(url, headers=HDR)
    with urllib.request.urlopen(req, timeout=20) as r:
        data = json.loads(r.read().decode())
    events = []
    for group in data:
        for ev in group.get("events", []):
            events.append(ev)
    return events


def parse_player_props(event: dict, league: str) -> list:
    """Extract all player props from a single Bovada event."""
    results = []
    game_desc = event.get("description", "")
    start_time = event.get("startTime")

    # Parse home/away from competitors
    competitors = event.get("competitors", [])
    home_team = ""
    away_team = ""
    for c in competitors:
        if c.get("home", False):
            home_team = c.get("name", "")
        else:
            away_team = c.get("name", "")

    for dg in event.get("displayGroups", []):
        group_desc = (dg.get("description") or "").lower()

        # Only process player/pitcher props
        if "prop" not in group_desc:
            continue

        for market in dg.get("markets", []):
            market_desc = (market.get("description") or "").strip()

            # Find canonical market name
            canonical = None
            for pattern, name in MARKET_MAP.items():
                if pattern in market_desc.lower():
                    canonical = name
                    break
            if not canonical:
                canonical = market_desc.lower().replace(" ", "_").replace("-", "_")

            for outcome in market.get("outcomes", []):
                desc = (outcome.get("description") or "").strip()
                price = outcome.get("price", {})
                handicap = price.get("handicap")  # the line number (e.g., 4.5)
                odds = price.get("american")       # American odds (e.g., -110)

                # Determine over/under from description
                desc_lower = desc.lower()
                if desc_lower == "over":
                    side = "over"
                elif desc_lower == "under":
                    side = "under"
                else:
                    # Not an over/under outcome — it's a player name for yes/no props
                    # e.g., "Kyle Schwarber (PHI)"
                    # For yes/no props, the player IS the outcome, side varies by market
                    continue  # skip player-name outcomes for now; we'd need to restructure

                # Extract player name from market description
                # e.g., "Total Strikeouts - Ryan Gusto (MIA)" → "Ryan Gusto"
                player_name = ""
                team_abbrev = ""
                if " - " in market_desc:
                    player_part = market_desc.split(" - ", 1)[1].strip()
                    # Parse "Ryan Gusto (MIA)"
                    import re
                    pm = re.match(r"(.+?)\s*\(([A-Z]+)\)", player_part)
                    if pm:
                        player_name = pm.group(1).strip()
                        team_abbrev = pm.group(2)

                results.append({
                    "player_name": player_name,
                    "team": team_abbrev,
                    "market": canonical,
                    "line": float(handicap) if handicap is not None else None,
                    "side": side,
                    "odds": odds,
                    "league": league,
                    "game_desc": game_desc,
                    "home_team": home_team,
                    "away_team": away_team,
                    "start_time": start_time,
                    "source": "bovada",
                    "market_raw": market_desc,
                })

    return results


def ingest_batch(batch: dict):
    """POST to the ingest API."""
    url = f"{API_BASE}/api/props/ingest"
    data = json.dumps(batch).encode()
    req = urllib.request.Request(url, data=data,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode())




def capture_snapshots(all_props: list, league: str):
    """Write prop_odds_snapshots for existing props. Does NOT create new props."""
    import urllib.request as _ur, json as _json
    url = f"{API_BASE}/api/capture-odds"
    data = _json.dumps({"league": league, "props": all_props}).encode()
    req = _ur.Request(url, data=data, headers={"Content-Type": "application/json"})
    with _ur.urlopen(req, timeout=30) as r:
        return _json.loads(r.read().decode())

def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    league = sys.argv[1]
    do_ingest = "--ingest" in sys.argv
    do_capture = "--capture" in sys.argv

    if league == "all":
        targets = list(LEAGUES.items())
    elif league in LEAGUES:
        targets = [(league, LEAGUES[league])]
    else:
        print(f"Unknown league: {league}")
        sys.exit(1)

    all_props = []
    today = dt.date.today().isoformat()

    for key, (sport, lg) in targets:
        print(f"Fetching {key.upper()} from Bovada...")
        try:
            events = fetch_events(sport, lg)
        except Exception as e:
            print(f"  FAIL: {e}")
            continue

        print(f"  {len(events)} events")

        for ev in events:
            props = parse_player_props(ev, key)
            if props:
                game_desc = ev.get("description", "?")
                print(f"  {game_desc}: {len(props)} props")
                all_props.extend(props)

    print(f"\nTotal props scraped: {len(all_props)}")

    if all_props:
        # Show sample
        for p in all_props[:10]:
            line_str = f" {p['line']}" if p['line'] else ""
            print(f"  {p['player_name']} {p['side'].upper()}{line_str} {p['market']} ({p['odds']})")

        # Optionally ingest
        if do_ingest:
            print(f"\nIngesting into {API_BASE}...")
            # Group by game
            by_game = {}
            for p in all_props:
                gkey = f"{p['league']}|{p['game_desc']}"
                if gkey not in by_game:
                    by_game[gkey] = {
                        "league": p["league"],
                        "date": today,
                        "home": p["home_team"],
                        "away": p["away_team"],
                        "espn_event_id": "",
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
            for batch in by_game.values():
                try:
                    result = ingest_batch(batch)
                    print(f"  {batch['away']} @ {batch['home']}: {result['ingested']} ingested")
                except Exception as e:
                    print(f"  FAIL ingest: {e}")
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


if __name__ == "__main__":
    main()
