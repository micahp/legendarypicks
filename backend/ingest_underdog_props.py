#!/usr/bin/env python3
"""
ingest_underdog_props.py — player props from Underdog Fantasy's public API.

Usage:
  python3 ingest_underdog_props.py ufc [--dry-run]
  LP_DB_PATH=/path/to/picks.dev.db  (required env)

Source: api.underdogfantasy.com/beta/v5/over_under_lines — no auth, unauthenticated GET
(see docs/UNDERDOG-API-RECON-2026-07-23.md). Underdog carries real per-option American
odds (unlike the initial recon assumption) — captured into props.odds same as Bovada.

UFC scope: only the 5 whole-fight aggregate markets (significant_strikes, submissions,
knockouts, fight_time, finishes) — the ~15 round/method-specific variants (ko_round_1,
sub_round_2, 1st_round_finish, etc.) are skipped as too granular for the board, same
"curate don't dump" call made for the ESPN raw-stat-blob fixes earlier tonight. Only the
"balanced" line_type is ingested (Underdog's primary line) — "alternate" tiers are the
same market at other price points, not additional markets.
"""
import sys, os, re, json, sqlite3, urllib.request, datetime as dt

DB = os.environ.get("LP_DB_PATH") or os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "data", "picks.db")
API = "https://api.underdogfantasy.com/beta/v5/over_under_lines"
HDR = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/131 Safari/537.36"}

# Underdog appearance_stat.stat -> our canonical market name. "knockouts"/"submissions" are
# semantically win-by-method events, not raw counting stats (verified empirically against
# Bovada's now-removed win_by_ko/win_by_submission markets — implied probabilities lined up
# closely per-fighter), but the display title stays Underdog's own framing since Bovada's
# overlapping copy of these markets was removed (see bovada_scraper.py's _UFC_METHOD).
_UFC_MARKETS = {
    "significant_strikes": "significant_strikes",
    "submissions": "submissions",
    "knockouts": "knockouts",
    "fight_time": "fight_time",
    "finishes": "finishes",
}

_SUBHEADER_RE = re.compile(r"^(Higher|Lower)\s+([\d.]+)\s")


def fetch() -> dict:
    req = urllib.request.Request(API, headers=HDR)
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode())


def parse_ufc(data: dict) -> list:
    players = {p["id"]: p for p in data["players"] if p.get("sport_id") == "MMA"}
    appearances = {a["id"]: a for a in data["appearances"] if a.get("player_id") in players}
    games = {g["id"]: g for g in data["solo_games"] if g.get("sport_id") == "MMA"}

    props = []
    for line in data.get("over_under_lines", []):
        if line.get("line_type") != "balanced":
            continue
        ou = line.get("over_under") or {}
        astat = ou.get("appearance_stat") or {}
        canonical = _UFC_MARKETS.get(astat.get("stat"))
        if not canonical:
            continue
        appearance = appearances.get(astat.get("appearance_id"))
        if not appearance:
            continue
        game = games.get(appearance.get("match_id"))
        if not game or game.get("status") != "scheduled":
            continue  # pregame board only — skip in-progress/final fights

        for opt in line.get("options", []):
            choice = opt.get("choice")
            if choice not in ("higher", "lower"):
                continue
            m = _SUBHEADER_RE.match(opt.get("selection_subheader") or "")
            if not m:
                continue
            line_val = float(m.group(2))
            price = opt.get("american_price")
            try:
                odds_int = int(price) if price is not None else None
            except (ValueError, TypeError):
                odds_int = None

            player_id = appearance["player_id"]
            player = players[player_id]
            fighter_name = f"{player['first_name']} {player['last_name']}".strip()

            props.append({
                "player_name": fighter_name,
                "market": canonical,
                "line": line_val,
                "side": "over" if choice == "higher" else "under",
                "odds": odds_int,
                "home": game["home_player_name"],
                "away": game["away_player_name"],
                "date": (game.get("scheduled_at") or "")[:10],
                "start_time": game.get("scheduled_at"),
            })
    return props


