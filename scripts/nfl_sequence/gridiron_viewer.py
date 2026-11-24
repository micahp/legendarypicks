"""Render two autonomous Gridiron plays with the existing retro replay viewer."""
import argparse
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
            elif event['type'] == 'throw':
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
    parser.add_argument('--seed', type=int, default=300001)
    args = parser.parse_args()
    snapshot = pregame_snapshot.load_frozen_snapshot(args.snapshot)
    names = {p['gsis_id']: p['player_name'] for side in ('home', 'away')
             for p in snapshot['rosters'][side]['players']}
    state = {'quarter': 1, 'clock': 600, 'offense': 'MIN', 'defense': 'SF', 'down': 1, 'togo': 10, 'yl': 50}
    runs, audits = {}, {}
    for key, family in (('man', 'run'), ('zone', 'pass')):
        call, provenance = gridiron_bridge.build_call(args.snapshot, args.participation, args.participation_sha256,
                                                      args.playbook, args.manifest, seed=args.seed, family=family, state=state)
        result, timing = gridiron_bridge.run(args.engine, call)
        reduced = gridiron_bridge.reduce_result(call, result, state)
        runs[key] = viewer_run(call, result, reduced, names)
        audits[family] = {'provenance': provenance, 'timing': timing, 'reduced': reduced,
                          'result': result['result'], 'warnings': result['diagnostics']['physical_warnings']}
    payload = {'runs': runs, 'snapshot_verified': snapshot['evaluation']['verified'], 'audits': audits}
    page = retro_viewer.PAGE.replace('MIN vs SF · retro live play', 'MIN vs SF · Gridiron autonomous plays')
    page = page.replace('Coverage <select', 'Concept <select').replace('>Man</option>', '>Inside zone</option>')
    page = page.replace('>Zone</option>', '>Slant-flat</option>').replace('},200);render();', '},33);render();')
    page = page.replace(r".join('\\n')", r".join('\n')")
    text = json.dumps(payload, separators=(',', ':')).replace('</', '<\\/')
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(page.replace('__DATA__', text), encoding='utf-8')
    print('replay', out, 'sha256', hashlib.sha256(out.read_bytes()).hexdigest())
    print(json.dumps({key: {'result': value['result'], 'timing': value['timing']} for key, value in audits.items()}))


if __name__ == '__main__':
    main()
