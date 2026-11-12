# V1.7 historical penalty data and forward-test protocol

**Branch:** `feature/slc-v1.7-penalty-model-2026-11-12`  
**V1.6 base:** current `slc-v1.6` merged before these changes  
**Purpose:** bring V2 historical penalty processing into the existing V1.7 probability-model branch without importing V2 game, strength, workload, or sampler systems.

## Evidence boundary

The V2 PBP extract, parsed clauses, and disposition categories are retrospective source records and text evidence. They are not verified rulings, unique independent opportunities, or cutoff-safe source vintages. A `penalty=0` source field does not prove no foul; a textual `enforced`, `declined`, or `offsetting` marker does not itself prove the official ruling. Several fouls can occur on one play, and one scalar penalty field cannot represent them all. The ten-play official-record check across two gamebooks is a small mapping check, not a representative adjudication dataset.

The V2 evidence report, JSON audits, manifests, and scripts are retained in `docs/research/slc-v2-penalty-opportunities-2026-11-10/`. The row-level CSV/Parquet artifacts remain at the V2 source revision and their SHA-256 values are recorded in that folder's README. They are intentionally not copied into V1.7.

## Adapted work sequence

1. Preserve the existing V1.7 occurrence model and tests, and sync its base to current V1.6.
2. Use the copied corpus builder, opportunity-extract generator, clause parser, disposition classifier, coverage/state audits, false-start audit, and official-sample audit to reproduce source-level research where the pinned V2 artifacts and raw sources are available.
3. Treat those results as candidate evidence only. Build the model JSONL denominator from independently reviewed opportunities, including verified no-foul opportunities. Resolve every event against an official record and retain source publication vintage, source row ID, and gamebook reference.
4. Run `penalty_train.py --adapt-historical-jsonl ... --adapted-output ...` only on records that already contain affirmative official-record and opportunity-denominator verification. The adapter validates the declared evidence and schema; it is not an adjudicator. It writes a separate `.audit.json` provenance manifest. V2 parsed clauses alone must be rejected.
5. Fit only on cutoff-safe verified training opportunities; evaluate on a later chronological holdout against context-only and league controls. Preserve exclusions and denominators by season, foul class, and reason. No model fitting is valid until verified opportunity-level inputs exist.
6. Run the isolated deterministic enforcement engine on its supported rule fixtures. Keep unsupported rule combinations as hard errors. Do not connect it to V1.6 game transitions until the complete transition and non-regression gate has passed.

## Verified adapter record

Each adapter input JSONL row carries the V1.7 model opportunity fields (`context`, `opportunity_id`, kickoff and source publication timestamps, `outcome`, `label_verified`, `foul_count`, and `disposition`) plus:

```json
{
  "audit_evidence": {
    "official_record_verified": true,
    "opportunity_denominator_verified": true,
    "official_record_url": "https://...official-gamebook.pdf#page=...",
    "source_row_id": "stable-publisher-game-play-id",
    "source_text_disposition_only": false
  }
}
```

Those booleans are an auditable human/data-owner attestation, not proof created by the adapter. Both true verifications and an official record reference are mandatory. The model's existing cutoff, duplicate, taxonomy, disposition, and denominator gates remain in force.

## Enforcement engine scope

`scripts/nfl_sequence/penalty_enforcement.py` is deterministic and separate from event sampling. Its initial tested subset covers pre-snap false start/delay of game/encroachment/neutral-zone infraction, plus supported live forward-pass offensive holding, defensive holding, illegal contact, and defensive pass interference. Acceptance or decline is an explicit input. It rejects scoring/goal-line, half-distance, possession-change, offsetting/multiple-foul, special-teams, and other unsupported cases. It is not a complete NFL enforcement engine and is not integrated into V1.6 state transitions.

The rule mapping follows the official 2026 NFL Rulebook: Rule 14-1-1 (declined penalties), 14-1-2 (down after penalty), 14-2-1 (half distance), 14-4-1 (before-snap enforcement), and 14-4-5 (passing-play enforcement and DPI exception); defensive holding/illegal contact and DPI automatic first downs are specified in the relevant foul rules. Source: [2026 NFL Official Playing Rules](https://static.www.nfl.com/image/upload/fl_attachment/league/tqivdkzt9mu6wdgsh1ku.pdf). The engine explicitly refuses the special cases omitted from its integer-yard state representation.

## Release gates

- V1.6 remains the baseline; penalties disabled must leave its play/RNG histories unchanged once integration is attempted.
- Reproducible source manifests, publisher hashes, full eligibility/exclusion accounting, independently verified no-foul denominators, and source vintage evidence.
- Chronological holdout scoring against simple controls; no score is reported as validated without real independent holdout rows.
- Legal enforcement fixtures for every supported foul, plus hard-rejection tests for unsupported transitions.
- Paired game-level comparison for penalty-off control and penalty-on candidate, with predeclared non-regression bounds for drive, clock, scoring, sacks, and turnovers.
- Freeze only after code/data hashes, seed ledgers, test results, and an explicit decision are recorded.

**Current data status:** V2 historical extracts and audits are ported, but they do not yet supply verified opportunity-level training JSONL. Therefore a real fit/holdout validation is intentionally not reported or fabricated.
