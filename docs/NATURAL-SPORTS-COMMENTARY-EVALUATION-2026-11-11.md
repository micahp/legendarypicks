# AGENT TASK: Evaluate Natural Sports Commentary Separately from Factual Accuracy

**Repository:** \`micahp/legendarypicks\`  
**Date:** 2026-11-11  
**Status:** Implementation instructions, not an evaluation result  
**Scope:** CPU-only, deterministic editorial quality evaluation for pregame previews, postgame recaps, and homepage/social feed copy. Research/QA first. No production feature-flag changes, deploys, schema migrations, or generated-story replacements without separate review.

## Why this is necessary

A story can be **100% factually supported and still sound like nobody who watches sports would say it**.

User-reported failure:

> "Jalen Brunson, averaging a team-high 23 points, led a New York offense that had scored 31 and 33 from him in his two games before this one."

The 23/31/33 numbers might all be backed by evidence, but "an offense that had scored 31 and 33 from him" is semantically broken. The opening participial clause is overloaded, "team-high" has an unstated period, "led an offense" can imply unproven causation, and "before this one" is vague. Do not treat "fact audit passed" or "contains basketball terms" as proof the prose is good.

Illustrative rewrites **only if the underlying facts and their time windows check out**:
- Pregame: "Brunson comes in averaging 23 points per game for New York, after scoring 31 and 33 in his previous two outings."
- Short, preferable when the streak is the story: "Brunson has topped 30 points in each of his past two games, scoring 31 and 33."
- Postgame: lead with what he did **in the game that just finished**; recent form belongs afterward, only if it adds context.

The agent must build a **separate evaluation lane**. Do not silently fold this into the current fact score or use a combined number to hide unnatural writing.

## 1. Inventory existing code; do not start from scratch

Inspect the actual branch/PR state before writing code:

- \`backend/story_engine.py\`: deterministic pregame fact selection, \`_nba_player_clause\`, \`_nfl_player_clause\`, \`render_story\`, \`select_story_angle\`.
- \`backend/story_engine_audit.py\`: independent evidence/claim verification. **Preserve as a separate gate.**
- \`backend/story_rubric.py\`: \`_fan_voice_score\` currently mainly recognizes jargon, a handful of sport-specific expressions, and generic filler; \`_flow_score\` checks length/repetition. Neither can reliably judge whether meaning is natural.
- \`backend/story_engine_runtime.py\`: accepted-cache and append-only generation history, cutoff and fallback behavior. No unreviewed production behavior changes.
- \`backend/core_stories.py\`: legacy LLM-generated previews and recaps; archived output may serve as a labeled offline comparison baseline, not truth or a model-run requirement.
- \`backend/test_story_engine.py\`, \`backend/test_story_rubric.py\`, \`backend/test_story_engine_runtime.py\`.
- Draft PR #35 / branch \`research/postgame-content-demo\`: \`backend/postgame_story_engine.py\`, \`backend/postgame_rubric.py\`, \`backend/demo_postgame.py\`, \`docs/research/postgame-content-demo-2026-11-10/\`. The PR's research artifacts are not production; verify current head.
- \`docs/research/narrative-event-knowledge-2026-11-03/espn-editorial-benchmark/README.md\`: prior same-cutoff comparison, editorial limitations and source metadata.
- \`docs/HISTORICAL-RELATIONSHIPS-RIVALRIES-2026-11-11.md\`: historical relationship/first-meeting storylines. Naturalness QA must cover them too.

First deliver a small inventory table naming the current evaluator, what it can/cannot detect, and what will be reused. Do **not** implement a second factual audit.

## 2. Three independent evaluation tracks

Produce separate, immutable results. No single weighted average across tracks.

| Track | Question | Source of truth | Gate |
|---|---|---|---|
| **Fact integrity** | Are numbers, identities, sources, dates and events supported? | Existing independent evidence/claim audit | Unsupported claims \`blocked\` |
| **Editorial selection** | Did the generator choose the most relevant sports storyline? | Ranked candidates + blinded editorial judgments | Important missed hook \`review\` |
| **Natural sports commentary** | Does the selected copy sound like a knowledgeable sports fan/commentator and communicate a coherent meaning? | Deterministic structural checks **plus separate human ratings** | Severe semantic failure \`review\`; human approval for rollout |

The current \`story_rubric.py\` may continue displaying its six pastel dimensions. Add a **separate naturalness evaluation** panel/ledger with its own version, category scores, problem spans and explanations; don't rewrite historic rubric scores. The legacy \`fan_voice\` metric must remain labeled as a heuristic proxy.

Factual errors found during naturalness review should be sent to the fact-audit track; do not misclassify them merely as bad prose. A missed Brown–Tatum reunion may be an **editorial selection** error even if the selected sentence reads naturally.

## 3. Naturalness dimensions and annotation guide

Use **six independent, human-readable dimensions, each 0–4** (4 = broadcast-ready, 3 = good, 2 = awkward but understandable, 1 = confusing, 0 = incoherent/incorrect meaning). Also return \`not_applicable\` if a dimension genuinely does not apply; never score missing information as perfect.

1. **Semantic coherence**: Does the literal sentence make sense? Correct agents, subjects, actions and objects. No "offense scored 31 from him", "player scored 30 assists", "team posted three rebounds", or inverted cause/effect.
2. **Sport-specific authenticity**: Would a sports fan naturally say this? NBA points/rebounds/assists, NFL passing/rushing/receiving yards, NHL goals/shots, tennis sets/breaks. Avoid robotic research terminology, but allow accurate advanced metrics when they genuinely explain the story.
3. **Stat framing and time clarity**: Every rate/average/trend has a clear window and denominator or implicit, conventional unambiguous context: season, last five games, previous two games, this game, pregame vs postgame. Do not switch time horizons mid-sentence or say "team-high" without specifying the comparison when needed.
4. **Readability and rhythm**: Natural syntax, short enough to follow aloud, minimal nested clauses, no repetitive team/location names, no overstuffed comma chains or awkward template joins. Grammar alone is necessary but insufficient.
5. **Contextual relevance and specificity**: Does a statistic actually add a meaningful angle, or is it padding? A legitimate two-game 30-point streak can be interesting; generic game-by-game lists with no hook are weak. Missing a reunion is logged in the **selection track** even if this axis mentions it.
6. **Narrative and temporal perspective**: Pregame forecasts sound prospective, postgame recaps sound retrospective, live feed describes only known game state. No "entered this game" in a pregame article unless idiomatic; no "will face" after final; avoid implying participation if a player was inactive. A team meeting, a player actually taking the floor, and a first arena return are different claims.

For each deficiency, collect:
\`error_code\`, \`severity\` (\`minor|major|critical\`), \`span\`, \`reason\`, \`suggested_rewrite\`, \`semantic_slots\` (when applicable), and whether this is a human finding or an automated rule. A suggested rewrite is a **review artifact**, not automatically published prose.

## 4. Build deterministic *structural* checks, not a fake AI taste detector

The code's role is to detect verifiable classes of construction mistakes and route ambiguous prose for review. It cannot prove that an arbitrary sentence "sounds like SportsCenter."

Introduce a versioned normalizer/representation of the *fact-to-sentence contract*:

\`\`\`json
{
  "event_id": "fixture-game",
  "league": "nba",
  "story_phase": "pregame",
  "fact_id": "player_recent_points:fixture",
  "subject_type": "player",
  "subject_id": "fixture-player-id",
  "action": "score_points",
  "value": [31, 33],
  "unit": "points",
  "window": {"type": "previous_games", "count": 2},
  "game_identity": "fixture-game",
  "source_evidence_ids": ["fixture-source"],
  "sentence_template_id": "nba_recent_30_plus_v1"
}
\`\`\`

*This is a synthetic schema example, not a real Brunson record or an existing database contract.*

- Renderer templates accept **typed, named slots** (player, team, sport, stat, unit, window, comparison cohort, outcome, tense) rather than generic concatenated text.
- Validate subject–predicate–object compatibility and units at render time.
- Reject ambiguous ownership and stat-window mismatches before publication; record precise error codes.
- Distinguish detection from revision. The evaluator never silently modifies public copy and must not generate novel claims.
- Static patterns may flag "scored [number] from [player]", "had scored ... from him", "led an offense that scored ... from him", missing stat units, repeated "in his previous two games before this one", and contradictory tense cues. Patterns should match **structures**, not blanket-ban safe words such as "offense", "scored", "led" or "from".
- Avoid pronoun-gender assumptions from names; prefer named subject or neutral phrasing when the antecedent is unclear.
- Allow natural variation: "put up 31", "dropped 31", "scored 31", "had 31 points" are valid NBA formulations in context. Do not force all outputs into identical dry sentences.
- Do **not** auto-fail correctly rendered stylistic choices merely because an n-gram is unfamiliar. Ambiguous constructions get \`needs-human-review\` with a rationale.

## 5. Required regression examples (tests first)

Use synthetic fixtures with explicit fact IDs and reliable source windows. These are targeted language tests; no invented results should be published.

| Input / scenario | Required evaluation |
|---|---|
| "Jalen Brunson, averaging a team-high 23 points, led a New York offense that had scored 31 and 33 from him in his two games before this one." | **Critical semantic failure**: awkward team-as-agent construction, mixed frames, unclear window; facts may pass separately |
| "Brunson scored 31 and 33 points in his previous two games." | Natural, clear if the corresponding two previous game logs are verified |
| "Brunson has scored at least 30 points in each of his last two games." | Natural, supported only when those games are complete and pre-cutoff |
| "Brunson is averaging 23 points per game this season." | Natural when the season denominator and eligible games are supported |
| "Brunson averaged 23 points over his last five games." | Distinguish rolling window from season average |
| "Brunson had 18 tonight after scoring 31 and 33 in his previous two games." | Accept only as postgame and when current-game 18 is verified; do not leak it pregame |
| "New York's offense scored 31 and 33 from Brunson." | Critical failure even if 31/33 are valid player stats |
| "New York is averaging 23 points from Brunson" | Flag unnatural/ambiguous attribution; prefer "Brunson is averaging 23 points for New York" |
| "Brown and Tatum meet for the first time since playing together" | Natural phrasing may be fine, but **truth requires separate** first-appearance and historical coverage checks |
| "Brown returns to Boston to face Tatum" | Venue must actually be Boston; otherwise fact-audit issue, not just style |
| "Durant faces Phoenix for the first time since his trade" | Requires the correct meeting/participation definition. Don't infer first playing appearance from first scheduled meeting |
| "Houston acquired Durant in exchange for Jalen Green and Dillon Brooks" | Treat trade structure as sourced fact; no invented motives or simplistic 1-for-2 attribution if the verified trade was multi-team |
| "He rushed for 120 receiving yards." | Critical semantic/stat-unit contradiction |
| "The team scored 12 shots on goal." | Critical sport-specific stat/action mismatch |
| "He won 6-4 in three sets." | Flag result/format ambiguity unless a complete tennis set score supports it |
| "Boston's offense dominated." | Human review for generic, unsupported causal/evaluative filler, not automatic factual assertion |

**Additional adversarial tests**: player traded midseason, zero vs missing game logs, last-game score referenced as current, opponent/teammate ambiguity, NBA Cup vs regular season, OT period, partial PBP, pronoun antecedent ambiguity, duplicated clauses, repeated headline in body, exact league-specific stat units, one meaningful advanced metric, and no-stat but historically significant rivalry preview.

Keep a fixed **negative set** and a fixed **clean set**. Test mutation behavior: change \`window=season\` to \`window=last_5\`, swap \`subject_type=player\` to \`team\`, swap \`points\` to \`assists\`, or change pregame to postgame. The evaluator must detect the introduced defect when it is within its structural competence; it must not use unrelated factual-audit results to pass.

## 6. Human editorial evaluation is the gold standard

A deterministic linter alone cannot learn whether copy actually feels like human sports commentary.

- Start with **at least 50 NBA and 50 NFL** distinct generated passages, balanced across pregame/postgame, exciting and ordinary games, lead types, successful and failed templates. Include the Brunson regression and historical relationship cases in a **separate, disclosed regression set**, not in the blinded held-out score.
- Freeze **game IDs, as-of cutoffs, input hashes, generator versions, output text, seeds, and template IDs** before judgment. Keep the evaluated text unchanged.
- Present **blind, randomized A/B pairs** of (A) existing deterministic output vs (B) revised output, and optionally (C) archived legacy LLM output if the original artifact and cutoff are already available. Do not call an LLM to make or judge each story.
- Include the same compact, cutoff-safe fact brief for both candidates, with named metrics and source IDs. Hide generator identity, rank, and rubric score. No post-cutoff facts in the brief.
- **Two independent human reviewers** with sports familiarity for an initial 40-pair subset (20 NBA / 20 NFL), plus targeted review of flagged semantic defects. Capture reviewer sports familiarity, confidence, versioned instructions and blind ordering. Reconcile disagreements; retain original independent labels.
- Human per-dimension 0–4 ratings; **overall question**: "Would you expect to hear or read this from a competent sports commentator?" (\`yes|borderline|no\`). Also request \`A|B|tie|neither\` and a concise free-text reason. Don't simulate human feedback.
- Track editorial preference separately from factual correctness and hook-selection recall. A more natural sentence about the wrong event still loses the editorial-selection evaluation.
- Track simple percent agreement and explain disagreements; report Cohen's kappa only when sample and label distribution make it interpretable.

No blind ratings yet? Report \`human_n=0\`, not \`passed\`.

## 7. Metrics, thresholds and rollout gate

Report **per league, story phase, story angle, template, and generator version**, plus aggregate:

- critical/major/minor semantic findings per 100 passages;
- percent clean of critical errors in fixed regression and held-out sets;
- precision and recall of automated *critical-defect flags* against human annotations, with examples of false positives/negatives;
- human \`broadcast_ready\` rate and 0–4 dimension distributions;
- blind pairwise preference, ties and "neither" share;
- stat-window confusion, entity/action mismatch, tense errors and filler rates;
- repeated sentence-template frequency and error concentration by template;
- inter-reviewer agreement and number of disputed cases;
- CPU median/p95 evaluation latency for real host.

**Proposed non-negotiable engineering gates**, distinct from human editorial goals:

1. 100% of the *known critical regression fixtures* correctly flagged without false "pass" classifications; clean fixtures remain unblocked. This tests the **documented rules**, not general language quality.
2. Zero unsupported claims accepted by the independent factual audit; this is unchanged from current policy.
3. No deterministic evaluator may label a story \`human_approved\` or \`broadcast_ready\` without real reviewer data.
4. Preserve existing generation semantics during shadow evaluation; no automatic rewriting or promotion from a proxy score.
5. New template cannot be released if an unresolved critical semantic failure is found on its targeted test set or in manual review. Do not overfit to the Brunson phrase alone.

**Research targets to report, not pre-claim:** high recall of known critical constructions with acceptable false-positive rate on natural variants; positive blind human preference over baseline. Capture baseline first, set numeric rollout thresholds with actual observed distribution, and include the trade-off. Do not claim that a scalar such as 85/100 proves naturalness.

## 8. Outputs / implementation boundaries

Suggested implementation on an **implementation feature branch**, not by changing production copy directly:

\`\`\`text
backend/sports_language_contracts.py
backend/sports_language_evaluator.py
backend/test_sports_language_evaluator.py
backend/test_sports_language_contracts.py
docs/research/natural-sports-commentary-2026-11-11/
  README.md
  regression_cases.jsonl
  fixture_manifest.json
  frozen_holdout_inputs.jsonl
  deterministic_findings.jsonl
  human_review_template.csv
  reviewer_guide.md
  evaluation.json
  demo.html
\`\`\`

- Evaluator: pure Python, standard library where practical, CPU-only, zero network/model calls for fixture replay. Stable IDs and byte-for-byte deterministic outputs (exclude machine-specific timestamps).
- \`demo.html\`: side-by-side old/new sentences with highlighted failure spans, evidence snippets, factual-audit status **in a separate column**, naturalness dimensions as a distinct pastel bar, reviewer vote capture only when truly entered. No fake counts. Self-contained and mobile-readable.
- Support either \`story_engine\` output or PR #35 postgame result via small adapters, not by hardcoding one branch's schema. Pin adapter versions and do not couple postgame research publication to \`dev\`.
- Append-only ledger keyed by \`(league, event_id, as_of, generator_version, output_hash, evaluator_version)\`; distinct human ratings keyed by review assignment.
- Preserve cutoff timestamps, model/fact manifest, source identity and renderer/template version; sanitize any HTML/CSV display strings.
- Keep ESPN/AP as **offline editorial benchmarks only**. Do not copy article text, assume it is a legal training corpus, or use ESPN as a runtime dependency.
- New gate initially **shadow-only**; do not mark existing accepted history unpublishable retroactively. Apply to new publication only after explicit authorization and an independently reviewed rollout/rollback plan.

## 9. Exact agent execution order

1. Inspect actual repo/PR heads and freeze existing generation/rubric baselines.
2. Write a short source-of-truth inventory of fields and current \`fan_voice\` blind spots.
3. Write failing TDD cases for the Brunson sentence, good rewrites, bad sport/stat windows, pronoun/relationship examples and phase mistakes.
4. Build typed contracts and deterministic rule checks, including **rule IDs with explainable spans**; verify fixes on all targeted tests.
5. Run evaluator in shadow against already generated stories; **do not regenerate the corpus after viewing the results**.
6. Freeze separate held-out data and perform a blinded human annotation round. Disclose no evaluator scores during review.
7. Compare old/new on identical fact bundles and cutoffs. Distinguish template fixes, missed hook selection, and missing input facts in findings.
8. Generate a self-contained inspection dashboard and README with replay commands, scores, examples, limits and next steps.
9. Open a **draft implementation PR** only after code/tests exist. Documentation can live on \`dev\`; no PR for docs-only changes. Never merge, deploy or alter live story flags as part of this assignment.

## Definition of done

The evaluator consistently catches the Brunson-style **meaning failure even when factual evidence passes**; accepts several genuinely natural rewrites; attributes errors to the correct evaluation track; preserves real human preference as separate evidence; and produces inspectable, replayable NBA/NFL results that the user can judge by reading actual before/after paragraphs. It must improve commentary without sacrificing factual safety or flattening all writing into one robotic template.
