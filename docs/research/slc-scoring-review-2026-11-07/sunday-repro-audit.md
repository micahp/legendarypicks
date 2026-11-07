# Sunday smoke bundle: reproducibility and evidence audit

**Audit date:** 2026-11-07, 23:30Z (17:30 CST) — i.e. **before any of the 13 kickoffs** (earliest 2026-11-08T14:30:00Z).
**Repo:** `C:\Users\micah\OneDrive\Documents\deepseek-harness\default-workspace\slc`, branch `slc-v2`, HEAD `2f87d817a6818967ca676103eb04f9e06e7a90ec`, working tree clean.
**Audited artefact:** `docs/research/slc-sunday-smoke-2026-11-08/` (commit `2f87d817`, 42 files).
**Auditor:** sunday-audit. Nothing in the repo was modified except this report; the patch-application test ran in a throwaway `git worktree` under the OS temp directory.

Method: every number below was re-derived from repo bytes (sha256, jsonl parsing, git blobs). The producer's own summaries (`manifest.json`, `smoke-table.csv`, commit message) were treated as claims to test, not as evidence.

## Verdict summary

| # | Required check | Verdict | One-line result |
|---|---|---|---|
| 1 | Structural completeness | **PASS** | 13 manifest games / 13 snapshots / 26 jsonl files (13 boxscores + 13 seeds) / 13 CSV rows; all game IDs align |
| 2 | Hash integrity | **FAIL (as written)** | Snapshots: 13/13 sha256 match manifest **and** smoke-table. Patch: manifest hash `0e6d79…` ≠ Windows file hash `74eb4a…`; the claimed hash is the LF-normalised/git-blob hash only |
| 3 | Data agreement | **PASS** | For all 13: boxscore source, seed source and smoke-table agree on away/home points, valid_full_game, complete_game and status; quarter scores sum to team totals |
| 4 | Executed-code reproducibility | **FAIL** | Patch applies cleanly to `9667cbc1`, but it is byte-identical to the *committed* `9667cbc1→2f87d817` diff of 8 files, not an uncommitted patch; the "exist in no commit" claim is false; base+patch omits files the run headers pin, so it cannot reproduce the recorded executed tree |
| 5 | Provenance timing | **PASS (with noted anomalies)** | 0 violations: every snapshot `as_of == built_at == 2026-11-07T22:16:59Z`, before every kickoff, and every input ingest precedes the build. GB_NE `snapshot_date_utc` anomaly explained (it is the *minimum* input ingest, not the build time) |
| 6 | Legality-fix disposition | **PASS (mapping), one sub-item UNVERIFIABLE** | Named regression tests exist for all four blockers. (a) is inside `9667cbc1`; (b) core check inside `9667cbc1` with later extensions; (c) and (d) core checks inside `9667cbc1` but the release-blocker fixes exist only after it (folded into `executed-code.patch`). Kicker-test runtime not executable here (no scipy) |
| 7 | Sample-size honesty | **PASS (statement)** | One seed per game cannot produce distribution bands; `valid_full_game: true` is a legality/input-provenance claim, not statistical reconciliation or forecast skill |

**Count of the seven required checks: 5 PASS, 2 FAIL, 0 UNVERIFIABLE.** In addition, six evidence items are **UNVERIFIABLE** from the repo alone (section "Unverifiable items"), and check 6 contains one unverifiable runtime sub-item.

**Single most serious defect:** the executed-code provenance statement is false and the stated recipe cannot reproduce the recorded executed tree. `executed-code.patch` is exactly `git diff --abbrev=8 9667cbc1 2f87d817 -- <8 paths>` (byte-identical, sha256 `0e6d790f…`), so the "uncommitted … exist in no commit" language is wrong; and applying it to `9667cbc1` leaves `pregame_snapshot.py` at its 9667 version while every one of the 13 seed headers pins that file (`producer_file_sha256`) to its **HEAD** hash. The patch also omits `test_kicker_field_goals.py`, which was changed in the same commit that changed the patched `e0_single_play.py`.

