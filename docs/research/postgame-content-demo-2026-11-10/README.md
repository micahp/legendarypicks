# Postgame content demo: score-only prototype

Status: **incomplete research draft; not suitable for deployment or publication**. The demo is standalone and does not modify the app, database, flags, routes, or cached articles. It reuses the existing pregame system's evidence, cutoff, independent-audit, and separate-storage concepts. The existing pregame audit and rubric cannot certify postgame claims and are not called here. This first slice supports only verified scoreboard results and derived score margins; it does not implement the requested substantive postgame engine.

## Replay

From `backend/`:

```sh
python demo_postgame.py
python -m unittest test_postgame_story_engine test_story_engine test_story_engine_runtime test_recap_fallback
```

The replay opens only the pinned JSON fixture files, writes artifacts in this research directory, and uses no model, GPU, database or network. Open `demo.html` directly in a browser. Three finalists produce nine preliminary cards: three final summaries, three score comparisons and three margin cards. These are intentionally repetitive score-only scaffolding, not a demonstration of editorial diversity. The comparison cards contain structured data; the static page does not yet draw charts.

## Provenance

The fixtures contain normalized fields copied from the `scoreboard_snapshots` table in the production `picks.db`, opened with SQLite `mode=ro`. The recorded ESPN source event IDs, local capture timestamps, teams and final scores are in each file. These are local captures of ESPN scoreboard data, not independently reconciled publisher snapshots. Fixture SHA-256 (raw bytes):

| ESPN event | Fixture SHA-256 |
|---|---|
| 401873037, JAX at BAL | `5b828f677e6d3122151fa421e045991c4131552ff1a66f33affda52b0a4153ab` |
| 401909957, DEN at HOU | `ab0f856764b9d9558c5f28ddb4fcd67323b32c475419525220a44e97cbd8e86b` |
| 401909960, MIL at NY | `6d31313b0e50bce875ae971277c49f58dd850a0e051df3ee805c7054356fd849` |

The fixtures do not establish exact end times, complete play-by-play, final-box-score player facts, pregame model locks or rights-cleared video. They intentionally contain none of those details.

## Limited held-out check

`evaluate_postgame_score_only.py` samples 50 captured NFL and 50 NBA `state=post` scoreboard rows using SHA-256 seed `20261110-postgame-v1`, excluding the three demo IDs. It reads a specified SQLite DB via `mode=ro`; it does not call external APIs. The measured run is in `evaluation.json` and `heldout_results.jsonl`. All 100 passed the current narrow score-only checks. They contain no narrative beyond the score. This is neither an independent source reconciliation nor a human editorial evaluation. Timings measure only the in-memory renderer, not collection or UI. No human ratings were collected. The files do not archive the held-out input snapshots, so this measurement is not yet independently replayable from committed fixtures.

## Remaining work before acceptance

- Implement and validate canonical player box scores, complete ordered play data and genuine substantiated hooks, plus reconciliation against a second source.
- Implement ranked, selected and rejected narrative candidates, full recaps, independent per-claim checks and the requested postgame-specific six-dimension rubric.
- Implement non-score-only varied cards, source-backed charts, model-lock receipts or explicit unavailable state, clip placeholder, local polls, runnable rundown and the four-state UI.
- Add durable append-only history for an isolated demo store and an accepted-story pointer, with no writes to live DBs. This prototype has no storage API.
- Complete the specified adversarial and responsive browser tests, immutable fixture capture for the held-out sample, blind human comparison, and an actual game-event example.
- The static HTML has not been tested in a browser at the requested viewport widths. No preference or production-readiness claim is supported.
