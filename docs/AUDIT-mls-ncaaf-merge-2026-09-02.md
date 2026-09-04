# MLS/NCAAF preservation-branch merge audit — 2026-09-02

## Answer

Nothing in the retired worktree is ready or worth adding to `dev` as written. Its useful
intent has been superseded by newer, broader implementations already on `dev`; the remaining
differences are obsolete source policy, an unnecessary refactor, generated cache data, and
dated research artifacts. The complete old state remains recoverable on
`preserve/mls-ncaaf-worktree-20260902`.

This conclusion is about landing the preserved files unchanged. It does not claim the old
research has no historical value, which is why the preservation branch is retained.

## Merge basis and method

- Preserved pre-retirement commit: `4c3522029873c29a38c82dde5887fe551dc2d2a9`.
- `origin/dev` merged for review: `75034981900744d8375ddf3b96467190eb44b2a2`.
- Git produced 11 content-conflict marker groups plus one modify/delete conflict.
- Classifications below use the conflict-marker line numbers before resolution.
- Resolution rule: current `dev` wins every conflict and every stale tracked edit. The eight
  additive files remain only on the preservation branch so their exact contents are not lost.

## Conflicted-hunk table

| ID | File | Pre-resolution lines | Classification | Reason |
|---|---|---:|---|---|
| P1 | `backend/routers/props.py` | 55-99 | SUPERSEDED | The worktree's MLS-only publisher filter and response decorator are obsolete. `dev` supports league rollups, preserves multiple providers, and derives honest pick'em/provider presentation from the stored `rotowire:<book>` source. |
| P2 | `backend/routers/props.py` | 137-203 | SUPERSEDED | `dev` has deterministic `captured_at,id` ordering, offset pagination, and settlement `result_status`. The worktree endpoint is hard-coded to the unused `rotowire_prizepicks_relay` source and its list path drops current pagination/result behavior. |
| P3 | `backend/routers/props.py` | 476-483 | SUPERSEDED | `dev` filters upcoming slates by canonical kickoff and retains a three-hour live window. The worktree falls back to calendar date and hides every MLS provider except an obsolete source key. |
| P4 | `backend/routers/props.py` | 552-561 | SUPERSEDED | `dev` orders by canonical kickoff and applies the live-window predicate. The worktree uses date/home/away ordering and the obsolete single-source MLS restriction. |
| P5 | `backend/routers/props.py` | 608-622 | SUPERSEDED | `dev` retains odds and deduplicates equal market/line/side questions while preferring the priced offer. Current UI code already identifies pick'em sources and renders provider labels without the relay prefix. |
| T1 | `components/Props/MarketSlateBoard.tsx` | 41-48 | SUPERSEDED | The worktree stores one source contract on a row; `dev` models multiple `BoardLine` offers per row, including raw market, line, source, and provider-specific sides. |
| T2 | `components/Props/MarketSlateBoard.tsx` | 75-84 | SUPERSEDED | The worktree narrows sorting and adds an obsolete source-status type. `dev` additionally supports confidence and odds sorting. |
| T3 | `components/Props/MarketSlateBoard.tsx` | 180-187 | SUPERSEDED | The worktree copies one source and line into each card. `dev` groups every provider-and-line offer beneath one player/market/game card. |
| T4 | `components/Props/MarketSlateBoard.tsx` | 314-338 | SUPERSEDED | The worktree's MLS-only empty state depends on a capture endpoint for an unused source key. `dev` has a league-agnostic upcoming-state message and a route back to all leagues. |
| T5 | `components/Props/MarketSlateBoard.tsx` | 666-670 | SUPERSEDED | This is the call-site half of T4; the current league-filter empty state is the valid contract. |
| T6 | `components/Props/MarketSlateBoard.tsx` | 791-870 | SUPERSEDED | `dev` has the current alternate-line dropdown, provider labels, click-away handling, and honest pick'em/no-price treatment. The worktree would replace that with one line and a fixed More/Less presentation. |
| D1 | `backend/data/esports_team_logos.json` | modify/delete, no markers | SUPERSEDED | The worktree changed a generated cache that `dev` deleted. No current `dev` code references this path, so retaining the stale cache would resurrect removed data. |

Classification totals: **12 SUPERSEDED, 0 UNIQUE, 0 CONFLICTING**.

## CONFLICTING hunks — verbatim worktree text

None. No hunk met the `CONFLICTING` definition after comparison with current `dev`, so there
is no raw worktree hunk text to reproduce in this section.

## Non-conflicted preservation changes reviewed

The merge auto-combined two of the five tracked edits, but auto-merging is not evidence that
they belong in current code. Both are resolved back to `dev`:

- `backend/_core.py`: the worktree centralizes source-identity/capture tables and introduces
  the obsolete `rotowire_prizepicks_relay` presentation policy. Current ingesters install
  their required additive identity schema themselves, while current RotoWire rows use one
  durable `rotowire:<book>` source per provider.
- `backend/ingest_underdog_props.py`: the worktree moves existing identity helpers into the
  new shared module. That is a refactor, not a new capability, and it changes the dependency
  and normalization path of a current ingest without a current need.

The eight files that were additive relative to the old branch were also compared with current
`dev`:

- `backend/ingest_rotowire_mls_props.py` is superseded by
  `backend/ingest_rotowire_props.py`, which handles MLS, Leagues Cup, NFL, MLB, and NCAAF,
  supports archives, stores each book separately, uses durable fixture/team identity, and
  has a larger fail-closed market vocabulary.
- `backend/prop_source_identity.py` extracts helpers whose behavior already exists in current
  ingesters. Landing it alone adds no runtime capability; converting current ingesters to it
  would be a separate refactor requiring fresh proof.
- `backend/test_ingest_rotowire_mls_props.py` is superseded by the current generalized RotoWire
  tests, including source-key conflicts, exact competition/fixture routing, idempotency,
  vocabulary refusal, and archive behavior.
- `backend/test_props_source_policy.py` asserts the obsolete single-source MLS policy and
  would contradict current multi-provider/alternate-line behavior.
- `components/Props/MarketSlateBoardThreshold.test.tsx` is superseded by current pick'em and
  alternate-line tests, which cover no fake price, provider-label cleanup, multiple providers,
  and selectable alternate lines.
- The three 2026-08-16 plan/research/reference documents are preserved history, but their
  implementation target and single-source assumptions were overtaken by the generalized
  ingest and later source audits already on `dev`. They should not be presented as current
  operational guidance.

## Resolution decision

Take `origin/dev` for all five stale tracked paths, including deletion of the generated
esports-logo cache. Keep the eight additive artifacts only on the preservation branch. Do not
merge this preservation branch into `dev` without a new, narrowly reviewed decision.
