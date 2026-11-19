"""Re-run arms B and C for all 14 Week 10 games through the choice harness. Same argv and environment as the original runs,
only the output folder differs. Two arms at a time; games in order."""
import glob, json, os, subprocess, time
from concurrent.futures import ThreadPoolExecutor

OUT = '/root/tnf-batch/audit'
ARMS = ['B-field', 'C-field-pbv1']


def job(game, arm):
    base = f'/root/tnf-batch/w10-eval/{game}/out'
    cmd = json.load(open(glob.glob(f'{base}/runs/{arm}/*.command.json')[0]))
    argv = cmd['argv']
    i = argv.index('--out')
    out_dir = f'{OUT}/{game}/{arm}'
    os.makedirs(out_dir, exist_ok=True)
    argv = argv[:i] + ['--out', f'{out_dir}/run.json'] + argv[i + 2:]
    r = subprocess.run(['/usr/bin/python3', f'{OUT}/choice_harness.py', f'{out_dir}/choices.json.gz'] + argv[2:],
                       cwd=f'{base}/runtime-{arm}', env=dict(cmd['env']), capture_output=True, text=True)
    return game, arm, r.returncode, (r.stderr or '')[-200:]


games = sorted(os.path.basename(p) for p in glob.glob('/root/tnf-batch/w10-eval/2026_10_*'))
with open(f'{OUT}/run.log', 'a') as log:
    for game in games:
        t = time.time()
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda a: job(game, a), ARMS))
        for g, a, rc, err in results:
            log.write(f'{g} {a} rc={rc} {err.strip()[-120:]}\n')
        log.write(f'{game} done {round(time.time() - t)}s\n')
        log.flush()
log.close()
open(f'{OUT}/DONE', 'w').write('done\n')
