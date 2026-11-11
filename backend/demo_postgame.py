"""Offline fixture replay; never opens a database or contacts the network."""
import argparse
import html
import json
from pathlib import Path
from postgame_story_engine import generate_recap
from postgame_feed_adapter import build_feed

ROOT=Path(__file__).resolve().parents[1]
DEFAULT=ROOT/'docs/research/postgame-content-demo-2026-11-10'

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--fixtures',type=Path,default=DEFAULT/'fixtures');parser.add_argument('--output',type=Path,default=DEFAULT);args=parser.parse_args()
    args.output.mkdir(parents=True,exist_ok=True)
    recaps=[];posts=[]
    for path in sorted(args.fixtures.glob('*.json')):
        facts=json.loads(path.read_text()); result=generate_recap(facts)
        recaps.append({'game':facts['game'],'recap':result});posts.extend(build_feed(facts,result))
    if not recaps: raise SystemExit('No fixtures found')
    for name,data in [('recaps.jsonl',recaps),('feed_posts.jsonl',posts)]:
        (args.output/name).write_text(''.join(json.dumps(x,sort_keys=True,ensure_ascii=False)+'\n' for x in data))
    cards=''.join('<article><small>'+html.escape(p['league'].upper()+' · '+p['kind'].replace('_',' '))+'</small><h2>'+html.escape(p['headline'])+'</h2><p>'+html.escape(p['body'])+'</p><small>'+html.escape(p['audit_status'])+'</small></article>' for p in posts)
    page='''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>LP postgame research demo</title><style>*{box-sizing:border-box}body{margin:0;background:#0f0f11;color:#f4f4f5;font:16px system-ui}header,main{max-width:1100px;margin:auto;padding:20px}header{border-bottom:1px solid #27272a;color:#22c55e}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,280px),1fr));gap:16px}article{min-width:0;background:#18181b;border:1px solid #27272a;border-radius:12px;padding:20px}h1,h2{overflow-wrap:anywhere}h2{font-size:1.2rem}small{color:#a1a1aa}</style></head><body><header>LEGENDARY PICKS · RESEARCH DEMO</header><main><h1>Postgame feed</h1><p>Score-only drafts from captured final scoreboards. No player or play details are implied.</p><div class="grid">'''+cards+'</div></main></body></html>'
    (args.output/'demo.html').write_text(page)
    print(f'{len(recaps)} recaps, {len(posts)} cards')
if __name__=='__main__':main()
