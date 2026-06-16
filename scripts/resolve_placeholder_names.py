"""Resolve placeholder mlbam_XXXXX names via the MLB Stats API (current, authoritative).
Run from backend/: venv/bin/python ../scripts/resolve_placeholder_names.py"""
import os, sqlite3, re, json, urllib.request
DB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "backend", "data", "picks.db")
con = sqlite3.connect(DB); con.row_factory = sqlite3.Row
ph = con.execute("SELECT id, mlbam_id FROM players WHERE league='mlb' AND name LIKE 'mlbam_%' AND mlbam_id IS NOT NULL").fetchall()
ids = [r["mlbam_id"] for r in ph]
print(f"placeholder players to resolve: {len(ids)}")
if not ids: raise SystemExit
name = {}
for i in range(0, len(ids), 100):
    batch = ids[i:i+100]
    url = "https://statsapi.mlb.com/api/v1/people?personIds=" + ",".join(str(x) for x in batch)
    try:
        d = json.load(urllib.request.urlopen(url, timeout=30))
        for p in d.get("people", []):
            if p.get("id") and p.get("fullName"): name[int(p["id"])] = p["fullName"]
    except Exception as e:
        print("  batch err:", str(e)[:80])
print(f"MLB Stats API resolved: {len(name)} / {len(ids)}")
fixed = 0
for r in ph:
    nm = name.get(r["mlbam_id"])
    if not nm: continue
    nn = re.sub(r'[^a-z ]',' ', nm.lower()); nn = re.sub(r'\s+',' ',nn).strip()
    con.execute("UPDATE OR IGNORE players SET name=? WHERE id=?", (nm, r["id"]))
    con.execute("UPDATE OR IGNORE player_stats SET player_name=?, name_norm=? WHERE player_id=?", (nm, nn, r["id"]))
    fixed += 1
con.commit()
print(f"updated {fixed} players + stat rows")
print("remaining placeholder stat rows:", con.execute("SELECT count(*) FROM player_stats WHERE league='mlb' AND player_name LIKE 'mlbam_%'").fetchone()[0])
