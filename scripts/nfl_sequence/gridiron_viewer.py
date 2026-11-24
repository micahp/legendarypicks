"""Render two autonomous Gridiron plays with the existing retro replay viewer."""
import argparse
import copy
import hashlib
import json
from pathlib import Path

import gridiron_bridge
import pregame_snapshot
import retro_viewer


def viewer_run(call, result, reduced, names):
    trajectory = result['trajectory']
    roster = trajectory['roster']
    events = sorted(result['events'], key=lambda event: event['t'])
    decisions = {}
    ball_phase = 'held'
    latest_qb = None
    cursor = 0
    frames = []
    for index, frame in enumerate(trajectory['frames']):
        time = trajectory['t0'] + index / trajectory['hz']
        while cursor < len(events) and events[cursor]['t'] <= time + 1e-6:
            event = events[cursor]
            if event['type'] == 'decision':
                decisions[event['player_id']] = event
                if event['player_id'] == call['offense']['lineup']['QB']:
                    latest_qb = event['decision']
            elif event['type'] in ('throw', 'throw_away'):
                ball_phase = 'flight'
            elif event['type'] in ('catch', 'interception', 'incomplete'):
                ball_phase = event['type']
            cursor += 1
        players = []
        for offset, p in enumerate(roster):
            d = decisions.get(p['id'], {})
            players.append({'id': p['id'], 'name': names.get(p['id'], p['id']), 'role': p['slot'],
                            'side': 'offense' if p['team'] == 'O' else 'defense',
                            'x': frame[6 * offset] - call['situation']['yardline_100'],
                            'y': frame[6 * offset + 1] - 160 / 6,
                            'assignment': d.get('assignment', 'not recorded'),
                            'state': d.get('decision', 'not recorded')})
        base = len(roster) * 6
        ball = {'x': frame[base] - call['situation']['yardline_100'],
                'y': frame[base + 1] - 160 / 6, 'height': frame[base + 2] / 0.9144,
                'phase': ball_phase}
        frames.append({'time': time, 'players': players, 'ball': ball, 'decision': latest_qb,
                       'event': reduced['play']['event_type'] if index == len(trajectory['frames']) - 1 else None})
    return {'frames': frames, 'yards': reduced['play']['outcome']['yards_gained']}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for option in ('snapshot', 'participation', 'participation-sha256', 'playbook', 'manifest', 'engine', 'out'):
        parser.add_argument('--' + option, required=True)
    parser.add_argument('--seeds', default='300001,300002', help='comma-separated seeds to precompute')
    args = parser.parse_args()
    seeds = [int(value.strip()) for value in args.seeds.split(',') if value.strip()]
    if not seeds or len(seeds) != len(set(seeds)):
        parser.error('provide distinct integer seeds')
    snapshot = pregame_snapshot.load_frozen_snapshot(args.snapshot)
    names = {p['gsis_id']: p['player_name'] for side in ('home', 'away')
             for p in snapshot['rosters'][side]['players']}
    state = {'quarter': 1, 'clock': 600, 'offense': 'MIN', 'defense': 'SF', 'down': 1, 'togo': 10, 'yl': 50}
    runs, audits = {}, {}
    concepts = ('slant_flat', 'curls', 'four_verticals')
    coverages = ('man', 'zone')
    with gridiron_bridge.GridironSession(args.engine) as session:
        for seed in seeds:
            base, provenance = gridiron_bridge.build_call(args.snapshot, args.participation, args.participation_sha256,
                                                          args.playbook, args.manifest, seed=seed, family='pass', state=state)
            for concept in concepts:
                for coverage in coverages:
                    call = copy.deepcopy(base)
                    call['offense']['call']['concept'] = 'assigned'
                    call['defense']['call']['coverage'] = 'cover_1' if coverage == 'man' else 'cover_3'
                    call['assignments'] = session.request('example_assignments', concept=concept, coverage=coverage)['value']
                    call['behavior_mode'] = 'retro'
                    result, timing = session.play(call)
                    reduced = gridiron_bridge.reduce_result(call, result, state)
                    key = f'{seed}|{concept}|{coverage}'
                    runs[key] = viewer_run(call, result, reduced, names)
                    audits[key] = {'provenance': provenance, 'timing': timing, 'reduced': reduced,
                                   'result': result['result'], 'warnings': result['diagnostics']['physical_warnings']}
    payload = {'runs': runs, 'snapshot_verified': snapshot['evaluation']['verified'], 'audits': audits,
               'seeds': seeds, 'concepts': concepts, 'coverages': coverages}
    page = retro_viewer.PAGE.replace('MIN vs SF · retro live play', 'MIN vs SF · Gridiron autonomous plays')
    page = page.replace('<label>Coverage <select id="mode"><option value="man">Man</option><option value="zone" selected>Zone</option></select></label>',
                        '<label>Concept <select id="concept"></select></label> <label>Coverage <select id="coverage"></select></label> <label>Seed <select id="seed"></select></label>')
    page = page.replace("let mode='zone',i=0", "let mode=Object.keys(data.runs)[0],i=0")
    page = page.replace("document.getElementById('mode').onchange=e=>{mode=e.target.value;i=0;render()};",
        "for(const [id,values] of [['concept',data.concepts],['coverage',data.coverages],['seed',data.seeds]]){const el=document.getElementById(id);for(const value of values){const opt=document.createElement('option');opt.value=value;opt.textContent=String(value).replaceAll('_',' ');el.appendChild(opt)}el.onchange=()=>{mode=[document.getElementById('seed').value,document.getElementById('concept').value,document.getElementById('coverage').value].join('|');i=0;render()}};")
    page = page.replace('},200);render();', '},33);render();')
    page = page.replace(r".join('\\n')", r".join('\n')")
    text = json.dumps(payload, separators=(',', ':')).replace('</', '<\\/')
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(page.replace('__DATA__', text), encoding='utf-8')
    print('replay', out, 'sha256', hashlib.sha256(out.read_bytes()).hexdigest())
    print('plays', len(runs), 'seeds', seeds, 'concepts', list(concepts), 'coverages', list(coverages))


if __name__ == '__main__':
    main()
