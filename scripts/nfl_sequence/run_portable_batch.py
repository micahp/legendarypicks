#!/usr/bin/env python3
"""Run portable model packs over a set of game snapshots, with the roster preflight before and the postflight after.

Before any run, every snapshot must pass roster_preflight.check (resolved eligible QB1, no unresolved required role,
current depth chart, injury statuses with publish times for this game, weekly-roster membership, no player on two
teams); one FAIL stops the batch before it starts. Every model reads the same snapshot file, so the same resolved roster
hash. After each run, roster_preflight.postflight checks the player box scores: no excluded player got stats and each
team's passer was its resolved QB1. The manifest holds every preflight and postflight table and each run's result.

Usage (on the host with the packs):
  python3.12 run_portable_batch.py --name NAME --snapshots DIR --packs DIR --runtime simulate_portable_pack.py \\
      --out DIR --models v1,v1.5,v1.6,v2,pbv1 --seeds 100 [--games G1,G2] [--parallel 2] [--runtime-workers 2]
"""
from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import roster_preflight  # noqa: E402

HEAVY = {'v1.6'}  # about 2.1 GB each; one at a time on the 11 GB fast host


def sha256_file(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as handle:
        for chunk in iter(lambda: handle.read(8 << 20), b''):
            digest.update(chunk)
    return digest.hexdigest()


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--name', required=True)
    ap.add_argument('--snapshots', required=True, type=Path, help='folder of <game_id>.json runner files')
    ap.add_argument('--packs', required=True, type=Path, help='folder with registry.json and the packs')
    ap.add_argument('--runtime', required=True, type=Path)
    ap.add_argument('--out', required=True, type=Path)
    ap.add_argument('--models', required=True)
    ap.add_argument('--seeds', type=int, required=True)
    ap.add_argument('--seed-start', type=int, default=300001)
    ap.add_argument('--games')
    ap.add_argument('--parallel', type=int, default=1)
    ap.add_argument('--runtime-workers', type=int, default=1)
    ap.add_argument('--python', default='/usr/bin/python3.12')
    args = ap.parse_args(argv)

    models = args.models.split(',')
    registry = {e['model_id']: e for e in json.loads((args.packs / 'registry.json').read_text())['packages']}
    for m in models:
        pack = args.packs / registry[m]['package']
        if sha256_file(pack) != registry[m]['sha256']:
            raise SystemExit(f'PACKAGE_HASH_MISMATCH: {m}')
    files = sorted(f for f in args.snapshots.glob('*.json') if not f.name.endswith('.streak.json') and f.name != 'manifest.json')
    if args.games:
        wanted = set(args.games.split(','))
        files = [f for f in files if f.stem in wanted]
        missing = wanted - {f.stem for f in files}
        if missing:
            raise SystemExit(f'NO_SNAPSHOT: {sorted(missing)}')

    snapshots, preflight, blocked = {}, {}, []
    for f in files:
        snap = json.loads(f.read_text())
        rows, resolved = roster_preflight.check(snap)
        frozen = roster_preflight.unwrap(snap).get('roster_resolution')
        rows.append(('frozen roster resolution matches', 'PASS' if frozen and frozen['content_hash'] == resolved['content_hash'] else 'FAIL',
                     resolved['content_hash'][:12]))
        print(roster_preflight.render(f'PREFLIGHT {f.stem}', rows), flush=True)
        preflight[f.stem] = {'file': str(f), 'file_sha256': sha256_file(f), 'roster_resolution_hash': resolved['content_hash'],
                             'rows': rows}
        snapshots[f.stem] = (f, snap, resolved)
        if roster_preflight.failed(rows):
            blocked.append(f.stem)
    args.out.mkdir(parents=True, exist_ok=True)
    manifest_path = args.out / f'manifest.{args.name}.json'
    manifest = {'schema': 'lp-slc-portable-batch-2', 'name': args.name, 'snapshots': str(args.snapshots), 'models': models,
                'seeds_per_game_model': args.seeds, 'seed_start': args.seed_start, 'runtime': str(args.runtime),
                'packages': {m: {k: registry[m][k] for k in ('sha256', 'code_commit', 'package')} for m in models},
                'preflight': preflight, 'runs': [], 'status': 'blocked' if blocked else 'running'}
    lock = threading.Lock()

    def save():
        tmp = manifest_path.with_suffix('.tmp')
        tmp.write_text(json.dumps(manifest, indent=1, sort_keys=True) + '\n')
        os.replace(tmp, manifest_path)

    save()
    if blocked:
        raise SystemExit(f'PREFLIGHT_FAILED, nothing run: {blocked}')

    heavy = threading.Semaphore(1)

    def run(game, model):
        f, snap, resolved = snapshots[game]
        folder = args.out / game
        folder.mkdir(parents=True, exist_ok=True)
        output, log = folder / f'{model}.json', folder / f'{model}.log'
        if output.exists():
            return {'game_id': game, 'model': model, 'status': 'skipped_existing_output', 'output': str(output)}
        entry = registry[model]
        cmd = [args.python, str(args.runtime), '--model', model, '--game', game, '--snapshot', str(f),
               '--pack', str(args.packs / entry['package']), '--pack-sha256', entry['sha256'], '--games', str(args.seeds),
               '--seed-start', str(args.seed_start), '--out', str(output), '--workers', str(args.runtime_workers)]
        start = time.time()
        with log.open('x') as handle:
            proc = subprocess.run(cmd, stdout=handle, stderr=subprocess.STDOUT,
                                  env=dict(os.environ, OMP_NUM_THREADS='1', OPENBLAS_NUM_THREADS='1'))
        data = json.loads(output.read_text()) if output.exists() else {}
        post = roster_preflight.postflight(snap, data, resolved) if data else [('run wrote output', 'FAIL', f'exit {proc.returncode}')]
        ok = proc.returncode == 0 and data.get('simulation', {}).get('requested_games') == args.seeds
        status = 'completed' if ok and not roster_preflight.failed(post) else 'failed_postflight' if ok else 'failed'
        return {'game_id': game, 'model': model, 'status': status, 'returncode': proc.returncode,
                'valid_full_games': data.get('simulation', {}).get('valid_full_games'), 'postflight': post,
                'elapsed_seconds': round(time.time() - start, 1), 'output': str(output), 'log': str(log)}

    def job(game, model):
        if model in HEAVY:
            with heavy:
                result = run(game, model)
        else:
            result = run(game, model)
        with lock:
            manifest['runs'].append(result)
            save()
        bad = roster_preflight.failed(result.get('postflight', []))
        print(time.strftime('%FT%TZ', time.gmtime()), game, model, result['status'], result.get('valid_full_games'),
              '; '.join(f'{n}: {d}' for n, _, d in bad), flush=True)

    with concurrent.futures.ThreadPoolExecutor(max_workers=args.parallel) as pool:
        for future in [pool.submit(job, g, m) for g in snapshots for m in models]:
            future.result()
    manifest['status'] = 'completed' if all(r['status'] in ('completed', 'skipped_existing_output') for r in manifest['runs']) \
        else 'completed_with_failures'
    save()
    print('BATCH_DONE', args.name, manifest['status'], flush=True)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
