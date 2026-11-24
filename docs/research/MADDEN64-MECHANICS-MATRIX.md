# Madden Football 64 mechanics matrix: source and runtime audit

Research checkpoint, 2026-11-24. Purpose: identify independently useful football behavior for Phase 1.5, not reproduce Madden's statistical outputs or copy its code or game assets. The original source audit is now extended with an authorized ROM extraction and an initial emulator session; this is still not a claim that every football AI routine has been identified.

## Evidence and scope

- **Target:** Madden Football 64, USA Rev 0, source repository [TheGh0stShip/Madden-64](https://github.com/TheGh0stShip/Madden-64) at **`3f79881ce369abbba504c87eb3a6520af53c1cbf`**. Sources in this document are linked to that commit. The project targets the original N64 program, not an independently verified original design document.
- **Template:** [NHL 95 mechanics matrix at `565aefc`](https://github.com/micahp/retro-sports-arcade/blob/565aefc/research/nhl95-reference-study/MECHANICS-MATRIX.md). Its structure is evidence → current implementation → independent test; its hockey cadence and probabilities are not evidence of Madden behavior.
- **Madden provenance:** the pinned [progress manifest](https://github.com/TheGh0stShip/Madden-64/blob/3f79881ce369abbba504c87eb3a6520af53c1cbf/decomphub.progress.json) reports 786,364 / 1,082,496 code bytes and 2,923 / 3,385 candidate functions as matched C. Assembly references and assembly-assisted C are separate. These remain project-reported byte-match results: this audit verified the supported ROM and reproduced record extraction, but did not rerun code matching. Matching instructions does not prove a recovered variable name or football interpretation.
- **Status labels:** **C-match** means this source path appears in a `matching_*_kmc_units.tsv` manifest. **ASM** means a reference assembly unit, not C-match. **Inference** means the mechanism or football meaning is inferred from access patterns, names, or callers and remains to be independently established. **Unknown** means no routine or semantics established here. A generated address-based function name is a label, not a semantic identification.
- **Address correction, stage 2:** the overlay catalog uses historical shifted coordinates. The project's [image builder](https://github.com/TheGh0stShip/Madden-64/blob/3f79881ce369abbba504c87eb3a6520af53c1cbf/tools/make_overlay_images.py#L57) and [configuration](https://github.com/TheGh0stShip/Madden-64/blob/3f79881ce369abbba504c87eb3a6520af53c1cbf/n64dk.toml) state that overlay 1 links at `0x8008B8E0`, with catalog addresses `0x4724` higher; overlay 4 links at `0x800C5F48`, with catalog addresses `0x18A0` higher. For example catalog `0x800972B8` corresponds to linked `0x80092B94`; catalog `0x800DEB2C` corresponds to linked `0x800DD28C`. This explains the main apparent mismatch in the first audit. The historical M-sections below retain their **catalog labels**; the stage-2 table provides linked addresses. Resident addresses are unshifted. A source-declared symbol or another generic label must still be reconciled against the correct overlay and byte boundaries before a breakpoint is set. Some catalog `# asm` comments are stale: matching C manifests list those units; use the matching manifests for C/ASM attribution.
- **Gridiron comparator:** research branch `research/slc-v1-consolidation-2026-11-23` at `d375f3f79fdd306f7f8ccfa6f6b87ef282de3da7`; SLC `research/slc-v1-complete-2026-11-23` at `8ec7c45be98010ee7515662fc6a41bd850e05793`. Current retro gameplay attributes are authored, not validated NFL player measurements.
- **ROM and emulator:** the user supplied an authorized USA Rev 0 image. Its hash/CRC, extracted archive records, emulator boot and an initial interactive demo sequence are verified in Stage 3 below. The image, extracted payloads, screenshots, and emulator setup remain outside this repository; no proprietary game code or assets are copied here.

Source-match manifests: [resident C](https://github.com/TheGh0stShip/Madden-64/blob/3f79881ce369abbba504c87eb3a6520af53c1cbf/config/us/matching_kmc_units.tsv), [overlay 1 C](https://github.com/TheGh0stShip/Madden-64/blob/3f79881ce369abbba504c87eb3a6520af53c1cbf/config/us/matching_overlay1_kmc_units.tsv), [overlay 4 C](https://github.com/TheGh0stShip/Madden-64/blob/3f79881ce369abbba504c87eb3a6520af53c1cbf/config/us/matching_overlay4_kmc_units.tsv), [overlay 1 ASM](https://github.com/TheGh0stShip/Madden-64/blob/3f79881ce369abbba504c87eb3a6520af53c1cbf/config/us/matching_overlay1_asm_units.tsv). C source paths can coexist with a reference `.s`; C-match requires the manifest, not merely the presence of a `.c` file.

## M1. Roster and availability: confirmed selection mechanism

- **Routines / evidence:** C-match [gameplay_roster_update, `0x80022E74`](https://github.com/TheGh0stShip/Madden-64/blob/3f79881ce369abbba504c87eb3a6520af53c1cbf/src/code/gameplay_roster_update.c#L39); C-match [game_session_process, `0x80021EE0`](https://github.com/TheGh0stShip/Madden-64/blob/3f79881ce369abbba504c87eb3a6520af53c1cbf/src/code/game_session_process.c#L12); C-match [roster_attribute_find, `0x8002209C`](https://github.com/TheGh0stShip/Madden-64/blob/3f79881ce369abbba504c87eb3a6520af53c1cbf/src/code/roster_attribute_find.c); C-match [team_slot_available_test, `0x8003FC94`](https://github.com/TheGh0stShip/Madden-64/blob/3f79881ce369abbba504c87eb3a6520af53c1cbf/src/code/team_slot_available_test.c).
- **Read:** session setup fills 40 rows of 11 slots, using the selector for unfilled entries. The selector walks up to 55 roster slots, compares low-six-bit position IDs, counts eligible positions against a depth value, checks for prior use and an availability predicate, and applies an injury-status threshold when a global flag is enabled. It then walks alternate-position lists and, if necessary, compares one position-indexed ratings byte across candidates. The two high position bits receive special handling; their exact football labels are not independently established here.
- **Important limitation:** later fallback passes omit the injury threshold. Therefore this game code does **not** establish SLC's stricter invariant that an Out, inactive, reserve or unelevated practice-squad player must never be selected. Do not port that fallback. The availability predicate uses a four-entry table and flags; its full relation to real NFL status is unknown. The source calls the byte `injury`, but the underlying original semantics and values are not fully identified.
- **Rating inputs:** an indexed byte from a 25-byte region in a 40-byte runtime player record, chosen using resident `D_8006AABC[position]`. No individual rating name has been verified. Depth counting occurs before all availability checks, so it must not be equated automatically with a modern depth-chart rank.
- **Gridiron / SLC:** `live_participation.advance`, `defense_lineup` and `roster_preflight` choose eligible players; Gridiron's assigned executor accepts the 22 IDs. Current SLC exclusion rules remain authoritative.
- **Independent test:** construct equal-position candidates with availability, depth and alternative positions; assert 22 unique eligible IDs, then remove every eligible candidate and require a named failure rather than an injured/ineligible fallback. Vary a verified gameplay rating only after its semantics and provenance are established.

## M2. Formation slots and runtime assignment: table structure, not a decoded route tree

- **Routines / evidence:** C-match [group_pair_byte_get, `0x8003C6B4` and `0x8003C708`](https://github.com/TheGh0stShip/Madden-64/blob/3f79881ce369abbba504c87eb3a6520af53c1cbf/src/code/group_pair_byte_get.c); C-match [initializer `0x8002F838`](https://github.com/TheGh0stShip/Madden-64/blob/3f79881ce369abbba504c87eb3a6520af53c1cbf/src/code/global_runtime_state_initialize.c); C-match [`func_80022354`, `0x80022354`](https://github.com/TheGh0stShip/Madden-64/blob/3f79881ce369abbba504c87eb3a6520af53c1cbf/src/code/func_80022354.c); C-match [gameplay_state_process, `0x80022C58`](https://github.com/TheGh0stShip/Madden-64/blob/3f79881ce369abbba504c87eb3a6520af53c1cbf/src/code/gameplay_state_process.c).
- **Read:** the two byte getters select one of a pair using a group index and an 11-element stride. The initializer sets the pair-table pointer to resident `D_8006AAD8`, recorded as 880 bytes, consistent with 40 × 11 × 2 byte pairs. The roster selector uses the first value as position and the second as a depth argument. `func_80022354` loops over 11 and writes a position-derived byte to a runtime object, then calls a further setter with the selected slot value.
- **Inference / limits:** this supports an 11-slot formation/personnel mapping. It does **not** identify route waypoints, offensive concepts, defensive coverage, or a complete playbook. The `D_8006AAD8` data are resident initialized program data, not shown to be one of the two archive-5 payloads. One source describes a formation table while other declarations of adjacent data are generic. Verify index bounds and exact object field identity before naming them.
- **Rating inputs:** position and depth selectors, not a demonstrated movement/skill rating.
- **Gridiron:** `engine/autonomous/assignments.js`, `routes.js` and `passing.js` use explicit offensive and defensive assignments. The demo uses one formation and three authored concept combinations.
- **Independent test:** perturb one role/depth entry in a synthetic table and verify only the corresponding eligible slot changes; assert formation, assignments and player identity are fixed before snap. Test every assignment with both offensive directions.

## M3. Top-level update and AI cadence: update chain found; decision scheduler unknown

- **Routines / evidence:** C-match [`func_800911B0`, `0x800911B0`](https://github.com/TheGh0stShip/Madden-64/blob/3f79881ce369abbba504c87eb3a6520af53c1cbf/src/overlays/overlay1/func_800911B0.c#L64); a possible downstream reference [func_800C1FA8, `0x800C1FA8`](https://github.com/TheGh0stShip/Madden-64/blob/3f79881ce369abbba504c87eb3a6520af53c1cbf/src/overlays/overlay1/func_800C1FA8.s) is **ASM**.
- **Read:** `func_800911B0` accumulates a global increment, calls a sequence of other functions, conditionally calls one routine for each of two team indices, decrements counters, and runs other update/render-adjacent calls. This is a strong update-chain lead. The assembly fragment contains register/branch context and tail jumps; interpreting it alone as a complete player-AI routine would be unsafe.
- **Rating inputs / limitations:** no awareness-to-decision mapping or actual player decision frequency was identified in this chain. Counter frequency, what owns it and the functions' football responsibilities are unknown. Do not infer Madden behavior from NHL 95 M3. `object_state_machine_update` at `0x800594D8`, despite its name, identifies itself as a JPEG decoder and is **not** football AI.
- **Gridiron:** `retro-cadence.js` independently maps authored awareness to decision intervals; `passing.js` integrates physics separately and interrupts on phase changes. These choices are not Madden 64 findings.
- **Independent test:** for a fixed seed, alter only awareness and measure decision count while physics-step count stays fixed; verify a possession change interrupts the timer and no decision occurs after whistle. For the source audit, locate the task scheduler's callers and inspect per-actor counters before assigning a decision cadence.

## M4. Rating fields and player behavior: storage established, mappings mostly unknown

- **Routines / evidence:** C-match [roster selector](https://github.com/TheGh0stShip/Madden-64/blob/3f79881ce369abbba504c87eb3a6520af53c1cbf/src/code/gameplay_roster_update.c#L126); C-match [roster_attribute_lookup, `0x80022280`](https://github.com/TheGh0stShip/Madden-64/blob/3f79881ce369abbba504c87eb3a6520af53c1cbf/src/code/roster_attribute_lookup.c); C-match [overlay `0x800C6280`](https://github.com/TheGh0stShip/Madden-64/blob/3f79881ce369abbba504c87eb3a6520af53c1cbf/src/overlays/overlay1/func_800C6280.c).
- **Read:** the selector's fallback indexes a byte array using a position-indexed resident lookup. `roster_attribute_lookup` uses an indirect mapping into an 11-byte row. `func_800C6280` passes a player-indexed signed value and a position-indexed byte to another function. None establishes that a particular byte means speed, awareness, throwing accuracy, catching or tackling.
- **Limits:** `D_8006AABC` is a **position → rating-index selection** for this fallback; it is not a decoded catalog of rating names. `0x800C6280`'s signed values and external function remain unnamed. No Madden 64 speed/strength/decision coefficients are established here. No actual roster payload was examined.
- **Gridiron:** `autonomous-run.js:ratingProfile` maps authored SPD, ACC, AGI and STR to physical capacities; assigned passing separates THA from ACC, and its `AWR`/`PRC` cadence is an authored choice.
- **Independent test:** change one input at a time under matched seeds and inspect the intended decision or physical interaction, including fallback and unchanged controls. Assert ACC changes acceleration, not THA. Do not map an unidentified Madden offset to a modern rating without consumer evidence.

## M5. Play selection and possible play records: partially established

- **Routines / evidence:** C-match [overlay catalog `0x800972B8`, source-declared `func_80092B94`](https://github.com/TheGh0stShip/Madden-64/blob/3f79881ce369abbba504c87eb3a6520af53c1cbf/src/overlays/overlay1/func_800972B8.c#L52); C-match [`func_800960B0`, `0x800960B0`](https://github.com/TheGh0stShip/Madden-64/blob/3f79881ce369abbba504c87eb3a6520af53c1cbf/src/overlays/overlay1/func_800960B0.c); C-match [resource setup `func_800DEA50`, `0x800DEA50`](https://github.com/TheGh0stShip/Madden-64/blob/3f79881ce369abbba504c87eb3a6520af53c1cbf/src/overlays/overlay4/func_800DEA50.c).
- **Read:** one selection routine obtains an ID from `func_800DD28C`, masks it with `0x1FFF`, and assigns the corresponding element of `D_800895DC` to team state. The setup routine places resource-manager entry `0x2E` in `D_800895DC` and invokes a strided base-addition helper over a count read from its header. A second team uses a value returned by `func_800DD524`. `func_800960B0` also takes the low five bits of the first selected record byte into team state and sets up both teams' roster assignments. The header/count, pointer-array and use in team state are stronger evidence for indexed play records than archive names alone.
- **Limitations:** the meaning of the low five bits, pointer entry payload and ID flag bits remain unresolved. The two selectors were found in the stage-2 trace below after accounting for overlay shifts; the code includes mode/context and weighted selection, but human/CPU ownership is not proven for every branch. The `0x2E` value is a **resource entry index**, not established as physical archive 5 index 0 or 1.
- **Rating inputs:** none identified in the matched excerpts.
- **Gridiron:** example calls compose `slant_flat`, `curls` and `four_verticals` from shared routes; SLC records an existing prior-season aggregate run/pass rate. They are not the Madden data structures.
- **Independent test:** serialize a synthetic indexed-call structure, switch offensive and defensive IDs independently, assert 22 legal assignments and replayable call provenance, and prove no outcome/target is supplied before the snap.

## M6. Movement and field-coordinate changes

- **Routines / evidence:** C-match [overlay catalog `0x800A79B8`, source-declared `func_800A3294`](https://github.com/TheGh0stShip/Madden-64/blob/3f79881ce369abbba504c87eb3a6520af53c1cbf/src/overlays/overlay1/func_800A79B8.c); C-match [`func_800BD8A8`, `0x800BD8A8`](https://github.com/TheGh0stShip/Madden-64/blob/3f79881ce369abbba504c87eb3a6520af53c1cbf/src/overlays/overlay1/vector_add.c); C-match [`func_800BD8DC`, `0x800BD8DC`](https://github.com/TheGh0stShip/Madden-64/blob/3f79881ce369abbba504c87eb3a6520af53c1cbf/src/overlays/overlay1/scaled_vector_add.c).
- **Read:** the first routine negates two coordinate-like and two delta-like fields across a linked player-like set and several shared objects, then calls other update functions. The vector helpers add three components, optionally scaled, to fields at offsets `0x2C..0x34`.
- **Inference / limits:** these are coordinate/transform leads and a possible field-direction reversal, not a recovered speed, acceleration, turn model, collision or proof of when quarters switch. The pointer called a player or ball elsewhere has conflicting generic declarations. The catalog/source symbol mismatch applies to the first routine. The `0x800BD8A8` helpers do not by themselves establish their caller's football semantics.
- **Rating inputs:** not established.
- **Gridiron:** `world.js` advances movement each physics step; the SLC bridge currently supports one attacking direction.
- **Independent test:** mirror a live call, both teams, ball and assignments around the field; assert corresponding possession and spot mapping. Independently test bounded acceleration and that physics continues between decision ticks.

## M7. Boundary/ball-state handling: a concrete lead, not ball-flight physics

- **Routine / evidence:** C-match [`func_800A5094`, `0x800A5094`](https://github.com/TheGh0stShip/Madden-64/blob/3f79881ce369abbba504c87eb3a6520af53c1cbf/src/overlays/overlay1/func_800A5094.c).
- **Read:** a structure locally labeled `Ball` supplies two signed coordinate-like fields. The function compares them against thresholds, emits several distinct status types, records shifted coordinates and attaches a `Carrier`-labeled pointer where present. It invokes downstream handlers and adjusts flags. The label and threshold behavior support a **boundary/status candidate**.
- **Limits:** the original type, exact coordinate system, the meanings of status IDs, and the equivalence to legal out-of-bounds/touchdown rules are unverified. This is **not** a throw trajectory, interception, catch or possession algorithm. No rating input was established.
- **Gridiron:** `passing.js` advances an airborne ball and contests reachable players; SLC's reducer currently rejects several unsupported boundary and possession cases.
- **Independent test:** exercise both directions, in-bounds and boundary crossings with and without a carrier; assert no out-of-bounds completion, correctly oriented spot, and one whistle. Trace the status-type consumers before assigning Madden event names.

## M8. QB decision and receiver selection: not yet identified

- **Candidate evidence:** M3's update chain and M5's selected-record pointer are real code, but neither identifies a QB read function. The resource table is not a receiver-selection algorithm.
- **Rating inputs / behavior:** **unknown.** No supported claim of first-read order, awareness-based response, target selection, pressure timing or vision cone.
- **Gridiron:** `passing.js:readOptions`, `qbDecision` and `launchPass` use current retro observations, lane and separation; THA controls an authored error term. Detailed perception is optional.
- **Independent test:** preserve lineup, play and seed; move a defender into the first lane and verify the QB observes the change and can change or delay the target. Instrument the source's per-actor target writes and trace them back before labeling any Madden routine.

## M9. Coverage and pursuit: proximity-selection candidate, roles unknown

- **Routines / evidence:** C-match [overlay catalog `0x800A34D4`, source-declared `func_8009EDB0`](https://github.com/TheGh0stShip/Madden-64/blob/3f79881ce369abbba504c87eb3a6520af53c1cbf/src/overlays/overlay1/func_800A34D4.c); C-match [`func_800C5F5C`, `0x800C5F5C`](https://github.com/TheGh0stShip/Madden-64/blob/3f79881ce369abbba504c87eb3a6520af53c1cbf/src/overlays/overlay1/func_800C5F5C.c).
- **Read:** the first examines four entries, approximates distance to a shared position in two dimensions, tracks both nearest overall and nearest with a particular state byte, and sends one of two calls a command byte for the selected entry. The second sends messages to player-labeled objects on two teams when shared state and a position threshold permit it. These establish proximity-based selection and team-wide message dispatch, respectively.
- **Rating inputs / behavior:** **unknown.** The four entries might have roles other than defenders; a `Ball` or `Player` type name is a decompiler label. The selected command and consumers have not been identified, and the first routine has a catalog/source symbol mismatch. Neither proves pursuit, man/zone coverage, target possession or awareness-specific cadence.
- **Gridiron:** `passing.js:defenseBrain` consumes man/zone/rush assignments and reacts to carrier and ball states; PUR influences pursuit behavior.
- **Independent test:** hold seed, offense and ratings fixed, exchange man and zone tasks, and verify assignments, defender trajectories and QB reads differ. On a possession change, pursuit must interrupt the old assignment.

## M10. Blocking and tackling: interaction candidate, football meaning unconfirmed

- **Routines / evidence:** C-match [overlay catalog `0x800C6A8C`, source-declared `func_800C2368`](https://github.com/TheGh0stShip/Madden-64/blob/3f79881ce369abbba504c87eb3a6520af53c1cbf/src/overlays/overlay1/func_800C6A8C.c#L111); C-match [scaled value helper `0x80031A1C`](https://github.com/TheGh0stShip/Madden-64/blob/3f79881ce369abbba504c87eb3a6520af53c1cbf/src/code/random_scale_u16.c).
- **Read:** this large candidate reads a lead and target object, their position-like, state and byte fields; computes relative direction and a threshold using fields from both; calls the scaled-value helper with variable limits; and can invoke object transitions and modify a shared motion-like object's velocity fields. The helper scales a value returned by another function into a bounded range. Source-local types call the objects `Player` and an event record `Tackle`; those names support a contact candidate but are inferred labels. Whether any particular branch is a tackle, broken tackle, fumble or unrelated interaction is not established. The catalog/source-declared address mismatch matters here: the catalog also has a separate `0x800C2368` ASM fragment, so do not conflate it with the C-match at `0x800C6A8C`.
- **Rating inputs / behavior:** offsets `0x08`, `0x0F`, `0x10`, `0x17` and `0x18` participate in thresholds. Stage 2 traces several to raw rating indices, but their named attributes, units, probability distribution and football context remain **unknown**. No block-shed formula or named tackle rating has been established. The catalog's historical `0x800C6A8C` translates to linked `0x800C2368`; the source-declared name is consistent with that mapping. An assembly reference bearing a historical filename with that same text must be located using its own manifest offset, not conflated by name. `func_800C1FA8` is another ASM fragment with unresolved surrounding context.
- **Gridiron:** `passing.js:chooseBlockTarget`, `tryShed`, and `startTackle`; legacy inside-zone contact is in `autonomous-run.js`. These are authored gameplay, not Madden-derived parameters.
- **Independent test:** under matched seeds vary only blocker, rusher or tackler rating and verify the corresponding observed engagement/shed/tackle path. Confirm contact alone cannot assign a predetermined outcome. Trace actual contact callbacks in the source before naming the underlying routine.

## M11. Passing flight, catches and interceptions: not yet identified

- **Candidate evidence:** M7 is a coordinate/status handler, not the flight integrator. Generic vector functions and graphics animation routines are not enough to establish a ball physics formula.
- **Rating inputs / behavior:** **unknown.** No supported attribution of throw speed, accuracy, catch probability, interception odds or trajectory height to Madden 64 ratings.
- **Gridiron:** `passing.js:launchPass`, `resolveContest`, and `engine/ball.js`; ball path and participants are simulated, not historical whole-play results.
- **Independent test:** vary THA while keeping ACC fixed, check actual throw error; separately vary receiver/defender positions and catch ratings. A defender must reach a catchable ball before an interception can occur. Trace initialization, integrator, collision and event consumers in that order.

## M12. Fatigue, substitutions, clock and statistics

- **Routines / evidence:** C-match [gameplay_state_process `0x80022C58`](https://github.com/TheGh0stShip/Madden-64/blob/3f79881ce369abbba504c87eb3a6520af53c1cbf/src/code/gameplay_state_process.c); C-match [`func_800C6934`, `0x800C6934`](https://github.com/TheGh0stShip/Madden-64/blob/3f79881ce369abbba504c87eb3a6520af53c1cbf/src/overlays/overlay1/func_800C6934.c); C-match [gameplay_event_prepare `0x80025B10`](https://github.com/TheGh0stShip/Madden-64/blob/3f79881ce369abbba504c87eb3a6520af53c1cbf/src/code/gameplay_event_prepare.c); C-match [`func_800911B0`](https://github.com/TheGh0stShip/Madden-64/blob/3f79881ce369abbba504c87eb3a6520af53c1cbf/src/overlays/overlay1/func_800911B0.c).
- **Read:** conditional roster refresh can compare a candidate against the current slot and inspect a status byte; another routine reduces a status byte with a floor of zero when enabled. `gameplay_event_prepare` iterates per-team events, accumulates certain event-type values in player records and sends several event types to another routine. The main update decrements counters under conditions.
- **Limits:** labels such as injury, fatigue, score, event type, CPU timeout or game clock are not established merely by offsets or counters. No full fatigue model, substitution cadence or clock-management decision identified. Do not adopt the game selector's relaxed injury fallback.
- **Gridiron / SLC:** the current bounded drive carries downs and player lines via `reducer.py` and `game_stats.py`; the caller provides snap clocks. No complete full-game clock, all legal special teams, overtime or penalty resolution is claimed.
- **Independent test:** substitutions cannot select an ineligible player; validate two-team stat sums and terminal possession; test stopped/running clocks, timeouts, period and overtime transitions separately when implemented. Cross-reference event IDs to UI labels and verify live traces before identifying Madden stats or clock behavior.

## Two gameplay records and two roster databases

The [ROM record ledger](https://github.com/TheGh0stShip/Madden-64/blob/3f79881ce369abbba504c87eb3a6520af53c1cbf/config/us/rom_files.tsv) reports:

| Physical archive / record | Packed ROM interval | Stored bytes | Expanded bytes | Reported class |
| --- | --- | ---: | ---: | --- |
| 5 / 0 | `0x2DFA58..0x2E065C` | 3,076 | 5,100 | gameplay table |
| 5 / 1 | `0x2E065C..0x2E2E16` | 10,170 | 26,668 | gameplay table |
| 13 / 0 | `0xB514F2..0xB5546C` | 16,250 | 27,125 | roster database |
| 13 / 1 | `0xB5546C..0xB7427E` | 126,482 | 243,720 | roster database |

All four are reported as type-1 compressed. These are **physical ROM addresses**, not function VRAMs or decoded field offsets. `tools/audit_rom_layout.py` classifies archive 5 as `gameplay_table` and archive 13 as `roster_database` by archive number after generic signature checks. Thus those labels are inventory classifications, not proof that individual payloads are playbooks or that the data contain a named rating dictionary. [Layout methodology](https://github.com/TheGh0stShip/Madden-64/blob/3f79881ce369abbba504c87eb3a6520af53c1cbf/docs/ROM_LAYOUT.md) explicitly separates record inventory from semantic reconstruction.

The tracked loader gives a **separate runtime-format lead**: resource entry `0x2E` is relocated as a header plus a counted four-byte pointer array and then consumed by the selection path in M5. Stage 3 maps this resource to archive 4, record 46; it is not either archive-5 physical record. The resident `D_8006AAD8` pair table supplies formation/position-depth inputs in M2. The runtime roster's 40-byte player records and position-indexed rating array are established by C consumers; Stage 3 checks the corresponding archive-13 record sizes and hashes, but does not establish player names, attribute labels, or a stable identity bridge.

**Answer:** the archive-5 gameplay payloads remain semantically unresolved. The runtime selection resource is a different item, archive 4 record 46; static source and bounds-checked extraction support an indexed candidate-record format used by the play-selection path, but do not reveal a reliable route tree, call names, or all record meanings. Archive-13 record sizes align with the runtime 217-byte and 40-byte record strides. No player names, raw payloads or proprietary assets are included here. See Stage 3 for hashes and extraction limits.

## Priority of remaining evidence

1. The catalog shifts, selector bodies, and static source of resource `0x2E` are resolved below. A bounded part of its nested candidate structure is decoded; use an emulator trace to tie selected IDs and entries to specific displayed plays and assignments. Keep archive-5 record semantics an open question.
2. Trace the per-actor update entry from `func_800911B0`, distinguish players from render/model objects, and identify actual QB, receiver and defensive state writes. Establish cadence and rating inputs with instruction-level and, if authorized, emulator evidence.
3. Trace ball initialization → integration → contact → event handler, then blocking and tackling contact handlers. Attribute outcomes only once the relevant state and events are established.
4. Runtime loader and record strides now align archive-13 payload sizes with 217-byte team-like records and 40-byte player-like records. Trace a selected team/player entry in the emulator before assigning record fields, names, dates, identity or provenance.
5. Preserve current V1 Complete behavior and the four historical replay hashes. Proposed tests are behavioral and independent; they do not copy code or assets and do not tune SLC to Madden score distributions.

## Stage 2: linked-address trace

### Evidence boundary

The Stage 2 findings below are static source and address-layout analysis. The ROM and emulator checks appear in Stage 3. A visible screen plus a program-counter read does not establish the semantics of a routine; source path and runtime event must still be correlated before assigning football behavior.

### Corrected overlay addresses

The previous pass treated catalog/source differences as unresolved. The pinned project explicitly records the historical shifts and real link bases in [`n64dk.toml`](https://github.com/TheGh0stShip/Madden-64/blob/3f79881ce369abbba504c87eb3a6520af53c1cbf/n64dk.toml) and [`tools/make_overlay_images.py`](https://github.com/TheGh0stShip/Madden-64/blob/3f79881ce369abbba504c87eb3a6520af53c1cbf/tools/make_overlay_images.py#L57). The linked addresses below were independently checked as `manifest offset + image vram_delta`. Overlay 1 catalog addresses are linked address + `0x4724`; overlay 4 catalog addresses are linked address + `0x18A0`. This is an address conversion, not proof that any emulator will have the relevant overlay resident at an arbitrary moment.

| Source and C-match catalog coordinate | Linked address | What the static trace supports |
| --- | --- | --- |
| [overlay 1 selection `0x800972B8`](https://github.com/TheGh0stShip/Madden-64/blob/3f79881ce369abbba504c87eb3a6520af53c1cbf/src/overlays/overlay1/func_800972B8.c) | `0x80092B94` | Selects an ID, indexes `D_800895DC`, stores selected records for team state. |
| [overlay 4 selector `0x800DEB2C`](https://github.com/TheGh0stShip/Madden-64/blob/3f79881ce369abbba504c87eb3a6520af53c1cbf/src/overlays/overlay4/func_800DEB2C.c) | `0x800DD28C` | The previously unresolved first selector; dispatches by mode and table-derived type. |
| [overlay 4 selector `0x800DEDC4`](https://github.com/TheGh0stShip/Madden-64/blob/3f79881ce369abbba504c87eb3a6520af53c1cbf/src/overlays/overlay4/func_800DEDC4.c) | `0x800DD524` | The previously unresolved second selector; similarly dispatches by mode and table-derived type. |
| [overlay 4 selection decoder `0x800E0178`](https://github.com/TheGh0stShip/Madden-64/blob/3f79881ce369abbba504c87eb3a6520af53c1cbf/src/overlays/overlay4/func_800E0178.c) | `0x800DE8D8` | Decodes nested tables and selects a candidate ID with weights. |
| [overlay 4 weighted picker `0x800E3AE8`](https://github.com/TheGh0stShip/Madden-64/blob/3f79881ce369abbba504c87eb3a6520af53c1cbf/src/overlays/overlay4/func_800E3AE8.c) | `0x800E2248` | Sums byte weights and uses the scaled RNG helper to select an index. |
| [overlay 1 interaction `0x800C6A8C`](https://github.com/TheGh0stShip/Madden-64/blob/3f79881ce369abbba504c87eb3a6520af53c1cbf/src/overlays/overlay1/func_800C6A8C.c) | `0x800C2368` | Reads two actors' fields in an interaction calculation; event semantics remain unconfirmed. |

The source declaration inside a shifted C file can itself use either naming convention. Do not blindly add or subtract a shift from a name referenced inside code: first identify its owning overlay and compare the matched manifest offset and `vram_delta`. The C-match attribution comes from the project manifest; the conversion is a static calculation, not an independent ROM match or debugger observation.

### Indexed selection records: more of the format, not a route decoder

The linked selection caller `0x80092B94` calls `0x800DD28C` and `0x800DD524`; their matching bodies are the catalog-named selector files in the table. Their zero-mode paths can return a direct value or call linked `0x800DE8D8` depending on a table-derived type; other cases use sentinel values and flags. The code does not by itself prove which branch is user selection or CPU selection in every game mode.

The selection decoder at linked `0x800DE8D8` reads a different resource set under `D_8007A178` and uses a team-indexed byte to choose among variants. Its static operations establish the following **partial** structure:

1. A table selected by side contains four-byte, little-endian assembled relative offsets; an entry indexed by a global selection value locates a nested record.
2. That record has a count byte at offset 4, followed by count key bytes. It chooses a matching key or a default. Per-key offsets are assembled from two bytes in big-endian order and applied relative to the key-offset-list base.
3. The selected subrecord starts with a count, then count weight bytes, then count two-byte candidate IDs in big-endian order. Depending on a byte condition, existing weights are copied or a temporary set is generated from another team byte and the selected record's first-byte mask. Linked `0x800E2248` chooses from the weight array; the corresponding candidate ID is returned.
4. A returned ID can then be masked and used to index `D_800895DC`, the separate relocated resource entry `0x2E`. Its first byte is also consulted through a bit mask by the decoder.

These facts describe code access paths and byte ordering; they do not establish an actual decoded play, the names of keys, the meaning of the candidate IDs, or the relation of the team byte to football attributes. Stage 3 checks the extracted table bounds and maps `0x2E` to archive 4 record 46. The nested weighted table is the separate `D_8007A178` resource (`0x2D`), not `0x2E`. The user-facing concept names, route encoding and exact selected-assignment linkage still need a paired emulator trace.

**Proposed controlled trace:** load the same verified save twice; choose two offensive plays while holding teams, settings and frame position fixed. Log selected ID, overlay identity, `D_800895DC` at `0x800895DC`, the entry pointer, record first byte and 11 resulting assignments before snap. Verify in-range reads and stable repeated selections before changing one input. Then single-step the selected-record consumer and compare writes to actor fields. Treat any human-readable play-name mapping or route semantics as a hypothesis until observed in repeated runs.

### Forty 11-slot groups

The resident byte array `D_8006AAD8` contains exactly 880 bytes: 40 rows × 11 pairs. A local read-only count of its tracked C initializer found 36 nonzero rows, four all-zero rows at indices 36–39, 21 distinct byte-pattern rows including the zero row, first-byte values 0–24 and second-byte values 0–5. These are representation counts, not 36 verified formations or named positions. The matched `0x8003C6B4` / `0x8003C708` getters first map a requested group through a descriptor, then select one byte of the relevant 11-pair row. The position/depth selector consumes both bytes.

There is now a **conditional source-level link** from a selected record to the slot table. In [overlay 1 catalog `0x800960B0`, linked `0x8009198C`](https://github.com/TheGh0stShip/Madden-64/blob/3f79881ce369abbba504c87eb3a6520af53c1cbf/src/overlays/overlay1/func_800960B0.c#L93), under its specific state/mode/flag condition, the code takes the low five bits of the first byte of the `D_800895DC` entry selected by `D_8006B7AC` and writes them to `D_80082DBC[team].unk_04`. That field's address is the team's `D_80082DC0` formation field. The same routine subsequently invokes `func_80022354` for both teams; it reads that field as the table ID, while the getters and `gameplay_state_process` use the corresponding descriptor and `D_8006AAD8` to populate or refresh 11 slots. This identifies the data path for that branch, **not** the football name of the ID, an unconditional rule for both sides or a decoded route assignment. Other branches and actual execution still need verification.

**Experiment:** keep personnel, matchup and save state fixed; choose two formations, capture selected record and group descriptor, then compare 11 slot bytes with on-screen alignment. Test a same-formation/different-play pair separately. A row's being all zero must not be interpreted as an empty legal formation without tracing its descriptor and consumers.

### Roster arrays and a partial 25-byte runtime map

The matched resident initializer [`audio_resources_initialize.c`](https://github.com/TheGh0stShip/Madden-64/blob/3f79881ce369abbba504c87eb3a6520af53c1cbf/src/code/audio_resources_initialize.c) at `0x80039674` passes `D_80000430` and a 24-byte table length to the resource manager, then obtains entries 0 and 1. The [boot loader](https://github.com/TheGh0stShip/Madden-64/blob/3f79881ce369abbba504c87eb3a6520af53c1cbf/src/boot/load_program.c) populates the 16-word archive-boundary table beginning at `0x80000400`; the committed layout places `0x80000430` at boundary index 12. Boundaries 12 and 13 coincide at `0xB514DA`, the start of the nonempty archive-13 table. The matched [`memory_block_update`](https://github.com/TheGh0stShip/Madden-64/blob/3f79881ce369abbba504c87eb3a6520af53c1cbf/src/code/memory_block_update.c) uses 12-byte entries, consistent with archive 13's two physical records.

The runtime consumer `frame_entry_at` advances through entry 0 by 217 bytes; `roster_selection_update` and `audio_frame_record_copy` treat entry 1 as 40-byte records. The reported expanded sizes divide exactly: 27,125 = 125 × 217 and 243,720 = 6,093 × 40. The loader chain plus these checks strongly supports archive 13/0 → 217-byte record array and 13/1 → 40-byte player-like record array. These are static, project-ledger-derived counts, **not** verified independent payload parsing or a claim that all 125/6,093 records are usable real teams or players. Attribute names, text encoding, provenance and exact identity mapping remain unknown.

Matched [`roster_selection_update` at `0x8003AA28`](https://github.com/TheGh0stShip/Madden-64/blob/3f79881ce369abbba504c87eb3a6520af53c1cbf/src/code/roster_selection_update.c) copies a 40-byte source record and can apply an alternate override beginning at offset `0x0E`. [`roster_symbol_lookup` at `0x80022B3C`](https://github.com/TheGh0stShip/Madden-64/blob/3f79881ce369abbba504c87eb3a6520af53c1cbf/src/code/roster_symbol_lookup.c) accesses indexed bytes starting at record offset `0x0F`. Matched [`audio_sequence_channel_configure` at `0x8003B9C0`](https://github.com/TheGh0stShip/Madden-64/blob/3f79881ce369abbba504c87eb3a6520af53c1cbf/src/code/audio_sequence_channel_configure.c) initializes a player-like runtime object; despite the generic audio-derived filename, its dataflow is visible in the source. It uses [`audio_stream_prepare` `0x8003BD68`](https://github.com/TheGh0stShip/Madden-64/blob/3f79881ce369abbba504c87eb3a6520af53c1cbf/src/code/audio_stream_prepare.c) and [`audio_stream_configure` `0x8003BF9C`](https://github.com/TheGh0stShip/Madden-64/blob/3f79881ce369abbba504c87eb3a6520af53c1cbf/src/code/audio_stream_configure.c) to transform several bytes based on context and optional status.

| Raw 25-byte region index | Runtime object field | Static source mapping |
| --- | --- | --- |
| 0, 1 | `0x08`, `0x09` | Direct byte copies; index 0 also contributes to a model field. |
| 2–8 | `0x0A`, `0x0C`, `0x0E`, `0x0F`, `0x10`, `0x11`, `0x12` | Passed through prepare types 2–8; `0x0C` is a halfword field. |
| 9–13 | `0x15`, `0x16`, `0x17`, `0x18`, `0x19` | Passed through types 9–13; `0x18` is later adjusted by a scaled-RNG draw and clamped. |
| 14–16 | `0x13`, `0x14`, `0x1A` | Passed through types 14–16; `0x14` is later adjusted by a scaled-RNG draw and clamped. |
| 17 | `0x1B` | Direct byte copy from the player-like record. |
| 18–24 | unknown | No actor-field mapping established in this trace. |

The two-object interaction candidate at linked `0x800C2368` uses object fields `0x17` and `0x18` in a threshold, linking that candidate to prepared raw indices 11 and 12. This is a **dataflow relationship**, not identification of those bytes as tackle, break-tackle, awareness or any other named skill. Several transforms depend on mode, status and contextual helpers, so the runtime field is not always a verbatim rating byte. An existing position-specific aggregate function, [overlay 5 `func_800D20A0`](https://github.com/TheGh0stShip/Madden-64/blob/3f79881ce369abbba504c87eb3a6520af53c1cbf/src/overlays/overlay5/func_800D20A0.c), uses different indexed combinations by numeric position; the position and attribute names remain unresolved. No coefficients or proprietary data are copied into Gridiron.

**Experiment:** after identity and access are established, change exactly one raw byte in an isolated emulator state, record the corresponding initialized actor field before and after any RNG adjustment, and compare matched-seed movement, decisions and interactions. Repeat by position; record all other inputs and RNG state. Do not name an attribute from an aggregate formula or a single visual change.

### Remaining controlled experiments

The ROM/emulator prerequisite is now satisfied, but controlled gameplay evidence is not. Save a repeatable state at play selection, set breakpoints only after confirming their linked overlay is loaded, and correlate the selected record ID, `D_800895DC` entry, 11 slot assignments and the visible call. Repeat with only one offensive selection changed. Then trace a first snap and ball transition. Only after that should one player rating or defensive assignment be varied. The current SLC full-game track remains independent of these research findings.

## Stage 3: verified image, extracted runtime tables, and emulator session

### Image verification and extraction reproduction

The authorized USA Rev 0 image supplied by the user was staged outside the repositories. The project's [`verify_rom.py`](https://github.com/TheGh0stShip/Madden-64/blob/3f79881ce369abbba504c87eb3a6520af53c1cbf/tools/verify_rom.py) accepts it as a 12,582,912-byte image with SHA-256 `39f25dad3af4782a909bf58d7127acae700ea7c6f17c48d39ab76fe331735d6f`, CRC1 `13836389`, and CRC2 `265B3C76`.

I reproduced the project's lossless record extraction into a private temporary directory using the verified main segment and [`extract_assets.py`](https://github.com/TheGh0stShip/Madden-64/blob/3f79881ce369abbba504c87eb3a6520af53c1cbf/tools/extract_assets.py). It emitted 1,353 records and 14,918,923 expanded bytes. A second extraction produced a byte-identical manifest and payload tree (`cmp` on the manifest and recursive `diff` on all extracted records).

This does **not** reproduce the whole `make extract-assets` prerequisite chain or rerun byte matching: the configured `n64-decomp-kit` checkout/toolchain is absent. The image was verified independently of the project's reported C-match totals. The ROM, expanded records and screenshots remain outside the worktree.

### The two inventory "gameplay tables"

The project's ROM ledger labels archive 5 records 0 and 1 `gameplay_table`. Their expanded lengths and SHA-256 digests are:

| Archive record | Expanded bytes | SHA-256 | Result |
| --- | ---: | --- | --- |
| 5 / 0 | 5,100 | `6cd5df02d2c724b2fd7814335bfef23e59715e8d957a63ade2915660ea66f4e2` | Payload identity verified; a stable football/playbook schema was not established. |
| 5 / 1 | 26,668 | `2897971e87e60eedec9acd1f4370dd33bc70e3bd4c9b46693937d7e1e99e509e` | Payload identity verified; a stable football/playbook schema was not established. |

Those labels derive from the archive inventory and should not be treated as proof that either file is the playbook. The resource table actually traversed by the play-selection source path is elsewhere: resource entries `0x2D`–`0x30` resolve to archive 4 records 45–48. Their manifest class is `graphics_auxiliary`, which is likewise a broad inventory label and not a reliable semantic description.

### Resource `0x2E`: indexed candidate records, partially decoded

The source-to-payload mapping is now established statically:

1. [`func_800E6290`](https://github.com/TheGh0stShip/Madden-64/blob/3f79881ce369abbba504c87eb3a6520af53c1cbf/src/overlays/overlay4/func_800E6290.c#L267) initializes a resource-manager handle from `D_80000410` and a 0x2B8-byte table.
2. [`func_800DEA50`](https://github.com/TheGh0stShip/Madden-64/blob/3f79881ce369abbba504c87eb3a6520af53c1cbf/src/overlays/overlay4/func_800DEA50.c#L17) loads indices `0x2D`, `0x2E`, `0x2F`, and `0x30` into `D_8007A178`, `D_800895DC`, `D_8008AF8C`, and `D_800869EC`. It relocates the first three as counted, four-byte pointer tables; `0x2E` supplies the count for `0x2F`.
3. The boot boundary table places that resource range in physical archive 4. The resource indices therefore map directly to records 45–48 below. The [selection caller](https://github.com/TheGh0stShip/Madden-64/blob/3f79881ce369abbba504c87eb3a6520af53c1cbf/src/overlays/overlay1/func_80090C9C.s#L94) calls the overlay-4 selector; the corrected linked-address path in Stage 2 returns a candidate ID and indexes `D_800895DC`.

| Resource | Physical record | Expanded bytes | SHA-256 | Bounds-checked structure / source use |
| --- | --- | ---: | --- | --- |
| `0x2D` | 4 / 45 | 23,868 | `eae3b98163afeea00988d283a32ef5ef09414a020fd12aabaad271efea222fd8` | Fourteen relative-offset table entries are consistent with the source's count and stride. This is `D_8007A178`, used by the selection decoder. |
| `0x2E` | 4 / 46 | 13,213 | `ba5e719a1c02e734ef13a15e897eedeb0ddd64c15202eeb0c9e975afc89aa9ce` | A big-endian count of 185 followed by 185 unique, ascending, in-bounds offsets. This is `D_800895DC`, indexed by selected candidate ID. Entry spans range from 39 to 125 bytes; median 68. |
| `0x2F` | 4 / 47 | 5,796 | `2eddb822d443064b30b614eb347401e36d867525d1e5da88437004e8aaab7a9a` | 185 unique, ascending, in-bounds offsets, matching the count sourced from `0x2E`; source assigns this table to `D_8008AF8C`. Relationship to individual candidate records remains unknown. |
| `0x30` | 4 / 48 | 900 | `787b0bb44e3cdd8a7f3de4bb9c9634af102f5d5b9605f66bba7a035808d3730a` | Loaded as `D_800869EC`; semantic role unresolved. |

The selection decoder reads nested relative-offset tables from `0x2D`, reaches weighted candidate-ID lists, and uses those IDs to index `0x2E`. I checked two traversed subtables: 9 table records/58 key-or-default paths in one and 36 records/42 paths in the other. Across the 100 parsed paths they contain 4,253 candidate-reference occurrences; every candidate masked by the consumer's `0x1FFF` mask is in the range 0–184, and all parsed offsets and candidate-list extents are in bounds. References repeat, so 4,253 is not a count of unique plays.

This is stronger than archive-size inference: it supports an indexed, weighted selection pool whose candidate entries feed the team's selected-record path. A conditional consumer masks the selected entry's first byte to choose a value used by the 40×11 slot-table path. But I have **not** established that every one of the 185 entries is a distinct football play, decoded route assignments or coverage, or tied a particular candidate ID to a displayed concept in an emulator trace. No payload bytes or candidate names are reproduced here.

### Roster payloads: runtime stride alignment, identities still unknown

| Archive record | Expanded bytes | Runtime stride evidence | SHA-256 |
| --- | ---: | --- | --- |
| 13 / 0 | 27,125 | Divides exactly into 125 × 217-byte records; source consumers advance by 217 bytes. | `7aefcda4bb0f2e2c1116a8f604673f07a8a7a3a175e25fa850ab915c0cd83ff5` |
| 13 / 1 | 243,720 | Divides exactly into 6,093 × 40-byte records; source consumers copy and index 40-byte player-like rows. | `daebec2f77a874b355a7b5f4bca69ada94221979fd652f5e97450643d7f04dd2` |

The physical archive mapping comes from the boundary table and loader chain in Stage 2; exact division corroborates the runtime strides. This still does not establish that all rows are active NFL teams or players, how text is encoded, which data vintage is represented, or how ratings map to named attributes. Do not import roster names or rating values into Gridiron/SLC from this evidence.

### Emulator boot and first interactive sequence

Mupen64Plus 2.5 was unpacked into a private temporary directory, not installed system-wide. It accepted the verified ROM and reported the expected game name, size, CRCs and USA region. With a clean temporary configuration and the Rice video, SDL input and HLE RSP plugins, it rendered the EA intro and title, then reached the football attract/demo sequence. The debugger-enabled configuration initially left the screen black because the core was paused; a separate clean configuration resolved that setup issue.

I drove the sequence with the core's SDL key injection command, not prerecorded game decisions. The visible flow reached the Madden demo coin toss, selected heads, chose the receiving team and end zone, and arrived at a kickoff play-call screen showing three kickoff concepts and three return concepts. This confirms ROM boot, rendering, controller-event delivery and entry into the game's play-call UI. It is an initial usability check, **not** a controlled comparison of two selected plays or evidence about AI execution.

This Mupen build exports the R4300 debugger API for memory reads/writes, CPU-register pointers, breakpoints and single-step. In a debugger-enabled run I read the emulated PC through `DebugGetCPUDataPtr`; breakpoint add/remove calls were accepted. I have not yet captured a hit at the linked play-selection or actor-update routines, tied a PC stop to the visible call, made a reproducible save state, or recorded a full play. Those remain the next research steps. Mupen's [front-end API reference](https://github.com/mupen64plus/mupen64plus-core/blob/master/doc/emuwiki-api-doc/Mupen64Plus-v2.0-Core-Front-End.mediawiki) documents the SDL key-injection commands used to navigate the demo.
