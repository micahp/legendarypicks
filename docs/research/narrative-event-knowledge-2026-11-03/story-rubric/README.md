# Legendary Picks: CPU-only Story Quality Rubric

A zero-model, zero-network, standard-library Python grader for previews produced by `backend/story_engine.py`. Includes an offline pastel-bar review dashboard and an optional append-only JSONL score ledger.

**Important:** The rubric measures *deterministic observable proxies*, not true human taste or guaranteed story accuracy. In particular, `headline`, `fan_voice`, and `flow` are heuristics. An `eligible` result means that all **supplied** independent mechanical checks passed and there were no blocking issues; it does not replace human editorial review.

## Use with the existing PR #30 output

Copy `story_rubric.py` into `backend/` or run it as a standalone script:

```bash
python backend/story_rubric.py grade \
  --input docs/research/narrative-event-knowledge-2026-11-03/deterministic-engine/heldout_final_results.jsonl \
  --output /tmp/story_rubric_scores.jsonl \
  --html /tmp/story_rubric_dashboard.html \
  --ledger /var/log/legendarypicks/story_rubric_ledger.jsonl
```

Open the generated HTML file in any browser. It's one local file with embedded scores, pastel segmented bars, category details, and league/status filters. It has no CDN or runtime dependencies. To rebuild the dashboard from the growing ledger:

```bash
python backend/story_rubric.py render \
  --input /var/log/legendarypicks/story_rubric_ledger.jsonl \
  --html /tmp/story_rubric_dashboard.html
```

For a running backend, call the library after fact collection and story generation:

```python
from story_engine import collect_story_facts, generate_story
from story_rubric import grade_record, append_ledger
from pathlib import Path

facts = collect_story_facts(db_path, game, as_of=as_of)
output = generate_story(facts)
quality = grade_record({
    "target_game_id": game["game_id"],
    "story": output["story"],
    "angle": output["angle"],
    "manifest": output["manifest"],
    "input_facts": facts,
    # Supply independently recomputed per-claim checks from your evidence audit.
    # Without them, the gate is deliberately "needs-audit".
    "mechanical_audit": audit_story_claims(output, facts),
})
append_ledger([quality], Path("/var/log/legendarypicks/story_rubric_ledger.jsonl"))
```

`audit_story_claims` in the snippet is a **placeholder for a production-independent claim validator**, not a function bundled with this package. Do not pass fake `True` audit values; the grader trusts provided booleans and cannot independently prove arbitrary numeric prose claims. Reuse/adapt the PR's held-out mechanical audit and harden it before public rollout. Log in the research area first.

## The six-part rubric

| Aspect | Weight | Mechanism |
|---|---:|---|
| Facts & evidence | 25 | Evidence IDs and capture times, team attribution, pregame cutoff; separate independent mechanical audit (required for full credit). |
| Story angle | 20 | Does the first sentence communicate the selected major story? Checks missed undefeated and winless team angles when supported. |
| Player relevance | 20 | Meaningful sustained performances and dominant players; penalizes weak one-off player statistics. Not applicable if no qualifying players exist. |
| Fan language | 15 | Bans research jargon, checks sport-specific terminology, penalizes generic filler. A heuristic, not a language model. |
| Pregame timing | 10 | A true within-48h pregame preview gets full credit. Long-range stories are flagged as potentially stale; date-only NFL timestamps cannot be fully scored. |
| Flow & variety | 10 | Brevity, sentence count, weak repeated player templates, and normalized-text repetitions in a batch. |

The overall grade is the weighted average of *applicable* dimensions, normalized to 100. N/A scores are explicitly marked; they are not silently counted as perfect. The pastel bar shows all six original weights and colors; each segment fills in proportion to the category score. Display `N/A` dimensions in neutral gray.

## Separate publish decision

- `blocked`: no pregame cutoff, a future supporting record, broken evidence linkage, unsupported player-team mapping, or a failed independent mechanical check. **Never auto-publish.**
- `needs-audit`: source links look sound, but independent numeric/semantic claim checks weren't supplied or are incomplete.
- `review`: valid supporting facts but a low-quality lead/player/fan/timing/overall score.
- `eligible`: score is at least 75, the independent mechanical checks all pass, and no severe editorial rule fails. This is **not** an editorial endorsement.

Do not display the model-facing gate/reasons inside the fan story. Use the pastel bar on an internal QA page or an opt-in transparent debug overlay, not in the preview prose.

## Going live and accumulating samples

Keep each grade immutable with: game ID, league, story text, as-of cutoff, rubric version, source evidence manifest, renderer version, selected templates, generated/published timestamps, and gate score. The JSONL ledger is lock-safe on Linux and deduplicates on `(rubric_version, game_id, as_of, story)`.

If a new version of the renderer or rubric creates a changed story or grade, append a fresh event instead of overwriting old results. **Capture actual human feedback separately**, for example `story_id`, `rating` (1 to 5), `notes` (optional), `submitted_at`, and viewer cohort. Do not fabricate user judgments or treat these heuristic scores as real fan preference. Use opt-in feedback and avoid storing unnecessary personal data.

The recommended first live workflow is shadow grading: render the CPU-generated preview normally, score it in the same request or queue, and write ledger rows behind a feature flag. Let fact failures gate publication only when the independent audit is fully wired; otherwise fall back to the existing story or a plain, verified game descriptor. Recompute and compare rolling scores by **rubric version**, league and template. Keep quality measurements separate from impressions/click data.

## Tests

```bash
cd backend && python -m unittest -v test_story_rubric
```

Tests include deterministic replay, source-timestamp and cutoff failures, missing independent audits, jargon, low-impact player performance, N/A handling, kickoff-time ambiguity, standalone HTML and idempotent append-only logging.

## Files

- `story_rubric.py` — grading library, JSONL CLI, offline HTML generator and ledger.
- `test_story_rubric.py` — regression tests.
- `demo_dashboard.html` — standalone sample pastel dashboard.
