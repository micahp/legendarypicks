# SLC code audit, 2026-11-08

Branch `slc-v2` at `d490757e6`. Three audits, run in parallel over disjoint axes, plus independent verification by the lead of every headline number.

| File | Axis | Findings |
|---|---|---|
| `determinism.md` | What the random streams are keyed on, and whether a run can be reproduced | 2 HIGH |
| `silent-failures.md` | Places that produce plausible-but-wrong output instead of raising | 1 HIGH, 5 MEDIUM, 7 LOW |
| `output-field-integrity.md` | Whether each reported field means what its name says | 2 aliases, 1 near-alias, 4 non-reconciling counters, 2 placeholders, 4 misleading names |

## Verdict

**The engine's outputs claim more than its inputs establish, and the mechanism that would catch that is either disabled, dead, or invisible to the reader.**

Three independent audits converged on that one sentence:

- A roster-legality check cannot fire, because a field the snapshot never carried is written into the output as `true`.
- Reproducibility is keyed on a wall-clock timestamp and on which flags are enabled, so a rebuilt input is a different simulation and a paired ablation is not paired.
- Each "valid" seed carries 368–602 recorded fallback events that no reader-facing table shows.

The good news is that the code is disciplined in the ways the repo's doctrine asks for: no bare excepts, no `assert` used as control flow, no lost exception causes, no global-RNG leakage, no parallelism, and the team-versus-player totals reconcile exactly.

---

## P0 — one already-published claim is weakened

### 1. `roster_eligible` missing becomes `true`, and the legality check can never fire

`slc_outputs.py:81` (input assumption also at `:39`, guard at `:444`):

```python
'roster_eligible': bool(player.get('roster_eligible', True)),
...
if meta is not None and not meta['roster_eligible'] and has_opportunity:   # :444
    raise FootballAssertionError('ILLEGAL_STATE', '... not roster-eligible')
```

The field is optional in the snapshot and defaults to the **permissive** value, so the `ILLEGAL_STATE` refusal is unreachable whenever the snapshot does not carry the field.

I verified this on the committed Sunday bundle myself:

| Artifact | Player rows | Carry `roster_eligible` |
|---|---:|---:|
| 13 smoke snapshots | 497 | **0** |
| 13 smoke boxscores | 497 | **497, all `true`** |

Those 13 seeds report `status: valid_complete` and `valid_full_game: true`. So the roster-eligibility component of that verdict is asserted by the writer, not established by the input. The renderer already has an `unknown` state for this column (`render_week8_matchup_report.py:197-198`); the writer never emits it.

**Fix:** write `None` when the input lacks the field and keep the guard keyed on an explicit `False`. One-line change plus a test that a depth-chart snapshot without the field yields `unknown`, not `true`.

### 2. The RNG key is provenance, so runs cannot be reproduced and the ablation is unpaired

Two defects, same root cause. Full detail in `determinism.md`.

- `pregame_snapshot.py:398` stamps `built_at_utc = datetime.now()` into the snapshot, and `reseal()` (`:78-82`) hashes the whole snapshot. That hash is the default stream key (`simulate_pregame_batch.py:839`, `paired_random_streams.py:25-33`). Reproduced from committed files: advancing `built_at_utc` by one second changed the stream root from `0b8127d053a23183` to `2c37dad78aa8a454` and the first draw from `0.814253003` to `0.559833443`. Hashing the same snapshot without `built_at_utc` gave an identical digest both times.
- `e2_reference.py:130-132` puts `slc-blocker-fixes` into the reference fingerprint, which is also resealed into the snapshot. So enabling `restore_sack_mass` **changes every seed's draws**. Under the default v1 protocol, ablation A's two arms are not paired at all — which invalidates the design in `SPEC.md`, not just its determinism.

The fix already exists: the opt-in v2 protocol keys on the pregame state and the model-input identity, and its `reference_data_sha256` deliberately excludes blocker fixes. `SPEC.md` must mandate `--rng-protocol v2` and record `stream_root_sha256` for both arms, with a pre-run assertion that the two roots are identical.

**This is also the first thing to check about the 14 refusals:** compare `source_snapshot_sha256` in the batch ledger and in the rerun. If they differ, the "non-determinism" was a rebuilt input, not a race.

---

## P1 — reported numbers that are not what their names say

### 3. `possession_seconds` is a sum of drive clock windows, not possession time

`957 of 962` complete-regulation games sum **below** 3,600 s (median 3,575); all 38 overtime games sum **above** it (median 3,984). The only clock advance outside a drive is kickoff runoff, so the field cannot reconcile to the game clock by construction.

Treat it as a diagnostic of drive windows, never as time of possession, and rename it or add the caveat to the model card.

