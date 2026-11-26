import glob, json, os, subprocess
G = '2026_10_BUF_NYJ'
for arm in ['A-control', 'B-field', 'C-field-pbv1']:
    base = f'/root/tnf-batch/w10-eval/{G}/out'
    cmd = json.load(open(glob.glob(f'{base}/runs/{arm}/*.command.json')[0]))
    argv = cmd['argv']
    i = argv.index('--out'); argv = argv[:i] + ['--out', f'/root/tnf-batch/rngdiag/{arm}.json'] + argv[i + 2:]
    j = argv.index('--games'); argv[j + 1] = '3'
    env = dict(cmd['env'])
    cwd = f'{base}/runtime-{arm}'
    log = f'/root/tnf-batch/rngdiag/{arm}.draws.json'
    r = subprocess.run(['/usr/bin/python3', '/root/tnf-batch/rngdiag/harness.py', log] + argv[2:],
                       cwd=cwd, env=env, capture_output=True, text=True)
    print(arm, 'rc', r.returncode, (r.stderr or '')[-300:], flush=True)
