# Draw diagnostic: BUF at NYJ, three seeds, arms A, B and C

What it checks: whether arms that share a stream root also get the same value for each draw they both request.
It runs the batch in-process through `code/harness.py`, which wraps the draw functions and returns exactly what they
would. Each arm runs seeds 300001 to 300003 with its own flags. Logs are in `logs/` (gzipped).

## Result

| Pair | Draws (A vs B, or B vs C) | Shared draw keys | Shared keys with equal value | Keys only in one arm |
|---|---|---|---|---|
| A vs B | 2825 vs 3599 | 1210 | 1210 | A 1615, B 2389 |
| B vs C | 3599 vs 3162 | 1840 | 1840 | B 1759, C 1322 |
| A vs C | 2825 vs 3162 | 1242 | 1242 | A 1583, C 1920 |

First divergent play, per seed:

| Pair | Seed 300001 | Seed 300002 | Seed 300003 |
|---|---|---|---|
| A vs B | 21 | 33 | 20 |
| B vs C | 49 | 46 | 20 |
| A vs C | 21 | 33 | 51 |

## What this shows

- **Same key, same value.** Every draw key that two arms both request gives the same number in both arms. This holds for
  every pair. The streams are aligned where the arms ask for the same draw.
- **The arms do not ask for the same draws.** Arm B adds `field:group` and `field:advance` draws. Arm C adds
  `field:advance` but not `field:group`, because the PBV1 package sets the grouping. Changed lineups and changed game
  states change which later draws are requested.
- **The first divergent play comes after play 20.** Before that, the plays match between arms. This fits the arms sharing
  draws until a decision changes.

## What this does not show

- It does not show that the same draw leads to the same choice. The same number can select a different player when the
  candidate list is different. Checking that needs the per-play choices, which the audit re-run records.
- It covers three seeds of one game. It is a diagnostic, not a test across the slate.
- Three draw seeds in the logs are large numbers, not 300001 to 300020. They come from the paired stream seed of the
  game-level streams. I have not traced where those seeds come from.

## Relation to the RNG flags

None of these runs set `--paired-randomness`. V2 turns on the named paired streams for every run, so the flag is not
needed. The output field `paired_randomness: false` records only the explicit flag.

## Reproduce

`code/run_diag.py` runs the three arms with the harness. It reads the command records from the Week 10 runs. Then
`code/compare_keys.py LOGDIR` prints the table above from `logs/`. The logs were unzipped into one folder before the
comparison.
