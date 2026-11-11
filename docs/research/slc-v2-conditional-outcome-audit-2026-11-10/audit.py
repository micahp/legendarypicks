import collections, hashlib, json, math, os, sqlite3, sys
from bisect import bisect_left
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / 'scripts' / 'nfl_sequence'))
import e0_single_play as e0
import e1_drive as e1
import team_tendency as tt
import team_season_adapt as tsa
import season_layers as sl

DB='/root/legendarypicks/backend/data/picks.dev.db'
PBP_RELEASE='/root/lp-snapshots/nfl-backfill-2026-11-03/raw/pbp/play_by_play_{season}.parquet'
OUT='/tmp/slc-conditional-offline.json'
INTENTS=('run','dropback')
EVENT_YARDS={'run','pass_complete','sack'}
K=25.0

def percentile(xs,p):
    if not xs:return None
    a=sorted(xs); x=(len(a)-1)*p; lo=int(x); hi=min(len(a)-1,lo+1)
    return a[lo]+(a[hi]-a[lo])*(x-lo)

def json_safe(value):
    if isinstance(value, dict):
        return {str(k):json_safe(v) for k,v in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_safe(v) for v in value]
    return value

def crps_weighted(values,weights,y):
    pairs=sorted((float(v),float(w)) for v,w in zip(values,weights) if w>0)
    sw=sum(w for _,w in pairs)
    if not pairs or sw<=0:return None
    pairs=[(v,w/sw) for v,w in pairs]
    term1=sum(w*abs(v-y) for v,w in pairs)
    cumw=cumx=pairhalf=0.0
    for v,w in pairs:
        pairhalf+=w*(v*cumw-cumx)
        cumw+=w;cumx+=w*v
    return term1-pairhalf

def mixture_crps(league,team,y):
    # Fixed K=25 pseudo-plays, matching the SLC offense/defense team tendency shrinkage strength.
    n=len(team); wt=n/(n+K) if n else 0.0
    vals=list(league)+list(team)
    weights=[(1-wt)/len(league)]*len(league)+([wt/n]*n if n else [])
    return crps_weighted(vals,weights,y)

def make_yard_distribution(league, team=()):
    nl=len(league); nt=len(team)
    if nl==0:return None
    wt=nt/(nt+K) if nt else 0.0
    pairs=[(float(v),(1-wt)/nl) for v in league]
    if nt:pairs.extend((float(v),wt/nt) for v in team)
    pairs.sort()
    xs=[]; pw=[0.0]; px=[0.0]; pairhalf=0.0; cw=cx=0.0
    for x,w in pairs:
        xs.append(x); pw.append(pw[-1]+w); px.append(px[-1]+w*x)
        pairhalf+=w*(x*cw-cx); cw+=w; cx+=w*x
    return {'xs':xs,'pw':pw,'px':px,'mean':cx,'pairhalf':pairhalf}

def yard_crps(dist,y):
    xs,pw,px=dist['xs'],dist['pw'],dist['px']; i=bisect_left(xs,float(y))
    term=float(y)*pw[i]-px[i]+(px[-1]-px[i])-float(y)*(pw[-1]-pw[i])
    return term-dist['pairhalf']

def mix_mean(league,team):
    n=len(team); wt=n/(n+K) if n else 0.0
    return (1-wt)*sum(league)/len(league)+wt*(sum(team)/n if n else sum(league)/len(league))

def new_sum():return {'n':0,'actual_sum':0.0,'pred_sum':0.0,'crps_sum':0.0,'abs_error_sum':0.0}
def acc_y(d,y,pred,crps):
    d['n']+=1;d['actual_sum']+=y;d['pred_sum']+=pred;d['crps_sum']+=crps;d['abs_error_sum']+=abs(pred-y)

def metric_y(d):
    n=d['n']
    return {'n':n,'mean_actual_yards':d['actual_sum']/n if n else None,'mean_predicted_yards':d['pred_sum']/n if n else None,
            'yards_per_play_bias':(d['pred_sum']-d['actual_sum'])/n if n else None,'mae_of_conditional_mean':d['abs_error_sum']/n if n else None,
            'mean_crps':d['crps_sum']/n if n else None}

