import argparse,glob,json,statistics,math,collections,hashlib
from pathlib import Path
parser=argparse.ArgumentParser(description="Summarize saved WAS-NYG model-family batches")
parser.add_argument("--run-root",type=Path,required=True)
parser.add_argument("--out",type=Path)
args=parser.parse_args()
base=args.run_root
models=("v1","v1.5","v1.6","v2"); all_boxes={}; invalid={}
for model in models:
 boxes={}; skips=collections.Counter()
 for path in sorted((base/"runs"/model).glob("*.boxscores.jsonl")):
  for line in path.open():
   row=json.loads(line)
   if row.get("type") != "boxscore" and not ("seed" in row and "teams" in row):continue
   if row.get("status") != "valid_complete":skips[str(row.get("status"))]+=1;continue
   seed=row["seed"]
   if seed in boxes:raise RuntimeError("duplicate seed: "+str(seed))
   boxes[seed]=row
 all_boxes[model]=boxes;invalid[model]=dict(skips)
common=set.intersection(*(set(all_boxes[x]) for x in models))

def q(vals,p):
 vals=sorted(vals); x=(len(vals)-1)*p; i=int(x); j=min(i+1,len(vals)-1);return vals[i]+(vals[j]-vals[i])*(x-i)

def summary(boxes):
 n=len(boxes); wins=collections.Counter();scores={"WAS":[],"NYG":[]};stats={x:collections.Counter() for x in scores};drives={x:collections.Counter() for x in scores}; bad=[]
 for seed,box in boxes.items():
  tm={r["team"]:r["stats"] for r in box["teams"]}
  for team in scores:
   s=tm[team];scores[team].append(s["points"])
   for key in ("drives","plays","sacks_taken","turnovers","interceptions","fumbles_lost","punts","touchdowns","field_goal_attempts","field_goals_made","turnovers_on_downs","rush_attempts","rushing_yards","pass_attempts","passing_yards","completions","third_down_attempts","third_down_conversions","fourth_down_attempts","fourth_down_conversions"):
    if s.get(key) is not None:stats[team][key]+=s[key]
  w,h=tm["WAS"]["points"],tm["NYG"]["points"]
  wins["WAS" if w>h else "NYG" if h>w else "tie"]+=1
  for d in (box.get("quarter_by_quarter") or {}).get("drive_summaries",[]):
   if d.get("offense_team") in drives:drives[d["offense_team"]][str(d.get("terminal"))]+=1
  rec=box.get("reconciliation") or {}
  if rec.get("status") not in (None,"passed","ok"):bad.append({"seed":seed,"status":rec.get("status")})
 out={"games":n,"wins":dict(wins),"percent":{"WAS":100*wins["WAS"]/n,"NYG":100*wins["NYG"]/n,"tie":100*wins["tie"]/n},"teams":{},"reconciliation_status_other":bad[:5]}
 for team in scores:
  s=stats[team];out["teams"][team]={"score_mean":statistics.mean(scores[team]),"score_median":statistics.median(scores[team]),"score_p10":q(scores[team],.1),"score_p90":q(scores[team],.9),"per_game":{k:v/n for k,v in s.items()},"yards_per_rush":s["rushing_yards"]/s["rush_attempts"] if s["rush_attempts"] else None,"yards_per_pass_attempt":s["passing_yards"]/s["pass_attempts"] if s["pass_attempts"] else None,"completion_pct":100*s["completions"]/s["pass_attempts"] if s["pass_attempts"] else None,"drive_ends_per_game":{k:v/n for k,v in drives[team].items()}}
 return out
out={"model_samples":{m:summary(all_boxes[m]) for m in models},"common_seeds":{"n":len(common),"min":min(common),"max":max(common),"models":{m:summary({s:all_boxes[m][s] for s in sorted(common)}) for m in models}},"invalid_boxes":invalid}
# Down-distance opportunities from V1.6 ordered plays only; all real scrimmage plays are retained.
down={t:collections.Counter() for t in ("WAS","NYG")}; scrimmage={"run","pass_complete","pass_incomplete","sack","sack_fumble_lost","interception","fumble_lost"};n=0
with (base/"runs/v1.6/simulation.plays.jsonl").open() as f:
 for line in f:
  data=json.loads(line)
  if not data.get("valid_full_game") or data.get("seed") not in all_boxes["v1.6"]:continue
  n+=1;record=data["record"];teams={"A":record["teams"]["home"],"B":record["teams"]["away"]}
  for drive in record.get("drives",[]):
   for play in drive.get("plays",[]):
    b=play["state_before"];event=play["event_type"];o=play["outcome"];t=teams.get(b.get("offense_team"));d=b.get("down");dist=b.get("yards_to_go")
    if t not in down or d not in (1,2,3,4) or dist is None:continue
    c=down[t]
    if d==3 and 3<=dist<=5:c["third_3_5_opportunities"]+=1
    if d==4 and dist<=5:c["fourth_le_5_opportunities"]+=1
    if event in scrimmage:
     c[f"down_{d}_attempts"]+=1
     after=play.get("state_after") or {}
     success=bool(o.get("touchdown") or o.get("first_down") or (after.get("offense_team")==b.get("offense_team") and after.get("down")==1 and not after.get("end_of_drive")))
     if success:c[f"down_{d}_conversions"]+=1
out["v1.6_ordered_plays"]={"valid_games_read":n,"by_team":{t:{**dict(c),"third_3_5_per_game":c["third_3_5_opportunities"]/n,"fourth_le_5_per_game":c["fourth_le_5_opportunities"]/n,"third_conversion_pct":100*c["down_3_conversions"]/c["down_3_attempts"] if c["down_3_attempts"] else None,"fourth_conversion_pct":100*c["down_4_conversions"]/c["down_4_attempts"] if c["down_4_attempts"] else None} for t,c in down.items()}}
out["inputs"]={"game_id":"2026_10_WAS_NYG","snapshot_file_sha256":hashlib.sha256((base/"snapshot.json").read_bytes()).hexdigest(),"seed_root":20261112,"source_cutoff_utc":"2026-11-13T00:10:12Z","kickoff_utc":"2026-11-13T01:15:00Z"}
rendered=json.dumps(out,indent=2,sort_keys=True)+"\n"
if args.out:
 with args.out.open("x") as f:f.write(rendered)
else:print(rendered,end="")
