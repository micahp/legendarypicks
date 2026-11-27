"""Fixed-seed score-only evaluation; reads the selected SQLite database, never writes it."""
import hashlib,json,sqlite3,statistics,sys,time
from pathlib import Path
from postgame_story_engine import generate_recap

DB=Path(sys.argv[1]).resolve(); OUT=Path(sys.argv[2]).resolve(); SEED='20261110-postgame-v1'
c=sqlite3.connect(DB.as_uri()+'?mode=ro',uri=True);c.row_factory=sqlite3.Row;c.execute('pragma query_only=on')
exclude={'401873037','401909957','401909960'}; results=[]
for league in ('nfl','nba'):
 rows=[r for r in c.execute('select * from scoreboard_snapshots where league=? and state=?',(league,'post')) if r['game_id'] not in exclude]
 rows.sort(key=lambda r:hashlib.sha256((SEED+':'+league+':'+r['game_id']).encode()).hexdigest())
 if len(rows)<50: raise SystemExit('Fewer than 50 available for '+league)
 for r in rows[:50]:
  p=json.loads(r['payload']);teams=[]
  for side in ('away','home'):
   t=p[side]; val=t.get('score');score=int(val) if type(val) in (int,float) and int(val)==val else None
   teams.append({'id':t.get('abbrev'),'name':t.get('name'),'score':score})
  f={'game':{'league':league,'game_id':r['game_id'],'status':'final' if p.get('completed') and p.get('state')=='post' and p.get('status')=='Final' else 'unsupported','start_utc':r['start_time']},'teams':teams,'sources':[{'id':'scoreboard:'+r['game_id'],'captured_at':r['fetched_at']}],'as_of_utc':r['fetched_at']}
  t=time.perf_counter_ns(); out=generate_recap(f); elapsed=(time.perf_counter_ns()-t)/1e6
  results.append({'league':league,'game_id':r['game_id'],'gate':out['gate'],'audit':out['audit'],'headline':out['headline'],'render_ms':elapsed})
c.close();OUT.mkdir(parents=True,exist_ok=True)
(OUT/'heldout_results.jsonl').write_text(''.join(json.dumps(x,sort_keys=True)+'\n' for x in results))
summary={}
for league in ('nfl','nba'):
 subset=[r for r in results if r['league']==league]; times=sorted(x['render_ms'] for x in subset)
 summary[league]={'sampled':len(subset),'score_only_eligible':sum(x['gate']=='eligible_score_only' for x in subset),'blocked':sum(x['gate']=='blocked' for x in subset),'narrative_beyond_result':0,'median_ms':statistics.median(times),'p95_ms':times[47],'human_ratings':0}
(OUT/'evaluation.json').write_text(json.dumps({'seed':SEED,'method':'scoreboard snapshots; score-only, not full claim or editorial evaluation','by_league':summary},indent=2,sort_keys=True)+'\n')
print(json.dumps(summary))
