# SLC determinism audit

Date: 2026-11-08
Auditor: lead
Branch: `slc-v2` at `d490757e6`
Scope: why the same command can produce a different result, and what that means for the pending batch and for ablation A.

**Verdict: two defects, both in what the random streams are keyed on. The engine's draw sites are sound; the key is not.** One is a reproducibility defect that is confirmed by reading the code. The other makes ablation A's paired comparison invalid as designed. Both are fixed by the same change: draw keys must not include provenance.

---

## F1 (HIGH): a wall-clock timestamp is inside the RNG key

`pregame_snapshot.build()` stamps the current time into the snapshot:

```python
# pregame_snapshot.py:398
'built_at_utc': datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
```

and then hashes the *whole* snapshot:

```python
# pregame_snapshot.py:78-82
def reseal(snapshot: dict) -> dict:
    """Recompute the content hash after adding a measured model input fingerprint."""
    snapshot.pop('snapshot_sha256', None)
    snapshot['snapshot_sha256'] = _canonical_hash(snapshot)
    return snapshot
```

That hash is the default random-stream key:

```python
# simulate_pregame_batch.py:839
source_snapshot_sha256 = snapshot['snapshot_sha256']
# paired_random_streams.py:25-33 -> root = sha256('...:{seed}:{snapshot_sha256}')
```

`rng_protocol.py` confirms the intent in its own docstring: *"v1 (legacy, the default). Every pre-event draw is keyed on the resealed snapshot hash."*

**Consequence.** Rebuild a snapshot and every seed draws a different game. A committed snapshot *file* is stable, because its `built_at_utc` is frozen — but any run path that builds rather than loads gets a fresh timestamp, a fresh hash, and therefore a completely different simulation from the same command. That is exactly the observed symptom: "the same command changed which seed failed", and 8 of 14 refusals not reproducing when rerun.

**This is testable in one line, and should be the first thing checked:** for the batch run and the rerun that disagreed, compare the `source_snapshot_sha256` recorded in each ledger header. If they differ, the runs were not the same game and "non-determinism" is really "the input was rebuilt". If they match, the cause is elsewhere and F2 does not explain the observed failures.

Either way F1 is a defect: **provenance belongs in the manifest, not in the RNG key.** A run cannot be reproduced from a rebuilt input, which is the whole point of freezing a snapshot.

### Reproduced from committed files, no database needed

Loaded `slc-sunday-smoke-2026-11-08/snapshots/2026_09_CIN_ATL.json`, resealed it the way the engine does, then resealed the same snapshot with `built_at_utc` advanced by one second:

```
committed built_at_utc : 2026-11-07T22:16:59Z
resealed as loaded      : 21a54b69fd144e75 ...   (equals the committed hash — the load path is stable)
resealed after rebuild  : f5f5ec7b13a401af ...
hashes equal?           : False

as loaded  stream root 0b8127d053a23183  first draw 0.814253003
rebuilt    stream root 2c37dad78aa8a454  first draw 0.559833443
```

One second of build time changes the stream root and therefore the first draw, and with it every draw for every seed. This is why a rebuilt snapshot cannot reproduce a run.

The same snapshot hashed with `built_at_utc` excluded gives `df0a33f2a9ad6827` in both cases. That is the key that should be used: identical for identical game content, regardless of when it was assembled.

So F1 is confirmed by construction, not merely suspected. Whether it is *the* cause of the 14-refusal discrepancy depends on the ledger comparison above — if the two runs used the same committed snapshot file, then F1 was not triggered there and the cause is elsewhere.

## F2 (HIGH): the ablation switch changes the RNG key, so the arms are not paired

The reference fingerprint adds the enabled blocker fixes:

```python
# e2_reference.py:130-132
if getattr(reference, 'blocker_fixes', None):
    add(['slc-blocker-fixes', sorted(reference.blocker_fixes),
         float(getattr(reference, 'fg_ordinary_cutoff', 60.0))])
```

That fingerprint is resealed into the snapshot, and under the default v1 protocol the resealed snapshot hash *is* the stream key. So turning on `restore_sack_mass` — a blocker fix, passed as `--slc-blocker-fix` — changes the key, which changes every draw for every seed.

`SPEC.md` states: *"Baseline and ablation run from the same frozen code commit. The switch is the only difference."* **Under the default protocol the switch is not the only difference.** The baseline and ablation would be independent samples, not paired ones. Any difference in the at-most-3 and at-most-10 shares would be treatment plus RNG noise, and with a 0.3-point threshold that noise is larger than the effect.

