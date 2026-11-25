"""Run one V2 ablation arm over every week 11 game in one process: the pack is decoded once and reused per game.

Usage: ABLATION_ARM=A00_control python3.12 run_arm.py --out DIR --seeds 100 --workers 3 [--games G1,G2]
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import simulate_portable_pack as spp  # noqa: E402

PACK = Path('/root/runs/week-11/inputs/models/portable-models-2026-11-19/v2--season-2026-runtimefix1.slcpkg')
PACK_SHA = '97c4a01e9a60c3f6e31c1701d4c954fddd5d6e9938c193bd1aba9218c7d7f5c3'
SNAPSHOTS = Path('/root/runs/week-11/snapshots/rerun-preflight-2026-11-23')
SEED_START = 300001  # the frozen V2 week 11 preflight rerun's seeds

_cache = {}
_real_load = spp.load_pack


def cached_load_pack(*args, **kwargs):
    """Return the pack the parent decoded before forking. Each game runs in its own forked child, so every game starts
    from the parent's untouched copy (copy-on-write): no state carries from one game to the next.

    Reusing one decoded reference across games in one process leaked state (IND at HOU, run 4th, matched the frozen V2
    on 0 of 20 seeds; run alone it matched)."""
    if 'pack' not in _cache:
        _cache['pack'] = _real_load(*args, **kwargs)
    return _cache['pack']


spp.load_pack = cached_load_pack


class _KeptDirectory:
    """The runner extracts the engine into a temporary folder and deletes it after each game; the cached pack's
    modules live there, so one folder is kept for the whole process and removed at exit."""
    path = None

    def __init__(self, prefix=None, **_kwargs):
        if _KeptDirectory.path is None:
            import atexit
            import shutil
            import tempfile
            _KeptDirectory.path = tempfile.mkdtemp(prefix=prefix or 'slc-ablation-engine-')
            atexit.register(shutil.rmtree, _KeptDirectory.path, True)

    def __enter__(self):
        return _KeptDirectory.path

    def __exit__(self, *exc):
        return False


class _TempfileShim:
    TemporaryDirectory = _KeptDirectory

    def __getattr__(self, name):
        import tempfile
        return getattr(tempfile, name)


spp.tempfile = _TempfileShim()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--out', required=True, type=Path)
    ap.add_argument('--arms', required=True, help='comma-separated arm names, run in order with one loaded pack')
    ap.add_argument('--seeds', type=int, default=100)
    ap.add_argument('--workers', type=int, default=3)
    ap.add_argument('--games', default='')
    args = ap.parse_args()
    games = args.games.split(',') if args.games else sorted(
        p.name[:-5] for p in SNAPSHOTS.glob('2026_11_*.json') if p.name.count('.') == 1)
    for arm in args.arms.split(','):
        out = args.out / arm
        out.mkdir(parents=True, exist_ok=True)
        os.environ['ABLATION_ARM'] = arm
        os.environ['ABLATION_STATS_OUT'] = str(out / 'stats')
        status_path = out / 'status.json'
        status = json.loads(status_path.read_text()) if status_path.exists() else []
        for game in games:
            target = out / f'{game}.json'
            if target.exists():
                continue
            start = time.time()
            if 'pack' not in _cache:  # decode once in the parent, which never runs a game itself
                from slc_model_registry import get_model
                with spp.tempfile.TemporaryDirectory(prefix='slc-model-runtime-') as engine_dir:
                    cached_load_pack(PACK, expected_sha256=PACK_SHA, expected_code_commit=get_model('v2')['code_commit'],
                                     engine_dir=Path(engine_dir))
            sys.stdout.flush()
            child = os.fork()
            if child == 0:  # the game runs in a child process
                try:
                    rc = spp.main(['--model', 'v2', '--game', game, '--snapshot', str(SNAPSHOTS / f'{game}.json'),
                             '--pack', str(PACK), '--pack-sha256', PACK_SHA, '--games', str(args.seeds),
                                   '--seed-start', str(SEED_START), '--out', str(target), '--workers', str(args.workers)])
                except BaseException as exc:  # noqa: BLE001  a failed game is recorded, the batch goes on
                    print(f'game {game} failed: {exc!r}', flush=True)
                    rc = 1
                sys.stdout.flush()
                os._exit(int(rc or 0))
            _, wait_status = os.waitpid(child, 0)
            code = os.waitstatus_to_exitcode(wait_status)
            status.append({'game': game, 'returncode': code, 'seconds': round(time.time() - start, 1)})
            status_path.write_text(json.dumps(status, indent=1) + '\n')
            print(json.dumps({'arm': arm, **status[-1]}), flush=True)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
