import collections, json, math, sys
from pathlib import Path
import pyarrow.parquet as pq
sys.path.insert(0, str(Path(__file__).resolve().parents[3] / 'scripts' / 'nfl_sequence'))
import e1_drive as e1
import transition_strength as ts
import team_tendency as tt

ROOT=Path('/root/lp-snapshots/nfl-backfill-2026-10-27/raw/pbp')
COLS=list(e1.COLUMNS)+['epa']

def pyval(x):
    if hasattr(x, 'item'):
        x=x.item()
    if isinstance(x, float) and not math.isfinite(x):
        return None
    return x

def season_pool(year):
    path=ROOT/f'play_by_play_{year}.parquet'
    table=pq.read_table(path, columns=COLS)
    rows=[{k:pyval(v) for k,v in r.items() if k!='epa'} for r in table.to_pylist()]
    rows.sort(key=lambda r:(r['game_id'] or '', r['play_id'] or -1))
    pool, excluded, unknown, unrecognized=ts._clean_pool_from_rows(rows)
    del rows, table
    return pool, {'source_rows':pq.ParquetFile(path).metadata.num_rows,'clean_pool_plays':sum(map(len,pool.values())),
                  'unknown_penalty_rows':unknown,'unrecognized_penalty_rows':unrecognized,'e1_exclusions':dict(excluded)}

def merge(dst, src):
    for cell, samples in src.items(): dst.setdefault(cell, []).extend(samples)

def intent(ev):
    if ev=='run': return 'run'
    if ev in ('pass_complete','pass_incomplete','sack','interception','fumble_lost'): return 'dropback'
    return None

def scores(train, test, target_year):
    model=ts.build_from_pool(train, target_year, cutoff=(target_year,1))
    event=tt.build_from_pool(train, target_year, cutoff=(target_year,1))
    # Precompute outcome counts once per cell and play intent. Re-scanning every
    # source sample for each observed team matchup causes quadratic work.
    counts_by_context=collections.defaultdict(collections.Counter)
    for cell, samples in train.items():
        for ev, row, _, _ in samples:
            it=intent(ev)
            if it:
                counts_by_context[(cell,it)][ts.transition_key(ev,row)] += 1
    # Cache only the small weighted distributions per observed team matchup.
    by_context={}
    sums={name:{'n':0,'logloss':0.0,'brier':0.0} for name in ('league_cell','event_team','joint_transition')}
    fallbacks=collections.Counter(); total=0
    for cell, samples in test.items():
        usable=[(ev,row) for ev,row,_,_ in samples if intent(ev)]
        for ev,row in usable:
            it=intent(ev); off=row.get('posteam'); deff=row.get('defteam')
            ctx=(cell,it,off,deff)
            dist=by_context.get(ctx)
            if dist is None:
                counts=counts_by_context.get((cell,it),{})
                n=sum(counts.values())
                if not n: continue
                weights={name:{} for name in sums}
                for key,count in counts.items():
                    key_event=key.split(':',1)[0]
                    weights['league_cell'][key]=float(count)
                    ew=1.0
                    for side,team in (('offense',off),('defense',deff)):
                        try: ew*=event.ratio(side,team,cell,key_event)
                        except ValueError: fallbacks[f'event_no_team_{side}']+=1
                    weights['event_team'][key]=count*ew
                    jw=1.0
                    for side,team in (('offense',off),('defense',deff)):
                        try: jw*=model.ratio_key(side,team,cell,key)
                        except ValueError: fallbacks[f'joint_no_team_{side}']+=1
                    weights['joint_transition'][key]=count*jw
                dist={}
                for name,ws in weights.items():
                    z=sum(ws.values()); dist[name]={k:v/z for k,v in ws.items()} if z else {}
                by_context[ctx]=dist
            actual=ts.transition_key(ev,row)
            for name,probs in dist.items():
                p=probs.get(actual,0.0)
                metric=sums[name]; metric['n']+=1; metric['logloss']-=math.log(max(p,1e-15))
                metric['brier']+=sum((q-(1.0 if k==actual else 0.0))**2 for k,q in probs.items()) + (1.0 if actual not in probs else 0.0)
            total+=1
    out={name:{'n':m['n'],'mean_log_loss':m['logloss']/m['n'] if m['n'] else None,
               'mean_multiclass_brier':m['brier']/m['n'] if m['n'] else None} for name,m in sums.items()}
    return out, {'scored_plays':total,'cached_contexts':len(by_context),'fallback_counts':dict(fallbacks),
                 'candidate_sha256':model.manifest['sha256'],'candidate_training_plays':model.manifest['plays']}

def main():
    train=collections.defaultdict(list); provenance={}
    for y in (2022,2023,2024):
        pool,provenance[str(y)]=season_pool(y); merge(train,pool); del pool; print(json.dumps({'training_season_loaded':y,'pool_plays':sum(map(len,train.values()))}),flush=True)
    train=dict(train)
    output={'source_root':str(ROOT),'training':provenance,'evaluations':{},
            'policy':'All seasons are read from the pinned 2026-10-27 Parquet snapshot. Fits include penalty==0 plays only; NULL/unrecognized penalty labels and confirmed penalties are excluded after ordered-sequence classification. No simulations run.'}
    for y in (2025,2026):
        test,info=season_pool(y)
        metrics,diag=scores(train,test,y)
        output['evaluations'][str(y)]={'input':info,'scores':metrics,'diagnostics':diag}
        print(json.dumps({'year':y,'input':info,'scores':metrics,'diagnostics':diag},sort_keys=True),flush=True)
        if y==2025:
            # Next held-out year is trained with 2025 as prior-season evidence.
            merge(train,test); train=dict(train)
        del test
    path=Path('/tmp/slc-transition-strength-offline-audit.json')
    path.write_text(json.dumps(output,sort_keys=True,indent=2)+'\n')
    print(json.dumps({'report':str(path),'bytes':path.stat().st_size}),flush=True)

if __name__=='__main__': main()
