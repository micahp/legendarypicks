#!/usr/bin/env python3
"""ingest_props.py — ingest player props from Kalshi markets (or manual JSON) into the DB.

Usage:
  python3 ingest_props.py kalshi <date>              # fetch today's sports markets from Kalshi
  python3 ingest_props.py file <path/to/props.json>  # ingest from a JSON file

JSON format (file mode):
{
  "league": "nba",
  "date": "2026-06-15",
  "home": "BOS",
  "away": "GSW",
  "espn_event_id": "401234567",
  "props": [
    {"player_name": "Jayson Tatum", "team": "BOS", "market": "points", "line": 27.5, "side": "over"},
    {"player_name": "Stephen Curry", "team": "GSW", "market": "threes", "line": 4.5, "side": "under"}
  ]
}
"""
import sys, json, os, datetime as dt, urllib.request

# Add parent to path for sports_service imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
API_BASE = os.environ.get("LP_API_BASE", "http://localhost:8000")


def ingest_batch(batch: dict):
    """POST a batch to the /api/props/ingest endpoint."""
    url = f"{API_BASE}/api/props/ingest"
    data = json.dumps(batch).encode()
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode())


def from_file(path: str):
    with open(path) as f:
        batch = json.load(f)
    result = ingest_batch(batch)
    print(f"Ingested {result['ingested']} props (game_id={result['game_id']})")


def from_kalshi(date: str):
    """Fetch sports markets from Kalshi and convert to prop batch format.

    Requires Kalshi API credentials (see ../prediction-market-trading/kalshi_client.py).
    This is a scaffold — wire to real market data when ready.
    """
    print("Kalshi ingestion not yet wired. Use `file` mode with a JSON file for now.")
    print(f"Target date: {date}")
    print("See prediction-market-trading/kalshi_client.py for the API client.")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    mode = sys.argv[1]
    if mode == "file":
        if len(sys.argv) < 3:
            print("Usage: python3 ingest_props.py file <path/to/props.json>")
            sys.exit(1)
        from_file(sys.argv[2])
    elif mode == "kalshi":
        date = sys.argv[2] if len(sys.argv) > 2 else dt.date.today().isoformat()
        from_kalshi(date)
    else:
        print(f"Unknown mode: {mode}")
        print(__doc__)
        sys.exit(1)
