"""Independent checks for score-only research recaps."""
import datetime as dt
import re

def timestamp(value):
    try:
        parsed=dt.datetime.fromisoformat(str(value).replace('Z','+00:00'))
        return parsed if parsed.tzinfo else None
    except (TypeError,ValueError):
        return None

def audit(bundle, recap):
    teams=bundle.get('teams',[]); src=bundle.get('sources',[])
    cutoff=timestamp(bundle.get('as_of_utc')); start=timestamp(bundle.get('game',{}).get('start_utc'))
    valid_scores=(len(teams)==2 and all(type(t.get('score')) is int and t['score']>=0 and t.get('id') and t.get('name') for t in teams) and teams[0]['id'] != teams[1]['id'])
    safe=bool(cutoff and start and cutoff>=start and src and all(timestamp(x.get('captured_at')) and timestamp(x['captured_at'])<=cutoff and x.get('id') and (not x.get('source_event_id') or str(x['source_event_id']) == str(bundle.get('game',{}).get('game_id'))) for x in src))
    final=(bundle.get('game',{}).get('status')=='final' and not (bundle.get('game',{}).get('league')=='nba' and len(teams)==2 and teams[0].get('score')==teams[1].get('score')))
    text=' '.join([recap.get('headline',''),recap.get('lede','')]+recap.get('paragraphs',[]))
    correct=False
    if valid_scores and final:
        a,b=teams
        if a['score']==b['score']:
            correct=('tie' in text.lower() and str(a['score']) in text)
        else:
            winner,loser=sorted(teams,key=lambda t:t['score'],reverse=True)
            correct=(recap.get('headline') == f"{winner['name']} beats {loser['name']}, {winner['score']}-{loser['score']}" and recap.get('lede') == f"{winner['name']} beat {loser['name']} {winner['score']}-{loser['score']}, a {winner['score']-loser['score']}-point margin.")
    unsupported=bool(re.search(r'\b(upset|comeback|dead last|historic|record-breaking|blowout|overtime)\b',text,re.I))
    return {'final_status':final,'valid_scores_and_teams':valid_scores,'cutoff_safe_sources':safe,
            'result_and_margin_recomputed':correct,'no_unsupported_hook':not unsupported}
