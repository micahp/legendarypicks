# SLC play-calling design note, M1 (2026-11-02)

Status: design note. No code changed, no test run, no 2026 outcome read. Written by the manager from the named
files in `PLAYCALL-WORKLOAD-TASK-2026-11-02.md`, because the executor was too slow to produce it. Each claim below
names the file it came from. Where the claim is from a module docstring and not from a code path, it says so.

## 1. What each layer decides today

| Module | Decides, before the outcome | Source of the prior | Status in the code |
| --- | --- | --- | --- |
| `decision_layer.py` | Labels A to N for each play, drawn from the offense's situation-cell prior (dropbacks: A, D, E, G, I, N; runs: B, C; both: F, H, J, K, L, M). Each drawn label lifts the outcome weights. | Most recent season before the cutoff, shrunk to league with K = 20. | Docstring says "research, not adopted". Enabled by `playcall_decision` (True in V1). |
| `playbook_prior.py` | Replaces the decision prior for pass depth (D), pass location (E), run gap (C), where the playbook has a prior for the situation. | Gridiron playbook files, season before cutoff. | Docstring says "off by default". V1 sets `playcall_playbook` True, and `slc_config.py` line 196 requires decision labels on. **Conflict, see Q1.** |
| `formation_layer.py` | Formation (SHOTGUN, UNDER CENTER, PISTOL) and personnel code (RB and TE counts, e.g. "11"), by intent, down and distance. Unknown stays UNKNOWN. | Play-by-play and participation, seasons before the cutoff, shrunk with PRIOR_STRENGTH = 25. | Docstring says "research, not adopted". Called from `pre_event.choose` (lines 325 to 328). |
| `defense_layer.py` | Coverage on dropbacks. Unpublished coverage stays UNKNOWN and is never assigned. | Defense's own coverage shares from participation 2016 to 2025, shrunk like the formation layer. | Docstring says "research, not adopted". |
| `pre_event.py` | The carrier (run) or target (pass), chosen from roster and usage shares before the outcome row is drawn. | Pregame roster and usage shares. | Docstring says it depends "on the pregame roster and usage shares only". |

## 2. Gaps, verified in the named files

- G1. Personnel is drawn but does not restrict who can play. `pre_event.py` stores `chosen['formation']` and
  `chosen['personnel']` (lines 325 to 328). A grep of the file finds no other use of either name. Participant
  choice therefore ignores the personnel group. This is the write-up's central claim, and it is confirmed for
  this file only.
- G2. The order of decisions is implicit. Intent (run or dropback) comes from the play-call layer, then formation
  and personnel, then participants, then the outcome. The docstrings describe each step; no single module
  assembles them into one ordered sequence.
- G3. The "play family" level (inside run, outside run, short pass, intermediate pass, deep pass, designed QB run)
  is not a named object in the four modules read. The closest structure is the decision labels (D pass depth,
  E pass location, C run gap, B rusher role). Whether a play family is built anywhere else is not checked.
- G4. Defensive labels exist (coverage from `defense_layer.py`). Front and blitz labels are not read from any
  module in this note. Box count, blitzers and pass rushers are named in the manager decision; their source
  columns are not yet located.

## 3. Interface proposal (for review, not implemented)

Ordered decisions for one snap, each with its inputs, its output, and the module that would own it:

1. Game state: score, clock, field position, down, distance, timeouts. Owner: existing game-state code.
2. Intent (run or dropback): existing play-call policy, unchanged in M1.
3. Play family: a new object mapping intent and state to a family. Owner: to be designed; no prior yet.
4. Personnel package: from the formation layer's personnel code, with the same cell and shrinkage. Output must
   change the eligible set (fixes G1). Owner: `formation_layer.py` plus `pre_event.py`.
5. Eligible players: the roster members whose listed position fits the package. Owner: `pre_event.py`.
6. Carrier or target: chosen among eligible players by usage share conditional on eligibility. Owner:
   `pre_event.py`. Held-out participation is never an input.
7. Defensive coverage: `defense_layer.py`, conditioned on intent and state, UNKNOWN allowed.
8. Outcome: existing outcome pool, lifted by the chosen labels.

Steps 3 to 5 are new behavior. They are not started. They wait for D1 to D5 and for WP1 approval.

## 4. Decisions recorded (manager)

- Defensive labels are proxies only. No named defensive calls are required or invented.
- Coach-specific policy is deferred until a dated team/coach join is verified (gate 4).
- No hard workload caps. No simulated injuries as a workload fix.
- 2026 stays sealed. Held-out participation is not a model input.

## 5. Open decisions and questions (not answered; no assumption made)

- D1 Status of 2025 (holdout record says examined; write-up says untouched). OPEN.
- D2 Fit and test split, depends on D1. OPEN.
- D3 Numeric advance thresholds for every gate. OPEN. No arm can advance without them.
- D4 Which source defines "eligible players": participation files, SLC records, or both. OPEN.
- D5 Which matchups are the "contrasting matchups" for gate 7. OPEN.
- Q1 Is the playbook prior on in `v1_full_stack`? `slc_config.py` sets `playcall_playbook` True; the module says
  "off by default". Which is the intended state? OPEN. Blocks any WP1 arm that touches D, E or C.
- Q2 Is G1 (personnel drawn but not restricting eligibility) intended, or a gap to close? OPEN. Recommended:
  treat it as a gap to close in WP1, but this needs the owner to confirm.
- Q3 Source columns for box count, blitzers and pass rushers (G4). OPEN.

## 6. Next steps

- WP0 (baseline, read-only) can run now, using only the named files and the participation and playbook sources.
  It must not open 2026 outcome values.
- WP1 waits for D1 to D5 and Q1 to Q3.
- Milestone reply to the manager: this note's path, and the list of open items above still unanswered.
