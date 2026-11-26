# Week 10 audit rerun: choice records for arms B and C

This folder holds the code for the audit rerun. The rerun re-simulates arms B-field and C-field-pbv1 for all 14 Week 10
games with the same argv and environment as the original 20-seed runs. The only change is a choice harness that writes
each decision to a gzipped record. Results are unchanged.

## Result

- **Box scores match.** All 28 game-arm `run.boxscores.jsonl` files are byte-identical to the original runs in
  `/root/tnf-batch/w10-eval/<game>/out/runs/<arm>/`.
- **Complete.** 28 of 28 game-arm outputs exist. Each has `choices.json.gz`, `run.json` and `run.boxscores.jsonl`.
- **Errors.** No job exited non-zero.

## What the records hold

`choice_harness.py` wraps `pre_event.choose`, `pre_event._draw` and `random.Random.choices`. Each record holds:

- Per play: seed, play index, side, team, intent, passer, rusher and receiver GSIS ids and positions, lineup group,
  lineup status, on-field flag, slots, and grouping source.
- Per named draw: the draw key, candidate ids, candidate weights, and the chosen id.

The records are about 586 MB in total. They stay on the fast host and are not in git.

## Where things are

- Fast host: `root@89.117.145.232:/root/tnf-batch/audit/<game>/<arm>/` (choices, run output, box scores).
- First runner: `run_audit.py`, log `/root/tnf-batch/audit/run.log`. It ran BUF_NYJ and CAR_NO and started HOU_CLE.
  Its parent process was stopped after HOU_CLE started. HOU_CLE's two jobs finished, but their log line is missing from
  `run.log`. Their outputs are complete and match the original box scores.
- Second runner: `run_audit_rest.py`, log `/root/tnf-batch/audit/run_rest.log`. It ran the other 11 games, four jobs at a
  time, all with rc=0. Done marker: `DONE_REST`.

## Not done yet

The allocation audit is not written. It still needs: the per-play lineup check, the candidate-weight analysis, the
first divergent decision for each seed, the carry and target reconciliation, and the paired score differences.

## Code

- `code/choice_harness.py`: the harness that writes the records.
- `code/run_audit.py`: first runner (games in order, two arms at once).
- `code/run_audit_rest.py`: second runner (remaining games, four jobs at once).