This is not a new discovery: `SLC-2025-REALISM-RESULTS-2026-11-05.md` already records the same failure for V1/V1.5 — *"The random streams are not shared across arms... 'Paired seed IDs' therefore means the same seed index, not the same random draws."* V2 escaped it because it uses the v2 protocol. Ablation A would not.

## The fix already exists in the codebase and is opt-in

`rng_protocol.py` implements a v2 scheme whose key is the pregame state plus the model-input identity, and deliberately excludes code and artifact hashes:

- stream root = `canonical_sha256({pregame_state_sha256, model_input_sha256})`
- `model_input_sha256` = `canonical_sha256({reference_data_sha256, layer_tables_sha256})`
- `reference_data_sha256` covers the reference tables only — **it does not include `blocker_fixes`**
- `layer_table_sha256` covers the play-call artifact and the enabled research layers — **not the blocker fixes**

So under `--rng-protocol v2`, toggling `restore_sack_mass` leaves the stream root unchanged and the two arms are truly paired. I checked `enabled_layers` in `slc_config.py`: it is the fixed set of research layers, so a blocker fix does not enter it either.

**Required changes:**

1. `SPEC.md` must require `--rng-protocol v2` for both arms and record the resulting `stream_root_sha256` in the freeze. Without it the ablation is unpaired and uninterpretable.
2. The freeze must record `pregame_state_sha256` and `model_input_sha256`, so a reader can confirm the arms share a root and differ only in the switch.
3. Add a pre-run assertion: the two arms' `stream_root_sha256` must be identical. If they are not, stop — that is F2 recurring.
4. Separately, remove `built_at_utc` (and any other wall-clock field) from the resealed hash. Hash the game-relevant content, and keep the timestamp in the manifest beside the hash. Otherwise a rebuilt snapshot can never reproduce a run, which defeats the freeze.

---

## What is not a source, checked

So the reader does not re-audit these:

| Candidate | Check | Result |
|---|---|---|
| Global RNG leaks across seeds | grepped every `random.<draw>` call in `scripts/nfl_sequence` | none — every draw site constructs a local `random.Random(...)` from a stable hash |
| Parallel workers reordering games | searched `simulate_pregame_batch.py` for multiprocessing, executors, worker pools | none; the seed loop is a plain sequential `for seed in seed_values` |
| In-memory frame cache | `e2_reference.py:529 _PLAY_CALL_FRAMES` | keyed on `(db, cutoff)`, built once per process, read-only afterwards |
| Optional disk frame cache | `SLC_FRAME_CACHE_DIR`, `e2_reference.py:539` | opt-in env var; if unset it is not used. If the host sets it, it becomes a candidate and should be recorded in the run manifest |
| Unsorted iteration in draw paths | checked `e1_drive`, `slc_playcall`, `e2_reference` selection code | candidate lists are built in insertion order from ordered scans and sorted explicitly (`sorted(...)`) before selection |
| Draw-site keys | `paired_random_streams.PairedRandomStreams.key` uses `json.dumps(..., sort_keys=True)` | deterministic for the same inputs |

## Residual risk: unordered SQL loads — checked, not a source

`e2_reference.py` and `player_shares.py` contain several `SELECT`s without `ORDER BY`. Row order from SQLite is not formally guaranteed, so each was traced to see whether it can reach a draw. None does:

| Load | Where | Why order cannot matter |
|---|---|---|
| participant facts | `e2_reference.py:276` | builds `out[(game_id, play_id)] = facts`, a dict keyed by the row's identity; later reads are by key |
| blocked-kick outcomes | `e2_reference.py:470` | has `ORDER BY fg.game_id, fg.play_id` |
| streak schedule | `e2_reference.py:554` | `streak_splits.streak_states` groups by `(team, season)` and then sorts with `key=(week, game_id)` before walking the sequence |
| player share counts | `player_shares.py:29,33` | `GROUP BY` aggregates; no per-row identity survives |
| pool rows | `e1_drive.py:87,102` | explicit `ORDER BY game_id, play_id` |
| charting joins | `decision_layer.py:175,180` | explicit `ORDER BY` |

So the two keying defects above are the only determinism findings in the execution path. That is a narrower and more actionable result than "the batch is non-deterministic".