**Can the slate be called validated? No.** See final section.

---

## 1. Structural completeness — PASS

`git show --stat 2f87d817` lists 42 files in the bundle commit: 1 patch + 1 manifest + 1 smoke-table + 26 jsonl + 13 snapshots. Independently parsed:

- `manifest.json` → 13 games; `smoke-table.csv` → 13 data rows; `snapshots/` → 13 files.
- `smoke-runs/` → 26 files: 13 `*.boxscores.jsonl` + 13 `*.seeds.jsonl`, each file exactly 2 lines (1 header record + 1 result; seed value is `1` in every file).
- Game-ID sets are identical across manifest, table, snapshot filenames and run filenames.
- `seeds_requested = 1` and exactly one seed record (`seed = 1`) per game.
- Working tree is clean; every bundle file exists at `2f87d817`.

Evidence: Python glob/CSV/JSONL parsing of the bundle (appendix command A1).

## 2. Hash integrity — FAIL as written (snapshots PASS; patch hash only survives line-ending normalisation)

### Snapshots — PASS, 13/13

Recomputed sha256 of every `snapshots/*.json`; all 13 match **both** `manifest.json.games[].snapshot_sha256` and `smoke-table.csv.snapshot_sha256` (0 mismatches). Example: `2026_09_GB_NE` = `406298bdf04051522a7719904d2843c9f5d32d2c5811b5bf556d4def892a5bdf`.

A second, independent consistency check also passes: each `*.seeds.jsonl` header's `source_snapshot_sha256` equals the `snapshot_sha256` field carried *inside* that snapshot JSON (13/13). That internal field is a different value from the file hash by design (sealed-payload hash); the manifest/table use the file hash and those are correct.

### `executed-code.patch` — FAIL as written

