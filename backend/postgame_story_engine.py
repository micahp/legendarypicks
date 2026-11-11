"""Research score-only postgame renderer. No I/O or model inference."""
import hashlib
import json
from postgame_story_audit import audit

VERSION='postgame-score-v0.1'

def generate_recap(bundle):
    material=json.dumps(bundle,sort_keys=True,separators=(',',':'),ensure_ascii=False)
    digest=hashlib.sha256(material.encode()).hexdigest()
    teams=bundle.get('teams',[])
    out={'engine_version':VERSION,'input_sha256':digest,'headline':'','lede':'','paragraphs':[],
         'candidates':[],'selected':None,'gate':'blocked'}
    if len(teams)==2 and all(type(t.get('score')) is int and t['score']>=0 and t.get('name') for t in teams):
        a,b=teams
        if a['score']==b['score']:
            out['headline']=f"{a['name']} and {b['name']} tie {a['score']}-{b['score']}"
            out['lede']=f"{a['name']} and {b['name']} finished level at {a['score']}-{b['score']}."
        else:
            winner,loser=sorted(teams,key=lambda t:t['score'],reverse=True)
            score=f"{winner['score']}-{loser['score']}"; margin=winner['score']-loser['score']
            out['headline']=f"{winner['name']} beats {loser['name']}, {score}"
            out['lede']=f"{winner['name']} beat {loser['name']} {score}, a {margin}-point margin."
        out['candidates']=[{'angle_id':'final_result','candidate_type':'fallback','priority':0,'data_quality':'score_only','evidence_ids':[s.get('id') for s in bundle.get('sources',[])]}]
        out['selected']='final_result'
    out['audit']=audit(bundle,out)
    if all(out['audit'].values()): out['gate']='eligible_score_only'
    return out
