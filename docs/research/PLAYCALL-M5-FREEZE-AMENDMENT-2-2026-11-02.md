# M5 freeze amendment 2, 2026-11-02

Status: owner-authorized integration (decision D1, 2026-11-02). Research only. Every new behaviour sits behind a research flag that is off by default. No SLC default changes. No production activation. No 2026 outcome was read.

The original freeze (`PLAYCALL-M3-FREEZE-2026-11-02.md` and `SLC-V2-M6-FREEZE-2026-11-02.md`) is not edited. Its hashes and values stand as written. Amendment 1 (`PLAYCALL-M3-FREEZE-AMENDMENT-1-2026-11-02.md`) is unchanged.

Scope of this amendment: PBV1 only (decision D1, first of three). P1 pass share and P2 target share are not integrated here and will get their own amendment.

## 1. Changed files

Base commit: `a4cbb8db`. "Frozen" is the hash at that commit. "Amended" is the hash of the working tree when this document was written.

| File | Frozen SHA-256 | Amended SHA-256 | Pinned in `slc_config.LAYER_CODE_FILES` | Change and reason |
|---|---|---|---|---|
| `scripts/nfl_sequence/pre_event.py` | `635c92864287903027ea02477c5c7b004f8ffa843ffaaeddf612495d796058f8` | `f5b7927691f468d786780dba651303a2def72df41d3ab5a4977506f0a4f75601` | yes | `choose()` and `chooser()` gain a keyword `pbv1=None`. With it set, the personnel label is replaced by the PBV1 package after the formation draw, when a package can be drawn. Nothing else in the file changes. |
| `scripts/nfl_sequence/slc_engine.py` | `e0dda6e44cd2c19dc41e744fab461fc9f090529731795581ae53bbd5065de29a` | `3504fa4c0ecff44824825eda53ed8c620f2ae988c44b70e66b5e15b7efc204df` | no | `load_reference()` gains `pbv1_table=None`, which loads the PBV1 model for the game season. `play()` creates one `Draws` per game and passes it to the chooser. The record gains `research_integration` only when the flag is on. |
| `scripts/nfl_sequence/simulate_pregame_batch.py` | `bd2f1f1e6a26dd5b93bbd706f22e301a4cb258ac66ef7f9f9a8c05c027a52ab6` | `57d031b78ddf2cda51962a01a2b7938789489b1f410d7990d4d349e16c8955b9` | no | Adds `--playcall-pbv1-package PATH` (off by default). Passes it to `load_reference`. Copies `research_integration` into the outcome row only when present. Adds `research_integration` to the ledger header only when the flag is on, so a resume must match the pinned inputs. |

Consequence of the `pre_event.py` change: `integration_code_sha256` (`slc_engine.py`, the `integration_files` tuple) hashes `pre_event.py`. Batch headers from this point carry a new value for that field. The artifact file (`SLC-PLAYCALL-ARTIFACT-v1.json`) does not pin it, so the artifact still loads. The regression in section 6 excludes this field and reports it separately.

`slc_playcall.py` is not changed by this amendment (hash `0cb9eecfeaecd3fe9c959f691eda19c5290b534320632416f8cd0703dd1c6f2c`, equal to the frozen hash).

## 2. New files

