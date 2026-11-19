"""Run the remaining Week 10 audit games with more parallel jobs. Same argv and environment as run_audit.py.
Skips the two finished games and HOU_CLE, which the first runner is still finishing."""
import glob, json, os, subprocess, time
from concurrent.futures import ThreadPoolExecutor

OUT = '/root/tnf-batch/audit'
ARMS = ['B-field', 'C-field-pbv1']
SKIP = {'2026_10_BUF_NYJ', '2026_10_CAR_NO', '2026_10_HOU_CLE'}


def job(game, arm):
    base = f'/root/tnf-batch/w10-eval/{game}/out'
    cmd = json.load(open(glob.glob(f'{base}/runs/{arm}/*.command.json')[0]))
    argv = cmd['argv']
    i = argv.index('--out')
    out_dir = f'{OUT}/{game}/{arm}'
    os.makedirs(out_dir, exist_ok=True)
    argv = argv[:i] + ['--out', f'{out_dir}/run.json'] + argv[i + 2:]
    t = time.time()
    r = subprocess.run(['/usr/bin/python3', f'{OUT}/choice_harness.py', f'{out_dir}/choices.json.gz'] + argv[2:],
                       cwd=f'{base}/runtime-{arm}', env=dict(cmd['env']), capture_output=True, text=True)
    return game, arm, r.returncode, round(time.time() - t), (r.stderr or '')[-200:]


games = sorted(os.path.basename(p) for p in glob.glob('/root/tnf-batch/w10-eval/2026_10_*'))
todo = [(g, a) for g in games if g not in SKIP for a in ARMS]
with open(f'{OUT}/run_rest.log', 'a') as log, ThreadPoolExecutor(max_workers=4) as pool:
    for game, arm, rc, secs, err in pool.map(lambda x: job(*x), todo):
        log.write(f'{game} {arm} rc={rc} {secs}s {err.strip()[-120:]}\n')
        log.flush()
open(f'{OUT}/DONE_REST', 'w').write('done\n')
