#!/usr/bin/env python3
"""
ingest_nhl.py — pull full NHL rosters + stats from api-web.nhle.com, persist to player_stats.

Roster source: api-web.nhle.com/v1/roster/{TEAM}/current (all 32 teams)
Stats source: api-web.nhle.com/v1/player/{id}/landing
Target: >=95% of rostered NHL players resolve to a stats row.

Usage: python3 ingest_nhl.py
"""
import sys, os, sqlite3, json, urllib.request, time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from league_stats import (
    LeagueStatContractError,
    load_unique_source_id_map,
    publish_player_stats,
    queue_unresolved_player,
)
from season_keys import normalize_season

DB = os.environ.get("LP_DB_PATH") or os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "picks.db")
HDR = {"User-Agent": "Mozilla/5.0"}

# All 32 NHL team abbreviations (nhle.com format — 3 letters for most, some differ from ESPN)
NHL_TEAMS = [
    "CAR","BUF","TBL","MTL","BOS","OTT","PIT","PHI","WSH","DET","CBJ","NYI","NJD","FLA","TOR","NYR",
    "VGK","DAL","MIN","EDM","UTA","ANA","LAK","STL","NSH","SJS","WPG","SEA","CGY","CHI","VAN","COL",
]


def fetch_roster(team: str) -> list:
    """Pull current roster from nhle.com. Returns list of {name, id, position, team}."""
    url = f"https://api-web.nhle.com/v1/roster/{team}/current"
    req = urllib.request.Request(url, headers=HDR)
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            data = json.loads(r.read().decode())
    except Exception as e:
        print(f"    {team}: roster FAIL ({e})")
        return []

    players = []
    for pos_group in ["forwards", "defensemen", "goalies"]:
        for p in data.get(pos_group, []):
            pid = p.get("id")
            fn = p.get("firstName", {}).get("default", "")
            ln = p.get("lastName", {}).get("default", "")
            name = f"{fn} {ln}".strip()
            pos = p.get("positionCode", "?")
            if pid and name:
                players.append({"name": name, "id": pid, "position": pos, "team": team})
    return players


def fetch_stats(nhl_id: int) -> dict:
    """Pull season stats from nhle.com landing endpoint."""
    url = f"https://api-web.nhle.com/v1/player/{nhl_id}/landing"
    req = urllib.request.Request(url, headers=HDR)
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            data = json.loads(r.read().decode())
    except Exception:
        return None
    st = data.get("seasonTotals", [])
    if not st:
        return None
    latest = st[-1]
    first = data.get("firstName", {})
    last = data.get("lastName", {})
    return {
        "name": f"{first.get('default','')} {last.get('default','')}".strip(),
        "position": data.get("position", "?"),
        "team": data.get("currentTeamAbbrev", "?"),
        "season": latest.get("season", ""),
        "games": int(latest.get("gamesPlayed", 0)),
        "goals": int(latest.get("goals", 0)),
        "assists": int(latest.get("assists", 0)),
        "points": int(latest.get("points", 0)),
        "shots": int(latest.get("shots", 0)),
        "shooting_pct": round(float(latest.get("shootingPctg", 0)) * 100, 1),
        "plus_minus": int(latest.get("plusMinus", 0)),
        "pim": int(latest.get("pim", 0)),
        "ppg": int(latest.get("powerPlayGoals", 0)),
        "ppp": int(latest.get("powerPlayPoints", 0)),
        "shg": int(latest.get("shorthandedGoals", 0)),
        "toi": str(latest.get("avgToi", "")),
        "faceoff_pct": round(float(latest.get("faceoffWinningPctg", 0)) * 100, 1),
    }


def ingest():
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row

    # Duplicate native IDs fail closed instead of silently choosing one owner.
    nhl_id_to_player, ambiguous_nhl_ids = load_unique_source_id_map(
        con, league="nhl", id_column="nhl_id"
    )
    print(f"Loaded {len(nhl_id_to_player)} unique nhl_id→player_id mappings")
    if ambiguous_nhl_ids:
        print(
            f"WARNING: {len(ambiguous_nhl_ids)} duplicate NHL IDs "
            "will be queued"
        )

    total_players = 0
    per_team = {}

    for team in NHL_TEAMS:
        print(f"{team}:", end=" ", flush=True)
        roster = fetch_roster(team)
        if not roster:
            per_team[team] = (0, 0, 0)
            continue

        size = len(roster)
        stats_count = 0
        for p in roster:
            total_players += 1
            source_key = str(p["id"])
            player_id = nhl_id_to_player.get(source_key)
            if player_id is None:
                queue_unresolved_player(
                    con,
                    source="nhle.com",
                    raw_name=p["name"],
                    league="nhl",
                    team=p["team"],
                    source_player_key=source_key,
                    reason=(
                        "duplicate_spine_nhl_id"
                        if source_key in ambiguous_nhl_ids
                        else "nhl_id_not_in_spine"
                    ),
                )
                continue

            s = fetch_stats(p["id"])
            if s:
                try:
                    publish_player_stats(
                        con,
                        player_id=player_id,
                        league="nhl",
                        # ESPN's key, not nhle's. `league_stats` resolves the
                        # current season with MAX(season), and 20242025 sorts
                        # above 2026 — mixing the two vocabularies in this
                        # column serves a two-year-old season as the live one.
                        season=normalize_season("nhle.com", "nhl", s["season"]),
                        stat_type="season",
                        source="nhle.com",
                        games=s["games"],
                        values={
                            "nhl_position": s["position"],
                            "nhl_team": s["team"],
                            "goals": s["goals"],
                            "assists": s["assists"],
                            "points_nhl": s["points"],
                            "shots": s["shots"],
                            "shooting_pct": s["shooting_pct"],
                            "plus_minus": s["plus_minus"],
                            "pim": s["pim"],
                            "ppg": s["ppg"],
                            "ppp": s["ppp"],
                            "shg": s["shg"],
                            "toi": s["toi"],
                            "faceoff_pct": s["faceoff_pct"],
                        },
                    )
                    stats_count += 1
                except (LeagueStatContractError, sqlite3.Error) as exc:
                    print(
                        f"    {p['name']}: publish FAIL ({exc})",
                        file=sys.stderr,
                    )
                time.sleep(0.15)  # gentle rate limit

        pct = round(stats_count / size * 100) if size > 0 else 0
        flag = "✅" if pct >= 95 else ("⚠️" if pct < 50 else "  ")
        print(f"{flag} {stats_count}/{size} ({pct}%)")
        per_team[team] = (stats_count, size, pct)

    con.commit()
    con.close()

    total_resolved = sum(c for c, _, _ in per_team.values())
    total_roster = sum(s for _, s, _ in per_team.values())
    print(f"\nTotal: {total_resolved}/{total_roster} ({round(total_resolved/max(total_roster,1)*100)}%)")


if __name__ == "__main__":
    ingest()