def new_prob():return {'n':0,'logloss':0.0,'brier':0.0,'actual':0,'pred':0.0}
def acc_bin(d,y,p):
    p=min(max(float(p),1e-12),1-1e-12); d['n']+=1; d['actual']+=int(y); d['pred']+=p
    d['logloss']-=math.log(p) if y else math.log(1-p); d['brier']+=(p-int(y))**2

def metric_bin(d):
    n=d['n'];return {'n':n,'observed_rate':d['actual']/n if n else None,'mean_predicted_probability':d['pred']/n if n else None,
                      'log_loss':d['logloss']/n if n else None,'brier':d['brier']/n if n else None}

def new_multi():return {'n':0,'logloss':0.0,'brier':0.0}
def acc_multi(d, probs, actual):
    p=max(1e-12,probs.get(actual,0.0));d['n']+=1;d['logloss']-=math.log(p)
    d['brier']+=sum((v-(1.0 if k==actual else 0.0))**2 for k,v in probs.items())
def metric_multi(d):
    n=d['n'];return {'n':n,'log_loss':d['logloss']/n if n else None,'multiclass_brier':d['brier']/n if n else None}

def classify_test_rows(rows):
    bygame=collections.defaultdict(list)
    for r in rows:bygame[r['game_id']].append(r)
    out=collections.defaultdict(list); excluded=collections.Counter()
    for gid,plays in bygame.items():
        for i,r in enumerate(plays):
            if r.get('qtr') is None or int(r['qtr'])>4:excluded['overtime']+=1;continue
            nxt=plays[i+1] if i+1<len(plays) else None
            why=collections.Counter(); classified=e1.classify(r,nxt,why,include_qb_scrambles=False);excluded.update(why)
            if classified is None:continue
            ev,_,_=classified
            out[gid].append((r,ev))
    return out,excluded

def row_intent(ev,row):
    if ev in e1.KICK_EVENTS:return 'kick'
    return 'run' if row['play_type']=='run' else 'dropback'

def conditional_probs(samples,intent,offense,defense,cell,table):
    c=collections.Counter(ev for ev,row,_,_ in samples if row_intent(ev,row)==intent)
    if sum(c.values())<10:return None,c
    def weighted(use_o,use_d):
        w={ev:float(n) for ev,n in c.items()}
        for ev in w:
            if use_o:w[ev]*=table.ratio('offense',offense,cell,ev)
            if use_d:w[ev]*=table.ratio('defense',defense,cell,ev)
        s=sum(w.values())
        if s<=0:return {ev:n/sum(c.values()) for ev,n in c.items()}
        return {ev:v/s for ev,v in w.items()}
    return {'league':{ev:n/sum(c.values()) for ev,n in c.items()},
            'offense_only':weighted(True,False),'defense_only':weighted(False,True),
            'matchup':weighted(True,True)},c

