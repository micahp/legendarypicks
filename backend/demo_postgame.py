"""Replay pinned fixtures offline; never connect to a database or the network."""
import argparse
import hashlib
import html
import json
from pathlib import Path
from postgame_story_engine import generate_recap
from postgame_feed_adapter import build_feed, rank_feed
from postgame_story_audit import timestamp
from postgame_rubric import grade_postgame

ROOT = Path(__file__).resolve().parents[1]
DEFAULT = ROOT / 'docs/research/postgame-content-demo-2026-11-10'


def esc(value):
    return html.escape(str(value), quote=True)


def write_jsonl(path, rows):
    path.write_text(''.join(json.dumps(x, sort_keys=True, ensure_ascii=False) + '\n' for x in rows))


def render_page(games, posts):
    options = ''.join(f'<option value="{esc(g["game"]["game_id"])}">{esc(g["label"])}</option>' for g in games)
    teams = sorted({(t['id'], t['name']) for g in games for t in g['facts']['teams']})
    favorites = '<option value="">No favorite selected</option>' + ''.join(f'<option value="{esc(code)}">{esc(name)}</option>' for code, name in teams)
    ranked_cards = ''.join(f'''<article data-feed-card data-game="{esc(p['league'] + ':' + p['game_id'])}" data-id="{esc(p['post_id'])}" data-kind="{esc(p['kind'])}" data-teams="{esc(' '.join(p['team_ids']))}" data-recency="{p['rank_components']['recency']}" data-impact="{p['rank_components']['event_impact']}" data-quality="{p['rank_components']['supporting_facts_quality']}"><small>{esc(p['league'].upper())} · {esc(p['kind'].replace('_',' '))}</small><h3>{esc(p['headline'])}</h3><p>{esc(p['body'])}</p></article>''' for p in posts)
    articles = []
    for g in games:
        facts, recap, rubric = g['facts'], g['recap'], g['rubric']
        segments = ''.join(f'<span title="{esc(name)}: {esc(dim["score"] if dim["score"] is not None else "not applicable")}" style="background:{esc(dim["color"])};flex:{dim["weight"]}"></span>' for name, dim in rubric['dimensions'].items())
        candidates = ''.join(f'<li>{esc(c["candidate_type"])}: {esc(c["reason"])} ({"selected" if c["angle_id"] == recap["selected"] else "not selected"})</li>' for c in recap['candidates'])
        source_links = ''.join(f'<li><a href="{esc(s["url"])}">{esc(s["id"])}</a> captured {esc(s["captured_at"])}</li>' for s in facts['sources'] if s.get('url'))
        cards = []
        for post in posts:
            if post['game_id'] != g['game']['game_id']:
                continue
            chart = ''
            if post['kind'] == 'chart':
                maximum = max(post['numerics'].values()) or 1
                chart = ''.join(f'<div class="barrow"><span>{esc(team)}</span><div class="track"><div class="fill" style="width:{score * 100 / maximum:.2f}%"></div></div><b>{score}</b></div>' for team, score in post['numerics'].items())
                chart += '<small>Points · one completed game · source and cutoff in evidence</small>'
            cards.append(f'<article><small>{esc(post["kind"].replace("_", " "))}</small><h3>{esc(post["headline"])}</h3><p>{esc(post["body"])}</p>{chart}</article>')
        articles.append(f'''<section class="game" data-game="{esc(g['game']['game_id'])}"><div class="panel"><small>FINAL · {esc(g['game']['league'].upper())}</small><h2>{esc(recap['headline'])}</h2><p>{esc(recap['lede'])}</p>{''.join('<p>'+esc(p)+'</p>' for p in recap['paragraphs'])}<p class="muted">{esc(rubric['status'])} · automated editorial proxy {esc(rubric['overall'])}/100 · not a human rating</p><div class="rubric">{segments}</div><details><summary>Story choices and evidence</summary><ul>{candidates}</ul><ul>{source_links}</ul><pre>{esc(json.dumps(recap['claims'], indent=2))}</pre></details></div><div class="grid">{''.join(cards)}<article><small>MODEL RECEIPT</small><h3>Unavailable</h3><p>No verified pregame lock is attached to this game.</p></article><article><small>CLIP</small><h3>The game's defining play</h3><p>Clip unavailable pending a verified event ID and a rights-cleared embed.</p></article></div><div class="graphics"><article class="square"><small>SOCIAL · 1:1</small><strong>{esc(g['label'])}</strong><p>{esc(recap['headline'])}</p></article><article class="portrait"><small>SOCIAL · 9:16</small><strong>FINAL</strong><p>{esc(recap['headline'])}</p></article></div></section>''')
    return '''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>LP postgame research demo</title><style>
*{box-sizing:border-box}body{margin:0;background:#0f0f11;color:#f4f4f5;font:16px system-ui}header,main{max-width:1120px;margin:auto;padding:20px}header{border-bottom:1px solid #27272a;color:#22c55e;font-weight:700}a{color:#86efac;overflow-wrap:anywhere}button,select{font:inherit;background:#27272a;color:#fafafa;border:1px solid #52525b;border-radius:8px;padding:9px;max-width:100%}button[aria-selected=true]{border-color:#22c55e;color:#86efac}.tabs{display:flex;flex-wrap:wrap;gap:8px;margin:20px 0}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,250px),1fr));gap:12px;margin:16px 0}.panel,article{min-width:0;background:#18181b;border:1px solid #27272a;border-radius:12px;padding:18px}h1,h2,h3,p,pre{overflow-wrap:anywhere}h2{font-size:1.4rem}h3{font-size:1.05rem}small,.muted{color:#a1a1aa}pre{white-space:pre-wrap;font-size:.75rem}.rubric{display:flex;height:9px;gap:3px;margin:12px 0}.rubric span{border-radius:4px}.barrow{display:flex;align-items:center;gap:8px;margin:8px 0}.track{background:#27272a;flex:1;height:12px}.fill{background:#22c55e;height:100%}.graphics{display:flex;flex-wrap:wrap;gap:12px}.square{width:min(100%,250px);aspect-ratio:1}.portrait{width:min(100%,180px);aspect-ratio:9/16}.square strong,.portrait strong{display:block;color:#22c55e;font-size:1.3rem;margin-top:24px}[hidden]{display:none!important}fieldset{border:1px solid #52525b;border-radius:8px;margin:12px 0}label{display:block;padding:5px}details{margin-top:16px}</style></head><body><header>LEGENDARY PICKS · RESEARCH DEMO</header><main><h1>Game stories</h1><p>Offline research from pinned final scoreboards and box scores. No production content is changed.</p><nav class="tabs" aria-label="Daypart">'''+''.join(f'<button type="button" data-tab="{t.lower()}" aria-selected="{str(t=="Postgame").lower()}">{t}</button>' for t in ('Morning','Pregame','Live','Postgame'))+'''</nav><section data-panel="morning" hidden><div class="panel"><h2>Morning rundown</h2><p>Final scores and supported player details are available in the Postgame tab. This is a text outline, not a video.</p></div></section><section data-panel="pregame" hidden><div class="panel"><h2>Demo polls</h2><p>Selections are local-only; there are no public voting counts. These general questions do not represent a live poll.</p><form>'''+''.join(f'<fieldset><legend>{esc(q)}</legend>'+''.join(f'<label><input type="radio" name="poll{i}" value="{esc(a)}"> {esc(a)}</label>' for a in answers)+'</fieldset>' for i,(q,answers) in enumerate([('What interests you most before tipoff?',('Win probability','Projected score')),('Which story would you open?',('Player usage','Defensive matchup')),('What would you read first?',('Team form','Player form'))]))+'''</form></div></section><section data-panel="live" hidden><div class="panel"><h2>Live</h2><p>No live stream in this offline demo.</p></div></section><section data-panel="postgame"><h2>Feed</h2><label for="favorite-league">League (local-only)</label><select id="favorite-league"><option value="">All leagues</option><option value="nba">NBA</option><option value="nfl">NFL</option></select><label for="favorite-team">Favorite team (local-only)</label><select id="favorite-team">'''+favorites+'''</select><div id="ranked-feed" class="grid">'''+ranked_cards+'''</div><h2>Game details</h2><label for="game-select">Choose a game </label><select id="game-select">'''+options+'''</select><div class="games">'''+''.join(articles)+'''</div></section></main><script>
const select=document.getElementById('game-select');function showGame(){document.querySelectorAll('.game').forEach(x=>x.hidden=x.dataset.game!==select.value)}select.addEventListener('change',showGame);showGame();document.querySelectorAll('[data-tab]').forEach(b=>b.addEventListener('click',()=>{document.querySelectorAll('[data-tab]').forEach(x=>x.setAttribute('aria-selected',x===b?'true':'false'));document.querySelectorAll('[data-panel]').forEach(x=>x.hidden=x.dataset.panel!==b.dataset.tab)}));document.querySelectorAll('input[type=radio]').forEach(x=>{try{x.checked=localStorage.getItem('lp-demo-'+x.name)===x.value;x.addEventListener('change',()=>localStorage.setItem('lp-demo-'+x.name,x.value))}catch(e){}});
const league=document.getElementById('favorite-league'),favorite=document.getElementById('favorite-team'),feed=document.getElementById('ranked-feed');try{league.value=localStorage.getItem('lp-demo-league')||''}catch(e){}try{favorite.value=localStorage.getItem('lp-demo-favorite')||''}catch(e){}function rank(){const all=Array.from(feed.children);all.forEach(x=>x.hidden=!!league.value&&!x.dataset.game.startsWith(league.value+':'));const pending=all.filter(x=>!x.hidden),game={},kind={};while(pending.length){pending.sort((a,b)=>{function score(x){return +x.dataset.recency + +x.dataset.impact + +x.dataset.quality + (favorite.value&&x.dataset.teams.split(' ').includes(favorite.value)?15:0) + Math.max(0,12-4*(kind[x.dataset.kind]||0))-25*(game[x.dataset.game]||0)}return score(b)-score(a)||a.dataset.id.localeCompare(b.dataset.id)});const x=pending.shift();feed.appendChild(x);game[x.dataset.game]=(game[x.dataset.game]||0)+1;kind[x.dataset.kind]=(kind[x.dataset.kind]||0)+1}}league.addEventListener('change',()=>{try{localStorage.setItem('lp-demo-league',league.value)}catch(e){}rank()});favorite.addEventListener('change',()=>{try{localStorage.setItem('lp-demo-favorite',favorite.value)}catch(e){}rank()});rank();
</script></body></html>'''


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--fixtures', type=Path, default=DEFAULT / 'fixtures')
    parser.add_argument('--output', type=Path)
    parser.add_argument('--db', type=Path, help='optional SQLite source, opened read-only')
    parser.add_argument('--league', choices=('nba', 'nfl'))
    parser.add_argument('--game-id')
    args = parser.parse_args()
    if args.db and (not args.league or not args.game_id or not args.output):
        parser.error('--db requires --league, --game-id and a separate --output directory')
    if not args.db and (args.league or args.game_id):
        parser.error('--league and --game-id require --db')
    if args.output is None:
        args.output = DEFAULT
    if args.db and args.output.resolve() == DEFAULT.resolve():
        parser.error('database mode must use a separate output directory')
    args.output.mkdir(parents=True, exist_ok=True)
    games, posts, manifest, rundown = [], [], [], []
    if args.db:
        from postgame_story_facts import load_scoreboard
        inputs = [(None, load_scoreboard(args.db, args.league, args.game_id))]
    else:
        inputs = [(path.read_bytes(), json.loads(path.read_bytes())) for path in sorted(args.fixtures.glob('*.json'))]
    for raw, facts in inputs:
        recap = generate_recap(facts)
        rubric = grade_postgame(facts, recap)
        game = facts['game']; label = ' at '.join(t['name'] for t in facts['teams'])
        games.append({'game': game, 'label': label, 'recap': recap, 'facts': facts, 'rubric': rubric})
        posts.extend(build_feed(facts, recap))
        manifest.append({'game_id': game['game_id'], 'fixture_sha256': hashlib.sha256(raw).hexdigest() if raw else None,
                         'input_sha256': recap['input_sha256'], 'as_of_utc': facts['as_of_utc'],
                         'sources': facts['sources'], 'claims': recap['claims'], 'candidates': recap['candidates'],
                         'selected': recap['selected'], 'audit': recap['audit'], 'rubric': rubric})
        if recap['gate'] in ('eligible', 'eligible_score_only'):
            rundown.append({'game_id': game['game_id'], 'segment': recap['headline'], 'script': recap['lede'], 'type': 'text_only'})
    if not games:
        raise SystemExit('No fixtures found')
    latest = max((g['facts']['as_of_utc'] for g in games), key=timestamp)
    posts = rank_feed(posts, as_of_utc=latest)
    write_jsonl(args.output / 'recaps.jsonl', [{'game': g['game'], 'recap': g['recap'], 'rubric': g['rubric']} for g in games])
    write_jsonl(args.output / 'feed_posts.jsonl', posts)
    write_jsonl(args.output / 'show_rundowns.jsonl', rundown)
    (args.output / 'evidence_manifest.json').write_text(json.dumps(manifest, indent=2, sort_keys=True, ensure_ascii=False) + '\n')
    (args.output / 'demo.html').write_text(render_page(games, posts))
    print(f'{len(games)} recaps, {len(posts)} cards')


if __name__ == '__main__':
    main()