### 4. Two exact aliases and one near-alias

| Field | Reality | Rows |
|---|---|---|
| `targets` | identically `pass_attempts` — the event vocabulary has no throwaway or spike, so every attempt finds a receiver | 2,000/2,000, all arms |
| `red_zone.red_zone_field_goals` | identically `red_zone_field_goal_attempts` — mislabelled column (`slc_outputs.py:112-116`) | 2,000/2,000 |
| `offensive_touchdowns` | near-alias of `touchdowns`, r = 0.997 | — |

I confirmed the first two on `team-stats-v2.csv` independently. Any analysis of target share or red-zone conversion built on these fields is measuring pass volume and attempts respectively.

### 5. `snaps` is a placeholder, and the check that would catch it is dead code

Median 333 per team-seed against a ≥740 expectation; the leading passer records 0 snaps in 2,000/2,000 team-seeds; 2,734 player rows hold production at zero snaps; 75.1% of 51,000 starter rows have zero snaps.

Worse: the snap-versus-production reconciliation added at `slc_outputs.py:587` in HEAD **never runs**, because realism is attached after `reconcile_boxscore` executes. A guard that cannot execute is worse than no guard, because it reads as covered.

### 6. `plays` and `points` do not reconcile, because the events are not in the export

- `plays ≠ pass + rush + sacks` in 192/2,000 V2 rows (357/2,000 V1) — 203 (V2) unlabelled sack-fumble events.
- `points = 6·TD + 3·FG` in only 163/2,000 V2 rows, because no PAT, two-point or safety field is exported.

Both are export gaps, not necessarily engine errors — but they mean the box score cannot be audited from the CSVs, and the bundle documents that field as validated.

### 7. Fallbacks are recorded but invisible where the reader looks

`execution_verification.fallback_events`, `blocker_resolution.counts_by_level/runtime_metrics` and per-seed `outcome.playcall.fallback_events` all exist. The console summary, `smoke-table.csv` (18 columns, none about fallbacks) and `render_slc_run_report.py` never read them. The 13 "valid" smoke seeds carry 368–602 fallback events each, 19–24 distinct kinds, and the reader-facing table shows only "valid".

**Publish the fallback count as a column.** A reader cannot judge a run whose fallbacks are only in a machine payload.

---

## What is clean, measured

Worth saying explicitly, so the next reader doesn't re-audit it:

- **Doctrine compliance:** 19 `except` sites in the execution path — 0 bare `except:`, 0 `assert` used for control flow, 0 exceptions re-raised with the cause discarded. 11 retain or re-raise with evidence; 6 substitute a silent value (all listed as findings).
- **No global RNG leakage:** every draw site constructs a local `random.Random` from a stable hash; there is no `random.seed`, no module-level draw.
- **No parallelism:** the seed loop is a plain sequential `for seed in seed_values`; no worker pool, so no completion-order effects.
- **Deterministic iteration:** candidate lists are built in insertion order from ordered scans and sorted before selection.
- **Unordered SQL loads traced and benign:** every `SELECT` without `ORDER BY` was followed to its consumer; each builds a dict keyed by row identity, or is sorted downstream, or is a `GROUP BY` aggregate.
- **Team versus player totals reconcile exactly** — carries, rushing yards, player pass attempts, receptions, receiving yards and targets each equal the team value in 2,000/2,000 team-rows in all three arms. Caveat: 9 of 15 player fields, including every touchdown, sack and interception, are omitted from the CSV export, so those identities are unverifiable from this bundle.
- **Legality suite:** 49 tests pass on HEAD.

## Limits

- The dev database is not in this workspace, so findings that need it (team-tendency and participation fallback frequencies, play-extras coverage) are code-path findings, not measured counts. Each such item says so in `silent-failures.md`.
- The 2025 backtest CSVs predate `9b5a1e43`, so the dead reconciliation check is a HEAD finding confirmed by reading, not by running that bundle.
- Nothing here is a forecast-quality judgement. It is a statement about whether the code's outputs mean what they claim.

## Recommended order

1. `roster_eligible`: emit `unknown`, restore the guard, test it. One commit.
2. Freeze rule for RNG: move `built_at_utc` out of the resealed hash; mandate `--rng-protocol v2` for every paired experiment and assert equal `stream_root_sha256` across arms.
3. Check `source_snapshot_sha256` in the two disagreeing runs, then close or confirm the non-determinism question.
4. Fix the two alias fields and withdraw any analysis that used them; rename `possession_seconds`.
5. Make the dead snap reconciliation run, then delete `snaps` from the export until it means something.
6. Add a fallback column to `smoke-table.csv` and the run report.
