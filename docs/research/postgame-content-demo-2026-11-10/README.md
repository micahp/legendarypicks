# Postgame content demo

Status: **research draft, incomplete, not approved for publication or deployment**. Fixture replay is CPU-only and uses no database, model, GPU or network. It does not change production routes, stories, flags, or data. The existing pregame engine and its timing-specific audit remain unchanged. The postgame grader reuses its pastel palette and jargon detection but applies separate dimensions and postgame timing rules.

## Replay

From `backend/` using the existing project environment:

```sh
/root/legendarypicks/backend/venv/bin/python demo_postgame.py
/root/legendarypicks/backend/venv/bin/python -m pytest -q test_postgame_story_engine.py test_postgame_rich.py test_postgame_facts.py test_postgame_store.py test_postgame_demo.py test_story_engine.py test_story_engine_runtime.py test_recap_fallback.py
```

Open `demo.html` directly. It has four daypart views, three local-only polls, favorite team and league controls, charts, 1:1 and 9:16 layouts, a text rundown, per-game candidate and claim evidence, and an automated six-dimension rubric. The live tab is explicitly empty. No clips or public poll totals are invented. The `show_rundowns.jsonl`, `feed_posts.jsonl`, `recaps.jsonl`, and `evidence_manifest.json` files are replay outputs. Scores are mechanical editorial proxies, not human preference ratings.

The optional scoreboard adapter opens SQLite with `mode=ro` and `query_only=ON`; it only collects the selected row and cannot establish final-box-score player facts. It requires a separate output directory:

```sh
/root/legendarypicks/backend/venv/bin/python demo_postgame.py --db /path/to/picks.db --league nba --game-id EVENT_ID --output /tmp/lp-postgame-output
```

An opt-in store API is provided for isolated demo history. It accepts only resolved paths under `/tmp` or this research directory. It independently checks the result, input hash and rubric before saving, deduplicates accepted versions, and does not replace the latest accepted pointer with an older capture. Fixture replay never opens or creates this store.

## Captures

The original final scoreboard fixtures came from read-only `scoreboard_snapshots` rows in the local production database. Later ESPN game-summary captures established publisher team IDs, final status and matching scores. The Houston fixture also archives the final player box-score fields and period scores from an ESPN summary captured at 2026-11-11 05:44:59 UTC. Both teams' player-point sums and period sums reconcile to their final scores. The replay uses these later facts only at or after that capture, not at the earlier scoreboard timestamp. The fixture includes the capture time, endpoint, source ID and raw-response hash; the raw publisher response is not stored.

| ESPN event | Fixture SHA-256 |
|---|---|
| 401873037, JAX at BAL | `55ce14248c84521a80e0d37d94a259776ab460f07bd1b60178baaef54525b9f0` |
| 401909957, DEN at HOU | `0c2af8db37f667370fee669b8d1d01df16dd2a14f41c6f58c07dca540f342259` |
| 401909960, MIL at NY | `c0c247fbd52c14092ae297eba8b46d2ac7b517042fdae35c322570a62b3d2e4a` |

The selected ESPN play sequences inspected for both NBA games contained sequence numbers that were not monotonic in response order. The Jacksonville drive sequence includes a score regression from 33-3 to 32-3 after a touchdown. No complete reconciled PBP has been established, so no turning-point or game-winning-play claim is made. The halftime score is independently recomputed from the captured period scores, not inferred from an incomplete play sequence. The Jacksonville fixture also includes final passing lines captured at 2026-11-11 05:50:32 UTC. NY remains a score-only example; missing data is not represented as zero.

## Evaluation and remaining work

`evaluation.json` and `heldout_results.jsonl` are the prior score-only v0.1 experiment. They are **not** a held-out evaluation of the current engine. Their input snapshots were not archived and the samples are now exposed development examples. A new fixed-seed held-out sample must exclude those games and the coached examples, archive its input facts, and be evaluated only after the rules are frozen. No human preference ratings have been collected.

The engine can select an NBA 30-point game or a 20-point, 10-rebound game for a winning team, verify its source and canonical identity, and add a supported halftime score. It also supports sourced NFL passing lines. It cannot yet select NFL rushing or receiving facts, richer stakes, or validated event hooks. Full multi-paragraph recaps, robust source reconciliation across publishers, game-specific pregame-lock receipts, more diverse supporting facts, a verified event sequence and the complete specified held-out editorial evaluation remain unfinished. The current score cards and two player cards remain repetitive. The rubric is a simple rule-based proxy; a high score does not prove editorial quality.

Five viewport widths were checked in headless Chromium for page overflow, local poll selection, and JavaScript errors. These checks do not establish every possible clipping or accessibility condition. No production feature flag or deployment was changed.
