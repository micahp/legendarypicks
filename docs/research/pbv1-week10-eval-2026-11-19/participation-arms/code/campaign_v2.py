"""SLC v2 with PBV1 and V1.5 season weighting. Base: the existing C-field-pbv1 command for each game (PBV1 package, the
existing participation field, protocol v2). Added: --slc-v2 (turns on season adaptation, RNG v2 and the v2 layers) and the
2026 snap counts through week 9, which --slc-v2 requires. The field stays field_v4_2022_2025 so only the v2 layers differ.
Caveat: --slc-v2 also loads the default field-goal kicker table, which the other arms do not use."""
import glob, json, os, subprocess, sys, time
import campaign as c

OUT = c.OUT + '/V2P'
KICKER = '/root/tnf-batch/kicker/kicker_table_through_2026_w10.json'
KICKER_SHA = '7d53cda1cd27774eb67e6a59219955657e26f27f5fed008f2d89ddf86383b13f'


def v2_argv(argv):
    return list(argv) + ['--slc-v2', '--participation-snap-counts', c.SNAP, '--participation-snap-counts-sha256', c.SNAP_SHA,
                         '--playcall-fg-kicker', KICKER, '--playcall-fg-kicker-sha256', KICKER_SHA]


def job(game, games=None, out_root=OUT):
    base = f'{c.W10}/{game}/out'
    cmd = json.load(open(glob.glob(f'{base}/runs/C-field-pbv1/*.command.json')[0]))
    argv = v2_argv(cmd['argv'])
    if games is not None:
        argv[argv.index('--games') + 1] = str(games)
    i = argv.index('--out')
    out_dir = f'{out_root}/{game}'
    os.makedirs(out_dir, exist_ok=True)
    argv = argv[:i] + ['--out', f'{out_dir}/run.json'] + argv[i + 2:]
    with open(f'{out_dir}/command.json', 'w') as f:
        json.dump({'arm': 'V2P', 'base_arm': 'C-field-pbv1', 'game': game, 'argv': argv,
                   'snap_sha256': c.SNAP_SHA}, f, indent=1)
    t = time.time()
    r = subprocess.run(['/usr/bin/python3', c.HARNESS, f'{out_dir}/choices.json.gz'] + argv[2:],
                       cwd=f'{base}/runtime-C-field-pbv1', env=dict(cmd['env']), capture_output=True, text=True)
    return game, r.returncode, round(time.time() - t), (r.stderr or '')[-600:]


if __name__ == '__main__':
    if sys.argv[1] == 'smoke':
        g, rc, secs, err = job('2026_10_KC_ATL', games=2, out_root='/root/tnf-batch/camp/V2Psmoke')
        print('smoke rc', rc, secs, 's')
        print(err)