| File | SHA-256 | Reason |
|---|---|---|
| `scripts/nfl_sequence/pbv1_package.py` | `7276bc0d2b672d9c650054960fbd3ac9bbbac6e09983b140e35fffc45c4c26a8` | Runtime PBV1 package sampler (K = 20, the spec's cell and parent rules, HPV1 distance buckets). Checks the training table SHA-256 before use. Counts every fallback by reason. |
| `scripts/nfl_sequence/test_pbv1_package.py` | `e675c70a4c9d029d05bb909d82e25cd2505a667c4e8d74eaff7db6c6b7d98db6` | Equality test: the runtime model reproduces the frozen PBV1 fold numbers (section 4 of the results), plus table, hash and draw tests. |
| `scripts/nfl_sequence/test_pbv1_criterion.py` | `ea215ba1d9eb24397f089356e645317697848c02c6f6e041443a5558f57be7be` | The Milestone 2 gate, criterion (c), as an executable verdict on the frozen results (section 4 below). |
| `scripts/nfl_sequence/test_pbv1_hook.py` | `21e18765a40cfb0766ea3c4840c7515dd523d4d79aa960036ea2eec8f1a48ddb` | With the flag off the choice is unchanged. With it on, only `personnel` changes, and the draw uses its own substream. |
| `docs/research/pbv1-package-integration-2026-11-02/export_training.py` | `4b5cb96014b7d53d9a8c8d0a681f417cc970e785556969ccb974f187f5c5fe74` | Writes the training table from the same population and filters as `pbv1_eval.py load_plays`, using gridiron `hpv1_build.season_frame`. |
| `docs/research/pbv1-package-integration-2026-11-02/pbv1_training_plays.csv` | `ab875384a82ea1d6472e12007d0e1f79316508861a1843730253f40253d8a993` | The frozen training table: 133,262 regular-season scrimmage plays, seasons 2022 to 2025 (33,592 / 33,761 / 33,252 / 32,657). Same totals as the frozen evaluation. |
| `docs/research/pbv1-package-integration-2026-11-02/pbv1_training_manifest.json` | `c8086e3faaf0818cd8d8fba60a3e2e88edcf1ffaba0c6328d17abf3a84df9bc0` | Records the CSV hash, row counts, exclusions and the gridiron commit `ad9880d653dbb3de99e58ffac114fc5919f1e952`, with the `hpv1_build.py` and `hpv1_contract.py` hashes. |

## 3. What the PBV1 flag does, and does not do

Flag: `--playcall-pbv1-package <training CSV>`, off by default. Model: `pbv1-package-sampler-spec-2026-11-02`, K = 20, target column `package` (RB-only, the SLC personnel code, for example `11`).

Training: seasons strictly before the game's season. A 2026 game is fitted on 2022 to 2025. The table SHA-256 must equal `TABLE_SHA256`, or the run stops.

Draw: `pbv1.draw(intent, down, togo, yardline_100, f'{base}:pbv1')`, with `base = snapshot_sha256:seed:index`. The draw uses its own `random.Random`, so the formation, rusher, receiver, passer and coverage draws receive the same random numbers with the flag on or off.

Fallbacks, each counted under its own name and each keeping the formation layer's personnel: `fallback_distance_outside_buckets`, `fallback_down_unknown`, `fallback_parent_unseen`.

What it changes: the personnel label only. In `v1_full_stack` the simulated outcome is matched on formation (`slc_playcall.py`, the `formation` match), and the personnel label is recorded but not read by any outcome rule (checked by search over `slc_playcall.py`, `slc_engine.py` and `player_conditioned_outcomes.py`). So with this flag the simulated plays are expected to be identical to the flags-off plays, and only the recorded personnel differs. Section 6 tests this. A change to game outcomes would need personnel to condition the outcome match, a model change that is not part of this amendment and needs its own decision.

## 4. Criterion (c): quote, intended property, reading, test

Quoted, from `PBV1-SAMPLER-SPEC-2026-11-02.md`, section 9: "A sampler "passes" PBV1 Milestone 2 only if: (a) its log-likelihood gain over B0 is positive with a 95% CI above zero on both development folds; (b) its unsupported-combination rate is at or below the B1 rate on the same folds; and (c) the retrospective fold agrees in sign. Failure is reported as failure."

Intended property of (c): the sampler's advantage over the marginal package distribution must not be an artifact of the development seasons. The retrospective season is scored separately, so its gain must carry the sign the development folds show.

Reading used: "agrees in sign" compares the retrospective gain over B0 with the development gains over B0, the same statistic as (a). The spec does not name the comparison. The reading is stated here, the spec is not edited, and the owner should confirm it.

Correction to the earlier report (`pbv1-sampler-2026-11-02/REPORT.md`, section on criterion (c)): that report says the retrospective fold "agrees in sign" under the B1 reading. It does not. The development gaps to B1 are negative (-0.00033 and -0.00037, CIs excluding zero). The retrospective gap is +0.00007 (CI -0.00015 to +0.00032). The signs disagree. The B1 reading therefore fails (c). `test_pbv1_criterion.py` asserts this.

Frozen results (`pbv1-sampler-2026-11-02/outputs/pbv1_results.json`), K = 20:

| Target (frozen name) | Table column | Fold | Gain over B0 (95% CI) | Gap to B1 | Unsupported sampler / B1 |
|---|---|---|---|---|---|
| `package` (RB plus FB, primary) | `package_comparable` | dev 2023 | +0.05940 (+0.05356 to +0.06515) | -0.00033 | 8 / 181 |
| `package` | `package_comparable` | dev 2024 | +0.06668 (+0.06141 to +0.07205) | -0.00037 | 4 / 71 |
| `package` | `package_comparable` | retro 2025 | +0.06905 (+0.06273 to +0.07520) | +0.00007 | 8 / 49 |
| `package_rb` (RB only, SLC code) | `package` | dev 2023 | +0.03698 (+0.03094 to +0.04281) | -0.00025 | 10 / 190 |
| `package_rb` | `package` | dev 2024 | +0.05102 (+0.04573 to +0.05640) | -0.00036 | 3 / 81 |
| `package_rb` | `package` | retro 2025 | not in the frozen results | not in the frozen results | not in the frozen results |

Verdicts (`test_pbv1_criterion.py`):

- Primary target, reading B0: **pass**. (a) holds on both development folds, (b) holds (8 against 181, 4 against 71), (c) holds (+0.06905 against positive development gains).
- Primary target, reading B1: **fail**. (a) and (b) hold, (c) does not, because the retrospective sign is opposite to the development sign.
- RB-only SLC target: (a) and (b) hold on both development folds. **Not evaluated** on (c), because the frozen results have no retrospective fold for `package_rb`. The spec scored the retrospective fold once, for the primary target, and reported the RB-only sensitivity on the development folds only.

## 5. Gate status and the open decision

The SLC integration uses the RB-only code, because the owner ruled RB-only for the SLC (approved 2026-11-02). That target has no criterion (c) result. The PBV1 integration is therefore research-only, labelled "criterion (c) not evaluated on the integrated target", and its gate status is "not passed" for the SLC code.

Decision for the owner: either (i) authorise one retrospective RB-only fold, pre-registered fold definition (fit 2022 to 2024, score 2025), scored once and reported whatever the result, or (ii) accept the RB-only integration as research-only, with (c) open. This amendment does not run that fold.

## 6. Verification

Unit and equality tests, run from `scripts/nfl_sequence`:

- `test_pbv1_criterion`: 3 tests, all pass.
- `test_pbv1_package`: 10 tests, all pass. The runtime model reproduces the frozen mean log-likelihoods for the sampler, B0 and B1, the comparable-play counts, and the unsupported counts of all three primary folds and both RB-only development folds, to 1e-5. The table's SHA-256 equals the pinned value and the manifest.
- `test_pbv1_hook`: 5 tests, all pass.

Batch regression, Week 8 frozen snapshot `2026_08_KC_DEN`, `v1_full_stack`, seeds 1 to 3, same command as the baseline:

- Baseline (HEAD code, before this amendment): `scratchpad/baseline/v1_full_stack_seeds1-3.json`, SHA-256 `0145bc4440e66674a0bf61e4578f65ec04e7a349244fb136fb00b236cf005082`, per-seed rows `…seeds.jsonl` SHA-256 `f22f120078f6882eb9819d928a1cbfcbcdba0ac20bb0b45b337dd6e2073ada93`.
- Flags off, amended code: PENDING.
- Flags on, `--playcall-pbv1-package`: PENDING.

## 7. Known defects, not fixed here

- `run_slc_game.py`, `player_shares_for(args)`, returns `bool(args.player_shares or args.dirichlet_shares)`. Requesting `--dirichlet-shares` therefore also loads the fixed-share layer, and `slc_config.validate_engine_layers` refuses the profile with "fixed_player_target_carry_shares expected False, actual True". The batch runner passes the fixed-share flag separately and is not affected. Single-game smokes use the batch runner until this is fixed by the owner.
- 2025 games cannot be run through `run_slc_game --game-id` as-of: `pregame_snapshot.build` needs a schedule version observed before the as-of time, and 2025 rows were first observed on 2026-07-28. Historical comparison uses archive reconstruction, which is outside this amendment.
