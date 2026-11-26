"""Week 10 participation experiment: four new arms on the same snapshots and seeds as the existing B and C arms.

H    field with player leave hazards (leave_power 1.5), no snap counts, no PBV1
HS   H plus current-season snap counts through week 9
HP   H plus the PBV1 package
HSP  HS plus the PBV1 package
Bcheck  the existing B-field command with the logging harness only, to confirm the harness changes no result.

Each command is the existing B-field (H, HS, Bcheck) or C-field-pbv1 (HP, HSP) record for that game, with only the
participation field file and its checksum changed, and the snap-count flags added for HS and HSP. The runtime tree for
the matching arm is used. Output: /root/tnf-batch/camp/<arm>/<game>/ (run.json, box scores, choices, command.json).
"""
import glob, hashlib, json, os, subprocess, time
from concurrent.futures import ThreadPoolExecutor

W10 = '/root/tnf-batch/w10-eval'
OUT = '/root/tnf-batch/camp'
HARNESS = OUT + '/choice_harness_v2.py'
FIELD = '/root/tnf-batch/field/out/field_lp15.json'
SNAP = '/root/tnf-batch/field/out/snapcounts_2026_w9.json'
ARMS = {'H': ('B-field', 'field'), 'HS': ('B-field', 'snap'), 'HP': ('C-field-pbv1', 'field'),
        'HSP': ('C-field-pbv1', 'snap'), 'Bcheck': ('B-field', None)}


def sha(path):
    with open(path, 'rb') as f:
        return hashlib.sha256(f.read()).hexdigest()


FIELD_SHA = sha(FIELD)
SNAP_SHA = sha(SNAP)


def new_argv(argv, mode):
    a = list(argv)
    if mode is None:
        return a
    i = a.index('--participation-field')
    a[i + 1] = FIELD
    j = a.index('--participation-field-sha256')
    a[j + 1] = FIELD_SHA
    if mode == 'snap':
        a += ['--participation-snap-counts', SNAP, '--participation-snap-counts-sha256', SNAP_SHA]
    return a


def job(game, arm):
    base_arm, mode = ARMS[arm]
    base = f'{W10}/{game}/out'
    cmd = json.load(open(glob.glob(f'{base}/runs/{base_arm}/*.command.json')[0]))
    argv = new_argv(cmd['argv'], mode)
    i = argv.index('--out')
    out_dir = f'{OUT}/{arm}/{game}'
    os.makedirs(out_dir, exist_ok=True)
    argv = argv[:i] + ['--out', f'{out_dir}/run.json'] + argv[i + 2:]
    with open(f'{out_dir}/command.json', 'w') as f:
        json.dump({'arm': arm, 'base_arm': base_arm, 'game': game, 'argv': argv, 'field_sha256': FIELD_SHA,
                   'snap_sha256': SNAP_SHA if mode == 'snap' else None}, f, indent=1)
    t = time.time()
    r = subprocess.run(['/usr/bin/python3', HARNESS, f'{out_dir}/choices.json.gz'] + argv[2:],
                       cwd=f'{base}/runtime-{base_arm}', env=dict(cmd['env']), capture_output=True, text=True)
    return game, arm, r.returncode, round(time.time() - t), (r.stderr or '')[-300:]


if __name__ == '__main__':
    games = sorted(os.path.basename(p) for p in glob.glob(f'{W10}/2026_10_*'))
    jobs = [('2026_10_KC_ATL', 'Bcheck')] + [(g, a) for a in ['H', 'HS', 'HP', 'HSP'] for g in games]
    os.makedirs(OUT, exist_ok=True)
    with open(f'{OUT}/campaign.log', 'a') as log, ThreadPoolExecutor(max_workers=4) as pool:
        for game, arm, rc, secs, err in pool.map(lambda x: job(*x), jobs):
            log.write(f'{arm} {game} rc={rc} {secs}s {err.strip()[-200:]}\n')
            log.flush()
    with open(f'{OUT}/DONE', 'w') as f:
        f.write('done\n')
