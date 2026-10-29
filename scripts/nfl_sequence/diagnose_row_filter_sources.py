"""Which rows does the label row filter over-sample? Same seeds, filter on versus off (research scratch)."""
import collections
import json
import sys
from pathlib import Path

REPO = Path('/root/lp-slc-preevent')
sys.path.insert(0, str(REPO / 'scripts' / 'nfl_sequence'))
import pregame_snapshot as ps  # noqa: E402
import slc_engine as se  # noqa: E402
import e1_drive as e1  # noqa: E402

SEEDS = int(sys.argv[1]) if len(sys.argv) > 1 else 20
snap = ps.load_frozen_snapshot(REPO / 'docs/research/slc-week8-2026/snapshots/2026_08_CAR_GB.json')
art = REPO / 'docs/research/SLC-PLAYCALL-ARTIFACT-v1.json'
result = {}
for label, filt in (('filter_on', True), ('filter_off', False)):
    ref, _ = se.load_reference(e1.DEFAULT_DB, snap, art, player_shares=True, decision=True, decision_filter=filt)
    counts = {'season': collections.Counter(), 'event': collections.Counter(), 'charted': collections.Counter(),
              'labelled_rows': 0, 'rows': 0}
    for seed in range(1, SEEDS + 1):
        snap['model_reference']['observed_reference'] = ref.model_inputs
        _rec, decisions = se.play(seed, ref, snap)
        for dec in decisions:
            if dec.get('intent') != 'dropback' and dec.get('intent') != 'run':
                continue
            src = dec['source']
            counts['rows'] += 1
            counts['season'][src['season']] += 1
            counts['event'][dec['event']] += 1
            counts['charted']['yes' if src['season'] >= 2022 else 'no'] += 1
            if dec.get('labels_matched'):
                counts['labelled_rows'] += 1
    result[label] = {k: (dict(v) if isinstance(v, collections.Counter) else v) for k, v in counts.items()}
    print(label, json.dumps(result[label], sort_keys=True), flush=True)
Path(sys.argv[2]).write_text(json.dumps(result, indent=1, sort_keys=True))
print('written', flush=True)
