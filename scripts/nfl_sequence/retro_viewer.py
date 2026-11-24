"""Build a standalone 2D replay of the autonomous retro MIN-SF pass play."""
import argparse
import hashlib
import json
from pathlib import Path

import retro_play

PAGE = r'''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>Retro football: MIN vs SF</title><style>
body{background:#10211b;color:#eef6ec;font:15px system-ui;margin:0;padding:16px}main{max-width:1100px;margin:auto}h1{font-size:24px;margin:0 0 6px}p{color:#c6d8c8;margin:5px 0 12px}canvas{width:100%;height:auto;background:#276742;border:1px solid #93b996;border-radius:8px}button,select{padding:9px;font:inherit}input[type=range]{width:min(65vw,550px);vertical-align:middle}#detail{white-space:pre-wrap;line-height:1.5}.legend{display:flex;gap:20px;flex-wrap:wrap}.min{color:#f0c94b}.sf{color:#ffaaa3}.ball{color:#fff}small{color:#b6c8b6}</style></head><body><main><h1>MIN vs SF · retro live play</h1><p>One autonomous play. Authored gameplay defaults; not an NFL prediction. Offense moves left to right.</p><p id="provenance"></p><div class="legend"><span class="min">● Minnesota offense</span><span class="sf">● San Francisco defense</span><span class="ball">● Ball</span></div><canvas id="field" width="1100" height="560" aria-label="Overhead view of all twenty-two players"></canvas><div><button id="toggle">Pause</button> <label>Coverage <select id="mode"><option value="man">Man</option><option value="zone" selected>Zone</option></select></label> <input id="seek" type="range" min="0" value="0"> <span id="time"></span></div><div id="detail"></div><details><summary>All 22 players, assignments and current states</summary><pre id="rosters"></pre></details><small>Labels are positions. Select a player on the field to see their name, assignment and current state. The ball's height is a number, not an animated z-axis. Replay is generated from engine frames and does not change outcomes.</small></main><script>
const data=__DATA__;document.getElementById('provenance').textContent='Frozen snapshot evidence: '+(data.snapshot_verified?'verified':'incomplete')+' · Player abilities: authored shared defaults';const canvas=document.getElementById('field'),ctx=canvas.getContext('2d');let mode='zone',i=0,playing=true,selected=null;const X=x=>130+(x+12)*19,Y=y=>280+y*9.4;const slider=document.getElementById('seek');
function render(){let run=data.runs[mode],f=run.frames[i];slider.max=run.frames.length-1;slider.value=i;ctx.fillStyle='#276742';ctx.fillRect(0,0,1100,560);ctx.strokeStyle='#a5d5a7';ctx.lineWidth=1;for(let x=-10;x<=40;x+=5){ctx.beginPath();ctx.moveTo(X(x),20);ctx.lineTo(X(x),540);ctx.stroke();ctx.fillStyle='#d2e8d1';ctx.fillText(String(x),X(x)+3,37)}ctx.strokeStyle='#fff';ctx.lineWidth=2;ctx.beginPath();ctx.moveTo(X(0),20);ctx.lineTo(X(0),540);ctx.stroke();ctx.fillStyle='#e0f0e0';ctx.fillText('LOS',X(0)+4,54);
ctx.strokeStyle='#fff';ctx.setLineDash([4,4]);ctx.beginPath();let started=false;for(const past of run.frames.slice(0,i+1)){if(past.ball.phase==='flight'){if(!started){ctx.moveTo(X(past.ball.x),Y(past.ball.y));started=true}else ctx.lineTo(X(past.ball.x),Y(past.ball.y))}}ctx.stroke();ctx.setLineDash([]);for(const p of f.players){ctx.beginPath();ctx.fillStyle=p.side==='offense'?'#f0c94b':'#e44a42';ctx.arc(X(p.x),Y(p.y),6.5,0,Math.PI*2);ctx.fill();ctx.fillStyle='#102019';ctx.font='bold 8px system-ui';ctx.textAlign='center';ctx.fillText(p.role,X(p.x),Y(p.y)+3)}let b=f.ball;ctx.beginPath();ctx.fillStyle='#fff';ctx.arc(X(b.x),Y(b.y),4,0,7);ctx.fill();ctx.textAlign='left';ctx.font='12px system-ui';ctx.fillText('ball h='+b.height.toFixed(1),X(b.x)+8,Y(b.y)-8);document.getElementById('time').textContent=f.time.toFixed(1)+' s / '+run.frames[run.frames.length-1].time.toFixed(1)+' s';let chosen=f.players.find(p=>p.id===selected);document.getElementById('rosters').textContent=f.players.map(p=>p.side.toUpperCase()+'  '+p.role+'  '+p.name+'  | '+p.assignment+' | '+p.state).join('\n');document.getElementById('detail').textContent='Decision: '+(f.decision||'QB reading coverage')+' | Ball: '+b.phase+' | Result: '+(f.event||'live')+(f.event?' ('+run.yards+' yards)':'')+(chosen?'\n'+chosen.name+' ('+chosen.role+') · '+chosen.assignment+' · '+chosen.state:'');}
canvas.onclick=e=>{let f=data.runs[mode].frames[i],r=canvas.getBoundingClientRect(),x=(e.clientX-r.left)*canvas.width/r.width,y=(e.clientY-r.top)*canvas.height/r.height;let hit=f.players.map(p=>[Math.hypot(X(p.x)-x,Y(p.y)-y),p]).sort((a,b)=>a[0]-b[0])[0];selected=hit[0]<20?hit[1].id:null;render()};document.getElementById('toggle').onclick=()=>{playing=!playing;document.getElementById('toggle').textContent=playing?'Pause':'Play'};document.getElementById('mode').onchange=e=>{mode=e.target.value;i=0;render()};slider.oninput=e=>{i=Number(e.target.value);render()};setInterval(()=>{if(playing){i=(i+1)%data.runs[mode].frames.length;render()}},200);render();
</script></body></html>'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--snapshot', required=True)
    parser.add_argument('--participation', required=True)
    parser.add_argument('--participation-sha256', required=True)
    parser.add_argument('--seed', type=int, default=300001)
    parser.add_argument('--out', required=True)
    args = parser.parse_args()
    snapshot, lineup, selection = retro_play.load_rosters(args.snapshot, args.participation, args.participation_sha256, args.seed)
    runs = {mode: retro_play.simulate(lineup, args.seed, mode) for mode in ('man', 'zone')}
    payload = {'runs': runs, 'snapshot_sha256': snapshot['snapshot_sha256'],
               'participation_sha256': args.participation_sha256, 'selection': selection,
               'gameplay_defaults': retro_play.DEFAULTS, 'ratings_source': 'authored shared defaults',
               'snapshot_verified': bool(snapshot.get('evaluation', {}).get('verified'))}
    text = json.dumps(payload, separators=(',', ':')).replace('</', '<\\/')
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(PAGE.replace('__DATA__', text), encoding='utf-8')
    print('replay', out, 'sha256', hashlib.sha256(out.read_bytes()).hexdigest())
    for mode, run in runs.items():
        print(mode, run['event'], run['yards'], run['decision'], 'frames', len(run['frames']))


if __name__ == '__main__':
    main()
