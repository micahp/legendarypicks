"""Run one batch arm in-process and log, for each play, the chosen passer, rusher and receiver with the on-field lineup, and,
for each named draw, the candidates, their weights and the chosen one.

Only logging is added. pre_event.choose, pre_event._draw and random.Random.choices return exactly what they returned before,
so draws and results are unchanged. Usage (from a runtime tree): python3 choice_harness.py LOG[.gz] <batch argv...>
"""
import atexit, gzip, inspect, json, os, random, sys

LOG_PATH = sys.argv[1]
ARGV = sys.argv[2:]
sys.path.insert(0, os.path.join(os.getcwd(), 'scripts', 'nfl_sequence'))
import pre_event  # noqa: E402
import simulate_pregame_batch  # noqa: E402

PLAYS, DRAWS = [], []
DRAW_NAME = {}      # id of a generator -> the text it was seeded from; generators are kept alive so ids are not reused
_orig_draw = pre_event._draw
_orig_choose = pre_event.choose
_sig = inspect.signature(_orig_choose)
_orig_choices = random.Random.choices


def _id(value):
    return value.get('gsis_id') if isinstance(value, dict) else value


def named_draw(seed_text):
    rng = _orig_draw(seed_text)
    DRAW_NAME[id(rng)] = seed_text
    DRAWS.append(rng)
    return rng


def logged_choices(self, population, weights=None, *, cum_weights=None, k=1):
    result = _orig_choices(self, population, weights=weights, cum_weights=cum_weights, k=k)
    name = DRAW_NAME.get(id(self))
    if name is not None and population:
        DRAWS.append({'draw': name, 'ids': [_id(p) for p in population],
                      'weights': None if weights is None else list(weights), 'chosen': [_id(p) for p in result]})
    return result


def _player(chosen, role):
    p = chosen.get(role)
    return None if not isinstance(p, dict) else {'gsis': p.get('gsis_id'), 'pos': p.get('pos_abb')}


def logged_choose(*args, **kwargs):
    chosen = _orig_choose(*args, **kwargs)
    if chosen is None:
        return chosen
    bound = _sig.bind(*args, **kwargs).arguments
    lu = chosen.get('lineup')
    PLAYS.append({'seed': bound['seed'], 'index': bound['index'], 'side': bound['side'], 'team': chosen.get('team'),
                  'intent': bound['intent'], 'passer': _player(chosen, 'passer'), 'rusher': _player(chosen, 'rusher'),
                  'receiver': _player(chosen, 'receiver'),
                  'lineup': None if lu is None else {'group': lu.get('group'), 'status': lu.get('status'),
                                                     'on_field': lu.get('on_field'), 'slots': lu.get('slots'),
                                                     'grouping_source': lu.get('grouping_source')}})
    return chosen


def write():
    payload = json.dumps({'plays': PLAYS, 'draws': [d for d in DRAWS if isinstance(d, dict)]})
    if LOG_PATH.endswith('.gz'):
        with gzip.open(LOG_PATH, 'wt') as f:
            f.write(payload)
    else:
        open(LOG_PATH, 'w').write(payload)


pre_event._draw = named_draw
pre_event.choose = logged_choose
random.Random.choices = logged_choices
atexit.register(write)
simulate_pregame_batch.main(ARGV)
