"""Per-play outcomes, filter on versus off, same seeds: touchdown and yards by event and yard-line bucket (research scratch)."""
import collections
import json
import sys
from pathlib import Path

REPO = Path('/root/lp-slc-preevent')
sys.path.insert(0, str(REPO / 'scripts' / 'nfl_sequence'))
import pregame_snapshot as ps  # noqa: E402
import slc_engine as se  # noqa: E402
import e1_drive as e1  # noqa: E402

SEEDS = int(sys.argv[1])
snap = ps.load_frozen_snapshot(REPO / 'docs/research/slc-week8-2026/snapshots/2026_08_CAR_GB.json')
art = REPO / 'docs/research/SLC-PLAYCALL-ARTIFACT-v1.json'


def bucket(yl):
    return '1-9' if yl <= 9 else '10-19' if yl <= 19 else '20-49' if yl <= 49 else '50+'


out = {}
for label, filt in (('filter_on', True), ('filter_off', False)):
    ref, _ = se.load_reference(e1.DEFAULT_DB, snap, art, player_shares=True, decision=True, decision_filter=filt)
    acc = collections.defaultdict(lambda: [0, 0, 0.0])  # (event, bucket) -> plays, touchdowns, yards
    for seed in range(1, SEEDS + 1):
        snap['model_reference']['observed_reference'] = ref.model_inputs
        rec, _dec = se.play(seed, ref, snap)
        for drive in rec['drives']:
            for play in drive.get('plays', []):
                ev = play['event_type']
                if ev not in ('run', 'pass_complete', 'pass_incomplete'):
                    continue
                yl = play['state_before']['yardline_100']
                if yl is None:
                    continue
                key = (ev, bucket(yl))
                acc[key][0] += 1
                acc[key][1] += 1 if play['outcome'].get('touchdown') else 0
                acc[key][2] += play['outcome'].get('yards_gained') or 0.0
    out[label] = {f'{ev}|{b}': {'plays': n, 'td_rate': round(td / n, 4) if n else None, 'mean_yards': round(y / n, 3) if n else None}
                  for (ev, b), (n, td, y) in sorted(acc.items())}
    print(label, 'done', flush=True)
Path(sys.argv[2]).write_text(json.dumps(out, indent=1, sort_keys=True))
print('written', flush=True)