def team_strengths(db,year):
    con=sqlite3.connect(f'file:{db}?mode=ro',uri=True)
    rows=con.execute("SELECT posteam,defteam,epa FROM nfl_pbp WHERE season>=2022 AND season<? AND week<=18 AND qtr BETWEEN 1 AND 4 AND play_type IN ('pass','run') AND down BETWEEN 1 AND 4 AND penalty IS NOT 1 AND posteam IS NOT NULL AND defteam IS NOT NULL AND epa IS NOT NULL",(year,)).fetchall();con.close()
    oc=collections.Counter();os=collections.Counter();dc=collections.Counter();ds=collections.Counter()
    for o,d,epa in rows:oc[o]+=1;os[o]+=float(epa);dc[d]+=1;ds[d]+=float(epa)
    off={t:os[t]/oc[t] for t in oc}; deff={t:ds[t]/dc[t] for t in dc}
    # High offensive EPA is strong; low opponent EPA is strong defense.
    rankoff=sorted(off,key=lambda t:off[t]);rankdef=sorted(deff,key=lambda t:deff[t])
    n=len(rankoff); q=max(1,n//4)
    offcat={t:('weak' if i<q else 'strong' if i>=n-q else 'middle') for i,t in enumerate(rankoff)}
    defcat={t:('strong' if i<q else 'weak' if i>=n-q else 'middle') for i,t in enumerate(rankdef)}
    return off,deff,offcat,defcat

def source_fact_map(db, seasons):
    con=sqlite3.connect(f'file:{db}?mode=ro',uri=True)
    lo,hi=min(seasons),max(seasons)
    rows=con.execute("SELECT game_id,play_id,passing_yards,receiving_yards,lateral_receiver_player_id,lateral_receiving_yards,lateral_rusher_player_id,lateral_rushing_yards FROM nfl_pbp WHERE season BETWEEN ? AND ?",(lo,hi)).fetchall();con.close()
    out={}
    for g,p,py,ry,lr,ly,lr2,ly2 in rows:
        lateral=False
        for x in (lr,ly,lr2,ly2):
            if x is None or x=='':continue
            try:
                if math.isnan(float(x)):continue
            except (ValueError,TypeError):pass
            if x!=0:lateral=True
        mismatch=(py is not None and ry is not None and float(py)!=float(ry))
        out[(g,int(float(p)))]=(lateral,mismatch)
    return out

def freeze_base(year):
    rows=e1.load(DB,eligible_before=(year,1))
    pool,excluded,team_pool=e1.build_pools(rows,regulation_only=True,team_before_season=year)
    hist=tt.build_from_team_pool(team_pool,year,cutoff=(year,1))
    facts=source_fact_map(DB,sorted({int(r['season']) for r in rows}))
    filtered={}; yardcounts=collections.Counter(); rawcounts=collections.Counter()
    for cell,samples in pool.items():
        keep=[]
        for ev,row,runoff,spot in samples:
            rawcounts[ev]+=1; lateral,mismatch=facts.get((row['game_id'],int(float(row['play_id']))),(False,False))
            if lateral:yardcounts['lateral_rows_excluded']+=1;continue
            if ev=='pass_complete' and mismatch:yardcounts['mismatched_completion_rows_excluded']+=1;continue
            keep.append((ev,row,runoff,spot))
        if keep:filtered[cell]=keep
    return rows,filtered,hist,excluded,rawcounts,yardcounts

def model_probs_by_action(cell_samples, offense, defense, cell, table, fg_allowed):
    action_counts=collections.Counter()
    for ev,row,_,_ in cell_samples:
        if ev=='field_goal_attempt' and not fg_allowed:continue
        if ev=='punt':action_counts['punt']+=1
        elif ev=='field_goal_attempt':action_counts['field_goal']+=1
        else:action_counts['go']+=1
    z=sum(action_counts.values())
    return ({k:v/z for k,v in action_counts.items()} if z else None),action_counts

def team_action_probs(cell_samples,team,which,base_probs,fg_allowed):
    counts=collections.Counter()
    for ev,row,_,_ in cell_samples:
        if ev=='field_goal_attempt' and not fg_allowed:continue
        if (row['posteam'] if which=='offense' else row['defteam'])!=team:continue
        action='punt' if ev=='punt' else 'field_goal' if ev=='field_goal_attempt' else 'go'
        counts[action]+=1
    n=sum(counts.values()); den=n+K
    keys=('go','punt','field_goal')
    return {k:(counts[k]+K*base_probs.get(k,0.0))/den if den else base_probs.get(k,0.0) for k in keys}

def score_action(metrics,probs,actual):
    for name,p in probs.items():acc_multi(metrics[name],p,actual)

def main():
    result={'database_path':DB,'database_sha256':'1a775208bc6e38763ef59c38a6cc79bda3636007feb8c6dc44f085f668341daa',
            'training_seasons_by_test':{},'evaluations':{},'model_rebuild_check':{},'notes':[]}
    for year in (2025,2026):
        train_rows,pool,hist,excluded,rawcounts,yardcounts=freeze_base(year)
        gcounts=collections.Counter()
        for ckey,ss in pool.items():
            if ckey[0]!=4:continue
            for ev,rr,_,_ in ss:gcounts['punt' if ev=='punt' else 'field_goal' if ev=='field_goal_attempt' else 'go']+=1
        gz=sum(gcounts.values());global_fourth_probs={k:v/gz for k,v in gcounts.items()} if gz else {'go':1.0}
        off_epa,def_epa,offcat,defcat=team_strengths(DB,year)
        con=sqlite3.connect(f'file:{DB}?mode=ro',uri=True,timeout=30)
        test_rows=[dict(zip(e1.COLUMNS,r)) for r in con.execute(f"SELECT {', '.join(e1.COLUMNS)} FROM nfl_pbp WHERE season=? AND week<=18 ORDER BY game_id,play_id",(year,))]
        sched=[dict(zip(('game_id','season','week','gameday','gametime'),r)) for r in con.execute("SELECT game_id,season,week,gameday,gametime FROM nfl_schedule WHERE season=? AND game_type='REG'",(year,))]
        detail={r[0]:(r[1],r[2]) for r in con.execute("SELECT game_id,home_team,away_team FROM nfl_schedule WHERE season=? AND game_type='REG'",(year,))}
        con.close()
        bygame,eval_excluded=classify_test_rows(test_rows)
        all_ids=set(bygame); current_by_game=collections.defaultdict(list)
        for r in test_rows:current_by_game[r['game_id']].append(r)
        schedule_by_id={r['game_id']:r for r in sched}
        targets_by_available=collections.defaultdict(list); avail_manifest={}
        undated=[]
        for gid in all_ids:
            sr=schedule_by_id.get(gid)
            if not sr or not sr.get('gameday') or not sr.get('gametime'):
                undated.append(gid); continue
            kickoff=tsa.kickoff_utc(sr['gameday'],sr['gametime']); cutoff=tsa.cutoff_utc(kickoff)
            ids,und=tsa.available_games(sched,year,cutoff,gid); key=tuple(ids)
            targets_by_available[key].append((gid,cutoff))
            games=collections.Counter()
            for x in ids:
                h,a=detail[x];games[h]+=1;games[a]+=1
            avail_manifest[key]={'cutoff':cutoff.isoformat(),'season_games':len(ids),'team_games':dict(games)}
        probs_metrics={m:new_multi() for m in ('league','offense_only','defense_only','matchup')}
        third=collections.defaultdict(lambda:{m:new_prob() for m in ('league','offense_only','defense_only','matchup')})
        yard=collections.defaultdict(lambda:{m:new_sum() for m in ('slc_league_cell','offense_only_k25','defense_only_k25')})
        fourth=collections.defaultdict(lambda:{m:new_multi() for m in ('slc_situation_cell','offense_only_k25','defense_only_k25','flat_league')})
        fourth_actual=collections.Counter(); fourth_situations=collections.Counter(); third_dist=collections.Counter()
        yard_dist_cache={}
        counts={'test_classifiable_plays':sum(map(len,bygame.values())),'test_penalty_rows_excluded':eval_excluded.get('penalty (not modelled)',0),
                'test_rows':len(test_rows),'target_games':len(all_ids),'games_without_dated_schedule':len(undated),
                'event_rows_supported':0,'event_rows_unsupported':0,'yardage_rows_supported':0,'yardage_rows_unsupported':0,
                'fourth_rows_supported':0,'fourth_rows_unsupported':0,'third_rows_supported':0,'third_rows_unsupported':0}
        hash_targets={}
        for avail_ids,target_list in targets_by_available.items():
            current=[r for gid in avail_ids for r in current_by_game.get(gid,())]
            team_games=avail_manifest[avail_ids]['team_games']
            adapted,diag=tsa.adapt(hist,current,n0=4.0,team_games=team_games) if current else (hist,{})
            th=adapted.manifest['sha256']
            for gid,_ in target_list:hash_targets[gid]=th
            for gid,cutoff in target_list:
                rows_by_game=bygame.get(gid,())
                for row,ev in rows_by_game:
                    cell=e0.pool_key(int(row['down']),row['ydstogo'],row['yardline_100'])
                    samples=pool.get(cell,[])
                    if not samples:continue
                    intent=row_intent(ev,row)
                    probs,icount=conditional_probs(samples,intent,row['posteam'],row['defteam'],cell,adapted)
                    if probs is None:
                        counts['event_rows_unsupported']+=1
                    else:
                        counts['event_rows_supported']+=1;actual=ev
                        acc_multi(probs_metrics['league'],probs['league'],actual)
                        acc_multi(probs_metrics['offense_only'],probs['offense_only'],actual)
                        acc_multi(probs_metrics['defense_only'],probs['defense_only'],actual)
                        acc_multi(probs_metrics['matchup'],probs['matchup'],actual)
                        # Third down line-to-gain probability conditional on the observed run/pass intent.
                        if int(row['down'])==3 and intent in ('run','dropback'):
                            togo=int(row['ydstogo']); dkey=e0.pool_key(3,togo,row['yardline_100'])[1]
                            third_dist[dkey]+=1
                            pconv={m:0.0 for m in probs}
                            for cls,p_ev in probs['league'].items():
                                pass
                            # Per-arm conversion probability; the conditional yardage within each class remains the historical cell.
                            for m in probs:
                                for cls,p_ev in probs[m].items():
                                    if cls not in ('run','pass_complete'):continue
                                    vals=[s[1]['yards_gained'] for s in samples if s[0]==cls and row_intent(s[0],s[1])==intent and s[1].get('yards_gained') is not None]
                                    if vals:
                                        successes=sum(1 for s in samples if s[0]==cls and row_intent(s[0],s[1])==intent and s[1].get('yards_gained') is not None and (int(s[1]['yards_gained'])>=togo or s[1].get('touchdown')==1))
                                        pconv[m]+=p_ev*successes/len(vals)
                            actual_conv=int(ev in ('run','pass_complete') and row.get('yards_gained') is not None and (int(row['yards_gained'])>=togo or row.get('touchdown')==1))
                            for m in probs:acc_bin(third[dkey][m],actual_conv,pconv[m])
                            counts['third_rows_supported']+=1
                    if ev in EVENT_YARDS and row.get('yards_gained') is not None:
                        cache_key=(cell,ev,'league')
                        if cache_key not in yard_dist_cache:
                            lv=[s[1]['yards_gained'] for s in samples if s[0]==ev and s[1].get('yards_gained') is not None]
                            yard_dist_cache[cache_key]=make_yard_distribution(lv)
                        ld=yard_dist_cache[cache_key]
                        if ld is None or len(ld['xs'])<10:
                            counts['yardage_rows_unsupported']+=1;continue
                        y=float(row['yards_gained']); key=f"{year}:{ev}:{offcat.get(row['posteam'],'unknown')}_offense:{defcat.get(row['defteam'],'unknown')}_defense"
                        slcmean=ld['mean'];slcc=yard_crps(ld,y)
                        for name in ('all',key):
                            acc_y(yard[f'{name}:{ev}']['slc_league_cell'],y,slcmean,slcc)
                            for side,team in (('offense',row['posteam']),('defense',row['defteam'])):
                                dkey=(cell,ev,side,team)
                                if dkey not in yard_dist_cache:
                                    tv=[s[1]['yards_gained'] for s in samples if s[0]==ev and s[1].get(side=='offense' and 'posteam' or 'defteam')==team and s[1].get('yards_gained') is not None]
                                    yard_dist_cache[dkey]=make_yard_distribution([s[1]['yards_gained'] for s in samples if s[0]==ev and s[1].get('yards_gained') is not None],tv)
                                td=yard_dist_cache[dkey]
                                pred=td['mean']; crps=yard_crps(td,y)
                                acc_y(yard[f'{name}:{ev}'][f'{side}_only_k25'],y,pred,crps)
                        counts['yardage_rows_supported']+=1
                # independent 4th-down action scoring, with situation-specific league action share.
                # Condition on historical source cell; FG feasibility is exactly the normal 60-yard rule + observed max.
                fgmax=70.0
                # `current_by_game` is built once above. Iterating all season rows
                # here for every target game made this section O(games * plays).
                # Restricting it to the current game makes the full pass O(plays).
                for row in current_by_game.get(gid,()):
                    if row.get('down')!=4 or row.get('qtr') is None or int(row['qtr'])>4:continue
                    if row.get('penalty')==1:continue
                    action={'run':'go','pass':'go','punt':'punt','field_goal':'field_goal'}.get(row.get('play_type'))
                    if action is None:continue
                    cell=e0.pool_key(4,row['ydstogo'],row['yardline_100']);samples=pool.get(cell,[])
                    if len(samples)<e1.MIN_POOL:
                        counts['fourth_rows_unsupported']+=1;continue
                    # The run's FG rule: <=60 ordinary, or a <=70 kick in period-end/desperation states.
                    dist=min(99,int(row['yardline_100'])+7)+10
                    raw=raw_extra.get((row['game_id'],int(float(row['play_id']))),{})
                    q=int(row.get('qtr') or 0);gsc=raw.get('game_seconds_remaining'); clock=int(gsc-900*(4-q)) if gsc is not None and q<=4 else 900
                    sd=raw.get('score_differential')
                    exception=(q in (2,4) and clock<=60) or (q==4 and clock<=300 and sd is not None and float(sd)<=-8)
                    fg_allowed=dist<=fgmax and (dist<=60 or exception)
                    base,ac=model_probs_by_action(samples,row['posteam'],row['defteam'],cell,adapted,fg_allowed)
                    if not base:counts['fourth_rows_unsupported']+=1;continue
                    keys=('go','punt','field_goal');base={k:base.get(k,0.0) for k in keys}
                    teamo=team_action_probs(samples,row['posteam'],'offense',base,fg_allowed)
                    teamd=team_action_probs(samples,row['defteam'],'defense',base,fg_allowed)
                    # Flat prior over all historical fourth-down decisions in the fitted pool.
                    flat=global_fourth_probs
                    if not fg_allowed:
                        flat={**flat,'field_goal':0.0};z=sum(flat.values());flat={k:v/z for k,v in flat.items()} if z else base
                    ps={'slc_situation_cell':base,'offense_only_k25':teamo,'defense_only_k25':teamd,'flat_league':flat}
                    for m in ps:acc_multi(fourth[f'{year}:{row["posteam"]}'][m],ps[m],action)
                    counts['fourth_rows_supported']+=1;fourth_actual[(row['posteam'],action)]+=1
                    rawrow=raw_extra.get((row['game_id'],int(float(row['play_id']))),{})
                    diff=rawrow.get('score_differential'); score=('tied' if diff is None or float(diff)==0 else 'leading' if float(diff)>0 else 'trailing')
                    fourth_situations[(row['posteam'],'score',score,action)]+=1
                    q=int(row['qtr']);clockb='late_q2_q4' if q in (2,4) and clock<=120 else 'other'
                    fourth_situations[(row['posteam'],'clock',clockb,action)]+=1
                    fourth_situations[(row['posteam'],'distance',e0.pool_key(4,row['ydstogo'],row['yardline_100'])[1],action)]+=1
                    fourth_situations[(row['posteam'],'field',e0.pool_key(4,row['ydstogo'],row['yardline_100'])[2],action)]+=1
        result['training_seasons_by_test'][str(year)]=sorted({int(r['season']) for r in train_rows})
        result['evaluations'][str(year)]={
          'source_pool':{'eligible_rows_before_filters':sum(rawcounts.values()),'event_counts_before_source_filters':dict(rawcounts),
                         'final_training_pool_plays':sum(len(v) for v in pool.values()),'e1_exclusions':dict(excluded),
                         'yardage_source_filters':dict(yardcounts),'history_tendency_sha256':hist.manifest['sha256']},
          'cutoff_adaptations':{'target_games':len(all_ids),'games_without_schedule_time':len(undated),'unique_evidence_sets':len(targets_by_available),
                                'available_games_by_target_summary':{'min':min((x['season_games'] for x in avail_manifest.values()),default=0),
                                'median':percentile([x['season_games'] for x in avail_manifest.values()],.5),
                                'max':max((x['season_games'] for x in avail_manifest.values()),default=0)},
                                'team_table_sha256_by_game':hash_targets},
          'coverage':counts,
          'conditional_event_probabilities':{m:metric_multi(d) for m,d in probs_metrics.items()},
          'third_down_line_to_gain_proxy':{str(k):{m:metric_bin(d) for m,d in ms.items()} for k,ms in third.items()},
          'conditional_yardage_crps':{k:{m:metric_y(d) for m,d in ms.items()} for k,ms in yard.items()},
          'fourth_down_actions':{k:{m:metric_multi(d) for m,d in ms.items()} for k,ms in fourth.items()},
          'fourth_down_observed_action_counts':{f'{t}:{a}':n for (t,a),n in fourth_actual.items()},
          'fourth_down_observed_situation_counts':{':'.join(map(str,k)):n for k,n in fourth_situations.items()},
          'third_down_distance_counts':{str(k):v for k,v in third_dist.items()},
          'pregame_strength_ratings':{'offense_epa_per_play':off_epa,'defense_epa_allowed_per_play':def_epa,'offense_category':offcat,'defense_category':defcat}}
        if year==2026 and '2026_09_BUF_MIN' in hash_targets:
            result['model_rebuild_check']['BUF_MIN_2026_week9_team_table_sha256']=hash_targets['2026_09_BUF_MIN']
    # Raw parquet metadata supplies pre-play score/clock missing from this compact DB table.
    result['notes']=['Outcome probabilities are conditional on the observed run/dropback intent; other SLC-v2 modifiers are isolated out so this audit specifically scores the team offense/defense outcome layer.',
                     'Yardage CRPS: SLC source is empirical exact-cell/event yardage. Offense-only and defense-only yardage baselines mix team-specific exact-cell/event rows with the league cell at K=25.',
                     'Fourth-down action scores use the historical exact-cell policy, with 60-yard ordinary FG limit and <=70-yard period-end/desperation allowance; team baselines are K=25 exact-cell shrinkage.',
                     'Third-down metric is conditional on observed run/dropback intent and uses yards-to-go or offensive touchdown; it is a line-to-gain proxy, not official series conversion.']
    Path(OUT).write_text(json.dumps(json_safe(result),sort_keys=True,indent=2)+'\n')
    print(json.dumps({'out':OUT,'years':{y:{'coverage':result['evaluations'][str(y)]['coverage'],
      'outcomes':result['evaluations'][str(y)]['conditional_event_probabilities'],
      'rebuild':result['model_rebuild_check']} for y in (2025,2026)}},sort_keys=True))

# Load score and clock records from the same nflverse PBP source release pinned by the 10K run.
try:
 import pyarrow.parquet as pq
 raw_extra={}
 for yr in (2025,2026):
  path=PBP_RELEASE.format(season=yr)
  cols=['game_id','play_id','game_seconds_remaining','score_differential','qtr','posteam','defteam','down','ydstogo','yardline_100','play_type','epa','penalty','penalty_yards','penalty_type','first_down_penalty']
  tab=pq.read_table(path,columns=cols).to_pydict()
  for i,(g,p) in enumerate(zip(tab['game_id'],tab['play_id'])):
   if p is None:continue
   raw_extra[(g,int(p))]={c:tab[c][i] for c in cols if c not in ('game_id','play_id')}
except Exception as exc:
 print('parquet join failed',repr(exc));raw_extra={}

if __name__=='__main__':main()
