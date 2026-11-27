#!/usr/bin/env python3
"""Run portable model packs over a set of game snapshots, with the roster preflight before and the postflight after.

Before any run, every snapshot must pass roster_preflight.check (resolved eligible QB1, no unresolved required role,
current depth chart, injury statuses with publish times for this game, weekly-roster membership, no player on two
teams), and every excluded player must be Out in the injury report; one FAIL stops the batch before it starts. Then a
smoke test runs one seed for every game and model into <out>/smoke with the same postflight; any failure stops the batch
before the full runs. Every model reads the same snapshot file, so the same resolved roster
hash. After each run, roster_preflight.postflight checks the player box scores: no excluded player got stats and each
team's passer was its resolved QB1. The manifest holds every preflight and postflight table and each run's result.

Usage (on the host with the packs):
  python3.12 run_portable_batch.py --name NAME --snapshots DIR --packs DIR --runtime simulate_portable_pack.py \\
      --out DIR --models v1,v1.5,v1.6,v2,pbv1 --seeds 100 [--games G1,G2 (run in this order)] [--parallel 2] [--runtime-workers 2]
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

sys.path[:0] = [str(Path(__file__).resolve().parent), str(Path(__file__).resolve().parents[2])]
import roster_preflight  # noqa: E402
import pregame_snapshot  # noqa: E402
from prop_identity import validated_priced_qbs  # noqa: E402

HEAVY = {'v1.6'}  # about 2.1 GB each; one at a time on the 11 GB fast host


def sha256_file(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as handle:
        for chunk in iter(lambda: handle.read(8 << 20), b''):
            digest.update(chunk)
    return digest.hexdigest()


def validate_run(data, requested, seed_start, game, model, pack_sha, snapshot_sha, *, score_only=False):
    """Validate actual completed seed census, not requested count or exit status."""
    sim = data.get('simulation') or {}
    summary = data.get('summary') or {}
    rows = summary.get('outcomes')
    expected = set(range(seed_start, seed_start + requested))
    identity = (data.get('snapshot_verified') is True and data.get('run_class') == 'verified_snapshot_batch'
                and data.get('run_status') == 'complete'
                and data.get('game_id') == game and data.get('snapshot_sha256') == snapshot_sha
                and (data.get('pack') or {}).get('model_id') == model
                and (data.get('pack') or {}).get('sha256') == pack_sha)
    census = (isinstance(rows, list) and len(rows) == requested
              and all(isinstance(row, dict) and type(row.get('seed')) is int for row in rows)
              and {row['seed'] for row in rows} == expected)
    valid = (census and all(row.get('valid_full_game') is True and row.get('complete_game') is True
                           and row.get('score_scope') == 'valid_final'
                           and type(row.get('home_points')) is int and row['home_points'] >= 0
                           and type(row.get('away_points')) is int and row['away_points'] >= 0
                           for row in rows))
    counts = (sim.get('requested_games') == requested and sim.get('attempted_games') == requested
              and sim.get('valid_full_games') == requested
              and summary.get('valid_full_games') == requested and sim.get('seed_start') == seed_start
              and sim.get('seed_end_inclusive') == seed_start + requested - 1)
    boxes = data.get('player_boxscores_by_seed') or []
    box_census = (isinstance(boxes, list) and len(boxes) == requested
                  and all(isinstance(row, dict) and type(row.get('seed')) is int and isinstance(row.get('players'), list)
                          for row in boxes)
                  and {row['seed'] for row in boxes} == expected)
    rows = [('run identity', 'PASS' if identity else 'FAIL', 'game, snapshot and pack'),
            ('requested seed census', 'PASS' if census else 'FAIL', str(requested)),
            ('all games valid and complete', 'PASS' if valid and counts else 'FAIL',
             f"{sim.get('valid_full_games')}/{requested}")]
    if score_only:
        rows.append(('score-only capability', 'PASS' if data.get('player_lines_available') is False and not boxes
                     else 'FAIL', 'explicit score-only output required'))
    else:
        rows.append(('player box score seed census', 'PASS' if box_census else 'FAIL', str(requested)))
    return rows


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
    if (args.seeds < 1 or args.seed_start < 0 or args.parallel < 1 or args.runtime_workers < 1
            or not all(models) or len(set(models)) != len(models)):
        ap.error('positive seed count, nonnegative start and unique model IDs required')
    registry = {e['model_id']: e for e in json.loads((args.packs / 'registry.json').read_text())['packages']}
    for m in models:
        pack = args.packs / registry[m]['package']
        if sha256_file(pack) != registry[m]['sha256']:
            raise SystemExit(f'PACKAGE_HASH_MISMATCH: {m}')
    files = sorted(f for f in args.snapshots.glob('*.json') if not f.name.endswith('.streak.json') and f.name != 'manifest.json')
    if args.games:
        # run in the order given, so a game that has not kicked off yet can go first
        order = args.games.split(',')
        if len(set(order)) != len(order):
            raise SystemExit('DUPLICATE_GAME_SELECTION')
        by_name = {f.stem: f for f in files}
        missing = [g for g in order if g not in by_name]
        if missing:
            raise SystemExit(f'NO_SNAPSHOT: {missing}')
        files = [by_name[g] for g in order]

    if not files:
        raise SystemExit('NO_SNAPSHOT: no games selected')
    snapshots, preflight, blocked = {}, {}, []
    for f in files:
        snap = json.loads(f.read_text())
        sealed = pregame_snapshot.load_frozen_snapshot(str(f))
        if sealed['schedule']['game_id'] != f.stem:
            raise SystemExit(f'SNAPSHOT_GAME_ID_MISMATCH: {f}')
        if (sealed.get('evaluation') or {}).get('verified') is not True:
            raise SystemExit(f'SNAPSHOT_UNVERIFIED: {f}; no forecast seeds run')
        rows, resolved = roster_preflight.check(snap, validated_priced_qbs(sealed))
        frozen = roster_preflight.unwrap(snap).get('roster_resolution')
        rows.append(('frozen roster resolution matches', 'PASS' if frozen and frozen['content_hash'] == resolved['content_hash'] else 'FAIL',
                     resolved['content_hash'][:12]))
        rows.append(roster_preflight.exclusions_applied(snap, resolved))
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
                'packages': {m: {**{k: registry[m][k] for k in ('sha256', 'code_commit', 'package')},
                                 'player_lines_available': registry[m].get('player_lines_available') is not False}
                             for m in models},
                'preflight': preflight, 'runs': [], 'status': 'blocked' if blocked else 'running'}
    lock = threading.Lock()

    def save():
        tmp = manifest_path.with_suffix('.tmp')
        tmp.write_text(json.dumps(manifest, indent=1, sort_keys=True) + '\n')
        os.replace(tmp, manifest_path)

    if manifest_path.exists():
        raise SystemExit(f'EXISTING_BATCH_MANIFEST: use a fresh output directory or name: {manifest_path}')
    # Exclusive creation prevents concurrent replacement of an existing manifest.
    with manifest_path.open('x') as handle:
        handle.write(json.dumps(manifest, indent=1, sort_keys=True) + '\n')
    if blocked:
        raise SystemExit(f'PREFLIGHT_FAILED, nothing run: {blocked}')

    heavy = threading.Semaphore(1)

    def run(game, model, seeds=args.seeds, root=args.out):
        f, snap, resolved = snapshots[game]
        folder = root / game
        folder.mkdir(parents=True, exist_ok=True)
        output, log = folder / f'{model}.json', folder / f'{model}.log'
        if output.exists() or log.exists():
            return {'game_id': game, 'model': model, 'status': 'existing_output_refused', 'output': str(output)}
        entry = registry[model]
        score_only = entry.get('player_lines_available') is False
        if sha256_file(f) != preflight[game]['file_sha256']:
            return {'game_id': game, 'model': model, 'status': 'snapshot_changed_after_preflight'}
        cmd = [args.python, str(args.runtime), '--model', model, '--game', game, '--snapshot', str(f),
               '--pack', str(args.packs / entry['package']), '--pack-sha256', entry['sha256'], '--games', str(seeds),
               '--seed-start', str(args.seed_start), '--out', str(output), '--workers', str(args.runtime_workers)]
        if score_only:
            cmd.append('--no-player-lines')
        start = time.time()
        with log.open('x') as handle:
            proc = subprocess.run(cmd, stdout=handle, stderr=subprocess.STDOUT,
                                  env=dict(os.environ, OMP_NUM_THREADS='1', OPENBLAS_NUM_THREADS='1'))
        try:
            data = json.loads(output.read_text()) if output.exists() else {}
            if not isinstance(data, dict):
                raise ValueError('run output must be an object')
        except (ValueError, OSError) as exc:
            return {'game_id': game, 'model': model, 'status': 'failed_postflight',
                    'returncode': proc.returncode, 'postflight': [('run output readable', 'FAIL', str(exc))],
                    'output': str(output), 'log': str(log)}
        post = validate_run(data, seeds, args.seed_start, game, model, entry['sha256'],
                            roster_preflight.unwrap(snap)['snapshot_sha256'], score_only=score_only)
        if not roster_preflight.failed(post):
            post += roster_preflight.postflight(snap, data, resolved, score_only=score_only)
        failures = [row for row in post if row[1] != 'PASS' and not (score_only and row[1] == 'NOT_APPLICABLE')]
        ok = proc.returncode == 0 and not failures
        status = ('completed_score_only' if score_only else 'completed') if ok else 'failed_postflight' if proc.returncode == 0 else 'failed'
        return {'game_id': game, 'model': model, 'status': status, 'returncode': proc.returncode,
                'player_lines_available': not score_only,
                'valid_full_games': data.get('simulation', {}).get('valid_full_games'), 'postflight': post,
                'elapsed_seconds': round(time.time() - start, 1), 'output': str(output), 'log': str(log)}

    def job(game, model, smoke=False):
        kwargs = {'seeds': 1, 'root': args.out / 'smoke'} if smoke else {}
        if model in HEAVY:
            with heavy:
                result = run(game, model, **kwargs)
        else:
            result = run(game, model, **kwargs)
        with lock:
            manifest['smoke' if smoke else 'runs'].append(result)
            save()
        bad = [row for row in result.get('postflight', []) if row[1] == 'FAIL']
        print(time.strftime('%FT%TZ', time.gmtime()), game, model, result['status'], result.get('valid_full_games'),
              '; '.join(f'{n}: {d}' for n, _, d in bad), flush=True)

    # smoke test: first requested seed for every game and model, before any full run
    manifest['smoke'] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.parallel) as pool:
        for future in [pool.submit(job, g, m, True) for g in snapshots for m in models]:
            future.result()
    bad_smoke = [f"{r['game_id']} {r['model']}" for r in manifest['smoke'] if r['status'] not in ('completed', 'completed_score_only')]
    if bad_smoke:
        manifest['status'] = 'blocked_by_smoke_test'
        save()
        raise SystemExit(f'SMOKE_TEST_FAILED, no full run started: {bad_smoke}')
    print('SMOKE_TEST_PASSED', len(manifest['smoke']), 'runs', flush=True)

    with concurrent.futures.ThreadPoolExecutor(max_workers=args.parallel) as pool:
        for future in [pool.submit(job, g, m) for g in snapshots for m in models]:
            future.result()
    manifest['status'] = 'completed' if all(r['status'] in ('completed', 'completed_score_only') for r in manifest['runs']) \
        else 'completed_with_failures'
    save()
    print('BATCH_DONE', args.name, manifest['status'], flush=True)
    return 0 if manifest['status'] == 'completed' else 1


if __name__ == '__main__':
    raise SystemExit(main())
