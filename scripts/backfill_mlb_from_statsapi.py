"""Backfill MLB batting coverage from the MLB Stats API (authoritative, complete).
For every 40-man rostered MLB player not already covered, upsert spine + season hitting row.
Run from backend/: venv/bin/python ../scripts/backfill_mlb_from_statsapi.py"""
import os, sqlite3, re, json, urllib.request, unicodedata
DB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "backend", "data", "picks.db")
SEASON = 2026
def norm(n):
    n=unicodedata.normalize('NFKD',n or '').encode('ascii','ignore').decode().lower()
    n=re.sub(r'[^a-z ]',' ',n); n=re.sub(r'\b(jr|sr|ii|iii|iv|v)\b',' ',n); return re.sub(r'\s+',' ',n).strip()
def get(url):
    return json.load(urllib.request.urlopen(url, timeout=30))
con=sqlite3.connect(DB); con.row_factory=sqlite3.Row
cols={r[1] for r in con.execute("PRAGMA table_info(player_stats)")}
covered=set(norm(x[0]) for x in con.execute("select player_name from player_stats where league='mlb' and stat_type='batting'") if x[0] and not str(x[0]).startswith('mlbam_'))
print("already-covered batters:", len(covered))
teams=get("https://statsapi.mlb.com/api/v1/teams?sportId=1")["teams"]
roster=[]
for t in teams:
    try:
        for e in get(f"https://statsapi.mlb.com/api/v1/teams/{t['id']}/roster?rosterType=40Man").get("roster",[]):
            p=e.get("person",{}); roster.append((p.get("id"), p.get("fullName"), t.get("abbreviation")))
    except Exception as ex: print("roster err", t.get("abbreviation"), str(ex)[:50])
print("40-man rostered players:", len(roster))
ins=0; skipped=0
for mlbam, full, tm in roster:
    if not mlbam or not full: continue
    nn=norm(full)
    if nn in covered: continue
    try:
        d=get(f"https://statsapi.mlb.com/api/v1/people/{mlbam}/stats?stats=season&season={SEASON}&group=hitting")
        splits=d.get("stats",[{}])[0].get("splits",[]) if d.get("stats") else []
        if not splits: skipped+=1; continue
        s=splits[0]["stat"]
        pa=float(s.get("plateAppearances") or 0)
        avg=float(s.get("avg") or 0) if s.get("avg") not in (None,".---") else None
        hr=int(s.get("homeRuns") or 0); games=int(s.get("gamesPlayed") or 0)
        kpct=round(float(s.get("strikeOuts") or 0)/pa*100,1) if pa else None
        bbpct=round(float(s.get("baseOnBalls") or 0)/pa*100,1) if pa else None
    except Exception as ex:
        skipped+=1; continue
    # upsert spine
    row=con.execute("select id from players where mlbam_id=?", (mlbam,)).fetchone()
    if row: pid=row["id"]
    else:
        pid=con.execute("insert into players(name,league,mlbam_id,team,active) values(?,?,?,?,1)",(full,"mlb",mlbam,tm)).lastrowid
    # insert batting row (statcast-only cols left null)
    con.execute(f"insert or ignore into player_stats(player_name,name_norm,league,team,stat_type,season,games,avg,hr,k_pct,bb_pct,source,player_id) values(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (full,nn,"mlb",tm,"batting",SEASON,games,avg,hr,kpct,bbpct,"mlb_statsapi",pid))
    ins+=1
con.commit()
print(f"inserted batting rows: {ins} | skipped (no {SEASON} hitting): {skipped}")