def direct_ingest(props: list, dry_run: bool) -> int:
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    now = dt.datetime.now(dt.timezone.utc).isoformat()
    ingested = 0
    try:
        by_game = {}
        for p in props:
            gkey = (p["date"], p["home"], p["away"])
            by_game.setdefault(gkey, []).append(p)

        for (gdate, home, away), gprops in by_game.items():
            # Check both fighter orderings — Bovada/Underdog don't always agree on
            # which fighter is "home", and this exact card may already exist from
            # tonight's Bovada UFC scrape.
            row = con.execute(
                "SELECT id, start_time FROM prop_games WHERE league='ufc' AND date=? "
                "AND ((home=? AND away=?) OR (home=? AND away=?))",
                (gdate, home, away, away, home)).fetchone()
            if row:
                game_id = row["id"]
                if gprops[0]["start_time"] and not row["start_time"]:
                    con.execute("UPDATE prop_games SET start_time=? WHERE id=?",
                                (gprops[0]["start_time"], game_id))
            elif dry_run:
                game_id = None
            else:
                game_id = con.execute(
                    "INSERT INTO prop_games(league,date,home,away,espn_event_id,start_time) VALUES(?,?,?,?,?,?)",
                    ("ufc", gdate, home, away, "", gprops[0]["start_time"])).lastrowid

            print(f"  {away} vs {home}: {len(gprops)} props")

            for p in gprops:
                pl = con.execute("SELECT id FROM players WHERE name=? AND league='ufc'",
                                  (p["player_name"],)).fetchone()
                if pl:
                    player_id = pl["id"]
                elif dry_run:
                    player_id = None
                else:
                    player_id = con.execute(
                        "INSERT INTO players(name, team, league) VALUES(?,?,?)",
                        (p["player_name"], None, "ufc")).lastrowid

                if dry_run:
                    print(f"    DRY-RUN {p['player_name']} {p['side'].upper()} {p['line']} "
                          f"{p['market']} ({p['odds']})")
                    ingested += 1
                    continue

                existing = con.execute(
                    "SELECT id FROM props WHERE game_id=? AND player_id=? AND market=? "
                    "AND line=? AND side=? AND source='underdog'",
                    (game_id, player_id, p["market"], p["line"], p["side"])).fetchone()
                if existing:
                    if p["odds"] is None:
                        con.execute("UPDATE props SET captured_at=? WHERE id=?", (now, existing["id"]))
                    else:
                        con.execute(
                            "UPDATE props SET captured_at=?,odds=?,odds_captured_at=? WHERE id=?",
                            (now, p["odds"], now, existing["id"]))
                elif p["odds"] is not None:
                    con.execute(
                        "INSERT INTO props(game_id,player_id,market,line,side,source,captured_at,odds,odds_captured_at) "
                        "VALUES(?,?,?,?,?,?,?,?,?)",
                        (game_id, player_id, p["market"], p["line"], p["side"], "underdog",
                         now, p["odds"], now))
                else:
                    con.execute(
                        "INSERT INTO props(game_id,player_id,market,line,side,source,captured_at) "
                        "VALUES(?,?,?,?,?,?,?)",
                        (game_id, player_id, p["market"], p["line"], p["side"], "underdog", now))
                ingested += 1

        if not dry_run:
            con.commit()
    finally:
        con.close()
    return ingested


def main():
    if len(sys.argv) < 2 or sys.argv[1] != "ufc":
        print(__doc__)
        sys.exit(1)
    dry_run = "--dry-run" in sys.argv

    print("Fetching Underdog over_under_lines...")
    data = fetch()
    props = parse_ufc(data)
    print(f"  {len(props)} UFC props parsed (scheduled fights, balanced-line tier only)")
    if not props:
        return
    n = direct_ingest(props, dry_run)
    print(f"{'Would ingest' if dry_run else 'Ingested'}: {n} props")


if __name__ == "__main__":
    main()
