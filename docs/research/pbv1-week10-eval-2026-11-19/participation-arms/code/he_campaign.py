"""Arm HE: the HS command plus --participation-entry-current-season. One change only: the bench draw weights each player by
his current-season share of team snaps (fallback: table rate). Code: runtime-HE per game = HS code with the four changed
files. Output: /root/tnf-batch/camp/HE/<game>/."""
import glob, json, os, subprocess, sys, time
from concurrent.futures import ThreadPoolExecutor
import campaign as c

W10 = c.W10
OUT = c.OUT + '/HE'
NEW = {'participation_field.py': '/tmp/he_participation_field.py', 'snap_update.py': '/tmp/he_snap_update.py',
       'slc_engine.py': '/tmp/he_slc_engine.py', 'simulate_pregame_batch.py': '/tmp/he_simulate_pregame_batch.py'}


def build_runtime(game):
    base = f'{W10}/{game}/out/runtime-B-field'
    rt = f'{W10}/{game}/out/runtime-HE'
    if not os.path.isdir(rt + '/scripts'):
        os.makedirs(rt, exist_ok=True)
        subprocess.run(['cp', '-r', f'{base}/scripts', rt + '/'], check=True)
        for e in os.listdir(base):
            if e != 'scripts' and not os.path.exists(f'{rt}/{e}'):
                os.symlink(f'{base}/{e}', f'{rt}/{e}')
    for name, src in NEW.items():
        subprocess.run(['cp', src, f'{rt}/scripts/nfl_sequence/{name}'], check=True)
    return rt


def job(game, games=None, out_root=OUT):
    rt = build_runtime(game)
    cmd = json.load(open(f'{c.OUT}/HS/{game}/command.json'))
    argv = list(cmd['argv']) + ['--participation-entry-current-season']
    if games is not None:
        argv[argv.index('--games') + 1] = str(games)
    i = argv.index('--out')
    out_dir = f'{out_root}/{game}'
    os.makedirs(out_dir, exist_ok=True)
    argv = argv[:i] + ['--out', f'{out_dir}/run.json'] + argv[i + 2:]
    with open(f'{out_dir}/command.json', 'w') as f:
        json.dump({'arm': 'HE', 'base_arm': 'HS', 'game': game, 'argv': argv}, f, indent=1)
    base_env = json.load(open(glob.glob(f'{W10}/{game}/out/runs/B-field/*.command.json')[0]))['env']
    t = time.time()
    r = subprocess.run(['/usr/bin/python3', c.HARNESS, f'{out_dir}/choices.json.gz'] + argv[2:],
                       cwd=rt, env=dict(base_env), capture_output=True, text=True)
    return game, r.returncode, round(time.time() - t), (r.stderr or '')[-600:]


if __name__ == '__main__':
    if sys.argv[1] == 'smoke':
        g, rc, secs, err = job('2026_10_KC_ATL', games=2, out_root='/root/tnf-batch/camp/HEsmoke')
        print('smoke rc', rc, secs, 's')
        print(err)
    elif sys.argv[1] == 'full':
        import glob as gl
        games = sorted(os.path.basename(p) for p in gl.glob(W10 + '/2026_10_*'))
        with open(c.OUT + '/campaign_he.log', 'a') as log, ThreadPoolExecutor(max_workers=6) as pool:
            for game, rc, secs, err in pool.map(lambda g: job(g), games):
                log.write(f'HE {game} rc={rc} {secs}s {err.strip()[-200:]}\n')
                log.flush()
        open(c.OUT + '/DONE_HE', 'w').write('done\n')
