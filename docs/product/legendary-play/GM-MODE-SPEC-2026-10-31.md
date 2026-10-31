# Legendary Picks GM Mode — Free-to-play product specification

**Date:** 2026-10-31  
**Status:** Proposed product design. Not implemented, approved for deployment, or an instruction to alter existing picks/forecasts.  
**Owner:** Legendary Picks  
**Companion:** [Live-Context Mini-Games](LIVE-CONTEXT-MINIGAMES-SPEC-2026-10-31.md)  
**Design explorations:** [16-bit homepage and NFL HQ mockups (PR #27)](https://github.com/micahp/legendarypicks/pull/27)  
**Existing product decisions:** [Forecast-first / market-first architecture](../DECISION-forecast-first-leagues-market-first-props-2026-10-20.md), [accounts and device identity](../SPEC-accounts-and-mock-draft.md), [NFL product direction](../SPEC-nfl-product-direction.md).

## 0. Product decision

**Make the user a fictional sports GM, not a bettor, and make their real sports knowledge matter to a persistent career.**

Legendary Picks remains a sports intelligence platform. GM Mode is an **optional playable layer** built on its data, not a replacement for forecasts, props, scores, or analysis. The visual reference is a 16-bit football manager apartment / scouting HQ whose objects launch meaningful activities. The feeling is career mode, not a mandatory game wrapper around research.

- **Quick loop (minutes / game day):** scout real sports -> lock free calls -> watch what happens -> earn a verified result / progression -> share or challenge a friend.
- **Slow loop (hours / weeks):** earn non-monetary credits -> train a fictional player / develop a GM organization -> enter simulated scrimmages -> customize HQ and return.
- **Separate fast bet:** short arcade mini-games derived from observed game state can be shipped and tested independently, then award capped GM progression. See companion spec. These may be more valuable to validate first than the full fictional roster simulator.

Do not accidentally rebuild PrizePicks, Underdog, DraftKings, a cash fantasy contest, or a Fortnite quest checklist. Every beta mode is free to play; points and assets are nonredeemable, nontransferable, and have no cash value.

### Vocabulary and boundaries

| Term | Means | Must not mean |
| --- | --- | --- |
| **GM** | User's persistent, customizable fictional manager / organization | A real team employee or automatically profitable betting agent |
| **Sharp Rating** | Evidence-backed record of the user's *real predictions*, with denominators and appropriate benchmarks | XP, paid power, a guarantee of skill based on five picks |
| **Career Level / XP** | Engagement and fictional progression | Proof of betting success or privileged future outcome access |
| **Training Credits** | Earned free currency to start fictional training and customize HQ | Money, cryptocurrency, wagering chips, withdrawable tokens |
| **Fictional attributes** | Ratings used only in our game mechanics / fictional scrimmages | Increases to true player forecasts, real-world probabilities, or published odds |
| **Receipt** | Locked, timestamped real-sports call + audited settlement | An invented win, live edit to a past pick, or wagering profit claim |
| **Mini-game** | Arcade activity based on a recorded play-state configuration | Real broadcast control or a certified physical reconstruction |
| **Cartridges** | A parked, exploratory collectible idea | A committed Madden-style ability system or beta prerequisite |

**Explicit clarification (2026-10-31):** The earlier proposal to make “cartridges” copies of real athletes' Madden ability badges was off target. Do not implement such a system. The minigame system and its earnings/progression are the near-term idea; cartridge inventory/design remains **undecided and out of scope**.

## 1. User jobs

1. **Sports researcher:** “Let me use all of Legendary Picks normally, with no game detour.”
2. **Casual fan:** “Give me something free and fun to do before/during a game, with an immediate outcome.”
3. **Competitive fan:** “Let me prove I know ball and compare my genuine pregame calls against friends.”
4. **Career player:** “Let my decisions and time build a fictional organization that changes and improves.”

The user's first action must not require a wallet, payment, token, paid pack, NFT, or immediate registration. The user may enter conventional Research Mode at any time.

## 2. IA and presentation

### Entry points

- Public homepage can invite the user to **Play** / **Enter NFL HQ** alongside an equally visible **Research** path.
- The 16-bit HQ is a navigable overlay or route; it must not remove /props, /predict, /scores, league Forecasts, player pages, or direct links.
- Each clickable object is both an in-world affordance and an accessible conventional text/button link.
- Muted by default. Original optional electronic / trap-inspired audio, explicit sound toggle, reduced-motion path, keyboard and touch support. Never auto-play unmuted audio.

### HQ interaction map

| Object/area | Opens | Beta action | Existing capability to reuse (verify before build) |
| --- | --- | --- | --- |
| Scouting desk / whiteboard | Free Picks / Game Forecasts | Research and lock 3–5 free calls on eligible games | Forecasts, schedule, /predict |
| Wall of player cards | Player detail / Props | Inspect player/game/market, history and coverage | /props and game/player pages |
| TV / scoreboard | Game Day | View a real game and your locked calls settling live | /scores, game detail, play-by-play |
| Arcade cabinet / console | Mini-Games | Take a short challenge derived from an observed play | Companion mini-game product (new) |
| Training room | Camps | Spend free credits to improve *fictional* attributes after time elapses | New fictional progression system |
| Trophy case | Career / Receipts | Review complete results, achievements and losses | New ledger + existing grading sources |
| Rival controller / visitor seat | Friends | Invite a friend to beat your slate or arcade score | New deep-link challenge system |
| Exit / tabs | Research Mode | Open standard product without gaming UI | Existing routes preserved |

Specific room art, avatar choices, and layout are *design direction*, not data-product contracts. Earlier mockup percentages and wins are fictional illustrative copy, not approved numbers.

## 3. Core game design

### 3.1 Create a GM, not a real athlete

- Start with a free avatar, display name, room color, organization name, and one fictional archetype. Proposed archetypes: Analyst, Scout, Coach, Grinder. These are identity/personality choices, **not model forecast multipliers**.
- Optional fictional starter roster comes later. MVP can launch with **one fictional athlete**, not an entire 53-person football team.
- Fixed and fair initial budget for *fictional attributes*: e.g. 10 points allocated across scouting, preparation, discipline, play design. These values are **examples**, not source-measured stats.
- Separately display (A) **Career Level**, (B) **Verified Record / Sharp Rating (if sufficient evidence)**. A high XP character must not masquerade as a profitable or exceptionally accurate predictor.

### 3.2 The free real-world pick'em loop

Proposed pilot: one NFL week or slate; up to **five locked, free calls per user**. A call can be game winner, spread, total or a player prop **only if the market, source, price/line and settlement rule are actually available and uniquely identifiable**.

1. Pick an eligible upcoming game/player/market using the existing research surfaces.
2. Display the *exact* market and offering source, the line, side, cutoff, timestamp, and settlement rules. Model forecast != bookmaker offer; historical L5 hit rate != P(over); “edge” requires a valid priced comparison.
3. Write an **immutable** call record server-side before the chosen cutoff. The user can inspect but not edit a locked call.
4. During game: show informational progress and timestamps, but **do not mark a pregame pick as won during an in-progress game**.
5. When final, settle through a canonical per-game, per-player, per-market outcome under explicitly versioned rules. Push / void / DNP / postponed / abandoned / not yet final are not losses.
6. Issue a **win, loss, push or void** receipt with its full denominator and provenance. Only correctly settled eligible calls can feed a verified record.

Do not reuse stale market lines as if they are current. Do not backdate user picks. If a required snapshot is missing, make the call ineligible and explain why.

### 3.3 Rewards and anti-gaming

Use **two separate nonmonetary reward streams**:

1. **Career XP and free Training Credits** reward limited, meaningful participation, completed challenges, and eligible settled calls. A losing pick may still earn small participation XP so the game remains enjoyable. Daily/slate caps block farming. Exact weights are an experiment, not a finalized economy.
2. **Sharp Rating / competitive record** is independent of XP and based only on qualifying frozen calls graded with consistent rules. Never increase it by watching ads, buying perks, idling a timer, playing arcade games, or selecting “easy” favorites.

**Do not rank by raw win rate alone.** Users can farm heavy favorites or exploit correlated entries. The research phase must select a defensible accuracy score against a market or calibrated baseline, with minimum sample sizes, duplicate/correlation rules and published exclusions. Before this metric is certified, show honest W–L–push–void counts and “insufficient sample,” **not an invented precision/ability score**.

No purchased advantages, redeemable tokens, cash prizes, paid head-to-head stakes, hidden gambling outcomes, or chance-priced loot packs in free beta.

### 3.4 Fictional development, training camps and scrimmages

A user can exchange free credits for a training slot. A training camp:
- targets one **fictional game attribute** (examples: QB awareness, route knowledge, conditioning, playbook familiarity);
- has a start timestamp, an actual server-computed end timestamp, and a declared attribute delta;
- progresses while the user is offline; refreshing or changing device time does not advance it;
- has at most one active camp in v1; optional multiple slots are future product decisions;
- is deterministic and auditable, with no surprise card odds or manipulative stamina loss;
- only impacts fictional gameplay/scrimmage calculations or cosmetic unlocks.

Example camp durations of 2h/6h/12h are *design candidates*; avoid excessive wait loops that overshadow the sports content. Offer the next meaningful football task while a camp is running.

**Scrimmages are fictional competitions.** Never label an LP simulated future NFL game as a GM-vs-GM result, and never modify adopted market models. Use a separate versioned fictional rules engine with seeded, reproducible outcomes and declared attribute effects. Solo vs computer is first; fair asynchronous rival challenges are next. Existing Gridiron/LP physics/simulation research remains a separate pipeline with its own readiness gates.

### 3.5 Cards, cosmetic collections and receipts

A card is a visual presentation, not necessarily a transferable asset.
- **Prediction Receipt (v1):** preserves the user's locked original call and actual result, including losses; shareable with a direct deep link.
- **Arcade Moment (v1.5):** user result on a fixed real-play-inspired minigame, scored relative to the *same versioned challenge*, not a claim about the actual player.
- **Fictional Athlete / HQ Cosmetics (v2):** progression items or skins, not paid packs.
- Real NFL logos, athlete likenesses and highlight clips require separate rights review. Use original art/fictional identities for early builds.

## 4. Viral loop, onboarding, and retention

### Recipient-facing experience

“Beat my 5 calls” or “Beat my kick” opens a **public landing** with: context, score/record, timestamp, provenance, next available attempt and an obvious free Play action. A recipient can make a first attempt before account creation, then claim/save the result later.

A share should record a **challenge ID**, not merely a tracking URL. Deduplicate recipients, guard against self-referrals, and make outcomes verifiable without revealing private information. Inviter and invitee may earn tiny **capped** participation XP, but never Sharp Rating or money.

### Product metrics (instrument before a launch)

| Funnel / outcome | Event or measure |
| --- | --- |
| Homepage -> entry | `gm_entry_view`, `gm_enter`, `research_enter` |
| First activation | `call_locked` or `arcade_attempt_completed` on valid record |
| Return | D1 / D7 and next-slate retention by activated cohort |
| Completed main loop | `call_settled` -> receipt viewed -> next eligible call |
| Slow loop interest | training started -> matured -> fictional activity resumed |
| Share loop | share created -> recipient arrived -> *new* qualified attempt / locked call |
| True viral coefficient | qualified activated new users per inviting user, not just link impressions |
| Integrity | stale/ineligible-call fraction, unresolved results, fraud flags, duplicate grants |

A/B test: research-first homepage vs HQ-first; anonymous play vs gate; “beat my kick” vs “beat my five calls.” Do not attribute organic viewing changes to a viral loop without cohort evidence.

## 5. Candidate data model (new tables, not claimed to exist)

All identities must reuse the repo's canonical player/game/market identifiers. Confirm the present tables, schema, auth state, and consumers before implementation.

| Table/entity | Minimum fields |
| --- | --- |
| `gm_profile` | id, owner_user_id nullable, device_id nullable, display_name, avatar_config, archetype, created_at |
| `gm_career` | profile_id, season_id, xp, level, training_credits, version; audited append-only credit ledger |
| `gm_call` | id, profile_id, league, game_id, canonical player_id nullable, market, side, line, source, rules_version, as_of_utc, cutoff_utc, locked_at_utc, result_state, canonical settlement_ref |
| `gm_call_event` | id, call_id, event_type, timestamp, source/version/reason; append-only |
| `gm_training` | id, profile_id, camp_type/version, credit_cost, started_at_utc, completes_at_utc, claimed_at_utc, attribute_delta |
| `gm_fictional_player` | id, profile_id, position, attribute schema/version, appearance |
| `gm_scrimmage` | id, participants, frozen roster/attribute hashes, seed, rule_version, result_hash, outcome |
| `gm_receipt` | id, owner, underlying call/arcade result, rendered template_version, public_share_token, issued_at |
| `gm_reward_ledger` | id, owner, source_type, source_id, grant_rule_version, xp_delta, credits_delta, created_at; unique(source_type, source_id, grant_rule_version, owner) |

Never store a name-only external athlete join. Avoid optimistic payouts: changes to source data use a correction/adjustment ledger, not a silent mutation.

### Account/anonymous boundary

The repo's [accounts spec](../SPEC-accounts-and-mock-draft.md) documents `lp_device_id` / `X-Device-Id` and a claim-on-sign-in design. **Verify what has actually shipped**; do not assume email accounts or migrations already exist. Anonymous attempts must be server-persisted and bound to a secure claim token; device ID alone must not authorize claiming another person's data. On sign-in, ownership moves atomically and cannot be reclaimed by a different account.

## 6. Release slices with hard gates

| Slice | Deliverable | Gate |
| --- | --- | --- |
| **G0: evidence / UX** | Existing flows inventory, data readiness matrix, design prototype, usability tests with current LP users | No new backend dependency or invented live features |
| **G1: free picks + receipts** | Immutable NFL 3–5 call slate, canonical settlement, free XP, public verified share cards | No backdates, no duplicate grants, all void/push cases correct |
| **G2: basic HQ** | Optional pixel-art room, one free GM avatar, trophy case, links to Research Mode | Mobile/keyboard/reduced-motion parity, routes preserved |
| **G3: training + fictional player** | One free training slot, credits, attribute changes, persistence | Server clock, ledger, no alteration to real forecasts |
| **G4: fictional competition** | One deterministic solo scrimmage and optional rival comparison | Seed and state reproducibility, gameplay performance validation |
| **Parallel fast track** | **Field Goal Arcade** (separate spec) accessible without GM login | Measured fun/share activation independent of full GM economy |

**Priority suggestion:** run the Field Goal Arcade prototype and free receipt experiment in parallel before investing in G3/G4. Don't make a whole management RPG just to learn whether short sports mini-games convert visitors.

## 7. Acceptance tests / TDD contract

These are **tests to write before implementing** (not claims tests currently exist).

1. `gm_call_locks_original_source_line_and_time`: write before cutoff; immutable read is byte-equivalent; edits denied.
2. `gm_call_rejects_late_or_unknown_market`: cutoff exceeded, source missing, identity unresolved, market unsupported -> ineligible.
3. `gm_call_settles_push_void_dnp_correctly`: distinct statuses; no false losses or win receipts.
4. `gm_call_corrected_source_issues_auditable_adjustment`: correction preserves original and logs reason/source.
5. `gm_rewards_are_idempotent_and_capped`: retries, concurrent processing, and duplicate play IDs do not double-award.
6. `gm_sharp_rating_ignores_xp_and_ungraded_calls`: XP, activities and fictional abilities cannot change accuracy ranking.
7. `gm_training_server_clock_and_idempotent_claim`: future camp cannot be completed early; repeated claim does not duplicate delta.
8. `gm_scrimmage_is_seed_and_snapshot_reproducible`: same version/seed/snapshot has same result; no dependency on live sportsbook changes.
9. `gm_public_receipt_shows_provenance_without_private_data`: original timestamp, rule version, full result, source; no email/device ID.
10. `gm_anonymous_claim_cannot_transfer_other_users_records`: token ownership, replay protection and account claim race.
11. `gm_original_routes_survive`: /props, /predict, /scores, league forecasts, deep links work without GM Mode.
12. `gm_mobile_and_accessibility`: keyboard, audio consent, reduced motion, screen reader names and lower-performance fallback.
13. `gm_live_coverage_fail_closed`: missing or late real-world data shows “unavailable” instead of imaginary outcomes.

### Go/no-go evidence

Before shipping to public beta: a recorded end-to-end test with a real pregame lock and correctly settled outcome; negative scenarios; a second-user share-link attempt; verified no real money/redeemability; device/auth persistence test; accessibility and production performance budget. Measure activation, return, and user comprehension against conventional Research Mode. Stop or shrink the feature if it lowers core task completion without improving relevant retention.

## 8. Non-goals and future decisions

**Not in beta:** cash contests, paid Pick'em, gambling integration, tokenomics, card trading, licensed player likenesses, real-world badge-based cartridges, Fortnite-style mandatory quests or monetized takeover meters, an all-22 NFL recreation, real-time GM-vs-GM league scheduling, or an automatic wager agent.

**Decide after prototypes:** actual free call limits, record-scoring metric and minimum cohort, skill vs career level display, camp durations, fictional attribute schema, whether avatars represent a manager or fictional athlete at each surface, minigame credit caps, and whether the fictional scrimmage is engaging enough to ship.

## 9. Related repo context

- [Forecast-first / market-first product decision](../DECISION-forecast-first-leagues-market-first-props-2026-10-20.md)
- [Historical identity/account migration design](../SPEC-accounts-and-mock-draft.md)
- [Prop settlement original design](../SPEC-settlement-pipeline.md); audit current implementation before coding
- [NFL product direction](../SPEC-nfl-product-direction.md)
- [Gridiron contract](../GRIDIRON-CONTRACT-v1.md): experimental synthetic full-game replays **not** GM scrimmages or observed play footage
- [Pixel-art design PR #27](https://github.com/micahp/legendarypicks/pull/27)

**This document is a design decision proposal, not authorization to change gameplay, live forecast grading, production data, services, or the deployed website.**
