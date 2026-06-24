#!/usr/bin/env python3
"""One-shot backfill: resolve mlbam_id for MLB players that lack it but appear in props.

These players came in from the Bovada scraper as name-only rows; without an mlbam_id the
settlement pipeline can't grade them against the MLB Stats API boxscore (keyed by mlbam_id)
→ they void forever. We resolve each by matching normalized name within the player's team
roster (MLB Stats API), then UPDATE only the matched rows.

Reversible: only populates a nullable column. Idempotent: skips players already resolved.

Run from backend/:  venv/bin/python ../scripts/backfill_mlbam_id.py [--dry-run]
"""
import os, re, sqlite3, json, unicodedata, urllib.request, time, sys

DB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "backend", "data", "picks.db")
MLB_TEAMS = "https://statsapi.mlb.com/api/v1/teams?sportId=1&season=2026"
MLB_ROSTER = "https://statsapi.mlb.com/api/v1/teams/{teamId}/roster?rosterType=40Man"
HDR = {"User-Agent": "Mozilla/5.0"}

# Our abbrev → MLB abbrev where they differ (Washington, Athletics)
_ABBR_ALIASES = {"WAS": "WSH", "OAK": "ATH", "ARI": "AZ"}


def _norm(name: str) -> str:
    if not name:
        return ""
    n = name.lower().strip()
    n = re.sub(r"\b(jr\.?|sr\.?|ii|iii|iv|v)\b", "", n)          # drop suffixes
    n = unicodedata.normalize("NFKD", n).encode("ascii", "ignore").decode("ascii")
    n = re.sub(r"[^a-z ]", "", n)                                  # strip punctuation
    n = re.sub(r"\s+", " ", n).strip()
    return n


def _get(url, timeout=15):
    req = urllib.request.Request(url, headers=HDR)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())


def main(dry_run=False):
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row

    # 1. Build MLB abbrev → teamId
    teams = {}
    for t in _get(MLB_TEAMS).get("teams", []):
        ab = (t.get("abbreviation") or "").upper()
        if ab:
            teams[ab] = t["id"]
    print(f"Loaded {len(teams)} MLB teams")

    # 2. Find MLB players that lack mlbam_id but are referenced by props
    targets = con.execute("""
        SELECT DISTINCT pl.id, pl.name, pl.team
        FROM players pl
        WHERE pl.league='mlb'
          AND (pl.mlbam_id IS NULL OR pl.mlbam_id=0)
          AND pl.id IN (SELECT player_id FROM props)
    """).fetchall()
    print(f"MLB players needing mlbam_id: {len(targets)}")

    # 3. Cache rosters per team abbrev (only fetch teams we need)
    roster_cache = {}  # our_abbr -> {_norm(name): mlbam_id}
    needed_abbrs = {r["team"] for r in targets if r["team"]}
    print(f"Teams to fetch rosters for: {len(needed_abbrs)}")

    resolved = 0
    unmatched = []
    updates = []

    for abbr in needed_abbrs:
        mlb_abbr = _ABBR_ALIASES.get(abbr, abbr)
        team_id = teams.get(mlb_abbr)
        if not team_id:
            # try our own abbr directly
            team_id = teams.get(abbr)
        if not team_id:
            print(f"  {abbr}: no teamId (mlb_abbr={mlb_abbr}) — skip")
            continue
        try:
            roster = _get(MLB_ROSTER.format(teamId=team_id))
        except Exception as e:
            print(f"  {abbr}: roster fetch failed ({str(e)[:60]})")
            continue
        nm = {}
        for entry in roster.get("roster", []):
            person = entry.get("person", {})
            full = person.get("fullName")
            mid = person.get("id")
            if full and mid:
                nm[_norm(full)] = mid
        roster_cache[abbr] = nm
        time.sleep(0.2)  # polite

    # 4. Match each target player by normalized name within their team roster
    for r in targets:
        name_n = _norm(r["name"])
        abbr = r["team"]
        if not name_n or not abbr:
            unmatched.append((r["name"], abbr, "no name/team"))
            continue
        nm = roster_cache.get(abbr)
        if nm is None:
            unmatched.append((r["name"], abbr, "no roster"))
            continue
        mid = nm.get(name_n)
        if not mid:
            # try last-name-only fallback
            last = name_n.split()[-1] if name_n.split() else ""
            cands = [v for k, v in nm.items() if k.endswith(" " + last) or k.split()[-1] == last]
            if len(cands) == 1:
                mid = cands[0]
        if mid:
            updates.append((mid, r["id"]))
            resolved += 1
        else:
            unmatched.append((r["name"], abbr, "not on 40-man"))

    print(f"\nResolved: {resolved}/{len(targets)}")
    if unmatched:
        print(f"Unmatched: {len(unmatched)} (sample):")
        for name, abbr, why in unmatched[:10]:
            print(f"  - {name} [{abbr}] — {why}")

    if dry_run:
        print("\n[DRY RUN] no updates written.")
        return

    if updates:
        con.executemany("UPDATE players SET mlbam_id=? WHERE id=?", updates)
        con.commit()
        print(f"\nWrote mlbam_id for {len(updates)} players.")


if __name__ == "__main__":
    main(dry_run="--dry-run" in sys.argv)
