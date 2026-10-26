# NHL official outcome backfill

Research-only import and reconciliation of official NHL regular-season boxscores. This directory does not fit a model, evaluate a market, calculate ROI, or write to the production database. It does not change the goalie preregistration or `docs/nhl-prediction-brief`.

## Frozen population

`canonical_frame.csv` is pinned to SHA256 `336d8a8d055febd742dbf31ce7a613bd2e47c2cd8fbc7a8d956fc8967ba47b1c` and contains 4,876 regular-season games through November 27, 2022:

| Start season | Canonical official games | SBR market games |
|---:|---:|---:|
| 2018 | 1,271 | 1,271 |
| 2019 | 1,082 | 1,082 |
| 2020 | 868 | 868 |
| 2021 | 1,312 | 1,312 |
| 2022 partial | 343 | 339 |
| **Total** | **4,876** | **4,872** |

The partial 2022–23 canonical frame spans October 7–November 27, 2022. The SBR subset spans October 11–November 27 and omits the four canonical-only games listed below.

The four canonical-only games are `2022020001`, `2022020002`, `2022020175`, and `2022020185`. This is the official-outcome frame; it does not replace the goalie experiment's 4,872-game SBR population, 4,763 eligible rows, or separate 3,509 out-of-fold scoring denominator.

## Raw response storage and resumability

Raw response bodies, per-game hash sidecars, source snapshots, fetch state, and rejected HTTP bodies live outside Git at:

`/root/lp-data/nhl-official-outcome-backfill-2026-10-20/`

The response files are `raw/{game_id}.json.gz`; each sidecar in `records/{game_id}.json` and each row in the tracked `manifest.jsonl` records raw-body and compressed-file SHA256 hashes. The original HTTP body is recoverable by gunzipping. The three hundred responses from the earlier official reconciliation sample are tagged `prior_official_audit_cache` and retain their source commit in their sidecars. Newly fetched bodies are tagged `official_gamecenter`.

The importer issues one request at a time with at least one second between request starts. It validates every existing response before resuming, skips already validated game IDs, checkpoints the manifest, and stops on HTTP access-refusal statuses (401, 403, 407, 429, or 451) or other unrecoverable errors. After a recorded refusal, it refuses to resume unless `--resume-after-refusal` is explicitly supplied after access is restored.

From the repository root, resume the import with:

```sh
/root/lp-goalie-research/.venv/bin/python research/nhl/official-outcome-backfill-2026-10-20/backfill_official_boxscores.py --fetch
```

After a refusal is cleared, add `--resume-after-refusal`. A bounded probe can use `--max-new 1`; the normal command fetches all remaining responses. Avoid running multiple importer processes.

The frozen canonical and SBR source snapshots used to derive the frame are also retained under the external artifact root's `source/` directory. Their hashes and crosswalk assumptions are in `frame_sources.json`.

## Normalized outputs

After all 4,876 boxes validate, the importer writes:

- `official_game_sides.csv`: two official team rows per game, scores, team SOG, canonical scores, market-frame flag, and source hashes.
- `official_skater_outcomes.csv`: forwards and defense SOG, player ID, team, game, TOI, source group, and appearance status.
- `official_goalie_outcomes.csv`: saves, shots against, goals against, TOI, starter field, and player identity. Zero-TOI goalie slots remain in this file with `appeared=0`; blank appearance status means TOI could not be parsed.
- `official_quality_issues.csv`: malformed or missing player IDs, invalid stats/TOI, duplicate IDs, SOG total mismatches, and goalie arithmetic failures.
- `official_team_sog_validation.csv` and `official_coverage_summary.json`.
- `manifest.jsonl` and `COVERAGE.md`.

Archive reconciliation is read-only and matches by numeric canonical game ID plus numeric NHL player ID. It uses names only as a cross-check after the ID join; potential display-name/ID conflicts are listed in `archive_name_crosscheck.csv` and are never auto-corrected. It writes full skater and goalie discrepancy tables, per-season coverage and reconciliation, prop-side flips at the prior audit lines, `played_goalie_one_sided_rows.csv`, official/archive nonappearance reports, identity issues, official team-SOG checks, and official-to-canonical score conflicts. Official goalie rows with TOI zero and archive rows with `icetime=0` are retained in separate reports and excluded from played-game prop comparisons.

## Run and verify

After coverage is complete, reconcile against the read-only historical archive:

```sh
/root/lp-goalie-research/.venv/bin/python research/nhl/official-outcome-backfill-2026-10-20/reconcile_archive.py
```

Then run the independent raw-to-normalized verifier:

```sh
/root/lp-goalie-research/.venv/bin/python research/nhl/official-outcome-backfill-2026-10-20/verify_official_artifacts.py
```

The verifier rehashes and decompresses every raw body; checks response identity, date, season, game type, state, and team IDs; and independently reconstructs the normalized game-side, skater, goalie, and team-SOG rows for comparison. It writes `artifact_verification.json` only after all checks pass.

No official outcomes are silently substituted for archive rows. Missing, duplicate, invalid, or conflicting identities remain visible in issue and discrepancy outputs. These official boxscores do not certify historical sportsbook settlement or correction timing and do not provide event or shift sequence data for V3 simulation.
