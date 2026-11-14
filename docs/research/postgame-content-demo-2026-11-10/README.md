# Postgame content demo

Status: **research draft, incomplete, not approved for publication or deployment**. Fixture replay is CPU-only and uses no database, model, GPU or network. It does not change production routes, stories, flags, or data. The existing pregame engine and its timing-specific audit remain unchanged. The postgame grader reuses its pastel palette and jargon detection but applies separate dimensions and postgame timing rules.

## Replay

From `backend/` using the existing project environment:

```sh
/root/legendarypicks/backend/venv/bin/python demo_postgame.py
/root/legendarypicks/backend/venv/bin/python -m pytest -q test_postgame_story_engine.py test_postgame_events.py test_postgame_rich.py test_postgame_facts.py test_postgame_store.py test_postgame_demo.py test_story_engine.py test_story_engine_runtime.py test_recap_fallback.py
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
| 401909961, BOS at PHI | `9304f2015d12cec4a66149a22d5322ab40c8617c10f71f99a83cfb49983ae563` |

The selected ESPN play sequences inspected for both NBA games contained sequence numbers that were not monotonic in response order. The Jacksonville drive sequence includes a score regression from 33-3 to 32-3 after a touchdown, so it is not used for turning-point claims. For Boston at Philadelphia, the complete 437-play ESPN summary and paginated core play endpoint matched in count, ordered IDs, scores, periods and clocks at 2026-11-11 06:08:35 UTC. The derived sequence passes chronological, period-boundary and final-score reconciliation. It supports the reported 17-point Boston scoring run. The two endpoints are from the same publisher and are not independent publishers. The halftime score is independently recomputed from the captured period scores, not inferred from an incomplete play sequence. The Jacksonville fixture also includes final passing lines captured at 2026-11-11 05:50:32 UTC. NY remains a score-only example; missing data is not represented as zero.

## Evaluation and remaining work

`evaluation.json` and `heldout_results.jsonl` are the prior score-only v0.1 experiment and are not an evaluation of this engine. The new `heldout-fixtures.jsonl` archives 50 NFL and 50 NBA fixed-seed games, excluding those earlier games, the demo fixtures, and the coached team pairings. `heldout-freeze.json` pins the v0.3 code before capture; `heldout-v03-results.jsonl` and `heldout-v03-evaluation.json` contain the offline replay.

All 100 games passed the implemented mechanical checks against their archived input facts, covering 214 structured claims. This is not independent publisher verification or a human accuracy assessment. Every game had a captured final box score; only three NBA games had a sequence cross-checked with the publisher play endpoint. No same-game pregame model locks or video rights were established. The engine chose a player or event headline in 20 of 50 NFL games and 17 of 50 NBA games; none selected an event headline. Average recap length was 15.44 NFL words and 18.2 NBA words. Median/p95 in-memory render times were 0.484/0.760 ms NFL and 0.417/6.470 ms NBA on this host. No human preference ratings have been collected.

The v0.3 gate labels a score plus a halftime score as `eligible`, although it remains a score-only story without a player or event hook. This is an identified gate defect, not evidence of a substantive recap. A future gate fix must preserve this frozen evaluation and be assessed separately.

The engine can select an NBA 30-point game or a 20-point, 10-rebound game for a winning team, verify its source and canonical identity, and add a supported halftime score. It supports sourced NFL passing lines and 100-yard rushing and receiving lines. A controlled fixture exercises late lead changes; the Boston fixture exercises a real scoring run after sequence, score and cutoff checks. It does not yet support richer stakes. Full multi-paragraph recaps, robust source reconciliation across publishers, game-specific pregame-lock receipts, more diverse supporting facts, a broader source reconciliation and human editorial comparison remain unfinished. The current feed contains repetitive score cards despite its format-diversity ranking. The rubric is a simple rule-based proxy; a high score does not prove editorial quality.

Five viewport widths were checked in headless Chromium for page overflow, local poll selection, and JavaScript errors. These checks do not establish every possible clipping or accessibility condition. No production feature flag or deployment was changed.
