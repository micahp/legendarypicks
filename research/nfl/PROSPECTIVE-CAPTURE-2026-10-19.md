# NFL prospective prop capture harness — 2026-10-19

## Result

This is a research-only forecast capture harness. It changes no serving code, model math, market gates, thresholds, or database tables. The harness reads only `/root/legendarypicks/backend/data/picks.dev.db` in SQLite read-only/query-only mode and writes immutable local files under `research/nfl/prospective-capture/`. It does not add a carries market.

The historical run is a harness test, not a prospective forecast. Every row is `capture_mode=backfill`, `cp4_evidence_eligible=false`, and explicitly records that its pre-kickoff assertion is negative. It must never be used as CP4 evidence.

## Implemented and run

| Requirement | Result |
| --- | --- |
| Schema and immutable artifact layout | Implemented in `capture_nfl_props.py` and `capture_validation.py`. Each sportsbook-side observation carries event/player/source identities, market and units, line/book, times and cutoff, pre-kickoff proof, integer-support PMF and mass/tail/truncation metadata, source/input/parameter hashes, and distinct outcome and settlement states. |
| Serving model and calibration imports | Implemented. Projection orchestration comes from `backend/nfl_player_projections_job.py`; draws and summaries from `backend/nfl_player_projection_v2.py`; the forward `v2-platt` map from `backend/nfl_prop_calibration.py`. Captured `v2-platt` is a scalar transform; the PMF remains the base v2 empirical distribution. |
| Route parity check | Implemented in `verify_route_parity.py`. It calls the v2 API handler on representative inputs for every captured provider market and stat, comparing raw P(over) and returned summaries at `1e-9`. The capture itself uses the imported serving functions for every line. The route's local Platt helper is compared with the imported calibration module on all unique captured inputs. |
| Fail-closed validation | Implemented and run on the backfill artifact, including the deliberately broken-row check. See exact output below. |
| 2026 weeks 3–5 backfill | Run to a separate immutable `backfill/` artifact. **26,638 observation rows** (13,319 paired quote lines); week 3 has no eligible model projections because the imported job requires three earlier games. Weeks 4 and 5 contribute 14,002 and 12,636 rows. All rows are backfill and CP4-ineligible. No carries rows were captured. |
| Source database protection | Read-only connection (`mode=ro`, `PRAGMA query_only=ON`) and pinned read transaction. Post-run read-only inspection confirmed `player_projections` still has zero rows for 2026 weeks 3–5. No production database/container was accessed. |
| Market gates and serving | Untouched. This work only records the supported sportsbook markets selected by the grading source; it does not alter market eligibility or evaluation gates. |

The saved PMF is the complete empirical distribution of 4,000 seeded draws after integerizing yardage with floor. Its declared support spans all observed integer outcomes in those draws. Its zero tail mass describes that finite sample only; it does not estimate unsampled analytic tails. Raw continuous-draw P(over) is kept separately to match the API calculation.

The artifact manifest records source commit `c4bd3c9fce7bf402d6fd52c731fdafe0bdbc922c`, the commit at capture time. The task branch was subsequently fast-forwarded to current `dev`, `fbd1dad6e1c9600c5360536c8d4201f0645222ff`. Checksums for the projection job, v2 engine, calibration module, and route match the manifest on the updated branch; none of those source files changed in the intervening dev commits.

### Validator output

```text
validation passed: 26638 observations; unique observation_id; all required fields present
deliberately broken row rejected: missing PMF, information cutoff, pre-kickoff proof, and outcome state
```

### Route parity output

```text
v2 route raw P(over): 6 representative market inputs; max abs delta=0; tolerance=1e-09
v2 route stored summaries: 6 representative stat inputs; max abs delta=0; tolerance=1e-09
exact fixed-seed simulation reuse: receiving 4 calls/1 unique inputs; passing 8 calls/1 unique inputs
v2-platt helper parity: 2698 unique parameter/probability inputs; route-vs-calibration max abs delta=0; differences > tolerance=0
```

### Backfill artifacts

- `research/nfl/prospective-capture/backfill/nfl-2026-w03-w05.jsonl.gz` — 26,638 observations
- `research/nfl/prospective-capture/backfill/nfl-2026-w03-w05-input-snapshot.jsonl.gz` — frozen source rows used by the run
- `research/nfl/prospective-capture/backfill/nfl-2026-w03-w05-manifest.json` — run counts, parameters and hashes

The forecast artifact SHA-256 is `5804a50674ed0acc1252b58e9e5a34f80f8342cbb88760e34fe831d17bb60a83` (compressed); its input snapshot SHA-256 is `6c9395b88823c588196e4a73ff9343e3b78878d8527811b28a3c39af7d1a3497` (compressed). The backfill contains resolved, true-zero, DNP, and missing outcomes. Push, void, and unresolved states are represented distinctly by the schema/validator but were not present among these selected final-game lines.

## Specified for future live capture, not installed or run

The scheduler entry point is `capture_nfl_props.py --mode live`. A scheduler must invoke it before the first kickoff for that slate, with enough time for the source snapshot and forecast generation to finish. The job aborts without writing the forecast if it cannot prove that capture, cutoff, and artifact serialization all finished before the earliest kickoff. No scheduler job or service has been installed.

Example for a future week 6 run from the repository checkout:

```sh
cd /root/lp-nfl-capture
python3 research/nfl/prospective-capture/capture_nfl_props.py \
  --mode live --season 2026 --week 6 \
  --db /root/legendarypicks/backend/data/picks.dev.db \
  --output research/nfl/prospective-capture/live/nfl-2026-w06.jsonl.gz \
  --input-snapshot research/nfl/prospective-capture/live/nfl-2026-w06-input-snapshot.jsonl.gz \
  --manifest research/nfl/prospective-capture/live/nfl-2026-w06-manifest.json
python3 research/nfl/prospective-capture/validate_capture.py \
  research/nfl/prospective-capture/live/nfl-2026-w06.jsonl.gz
```

The command is the scheduler entry point; the scheduler supplies the season/week and must run before kickoff. Live outputs must be direct children of `research/nfl/prospective-capture/live/`. A rerun with the same existing output is an idempotent no-op; an already-frozen run ID elsewhere in that mode directory is also not duplicated. The writer uses exclusive creation and refuses to replace a different existing artifact or manifest. Treat published artifacts as append-only: create a new season/week run for new forecasts, and never edit or regenerate a frozen row in place. A conflicting file requires investigation and a new versioned artifact name, not replacement.

The CLI, live-time checks, immutable writes, and live validator path are implemented, but no live run has been executed, no scheduler is configured, and no live file is included here. The example points at the dev database per the research restriction; operational deployment would need its authorized source and storage configured separately.

## Served contract gaps

The supplied reconciliation states that the running image checked on 2026-10-17 did not include the versioned v2-platt route. The repository source handler exposes point summaries and computes scalar P(over) from stored projection means when requested; it does not serve or persist per-observation PMF/CDF artifacts or an event-level frozen forecast row with an information cutoff and pre-kickoff proof. This work does not query production or claim a current deployed-state check. The harness provides a research capture path, but those served-path contract gaps remain until an authorized live capture is operating and the serving/evaluation path consumes its frozen records.
