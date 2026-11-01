# Legendary Picks — NFL Arcade & Training Mini-Games

**Date:** 2026-11-01  
**Status:** Proposed implementation specification; not implemented.  
**Products:** Free, standalone NFL mini-games, optionally connected to future fictional GM career progression.  
**Companion channel:** [Pixel Red Zone](PIXEL-RED-ZONE-CHANNEL-SPEC-2026-11-01.md).  
**Earlier concepts:** [Live-Context Mini-Games spec in draft PR #28](https://github.com/micahp/legendarypicks/pull/28), [GM Mode in draft PR #28](https://github.com/micahp/legendarypicks/pull/28), [16-bit NFL HQ draft PR #29](https://github.com/micahp/legendarypicks/pull/29).

**Design refinement from the 2026-11-01 discussion:** Combine **Facebook Messenger basketball-style ultra-simple, instant-repeat, one-input arcade controls** with **Madden-style situational drills, scored technique and practice progression**. This document *adds a concrete training mode* to the earlier field-goal challenge spec; do not treat it as an ability-badge or cartridge implementation.

## 0. The experience in one minute

Someone watches a real game through [Pixel Red Zone](PIXEL-RED-ZONE-CHANNEL-SPEC-2026-11-01.md) or opens an NFL game on Legendary Picks. A verified 52-yard field-goal attempt happens. An unobtrusive card offers:

> “52 yards. Same distance. Your turn. Beat this kick.”

They tap, see a little 16-bit field, aim with one thumb, make a flick/timing gesture, and instantly get feedback: **GOOD / LEFT / RIGHT / SHORT**, an honest arcade score, and a **Beat my kick** link for friends. They can play again immediately, or open **Kicking Camp** to practice controlled skill drills (aim, power, timing, pressure) with bronze/silver/gold medals. Future GM Mode can grant **capped fictional training XP** from completed practice, but it is not required.

**Primary product test:** Is the minigame fun and shareable *even when no virtual economy, reward meter or GM account exists*?

### Product principles

1. **10–30 seconds** for one real-context challenge, and **30–90 seconds** for a deliberate training drill. One-thumb first; no long instructions.
2. **Direct physical input** (flick, aim, timing, one-tap movement), not trivia quizzes or menus disguised as games.
3. The challenge is **inspired by confirmed real play context**, but the user's kick/pass is a separate fictional arcade action. A score is an arcade score, not proof a player could execute the real play.
4. **Skill and mastery** drive scores. Fair deterministic rules, no purchasable boosts, no unannounced randomness, same challenge settings for all challengers.
5. Short actions produce visible feedback, readable motion and satisfying **original audio**. Always support mute, reduced motion and accessible alternative input.
6. Practice is optional and rewarding because it improves the player's *own technique*, not because they must grind a chore list to unlock basic play.
7. **Completely free beta.** No deposit, cash prize, wager, token, tradable card, paid energy refill, real-money entry or prize-gated collection.

## 1. Two related modes, different goals

| Mode | Trigger | Session | Reward/loop | Required data |
| --- | --- | --- | --- | --- |
| **Live Moment Challenge** | Verified current or archived NFL play; deep link | One short attempt, immediate retry | Compare score, share “beat me”, optional GM XP | Stable source play ID, canonical game, verified situation (e.g. FG attempt distance) |
| **Training Camp** | Arcade cabinet / “Practice” button, always available | 30–90 s scored drill (3–5 reps) | Get better at the controls; track medals and personal best | Versioned fictional practice config; **no live data required** |

There is no requirement to complete Training Camp before challenging a friend. Beginner training can be offered after the user's first attempt (“Want to improve your timing?”).

**Important:** The fictional GM Mode's **hours-long attribute training camps** and these **short action-based Madden-style drills** are distinct mechanisms. A future bridge may count training medals toward the GM's purely fictional stats, but the arcade itself must work independently without timers/currencies.

## 2. Launch game: Field Goal Frenzy

### A. Live-context challenge

Only create a **verified live-derived** field-goal challenge after the actual FG attempt appears with **published attempt distance**. If a game is in FG range but an attempt has not occurred, the user may enter a plainly labeled **fictional practice kick** based on a declared practice distance; no claim it came from a live attempt.

- Frozen input: source `game_id` + `play_id` + `revision`, teams, period, clock, actual `attempt_distance_yards`, source observation timestamp, optional factual actual made/missed result.
- Difficulty: same kick distance, neutral fictional wind by default, same obstacle/accuracy parameters for all on that challenge version. Do not mirror an actual stadium weather/wind without verified event-time data.
- Controls: (1) drag/flick direction or position aim, (2) release with power and timing using one-thumb gesture or two taps, optionally an always-visible accessibility control for aim/power.
- Render: 16-bit goalposts and football, consistent pixel camera, aim guide, power bar, kick trajectory **from the user's input**, not sourced athlete tracking.
- Feedback: immediate `GOOD`, `LEFT`, `RIGHT`, `SHORT`, `INVALID`; after ~2 sec show a fair 0–1000 score and personal best.
- Score: a **made** kick scores 600 base + precision bonus 0–300 + distance-adjusted execution bonus 0–100 (proposal, versioned); miss = 0 competitive points but provides specific practice feedback. Never imply a made field goal in the real game.
- One-tap **Retry** or **Challenge a friend**. Deep link must open exactly the same frozen challenge/rules/distance and permit a first anonymous attempt.
- Personal score is based on user's verified action, not whether the real kicker made it. Actual real outcome may be a factual secondary card (“Real attempt: missed”), but **after** user's own result to avoid confusing the game mechanic.

### B. Field Goal Academy (Madden-style training)

One short training drill with 3–5 attempts, each purposeful:

| Drill | Input skill | Example sequence | Feedback |
| --- | --- | --- | --- |
| Aim Lab | direction | 25 yd center → 35 yd left hash → 45 yd right hash | aim error, “left/right of center” |
| Power Control | controlled flick / release | same line, 30→45→55 yds | too short / overshot timing window |
| Pressure Kick | consistency under tighter *declared fictional* timing window | 3 late-game themed kicks | stability, successful reps |
| Precision Set | combined aim + power + timing | three diverse distances | total score, medal |

For v1 **ship Aim Lab and Precision Set only**; the rest are expansion ideas. Each drill has bronze/silver/gold medals based on published static score thresholds, and concise coaching on how to improve. No grinding to fill XP meters. Repeat as often as desired.

“Training” should actually teach motor skill: on a miss, point out which control failed. Progress over sessions should be visible (personal best and distribution), and target skill improvement rather than daily login streaks.

### C. Reference behavior (copy the principle, not proprietary content)

- **Messenger basketball:** one obvious gesture, a simple target, a self-evident result, frictionless replay, changing difficulty, friendly high score.
- **Madden training mini-games:** purposeful timed/precision drills with variable scenarios, skill-specific scoring, medals and coaching.
- **Legendary Picks difference:** real NFL play state can generate *new challenges on every slate*, while training improves user's control and a fictional GM career may benefit later.

Do not copy Messenger/Madden sounds, art, menus, labels, exact scoring, game code or licensed characters.

## 3. Next drills after FG is validated (not all shipped at once)

| Mode | Real observed context needed | 16-bit inputs | Training analog | Risk / release gate |
| --- | --- | --- | --- | --- |
| **Deep Ball / QB Target Drill** | Verified pass play and **actual air-yards/target distance if published**; otherwise fictional distance | Tap timing + swipe throw arc at 2D moving target | Madden-style QB accuracy targets, 3 reps | Never infer receiver route or target coordinates from PBP prose; prove event field availability |
| **Breakaway / RB Lane Drill** | Verified rush gain, start spot, down/distance (if known) | Swipe left/right, timed juke to avoid stylized defenders | Footwork/pursuit drill | Defenders synthetic, not a recreation of real defenders |
| **Catch Window / WR Drill** | Verified reception or target + safe generic field context | Tap correct moving catch window | Catch timing ladder | Route geometry and exact catch location fictional unless tracked |
| **Goal-Line Stand / Defense Drill** | Verified goal-to-go/down and play type | React quickly to visible gap indicators | Read-and-react challenge | Do not portray invented defensive coverage as factual |
| **NBA Shot Clock (future sport)** | Verified field-goal attempt distance/location if available | Messenger-like flick-to-shoot | 3-point / free-throw shooting camp | New sport-specific contract and rights review |

**Launch order:** FG standalone practice -> historical real FG challenges -> share links -> Field Goal Academy -> live-event trigger -> QB Target Drill -> others *only if measured fun and source coverage justify it*.

## 4. User journeys and UI surfaces

### A. War Room

- The **arcade cabinet** is a real interactive object in [draft NFL HQ PR #29](https://github.com/micahp/legendarypicks/pull/29). It opens “PLAY ARCADE”: **Today's Moments** (only verified events), **Training Camp**, **Friends' Challenges**. Not a notice saying “future feature” once the feature actually exists.
- The **TV** opens [Pixel Red Zone](PIXEL-RED-ZONE-CHANNEL-SPEC-2026-11-01.md); after a qualifying FG event, the ticker may surface **“Try the 52-yard kick”**. Watching is never interrupted automatically and a highlight can remain in the user's queue.
- A **standalone shareable route** (proposed `/arcade/nfl/field-goal/:challengeId`) runs without first visiting HQ. This is critical to the viral loop and mobile links from texts/X.
- An explicitly separate **Training Camp** route (proposed `/arcade/nfl/training/kicking`) lets players practice with fictional drills even when no games are on. No forced daily quota.
- After a valid attempt, link back to the **exact associated game/play** and to Legendary Picks' real research /scores /props (never conflate an arcade score with a pick or market edge).

### B. Mock screen flow

```text
[TV: Verified FG play]  →  “Think you can kick it from there?”
                                   ↓
                             [16-BIT FIELD]
                         52 YARDS / Q4 / 0:18
                     aim ← →   power/timing swipe
                                   ↓
                         [GOOD!   934 / 1000]
                   [RETRY] [BEAT MY KICK] [TRAIN]
                                   ↓ share
                        [friend opens same event]
                            [PLAY FREE NOW]
```

All text, timing and scores in sketch are **illustrative**. A real example requires a verified event ID and published FG distance.

### C. Game feel and audio

- Visual: original coordinated 16-bit pixel textures / pixel stadium, large goalposts, readable football arc, impact particles, tiny crowd animations, star/medal display. Shared art style with NFL HQ.
- Mix: original kick thud, swish/clank-like goalpost impact (football-appropriate, not pinball), small crowd pop, success/failure sting, optional looping practice beat. Avoid trademarked NFL broadcast audio or copied Madden sound packs.
- Audio muted until user gesture; volume/mute toggle, persistent choice where appropriate, captions and non-audio feedback. Background tab pauses loops. Honor reduced motion.
- Smooth on a typical mobile browser, but **do not turn pixel art blurry**. Internal resolution and nearest-neighbor/integer pixel scaling must be tested on real phone sizes.
- Motion matters more than decorative complexity. Consistent release physics and hit feedback must feel responsive before cosmetics or achievements.

## 5. Gameplay physics, fairness and scoring contract

**Don't port the full 3D Gridiron simulator just to kick a football.** Use a small versioned 2D deterministic arcade model.

- Authoritative `input`: `aim` normalized [-1,1], `power` [0,1], `release_timing` [0,1], optional `gesture_samples` limited by size and verified client/time; inputs cannot carry their own result.
- Arcade trajectory function outputs miss direction / enough range / precision; score derived from exact `physics_version` and `scoring_version`.
- Server recalculates a legitimate attempt from inputs and frozen challenge config. Client renders predicted result immediately but final verified score comes from server.
- Never compute a competitive result from client-reported “made=true,” performance clock, frame count, browser refresh, or duplicate submission.
- Same challenge/version and normalized input must produce same server score (within defined deterministic quantization). No hidden advantage from having a faster GPU, larger swipe area, or paying.
- If platform input parity fails (e.g., touch vs mouse timing drift), create per-device *practice* aids without affecting competitive scoring and measure parity across devices.
- Training drills have declared, fixed thresholds and scenario order; random sequences must be explicitly seeded and stored per version.
- Friend head-to-head is an **asynchronous high-score challenge**, not cash wagering or user-controlled odds.

### Proposed challenge schema, illustrative

```json
{
  "schema_version": "lp-arcade-challenge-v2",
  "challenge_id": "FIXTURE_FG_052_v1",
  "kind": "field_goal",
  "origin": "observed_nfl_play",
  "source_ref": {"game_id": "FIXTURE_GAME", "play_id": "FIXTURE_PLAY", "source_revision": "1"},
  "source_verified_at_utc": "2026-11-01T18:25:07Z",
  "observed_context": {"period": 4, "clock": "00:18", "attempt_distance_yards": 52},
  "challenge_config": {"weather_mode": "neutral_arcade", "aim_bias": 0, "precision_window": 0.13},
  "physics_version": "fg-physics-v1",
  "scoring_version": "fg-score-v1",
  "config_hash": "FIXTURE_HASH_NOT_REAL",
  "state": "illustrative_fixture_only"
}
```

The schema is a design proposal and fixture, **not an endpoint/current production data**. A challenge is **immutable**: source correction supersedes it with a new version and an audit pointer, never changes a friend's target retroactively.

### Proposed entities / APIs

| Entity / proposed endpoint | Job |
| --- | --- |
| `arcade_challenge` | Frozen game-event reference or practice scenario, hash/version, availability, correction chain |
| `arcade_training_drill` | Authored fixed/seeded targets, declared thresholds, versioned scoring |
| `arcade_attempt` | One signed/server-verified attempt, owner/session, normalized input, version/result/score, source hash |
| `arcade_personal_best` | Derived maximum verified score per user and challenge/config version |
| `arcade_share` | Deep link for exact challenge, opt-in inviter id, privacy-safe referral attribution |
| `arcade_training_progress` | Best attempt and earned medals per drill/version, no fake skill inference |
| `arcade_gm_grant` | **Optional future** capped and idempotent fictional XP/credits; never Sharp Rating |
| `GET /api/arcade/challenges/:id` | Frozen config, source provenance, state |
| `POST /api/arcade/attempts` | Verify inputs on server, idempotency key, return authoritative result |
| `GET /api/arcade/training` | Versioned drill catalog |
| `GET /api/arcade/leaderboard?challenge_id=...` | Fraud-filtered best scores for one challenge version |

Names above are planning proposals. Before coding, inspect existing account/device claim, backend route conventions and SQLite schema; do not create an entire separate identity database by accident. Use secure anonymous claim tokens rather than trusting `lp_device_id` alone to authorize score ownership.

## 6. Input sources and channel integration

The **real-play trigger** should reuse a single validated *observed* event contract from [Pixel Red Zone](PIXEL-RED-ZONE-CHANNEL-SPEC-2026-11-01.md), not scrape a UI text string:

```text
Authoritative NFL publisher / LP PBP ledger
          ↓ stable game ID + play ID + source revision + event provenance
     Normalized observed event (read-only)
          ├──> Pixel Red Zone: show a game and touchdown / FG event
          └──> Arcade eligibility adapter: “verified FG, 52 yds” → freeze challenge
                                                       ↓
                           standalone minigame + GM rewards (optional)
```

Only emit a field-goal challenge for source-verified FG **attempt** distance; no `yardline_100+17` shortcut as an authoritative published distance. A public event with missing/corrupt context has no game-linked challenge; an unrelated **fictional tutorial** may still work.

Do not use the [`GET /api/nfl/game/{game_id}/playbyplay`](../../../backend/routers/games/game_detail.py) text-only output as if it contained valid play identity and location. It currently exposes clock, text, score, and `scoringPlay`, with key fields stripped; R0 must inspect upstream real PBP before building a live challenge adapter.

Maintain exact source publisher and observed timestamp, UTC ingestion and version, game status, canonical team/player identifiers when relevant, replay/correction audit. Player-specific mini-game branding is prohibited until likeness/image rights are cleared. No broadcast footage or private source feeds.

## 7. Rewards, training and fictional GM bridge (optional, not a prerequisite)

Two independent notions of progress:

1. **Skill scoreboard:** verified game scores, completion, best attempts, drill medals, friend challenges. This is the primary game loop and cannot be improved by spending XP.
2. **GM progression:** optional **nontransferable, nonredeemable, free** career XP/credits or fictional skill tree bonuses. A successful training drill may grant a small capped award once per drill/day; gameplay retries never mint unlimited credits. A purchased cosmetic cannot change competitive physics.

No mandatory “complete 15 kicks” Fortnite-style checklist, artificial starvation timers, daily penalties, streak anxiety, chance-priced loot boxes or pay-to-win. Cosmetic achievements may recognize natural accomplishments (first 55-yarder, three precision medals, challenge rival win). The prior speculative **cartridges / actual athlete badges** idea remains parked, with no equipment advantage system.

A later fictional GM's special teams unit could gain practice proficiency or unlock facility visuals, **without changing real sports projections, model inputs, sportsbook lines, verified prediction records, or public Sharp Rating**.

## 8. Delivery plan and evidence gates

| Gate | Deliverable | Acceptance evidence |
| --- | --- | --- |
| **A0 gameplay references + data audit** | Prototype animation/control study, stable FG source audit on 5–10 verified historical FGs across short/long attempts | Published attempt distance, stable play ID, rights/latency, input accessibility |
| **A1 fun-first prototype** | Fictional practice kick in original 16-bit field, one-thumb timing and immediate retries | 10 first-time testers can play without onboarding wall; touch/keyboard parity; clear failure reason |
| **A2 verified historical challenge** | Frozen real FG challenge, server-verified scoring and replay-safe versioning | Source match, no fake weather, same settings across devices and friends |
| **A3 viral loop** | Shareable “beat my kick” URL, anonymous first attempt, personal-best board | Recipient completes attempt without signup, source and scores match; basic bot/rate controls |
| **A4 training** | Aim Lab + Precision Set, medals and personal progress, no GM dependency | Deterministic targets, repeatability, skill feedback, transparent reward policy |
| **A5 live-event channel bridge** | Real-context “try this kick” appears in Pixel Red Zone after verified attempt | Event dedupe, source lag disclosure, never interrupts viewing automatically |
| **A6 optional GM bridge** | Capped fictional XP and training-room progress | No competitive or forecast contamination; retry/duplicate grants idempotent |

**Do not block A1–A3 on A5/A6.** User's priority is fast, fun mini-games; GM Mode is complementary, not the prerequisite.

## 9. Test-driven acceptance suite

Write the failing tests for the next gate **before** building its gameplay/adapter. At minimum:

1. `arcade_only_uses_verified_fg_attempt_distance`: missing published attempt yards -> no sourced challenge; tutorial clearly fictional.
2. `arcade_source_event_agrees_with_redzone`: same canonical play ID and revision; correction supersedes both visual and arcade eligibility consistently.
3. `arcade_no_player_outcome_leakage`: real made/missed never predetermines user's arcade kick.
4. `arcade_same_input_same_result`: independent client/server verification across seeded configs, retries and repeated renders.
5. `arcade_rejects_tampered_result`: forged made/score/physics version, impossible timing, invalid inputs and replayed idempotency keys fail safely.
6. `arcade_score_cap_and_legend`: score in 0–1000, made/miss states consistent, visual feedback matches authoritative score.
7. `arcade_timing_input_device_parity`: mobile touch, mouse and keyboard control bindings yield equivalent normalized inputs and fairness.
8. `arcade_friend_exact_frozen_challenge`: invitation shares the same source/version/config hash and game context after opening on different device.
9. `arcade_anonymous_play_secure_claim`: first play without login, cannot steal others' scores through editable device ID.
10. `arcade_training_drill_frozen_and_medals_correct`: scenario/order/version and medal threshold deterministic, no daily grind.
11. `arcade_gm_optional_and_idempotent`: absent GM subsystem cannot break game; when present capped reward emitted once; Sharp Rating unchanged.
12. `arcade_no_fake_live_state`: stale/disconnected/unsupported events cannot be shown as newly live.
13. `arcade_touch_and_a11y`: >=44px controls, labels, reduced motion, no forced audio, workable low-motion/keyboard path.
14. `arcade_shared_audio_policy`: entering from room/channel never starts unmuted playback without user permission; stop on exit.
15. `arcade_latency_and_low_end_performance`: input-to-animation tested on ordinary phones, bounded asset sizes and no hidden GPU assumptions.
16. `arcade_data_source_correction`: altered source attempt distance produces a superseding version and never silently changes an existing leaderboard.
17. `arcade_existing_lp_workflows_unchanged`: /props, /predict, /scores, published model grading, data ingests and source identity unaffected.
18. `arcade_referral_qualified_activations`: only verified distinct recipient completions count toward viral coefficient, not views.
19. `arcade_no_paid_advantage`: user XP, skins or fictional GM stats cannot alter standardized competitive challenge scoring.

### Metrics for the beta

- First-view → first valid completed kick; median time to complete.
- Replay rate **without** XP prompts; average rounds/session; median practice improvement after 3 reps.
- Share rate; invited visitor → first qualified completed attempt; qualified new players per sharer; D1/D7 next-slate returns.
- Same-challenge device score parity, invalid/fraud rejects, source-event eligibility, event-to-challenge latency and data freshness.
- Whether arcade users subsequently open Legendary Picks game/research pages and whether their core research usage declines.

Stop and simplify if first-time players don't understand the kick, the controls feel wrong, or friends fail to play from a shared link; do not attempt additional games to compensate for an unfun basic kick.

## 10. Engineering references and rights boundaries

- [Prior free mini-game product spec (PR #28)](https://github.com/micahp/legendarypicks/blob/docs/gm-mode-live-minigames-2026-10-31/docs/product/legendary-play/LIVE-CONTEXT-MINIGAMES-SPEC-2026-10-31.md)
- [GM Mode spec (PR #28)](https://github.com/micahp/legendarypicks/blob/docs/gm-mode-live-minigames-2026-10-31/docs/product/legendary-play/GM-MODE-SPEC-2026-10-31.md)
- [Pixel Red Zone normalized observed-event contract](PIXEL-RED-ZONE-CHANNEL-SPEC-2026-11-01.md)
- [NFL authoritative rules reference](../../rules/NFL-2026-GAME-STATE-RULES.md)
- [Existing play-by-play service](../../../backend/routers/games/game_detail.py), [16-bit War Room prototype PR #29](https://github.com/micahp/legendarypicks/pull/29)
- Audio browser behavior: [MDN autoplay guide](https://developer.mozilla.org/en-US/docs/Web/Media/Guides/Autoplay).

Only original/cleared art and audio. An original 16-bit football play is not a broadcast replay. All data-driven sport references must be source-verifiable and labeled correctly.

**This document is a proposed product/engineering spec, not an implementation change or authorization to deploy.**
