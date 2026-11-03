# Legendary Play — Product specs (2026-10-31)

**Status: Proposed concepts, documentation only. Nothing here is deployed.**

This folder records the clarified product direction after discussions of Rainmaker.fun's character-first homepage, Sport.fun's fantasy progression, Real Sports' cards, Underdog's paid fantasy contests, and MoMMA Game's training camps and free pick'ems. It is not a plan to duplicate their proprietary features or images.

## Read first

1. **[Legendary Picks GM Mode](GM-MODE-SPEC-2026-10-31.md)** — an **optional, free** 16-bit GM career that connects *real sports research and frozen pick receipts* to a *fictional* manager, training camps and eventually fictional scrimmages. Sharp Rating is evidence-based; Career XP is game progression. No wagering or paid contest.
2. **[Live-Context Mini-Games](LIVE-CONTEXT-MINIGAMES-SPEC-2026-10-31.md)** — a **standalone fast-track** 10–30 second arcade experience built from verified real play context. First: field goal from the actual reported attempt distance, comparable scores, and deep-link “beat my kick” challenges. GM rewards can plug in later but are not required.

## Critical guardrails

- The user explicitly asked to **pin** the cartridges concept. They are **not currently the athlete ability-badge system** from a previous assistant proposal. No badges or takeover-meter chores are prerequisites for these specs.
- Do not force a gamified homepage on the existing research user. Preserve /props, /scores, /predict and Forecasts.
- A challenge based on a real play is **not the actual play**. The player's arcade result is fictional and must not rewrite real outcomes or affect published models.
- Any saved user pick requires an immutable, pre-cutoff line/source/identity snapshot, honest push/void/DNP settlement and auditable reward grants. Gamification is not permission to fake an “edge.”
- All beta progression is free, nontransferable and nonredeemable. Licensed athlete/league art and music are not inherited by using a sport's data.
- No work against production data, services or live websites was performed by these documentation commits.

## Visual direction

Use the existing **[16-bit Legendary Picks visual exploration PR #27](https://github.com/micahp/legendarypicks/pull/27)** as art direction: a playable football-manager apartment/HQ whose desk, TV, trophy cabinet, arcade cabinet and training area act as navigation. Those images are mockups with illustrative statistics and are not evidence of implemented functionality.

## Execution order

**Recommended:** (1) verify official/independent NFL field-goal attempt distance sources, (2) build a short fictional practice kick, (3) ship verified historical “beat my kick” links, (4) test a small free slate + authentic receipt, (5) only then invest in timed camps and GM-vs-GM fictional play. These priorities are hypotheses to validate, not a fixed rollout order.

**To implement:** follow each spec's schema proposals, test-first acceptance criteria, source coverage/audit gates and no-go conditions. Treat all proposed table/component names as suggestions until current repo architecture is checked.
