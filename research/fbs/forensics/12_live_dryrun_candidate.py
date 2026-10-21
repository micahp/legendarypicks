"""Step 12: the candidate's run() on a saved ESPN slate snapshot, previews only, scratch database.

usage: 12_live_dryrun_candidate.py SLATE_CSV OUT_DB
Locks stay blocked by the gate: no parity certificate exists beside OUT_DB, so nothing is locked.
"""
import datetime as dt
import json
import sys

import pandas as pd

import common

slate_csv, out_db = sys.argv[1], sys.argv[2]
sys.path.insert(0, common.CANDIDATE_BACKEND)
import fbs_model_runner as runner  # noqa: E402
import fbs_model_store as store  # noqa: E402

live = pd.read_csv(slate_csv, dtype={"game_id": str, "home": str, "away": str})
slate = pd.DataFrame({"game_id": live.game_id, "kickoff_utc": pd.to_datetime(live.date, utc=True),
                      "home_team_id": live.home, "away_team_id": live.away,
                      "home_team": live.home_name, "away_team": live.away_name,
                      "neutral_site": live.neutral.fillna(False).astype(bool), "week": live.week,
                      "completed": live.completed.astype(bool), "home_score": None, "away_score": None})
runner.fetch_slate = lambda days=10, now=None: slate
now = dt.datetime.now(dt.timezone.utc)
result = runner.run(days=10, db_path=out_db, now=now)
print("RESULT", json.dumps(result, default=str))
con = store.open_db(out_db, readonly=True)
payload = store.export_payload(con, 2026)
con.close()
ok = sum(1 for g in payload["games"] if pd.Timestamp(g["kickoff_utc"]) == pd.Timestamp(
    live.set_index("game_id").at[g["game_id"], "date"]))
print("games=%d kickoffs matching the slate=%d models_all_three=%d parity_certified=%s" % (
    len(payload["games"]), ok, sum(1 for g in payload["games"] if len(g["models"]) == 3),
    payload["meta"].get("parity_certified")))
