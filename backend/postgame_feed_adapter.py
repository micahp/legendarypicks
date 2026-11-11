"""Turn a supported final score into separately traceable score graphics."""
from postgame_story_engine import VERSION

def build_feed(bundle,recap):
    if recap['gate'] != 'eligible_score_only': return []
    game=bundle['game']; teams=bundle['teams']; ids=[s['id'] for s in bundle['sources']]
    base={'league':game['league'],'game_id':game['game_id'],'daypart':'postgame','asset_refs':[],
          'fact_ids':ids,'source_ids':ids,'generated_at_utc':bundle['as_of_utc'],
          'as_of_utc':bundle['as_of_utc'],'generator_version':VERSION,'audit_status':recap['gate'],
          'render_context':'homepage'}
    posts=[]
    for kind,headline,body in [('final_score',recap['headline'],recap['lede']),
                                ('chart','Final score comparison','Final points for each team.')]+([('stat_nugget', f"{max(teams, key=lambda t:t['score'])['name']} wins by {abs(teams[0]['score']-teams[1]['score'])}", f"The final margin was {abs(teams[0]['score']-teams[1]['score'])} points.")] if teams[0]['score'] != teams[1]['score'] else []):
        posts.append({**base,'post_id':f"{game['league']}:{game['game_id']}:{kind}:v1",'kind':kind,
                      'headline':headline,'body':body,'numerics':{t['id']:t['score'] for t in teams},
                      'graphic_spec':{'type':'bars','unit':'points','sample':'one completed game'} if kind=='chart' else None})
    return posts