- Manifest claim: `executed_simulator_code.patch_sha256 = 0e6d790f6dcf01e8bc60e4355d6d89360f7135dc9ef30f3679411c3bb4bb8d56`.
- Literal recompute on the committed working file (PowerShell `Get-FileHash -Algorithm SHA256` and Python `hashlib` over the file's bytes agree): **`74eb4a687fe4523eec4357e5c4068cecae4237ab2782742d7f852029839a5cc5`** → mismatch.
- Cause is line-ending normalisation, not content damage: this Windows checkout has `git config core.autocrlf = true`, so the checked-out file is 40,720 bytes with 694 CRLF pairs. After `CRLF → LF` the file is 40,026 bytes and hashes to **`0e6d790f…` = the manifest value**. The same hash is obtained from the committed git blob (`git cat-file blob ea380971f3b927b5c32870fbaf9992e3ee7d11d1`, 40,026 bytes, no CR).
- Conclusion: the manifest hash is correct **for LF content / the git blob**, but the bundle does not state that normalisation, so a plain `sha256` of the shipped file on a normal Windows checkout fails. The patch should be pinned with a canonical (LF/`*.patch eol=lf`) rule or both hashes recorded.

There is no hash, manifest or table entry for the 26 run-output files themselves; their integrity rests only on being committed. That is acceptable for git but means the bundle does not self-verify its outputs.

## 3. Data agreement — PASS

For every game, parsed line 2 of the boxscore jsonl (team stats + points + reconciliation + quarter data) and line 2 of the seeds jsonl (`outcome`):

- `smoke-table.csv` away/home points equal **both** the boxscore team points and the seed outcome `away_points`/`home_points` — 13/13.
- `valid_full_game`, `complete_game` and `seed_status` in the table equal the seed outcome fields — 13/13. All 13 are `status=complete_regulation`, `complete_game=true`, `valid_full_game=true`, `blocker=null`, `error=null`, `unsupported_rules=[]`, `regulation_end_reached=true`, `final_tie=false`, `score_scope=valid_final`.
- Boxscore `status=valid_complete`, `quarter_scoring_complete=true`, and `points_by_period` sums equal the team totals for all 26 team rows.
- `reconciliation.status=passed` and `reconciliation.teams[].matches=true` for all 13 games (the recorded `strict:false` is just the caller's label; `reconcile_boxscore` does not relax any check because of it — `slc_outputs.py:536-603`).
- The boxscore copy inside the seeds file is identical to the boxscores-file record except for the metadata key `type` (no statistical disagreement), checked for all 13 games.

The `verified=true` / `evaluation_class=verified_forecast` values in the table match the snapshot files' own `evaluation` block (13/13 `verified=true`, `unverified_inputs=[]`). They are self-consistent; whether they are *sufficient* is a provenance question (check 5).

## 4. Executed-code reproducibility — FAIL

Manifest claim (quoted):

> `base_commit 9667cbc1…` plus an uncommitted patch `executed-code.patch`; note: "game_legality.py on the host equals local HEAD; e0_single_play.py, e1_drive.py, slc_playcall.py and team_tendency.py are uncommitted on the host and exist in no commit".

### 4.1 What the patch actually contains

8 files, not 4: `e0_single_play.py`, `e1_drive.py`, `game_legality.py`, `slc_playcall.py`, `team_tendency.py`, `test_game_legality.py`, `test_slc_blocker_resolution.py`, `test_slc_integration.py`. So it does cover the four named files plus `game_legality.py` and three test files. The manifest note does **not** name `game_legality.py` among the "no commit" files even though it is patched.

### 4.2 It applies cleanly to 9667cbc1

Throwaway worktree test (no touch to the main working tree):

```
git worktree add --detach <tmp> 9667cbc1
git -C <tmp> apply --check <bundle>/executed-code.patch   # exit 0
git -C <tmp> apply <bundle>/executed-code.patch           # exit 0
```

After applying, the worktree content hash of each of the 8 files equals the corresponding **HEAD (`2f87d817`) blob**:

| file | base blob at 9667cbc1 | post-image = HEAD blob |
|---|---|---|
| e0_single_play.py | `badbe8a7…` | `1be140ce…` |
| e1_drive.py | `96f6fdaf…` | `89e9ca9e…` |
| game_legality.py | `33231b01…` | `9f0588a2…` |
| slc_playcall.py | `860b242d…` | `03beebcf…` |
| team_tendency.py | `3a50512e…` | `7a84c9f1…` |
| test_game_legality.py | `8fbd91a2…` | `849062a1…` |
| test_slc_blocker_resolution.py | `d506ad74…` | `e0b91725…` |
| test_slc_integration.py | `faa4946c…` | `d669a7bf…` |

### 4.3 The patch is a committed diff, not an uncommitted one

`git diff --abbrev=8 9667cbc1 2f87d817 -- <the same 8 paths>` is **byte-identical** to the shipped patch (40,026 bytes, sha256 `0e6d790f…`, same as the manifest hash). Therefore:

- The patch is exactly the committed delta from the manifest's alleged base to the current repo HEAD, restricted to 8 simulator/test files.
- The claim that the four files "exist in no commit" is **false for this repository**: all four exist at `9667cbc1` (base blobs above), and their patched content exists at `2f87d817` (post blobs above). `git log --all --oneline -- <path>` finds commits touching them: `e0_single_play.py` (6 commits), `e1_drive.py` (39), `slc_playcall.py` (32), `team_tendency.py` (5). The post-patch versions were introduced by commits after `9667cbc1` (`a0b00a3e`, `acd0c2a0`, `c0cb16a5`, `d93b0b4e`, `47707c33`, `0febeff7`).
- The claim is also mis-assigned: `e1_drive.py` **is** one of the 25 files hash-pinned at run time (see 4.4), while the four files that are *not* hash-pinned are `e0_single_play.py`, `game_legality.py`, `slc_playcall.py` and `team_tendency.py`.

### 4.4 Applying the patch does **not** reproduce the recorded executed tree

Applying the patch to `9667cbc1` yields a tree that still differs from HEAD (`2f87d817`) in three non-doc files:

- `scripts/nfl_sequence/pregame_snapshot.py`
- `scripts/nfl_sequence/test_kicker_field_goals.py`
- `scripts/nfl_sequence/test_pregame_snapshot.py`

The run records make `pregame_snapshot.py` decisive. Every seed header carries `producer_file_sha256` for 25 producer files; for all 13 games and all 25 files those hashes equal the **HEAD (`2f87d817`) LF-normalised content** (0 mismatches; 25 hashes × 13 games checked). That set includes `pregame_snapshot.py` at HEAD content hash `d5331e4f…`, which is **not** the `9667cbc1` content of that file. So:

- `9667cbc1 + executed-code.patch` produces the `9667cbc1` version of `pregame_snapshot.py`;
- the run headers say the executed `pregame_snapshot.py` was the HEAD version;
- therefore the manifest's stated recipe **cannot reproduce the recorded executed tree**.

`test_kicker_field_goals.py` is a second, independent gap: it was changed in commit `acd0c2a0` together with `e0_single_play.py` (which the patch *does* change), yet the patch omits it, so base+patch pairs the new `pool_key` code with the old kicker-test expectations.

### 4.5 The run records do not even agree with themselves on `source_commit`

Per-game `source_commit` in the seeds headers:

- 11 games: `0febeff7fefa10142a64f5c3bf371a30fc0a226a`
- `2026_09_ARI_SEA`, `2026_09_TB_CHI`: `7890e7cc28b8d876892c6ffd355232b1d71398bb`
- `2026_09_GB_NE`: `da4636cdcb24c32e0c5ebe587ac7e30ee0332d8a`

No game records the manifest's `9667cbc1`. Worse, the `0febeff7` and `da4636cd` labels are **incompatible with the same headers' own `producer_file_sha256`**: at both commits `pregame_snapshot.py` has a different hash from the recorded one. Only the two `7890e7cc` games are self-consistent, and all 13 headers' producer hashes are consistent with `2f87d817` (or the code-equivalent `a0e4bd5b`/`7890e7cc` docs-level ancestry). The 13 games therefore do not record one executed code vintage.

The run header also **omits** `producer_worktree_dirty`, which `producer_source()` computes (`simulate_pregame_game.py:58-71`); so the outputs contain no record of whether the host checkout was dirty.

## 5. Provenance timing — PASS, with the GB_NE anomaly explained

Independent parse of all 13 snapshots and the seeds/boxscore headers:

- All 13: `as_of == built_at_utc == 2026-11-07T22:16:59Z`.
- Kickoffs range `2026-11-08T14:30:00Z` (CIN_ATL) to `2026-11-09T01:20:00Z` (TB_CHI). Every snapshot precedes every kickoff; the latest build is ~15.2 h before the earliest kickoff.
- All input ingests are before the build: schedule ingests at `2026-11-07 04:56:40` (GB_NE), `11:00:02` (DEN_CAR, LV_SF) or `21:03:55` (other 10); depth ingests all `2026-11-07 10:58:49`; depth `snapshot_at = 2026-11-05T07:01:33Z`. No input `ingested_at`/`snapshot_at` exceeds `built_at`. **0 timing violations.**
- Schedule kickoff conversion re-derived independently: `schedule.gameday + gametime` interpreted as `America/New_York` converts to the claimed `scheduled_kickoff_utc` for all 13 (e.g. CIN_ATL 09:30 ET → 14:30Z; TB_CHI 20:20 ET on 11-08 → 2026-11-09T01:20:00Z). TB_CHI is simply the Sunday-night game, not an anomaly.

**GB_NE `snapshot_date_utc = 2026-11-07T04:56:40Z` vs `2026-11-07T10:58:49Z` elsewhere** — explained, but worth flagging as a data-quality asymmetry rather than a timing violation. The builder defines `snapshot_date_utc` as the **minimum input ingest time** (`pregame_snapshot.py:400`), not the snapshot build time. GB_NE's schedule row was ingested at `04:56:40` (its schedule ingest), which is earlier than its depth ingest (`10:58:49`), so the minimum is the schedule time; for the other 12 games the depth ingest is the minimum. Consequences: (a) the table's `snapshot_date_utc` column is not comparable across games and is not "the snapshot date"; (b) GB_NE's schedule input is ~16 h older than the other games' schedule rows (04:56 vs 21:03) even though all 13 snapshots were built in the same minute. `built_at_utc` is the field to use for build time.

Caveat on "verified": `verified_forecast` is the builder's rule that each input row was written to the local DB at or before the cutoff (`pregame_snapshot.py:236-260`); it verifies **DB ingest time**, not the publisher's capture time. That is a real limitation of the "verified" label, not a failure of the 13 snapshots' internal consistency.

## 6. Legality-fix disposition — PASS (mapping), one sub-item UNVERIFIABLE

No document in the repo names the four blockers with the task's labels, so each was mapped to the code and regression tests that implement the described rule. `game_legality.check()` is invoked from `game_state.validate_game()` (`game_state.py:2075`), so a `valid_full_game=true` record has passed it.

| Blocker | Where the rule lives | Regression test(s) | In `<= 9667cbc1` or only after? |
|---|---|---|---|
| (a) overtime winning-touchdown try takes no try | `game_state.py` overtime try rule; `producer_file_sha256` pins the executed `game_state.py` at HEAD content, and the file is unchanged `9667→HEAD` | `scripts/nfl_sequence/test_game_state.py::OvertimeCompletedRules::test_a_winning_touchdown_from_a_tie_takes_no_try` (also `test_a_first_possession_touchdown_carries_a_try_and_the_game_goes_on`, `test_an_answering_touchdown_that_ties_carries_its_try`) | **Inside `<= 9667cbc1`**: test present in the 9667 tree, introduced by `480b9826` (ancestor of 9667); `game_state.py`/`test_game_state.py` have zero diff 9667→HEAD |
| (b) adjacent-play state continuity | `game_legality.py::_play_chain` ("Each play starts from the state the previous play left, inside one possession", incl. clock continuation across a quarter change) | `test_game_legality.py::Corruption::test_next_down_becomes_five`, `test_ball_moves_to_the_wrong_yard_line`, `test_distance_becomes_seventy_seven_yards` (all present at 9667); later patch-only additions: `PlayClock::*`, `PlayScore::*`, `ScoringSide::*` | **Core check inside `<= 9667cbc1`** (`_play_chain` is identical at 9667 and HEAD). The supplementary per-play clock/score checks (`_play_clock`, `_play_scores`, `_state_domain` team/score checks) and their tests exist **only after 9667** (folded into the patch) |
| (c) clocks between possessions | `game_legality.py::_possession_and_clock`, `_kickoff_clock`, `_check_boundary` | `test_game_legality.py::FirstHalfExpiry::test_the_second_half_kickoff_is_paired_with_the_first_half_expiry` (added by `47707c33`); `LateScore::test_a_kickoff_that_runs_the_clock_out_ends_the_game` (added by `d93b0b4e`) | The base check exists in 9667, but the release-blocker fixes (legal-game false refusals at a first-half expiry and at a late-score kickoff that runs the clock out) exist **only after 9667** → patch-only |
| (d) final-clock reconciliation | `game_legality.py::_game` (final score, final clock and regulation ending agree with the drives); `_ends_the_game`/`_game_ending_kick` for a late score whose kickoff expires the clock | Base: `Corruption::test_the_game_ends_on_a_punt_before_the_clock_expires`. Patch-only: `LateScore::test_a_made_field_goal_at_two_seconds_ends_the_game_on_its_kickoff` (added by `0febeff7`), `LateScore::test_a_kickoff_that_runs_the_clock_out_ends_the_game` | Core `_game` reconciliation is **inside `<= 9667cbc1`** and identical at HEAD; the late-score game-ending-kickoff acceptance — the release-blocker defect in `0febeff7` ("a legal game was refused, ablation run seed 41") — is **patch-only** |

Verification runs (throwaway worktree with the patch applied, and the main tree at HEAD):

- `python -m unittest test_game_legality` → **43 tests, OK** (includes `Corruption`, `PlayClock`, `PlayScore`, `ScoringSide`, `LateScore`, `FirstHalfExpiry`, `HalftimeSkip`, `OvertimeReturnTouchdown`, `BlockedKickTouchdown`, `Domain`).
- `python -m unittest test_game_state.OvertimeCompletedRules test_game_state.Clock` → **10 tests, OK**, including the OT no-try test.
- **UNVERIFIABLE here:** `test_kicker_field_goals` cannot run in this environment (`ModuleNotFoundError: No module named 'scipy'`). This matters because that test file is changed by the same commit as the patched `e0_single_play.py` and is *not* covered by the patch; base+patch would give mismatched code/test expectations. Static diff evidence is conclusive; the runtime result is not available here.

Caveat: `game_legality.py` is **not** in the run headers' `producer_file_sha256` list (the list covers 25 modules and omits `e0_single_play.py`, `game_legality.py`, `slc_playcall.py`, `team_tendency.py`). So the identity of the validator version actually executed is asserted by the manifest/patch only — it cannot be confirmed from the run outputs.

## 7. Sample-size honesty

Stated plainly, as required:

- **One seed per game cannot produce distribution bands.** Thirteen single draws are 13 point forecasts; they support no median, no percentile, no interval, no spread/calibration claim. The manifest itself calls it "the smoke test before the 50-seed pass"; the table's `verified_forecast`/`verified` columns and the commit message's "pass the batch legality check and the statistical reconciliation" must not be read as a distribution result.
- **`valid_full_game: true` is a legality/input-provenance claim, not statistical reconciliation.** Per `game_state.py:2067-2075` it requires `pregame_full_game` mode, complete regulation, no blocker, a tie played out in overtime, no unsupported rule, and a passing `game_legality.check()` (legal plays/drives/kickoffs/clocks). It also relies on the snapshot's `verified` class (itself a DB-ingest-time check). It says nothing about score realism, calibration, or predictive skill; the companion scoring memo measures a 0.79 team-spread ratio and explicitly says a distribution from this build would be "confidently wrong".
- No outcome validation is possible yet: at audit time (23:30Z, 2026-11-07) all 13 games are still unplayed; the earliest kickoff is 2026-11-08T14:30:00Z.

## Unverifiable items (cannot be settled from the repo alone)

| ID | Item | Why unverifiable | What would settle it |
|---|---|---|---|
| U1 | Host tree byte identity (`/root/lp-slc-v2-sim`) | The host is not this repo and no host files/commands are shipped. The repo already proves the stated recipe is incomplete (4.4), but it cannot prove what the host actually contained | Host `git rev-parse HEAD`, `git status --porcelain`, and sha256 of `e1_drive.py`, `game_legality.py`, `e0_single_play.py`, `slc_playcall.py`, `team_tendency.py`, `pregame_snapshot.py`; plus the exact run command/script |
| U2 | Playcall artefact | Every seed header pins `playcall_artifact_sha256 = 27c02afd6d9f6f80a38b3bc7ae278b1efebcc7caa5664688c64c55bc0c698ac7`, but the repo file named as the input (`docs/research/SLC-PLAYCALL-ARTIFACT-v1.json`) hashes to `6ba495f1…` raw / `c8f16540…` LF, and no file under `docs/`, `scripts/`, `backend/`, `fixtures/` hashes to `27c02afd…` (searched, LF-normalised; also tried 8 canonical JSON serialisations). | Ship the exact artefact bytes (or the host path it was read from) and the hashing rule used |
| U3 | Inputs not shipped | The DB (`/root/legendarypicks/backend/data/picks.dev.db`), `wl-streaks-2026-11-07.json` (repo contains only `docs/research/slc-week8-2026/wl-streaks-2026-10-29.json`), and the per-game `observed_reference_sha256` inputs are not in the bundle. | Export the exact DB rows/snapshot inputs, the 2026-11-07 streak file, and the reference tables with matching hashes |
| U4 | Rerun/reproduce the 13 outputs | Requires the DB, artefacts, streak file and host environment; the bundle records flags only in `manifest.json`; there is no run log, command transcript or environment lock | A committed run script + environment lock + input hashes that match; or a host-side reproduction record |
| U5 | Independent legality/statistical validation of the 13 games | The bundle ships boxscores and drive summaries but **no per-play records**, and no `game_legality` checks list. `smoke-table.validation_error` is empty and `valid_full_game=true`, but the validator output cannot be re-run or inspected independently | Per-play/drive record per game (the input the validator consumed) plus its returned checks list |
| U6 | Forecast skill/calibration | No outcomes exist yet (games unplayed at audit time) and one seed per game has no distribution | Post-kickoff actual results, ≥30-50 seeds per game, and the pre-registered grading protocol |

## Ranked defect list

1. **Executed-code provenance is false and the stated recipe is incomplete** (most serious). The patch is byte-identical to the committed `9667cbc1→2f87d817` diff of 8 files ("uncommitted / exists in no commit" is false), and `9667cbc1 + patch` leaves `pregame_snapshot.py` at the 9667 version while all 13 run headers pin it at the HEAD hash. `test_kicker_field_goals.py` (changed with the patched `e0_single_play.py`) is also omitted. So the bundle does not specify a code tree that reproduces the executed one.
2. **Per-game `source_commit` values contradict the headers' own file hashes and the single-vintage claim**: 11 × `0febeff7`, 2 × `7890e7cc`, 1 × `da4636cd`; none is `9667cbc1`, and the `0febeff7`/`da4636cd` labels are incompatible with the recorded `pregame_snapshot.py` hash. All 13 producer hash sets are consistent with HEAD (`2f87d817`) instead.
3. **The run records omit `producer_worktree_dirty`** although `producer_source()` computes it; the outputs contain no evidence of the "uncommitted" state, and the manifest's patch story cannot be corroborated from the run data.
4. **Patch sha256 fails a literal recompute on a normal Windows checkout** (CRLF vs LF); content is intact (git blob hash matches the manifest), but the bundle does not state the normalisation rule.
5. **Pinned executed inputs are unverifiable/missing**: `playcall_artifact_sha256` matches no repo file; the 2026-11-07 streak file is absent; the DB/reference inputs are not shipped. Reproducibility from the repo alone is therefore impossible even if the code tree were right.
6. **No per-play records or validator output in the bundle**, so the "13 of 13 legal" claim cannot be independently re-checked; only the exported flag (`valid_full_game=true`, `validation_error` empty) asserts it.
7. **Patch omits `test_kicker_field_goals.py` and the kicker-test runtime could not be exercised here** (no scipy), so the code/test pairing produced by the patch is statically inconsistent and its effect was not verified.
8. **Snapshot freshness/labelling:** `snapshot_date_utc` is the minimum input ingest, not the build time; GB_NE is `04:56:40Z` because its schedule row was ingested 16 h earlier than other games' schedule rows (other games `21:03:55`/`11:00:02`). Not a kickoff violation, but the slate's schedule inputs are not one vintage and the table column invites misreading.
9. **The bundle overstates what it demonstrates** (commit message: "pass the batch legality check and the statistical reconciliation"; table: `verified_forecast`, `verified=True`) without the sample-size caveat: 13 one-seed games cannot support a distribution claim, and "valid" here means legal + input-provenance, not accurate.

## Final determination: can this slate be called a validated, reproducible forecast artifact?

**No.**

Reasons, in order of weight:

1. **Reproducibility of the code is not established and the stated provenance is demonstrably wrong.** `executed-code.patch` is a committed diff, not an uncommitted one; applying it to the stated base does not reproduce the run headers' recorded producer hashes (specifically `pregame_snapshot.py`), and the 13 outputs disagree with each other on `source_commit` while the manifest asserts a single base+patch vintage.
2. **Reproducibility of the outputs is impossible from the bundle**: the input database, the pinned playcall artefact (hash matches nothing shipped), the 2026-11-07 streak file and the observed-reference inputs are absent or unpinned; there is no run log/command transcript.
3. **Legality is not independently evidenced**: no per-play records and no validator checks list are shipped, so the 13/13 "legal" claim rests on self-reported output flags.
4. **It is a 13-game, one-seed point forecast, not a distribution or a validated forecast.** One seed per game cannot produce bands, and no outcomes exist yet against which to validate.

What would turn this into a yes: (i) a corrected executed-code statement with a tree that reproduces the recorded producer hashes and every non-hash-pinned module (or a clean checkout whose hashes match), including the dirty-state record; (ii) a patch covering every changed file with a canonical (LF) hash; (iii) shipped, hash-matching inputs (DB extract, artefact, streak, reference) plus the run command/environment; (iv) per-play records and the validator's checks list per game; (v) the 50- then 200-seed pass for bands; (vi) post-kickoff actuals for any calibration claim. Items (i)-(ii) are cheap; (iii)-(iv) are the difference between a smoke artefact and a reproducible one.

## Appendix: commands used

All commands run from `C:\Users\micah\OneDrive\Documents\deepseek-harness\default-workspace\slc`; Python = `C:\Users\micah\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe`; all parsing was Python (jsonl lines are very long).

- A1 structure/JSONL/CSV/points: `python` open/`json.loads`/`csv.DictReader` over `docs/research/slc-sunday-smoke-2026-11-08/{manifest.json,smoke-table.csv,snapshots/*.json,smoke-runs/*.jsonl}`.
- A2 hashes: Python `hashlib.sha256` of raw bytes and of `bytes.replace(b'\r\n', b'\n')`; `Get-FileHash -Algorithm SHA256` for a cross-check; `git cat-file blob ea380971f3b927b5c32870fbaf9992e3ee7d11d1` for the committed blob.
- A3 patch application test: `git worktree add --detach "$env:TEMP\...\wt9667" 9667cbc1`; `git -C <wt> apply --check ...\executed-code.patch` (exit 0); `git -C <wt> apply ...` (exit 0); `git -C <wt> hash-object <file>` vs `git rev-parse 2f87d817:<file>` for the 8 patched files; `git -C <wt> diff --name-status 2f87d817 -- scripts/` → the three uncovered files. Worktree removed after the test.
- A4 patch identity: `git diff --abbrev=8 9667cbc1 2f87d817 -- <8 paths>` and sha256-compared to the stored patch; `git diff --full-index`/`--abbrev=8` variants to confirm abbreviation width.
- A5 git history: `git show --stat 2f87d817`, `git diff --name-status 9667cbc1 HEAD`, `git log --oneline 9667cbc1..HEAD -- <path>`, `git log --all --oneline -- <path>` (per-file commit counts), `git merge-base --is-ancestor 480b9826 9667cbc1` (exit 0).
- A6 producer hashes: parsed each `*.seeds.jsonl` header `producer_file_sha256`; compared to `sha256(LF)(HEAD:<path>)` and to `git show <commit>:<path>` for `9667cbc1`, `0febeff7`, `7890e7cc`, `da4636cd`, `2f87d817`.
- A7 timing: parsed snapshot `as_of`, `built_at_utc`, `input_ingests`, `schedule`, depth `snapshot_at`; compared to `scheduled_kickoff_utc`; re-derived kickoff with `zoneinfo.ZoneInfo("America/New_York")`.
- A8 tests: (in the patch-applied throwaway worktree) `python -m unittest test_game_legality` → 43 OK; (in the main HEAD tree) `python -m unittest test_game_state.OvertimeCompletedRules test_game_state.Clock` → 10 OK; `python -m unittest test_kicker_field_goals` → ImportError, no scipy.
