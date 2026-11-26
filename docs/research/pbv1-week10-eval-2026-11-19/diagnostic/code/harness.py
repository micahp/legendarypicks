"""Run one batch arm in-process and log every pre-event draw: its key text and the first value it gives.

The batch code is not changed. pre_event._draw is wrapped; the wrapper builds the same generator twice, reads one value
from one copy, and returns the other, so the batch sees exactly the generator it would have seen.
Usage (from a runtime tree): python3 harness.py LOGFILE <batch argv...>
"""
import atexit, json, os, sys

LOG_PATH = sys.argv[1]
ARGV = sys.argv[2:]
sys.path.insert(0, os.path.join(os.getcwd(), 'scripts', 'nfl_sequence'))
import pre_event  # noqa: E402
import simulate_pregame_batch  # noqa: E402

ROWS = []
_orig = pre_event._draw


def logged_draw(seed_text):
    ROWS.append([seed_text, _orig(seed_text).random()])
    return _orig(seed_text)


pre_event._draw = logged_draw

import paired_random_streams as prs  # noqa: E402
_orig_rng = prs.PairedRandomStreams.rng


def logged_rng(self, stream, *coordinates):
    ROWS.append([f'stream|{self.seed}|{self.root_sha256}|{stream}|' + json.dumps(list(coordinates), default=str),
                 _orig_rng(self, stream, *coordinates).random()])
    return _orig_rng(self, stream, *coordinates)


prs.PairedRandomStreams.rng = logged_rng
atexit.register(lambda: open(LOG_PATH, 'w').write(json.dumps(ROWS)))
simulate_pregame_batch.main(ARGV)
