# M5 freeze amendment 3, 2026-11-04: participation field lineups

Status: owner-authorized integration (2026-11-04, option A: the lineup grouping counts RB and FB together). Research only.
The new behaviour sits behind a research flag that is off by default. No SLC default changes. No production activation. No
2026 outcome was read.

The original freeze and amendments 1 and 2 are not edited. Their hashes and values stand as written.

## 1. Changed files

Base commit: `79252f2a`. "Frozen" is the hash at that commit. "Amended" is the hash committed with this document.

| File | Frozen SHA-256 | Amended SHA-256 | Pinned in `slc_config.LAYER_CODE_FILES` | Change and reason |
|---|---|---|---|---|
| `scripts/nfl_sequence/pre_event.py` | `5a8b5888a27755389ec6a5aeb6034627c0f9b44f099d6805a48dde45e5fc2e61` | `bd2a42be8b3412db27c4eb0e262910623a8dd913d2ee1e2569bce907ec23daaf` | yes | `choose()` gains `field=None, lineup_state=None` and `chooser()` gains `field=None`. With a field, the side's skill lineup advances one snap first (`_advance_lineup`); the runner, receiver and trick thrower are then chosen only from RB, FB, TE and WR on the field. The game's Dirichlet share population stays the full eligible roster. The personnel label becomes the lineup grouping. `ids()` records `lineup`. A team code the table does not use is refused. With the flag off nothing changes. |
| `scripts/nfl_sequence/slc_engine.py` | `b6a9ae57c4840bd4d52dcfc5e735d5c2953f187c1471de4d1b21bf5c3565dcdb` | `29834b829bd32e4f2dc23c280623a66228e5d71922acf6656a6bc7eff123fd5a` | no | `load_reference()` gains `participation_field=None` (path, sha256). It refuses PBV1 at the same time and a table not fitted only on seasons before the game. `play()` refuses the field without RNG protocol v2 and passes it to the chooser. `summary()` adds `lineup` (per-team snaps, player snaps, groupings, short snaps, cell fallbacks) only when a play carries a lineup. |
| `scripts/nfl_sequence/simulate_pregame_batch.py` | `e167deb00ada574ce24e4d0696b7c556b8efe52ab4216953693fd2c296b31e24` | `68434725a4763eb4783c282c9461d195651595a3c3a956367fcc1c410e62780e` | no | Adds `--participation-field PATH` and `--participation-field-sha256 HEX` (off by default). Requires the hash, RNG protocol v2 and the SLC engine; refuses PBV1. Pins the table in the ledger header's `research_integration`. |
| `scripts/nfl_sequence/participation_field.py` | `e1621223e35ff35ab904c064799b3d18c66a4466bdfbab67dc1c538dd76c4add` | `2998c6c23e757595d0abb68bf1aee849795762edfa0111c1c2fe49d514a295ba` | no | `Field` keeps its fit seasons and teams. `supported_cell()`: a situation cell with fewer than 20 league plays borrows the same down and field bucket at the nearest distance with 20, then the same down's largest cell. Two cells (`1|short|own`, `1|short|deep`) have no data. The rule is provisional; an out-of-sample comparison of fallback rules is queued. |

`slc_playcall.py` is not changed (hash `0cb9eecfeaecd3fe9c959f691eda19c5290b534320632416f8cd0703dd1c6f2c`).

## 2. New files

| File | SHA-256 | Reason |
|---|---|---|
| `scripts/nfl_sequence/test_participation_field_hook.py` | `7b50f9ea310f502222c1520d4359e0946888a9f10077e06883bf7ef64e6ece20` | Flag off unchanged; runner and receiver on the field; grouping is the label; lineups persist; same seed replays; sides kept apart; lineup in the decision record; summary counts; unknown team refused; cell fallback recorded; table hash refused. 15 tests. |

## 3. Verification

- Tests: `test_pre_event`, `test_pbv1_hook`, `test_participation_field`, `test_participation_field_hook`, `test_rng_protocol`, `test_slc_playcall`: 85 passed (python3 3.8).
- Flags-off regression on the frozen reference extract (Week 8 `2026_08_KC_DEN`, `v1_full_stack`, RNG v2, seeds 1 to 3, the
  command in `docs/research/pbv1-flags-off-regression-2026-11-02/run_all.sh`): 0 of 3 seeds differ from the HEAD-code v2
  run, before and after the `summary()` change.
- Flag-on smoke, same command plus `--participation-field docs/research/participation-model-2026-11-02/outputs/field_2022_2025.json`
  (SHA-256 `f5ec825a...`): seeds 1 and 3 complete (30-20, 29-37); seed 2 blocked by
  `non_scramble_run_source_rows_missing:(4, '4-6', '10-19')`. That blocker is the play pool's: the cell's run rows are all QB
  scrambles. The lineup changes the game path, not that cell. Each seed reports `lineup` for DEN and KC (for example seed 1:
  DEN 76 team snaps, groupings 11 x51, 12 x16, 13 x4; no short lineups, no cell fallbacks).

## 4. Known limits, not fixed here

- The lineup covers RB, FB, TE and WR only. QB and offensive line are assumed to be one and five. Six-lineman and two-QB
  snaps are coded as five-skill groupings (8.1% of 2025 snaps do not match their code). Next amendment.
- Personnel is drawn after run or pass, as a label; it does not condition the call. Next amendment.
- The table is fitted on 2022 to 2025 with fixed season weights and no current-season update.
