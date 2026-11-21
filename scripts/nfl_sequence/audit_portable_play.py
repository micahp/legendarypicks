"""Trace the first sampled play in forked, identically initialized research runs."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import sys

import simulate_portable_pack as runtime


class PlayCaptured(BaseException):
    pass


def trace_play(run, seed_args, disable_filter):
    sampler = seed_args[1].contextual_sampler
    if disable_filter:
        sampler.decision_filter = False
    sampler.trace_outcome_probabilities = True
    sample = sampler.sample.__code__
    calls, changes = {}, []
    active = False
    previous = None
    previous_line = None

    def trace(frame, event, value):
        nonlocal active, previous, previous_line
        code = frame.f_code
        if event == 'call' and code is sample:
            active = True
        if not active:
            return None
        if event == 'call':
            frame.f_trace_lines = code is sample
            parent = frame.f_back.f_code
            edge = (parent.co_qualname, frame.f_back.f_lineno, frame.f_globals.get('__name__'),
                    code.co_qualname, code.co_firstlineno)
            calls[edge] = calls.get(edge, 0) + 1
        elif code is sample and event == 'line':
            loc = frame.f_locals
            candidates = loc.get('candidates')
            state = [len(candidates) if candidates is not None else None,
                     loc.get('p'), loc.get('cat'), loc.get('weight')]
            if state != previous:
                changes.append([previous_line, *state])
                previous = state
            previous_line = frame.f_lineno
        elif event == 'return':
            if code is sample:
                active = False
                if value is not None:
                    raise PlayCaptured
        return trace

    sys.settrace(trace)
    try:
        run(*seed_args)
    except PlayCaptured:
        decision = sampler.decisions[-1]
    else:
        raise RuntimeError('no play captured')
    finally:
        sys.settrace(None)
    return dict(calls=[[*edge, count] for edge, count in calls.items()], changes=changes, decision=decision)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('registry', type=Path)
    parser.add_argument('model')
    parser.add_argument('snapshot', type=Path)
    parser.add_argument('out', type=Path)
    parser.add_argument('--seed', type=int, default=300001)
    args = parser.parse_args()
    snapshot = json.loads(args.snapshot.read_text())
    schedule = snapshot.get('pregame_snapshot', snapshot)['schedule']
    packages = json.loads(args.registry.read_text())['packages']
    matches = [entry for entry in packages if entry['model_id'] == args.model
               and entry['training_season'] == schedule['season']]
    if len(matches) != 1:
        parser.error(f"expected one {args.model} package for season {schedule['season']}, found {len(matches)}")
    package = matches[0]
    args.out.mkdir(parents=True, exist_ok=True)
    original = runtime._run_seed

    def capture(*seed_args):
        for disabled in (False, True):
            identity = dict(model=args.model, pack=package['sha256'], seed=seed_args[0],
                            commit=package['code_commit'], snapshot=seed_args[2]['snapshot_sha256'],
                            rng=seed_args[5].manifest(), disable_decision_row_filter=disabled)
            digest = hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()
            pid = os.fork()
            if pid == 0:
                try:
                    result = trace_play(original, seed_args, disabled)
                    with (args.out / (args.model + ('-filter-off' if disabled else '-control') + '.json')).open('x') as f:
                        json.dump(dict(identity=identity, config_sha256=digest, **result), f, default=str)
                except BaseException:
                    import traceback
                    traceback.print_exc()
                    os._exit(1)
                os._exit(0)
            if os.waitpid(pid, 0)[1]:
                raise SystemExit(1)
        raise SystemExit(0)

    runtime._run_seed = capture
    runtime.main(['--pack', str(args.registry.parent / package['package']), '--pack-sha256', package['sha256'],
                  '--model', args.model, '--snapshot', str(args.snapshot), '--game', schedule['game_id'],
                  '--games', '1', '--seed-start', str(args.seed), '--out', str(args.out / 'unused.json')])


if __name__ == '__main__':
    main()
