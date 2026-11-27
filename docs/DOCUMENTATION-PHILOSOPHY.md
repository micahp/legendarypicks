# Documentation philosophy: Diátaxis

[Handbook](README.md) · [Agent rules](../AGENTS.md) · [Decisions](decisions/README.md)

**Framework:** [Diátaxis (Diataxis)](https://diataxis.fr/), adapted to Legendary Picks' software engineering and scientific research needs. The upstream framework explains how documentation serves different reader needs; it does not require a particular directory layout.

**Decision provenance:** The documentation consolidation of 2026-11-26 ([PR #63](https://github.com/micahp/legendarypicks/pull/63), merge `05e97b05d6cc61f47ac72f7c8295e05424cfb440`) established the maintained handbook, model cards, research and decision indexes, and historical archive. [PR #64](https://github.com/micahp/legendarypicks/pull/64) followed with architecture diagrams. This follow-up records the owner's documentation framework explicitly so it can be recovered from the repository without access to prior conversations. It does not change model identities, deployment status, or runtime behavior.

## Four reader needs

| Diátaxis form | Reader's need | Application in Legendary Picks |
|---|---|---|
| Tutorials | Learn through a guided experience | Onboarding and worked examples; use safe, reproducible inputs. |
| How-to guides | Accomplish a specific task | Runbooks, API workflows, simulation and evaluation procedures. |
| Reference | Look up precise facts | Model cards, glossary, schemas, API contracts, specifications, version and artifact identities. |
| Explanation | Understand why and how something works | Architecture, design rationale, decision records, and interpretation of research. |

Use the [upstream guide](https://diataxis.fr/) to resolve ambiguities. The mapping describes document purpose, not a mandatory four-folder migration. A model card can link to explanation or a procedure rather than reproducing it.

## Research-specific conventions

The [handbook](README.md) is the maintained entry point. The following responsibilities complement Diátaxis; they are not extra quadrants of the upstream framework.

- [Architecture](architecture/README.md) and [glossary](architecture/GLOSSARY.md): stable definitions, system boundaries and relationships; separate target design from implemented behavior.
- [Model registry](model-cards/README.md): canonical versioned identity, purpose, execution, inputs, cutoff, exact source/config/artifact pins, evaluation and status.
- [Specifications](specifications/README.md): intended behavior, contracts, and acceptance criteria. A specification is not evidence of implementation.
- [Evaluation](evaluation/README.md): comparable cohorts, metrics, baselines, limitations and results. Distinguish legality, realism, predictive accuracy and adoption.
- [Research](research/README.md) and [decisions](decisions/README.md): preserve hypotheses, experimental conditions, positive and negative findings, rejected alternatives, blockers, rationale and reversal criteria. Do not overwrite frozen evidence or repeat investigations without reviewing prior work.
- [Archive](archive/README.md): historical context and superseded handoffs, not active instructions or proof of completion. Preserve provenance, required paths, hashes and machine consumers.

## Authoring and maintenance

1. Start with the reader's question and inspect the handbook, existing canonical page, research history and relevant source. Update the authoritative document instead of creating another dated summary that competes with it.
2. Select the documentation form by purpose. Separate procedures, exact facts, rationale and learning material where mixing them obscures the reader's goal. Link related pages rather than duplicating authoritative content.
3. Keep named models and architecture discoverable from the handbook. Cite exact source commits for implementation claims; distinguish proposed, implemented, integrated, independently tested and deployed states. Record unresolved findings and limitations explicitly.
4. Keep transient notes out of the repository root. Before relocating or archiving material, verify links, active instructions, machine consumers and reproducibility dependencies; preserve required evidence and report anything not verified.
5. Check that a reader starting from the handbook or AGENTS.md can find the new or revised documentation and its sources. For documentation-only changes, verify links, changed paths and factual claims; do not imply runtime tests or deployment.

## Guardrail

Do not reorganize the repository just to achieve a visually tidy taxonomy. The objective is reliable discovery and preservation of knowledge with minimal duplication. Apply Diátaxis incrementally to actual reader needs. Change this policy only with an explicit, recorded decision explaining why; retain the original reference and historical rationale.
