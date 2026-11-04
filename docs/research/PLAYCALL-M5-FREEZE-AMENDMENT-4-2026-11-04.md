# M5 freeze amendment 4, 2026-11-04: six-lineman and two-QB groupings

Status: owner-authorized (2026-11-04). Research only, behind the `--participation-field` flag, off by default. No SLC
default changes. No production activation. No 2026 outcome was read. Earlier freeze documents and amendments are not edited.

## Why

The lineup table coded a grouping as the RB (with FB) and TE counts only and assumed one QB and five linemen. A six-lineman
12 (1 RB, 2 TE, 1 WR) was coded 12 and simulated with two WRs; a second QB's spot went to a skill player. On 2025, 8.1% of
observed snaps had skill counts that did not match their code.

## The change

- Grouping codes carry the line and QB counts: `12-OL6` is a six-lineman 12, `11-QB2` a two-QB 11. The WR count is what the
  line, QBs, RBs and TEs leave of eleven. From 2023 the participation file lists every position (C, G and T), so a missing
  QB is zero QBs; the 2022 format lists only the skill players, plus OL and QB when they are not five and one.
- Plays with no QB, a kicker, punter or snapper on the field (fake kicks), or a personnel string that does not total eleven
  (a publisher error: the same rows list eleven IDs) are kept, flagged `flag_nonstandard_offense` and left out of the fit:
  535 of 140,712 scrimmage rows, including the 387 defensive-label rows already excluded.
- The lineup places a second QB from the QBs other than the starter (the lowest depth rank, the engine's passer). A backup QB
  can carry or catch only when he is on the field. The starter is never in the lineup and always passes.
- The scrimmage table is written with gzip mtime 0, so its file hash depends on its content only.

## Changed files

Base commit: `9dbab0a1`.

| File | Frozen SHA-256 | Amended SHA-256 | Pinned | Change |
|---|---|---|---|---|
| `scripts/nfl_sequence/pre_event.py` | `bd2a42be8b3412db27c4eb0e262910623a8dd913d2ee1e2569bce907ec23daaf` | `6b91c7de4b11de975197d8c0f4af3cfccd5435784a67699c07ae1dca9c25ee3f` | yes | The lineup sees the QBs; `on()` keeps the starter and admits another QB only when he is on the field. Flag off: unchanged. |
| `scripts/nfl_sequence/participation_field.py` | `2998c6c23e757595d0abb68bf1aee849795762edfa0111c1c2fe49d514a295ba` | `75c54dcec70d84cb05feaefa6a6cdaffd29f58305326939128ade6818596f5ce` | no | `group_counts` reads `-OL<n>` and `-QB<n>` and returns a `QB` count for a second QB; `starter_qb`; schema v3 accepted with v2. |

Research files (not pinned): `build_tables.py` `bae2d95b...`, `lineup_fit.py` `fcc421f3...` (decodes codes through
`participation_field.group_counts`), `export_field.py` `31e0a029...` (schema v3), `participation_model.py` `70fc678a...`
(leaves out flagged rows). Tests: `test_participation_field.py` `b3aa42ae...`, `test_participation_field_hook.py` `2ba5f971...`.

## New tables

| File | SHA-256 | Fit seasons |
|---|---|---|
| `participation-model-2026-11-02/outputs/field_v3_2022_2025.json` | `a31fc7150c107b3c15b11e2e643ace88828c033f8da3576b51348e4b5a677107` | 2022 to 2025, for 2026 games |
| `participation-model-2026-11-02/outputs/field_v3_2022_2024.json` | `da0c439b17a286c524b33f7005b6280f66a13b4ea9dc3603324ddedc1a3ef917` | 2022 to 2024, for the 2025 check |

Rebuilt from the same raw files; the rebuild reproduces the v3 table byte for byte. Snaps in the fit whose players' roster
classes do not match their grouping: 7,764 of 140,325 (5.5%) before, 2,966 of 140,177 (2.1%) after.

## Verification

- Tests: 91 passed (`test_participation_field`, `test_participation_field_hook`, `test_pre_event`, `test_pbv1_hook`,
  `test_rng_protocol`, `test_slc_playcall`).
- 2025 lineup validation (`validate_lineups.py`, fit 2022 to 2024, 3 seeds; `outputs/lineup_validation_v3_2025.json`,
  `332b43da...`): observed snaps whose players match their code 91.9% to 97.0%. Free-run model against observed: same skill
  lineup as the previous snap 22.7% (observed 24.1%; v2 model 23.7%), entries per snap 1.21 (observed 1.39; v2 1.19), same
  grouping as the previous snap 56.2% (observed 53.1%; v2 58.3% against 55.8%).
- Flags-off regression (frozen extract, Week 8 `2026_08_KC_DEN`, RNG v2, seeds 1 to 3): 0 of 3 seeds differ.
- Flag-on smoke with `field_v3_2022_2025.json`: 3 of 3 seeds complete (31-26, 45-29, 19-16); six-lineman groupings appear
  (DEN `12-OL6` 3 to 5 times a game); no short lineups.

## Known limits

- The grouping is still drawn without the run or pass call. Next amendment.
- The substitution shortfall (1.21 against 1.39 entries per snap) is unchanged.
