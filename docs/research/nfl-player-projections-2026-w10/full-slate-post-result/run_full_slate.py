"""Week 10 2026, full slate, for comparison with the SLC family run.

Read-only on prod. The job skips games that already have a final score, so this
hides week 10 scores in a TEMP view (temp objects shadow main tables) and runs
the job's own projection code. Nothing is written to the database.
"""
import json, os, sqlite3, sys
sys.path.insert(0, "/root/legendarypicks/backend")
os.chdir("/root/legendarypicks/backend")
import nfl_player_projections_job as job

DB = "/root/legendarypicks/backend/data/picks.db"
OUT = sys.argv[1]
con = sqlite3.connect("file:%s?mode=ro" % DB, uri=True)
cols = [r[1] for r in con.execute("PRAGMA main.table_info(nfl_schedule)")]
exprs = []
for c in cols:
    if c in ("home_score", "away_score"):
        exprs.append("CASE WHEN season=2026 AND week=10 THEN NULL ELSE %s END AS %s" % (c, c))
    else:
        exprs.append(c)
con.execute("CREATE TEMP VIEW nfl_schedule AS SELECT %s FROM main.nfl_schedule" % ", ".join(exprs))
entries, summary = job.project_week(con, 2026, 10, n_sims=1000)
rows = []
for e in entries:
    base = e["scenarios"]["base"]
    rows.append({"game_id": e["game_id"], "player_id": e["player_id"], "team": e["team"],
                 "pos": e["pos"], "stats": {k: list(v) for k, v in base.items()}})
cal = con.execute("SELECT a, b, n_items FROM main.nfl_prop_calibration WHERE season=2026 AND week=10 AND model_version='v2-platt'").fetchone()
json.dump({"season": 2026, "week": 10, "summary": summary, "n_sims": 1000,
           "calibration_map_week10": {"a": cal[0], "b": cal[1], "n_items": cal[2]} if cal else None,
           "rows": rows}, open(OUT, "w"), indent=1, default=str)
print(summary, "rows", len(rows))
