# Legendary Picks Live-Context Mini-Games — Independent MVP specification

**Date:** 2026-10-31  
**Status:** Proposed / exploratory. No minigame is implemented by this document.  
**Priority:** Potentially the **fastest testable consumer product** in this concept family, independent of a full GM career or fictional football simulator.  
**Companion:** [GM Mode](GM-MODE-SPEC-2026-10-31.md)  
**Design context:** [16-bit NFL HQ designs (PR #27)](https://github.com/micahp/legendarypicks/pull/27).

## 0. Clarifying the idea

A live or recently completed **real sporting event supplies the *context*** for a 10–30 second, extremely simple, replayable arcade challenge. The real play is an input to the challenge's *starting position, distance, type and difficulty*, **not the outcome of the user's arcade attempt**.

Example: an NFL kicker attempts a 52-yard field goal. Legendary Picks creates a **“Can you make it from 52?”** minigame from that confirmed kick, at the corresponding field position. The user aims and swipes to kick, receives an immediately comparable arcade score, and shares a deep link so friends can try the **same frozen challenge**.

This is **not** an interactive live broadcast, real-time play prediction, a Madden-style simulation, or a way to affect a real match. Users can play the archived challenge long after the game ends.

**Core rule: the game must be fun even if the GM Mode, XP, training camps, player cards, and any cartridge concept do not yet exist.** The project is a standalone fast-track experiment, with optional later GM career rewards.

### Explicit exclusions from early discussion

- Don't turn cartridges into real-player ability badges, Madden abilities or paid power-ups; no badge inventory MVP.
- No Fortnite-style “fill meter by completing chores” progression requirement.
- No sprawling multi-sport minigame catalog in v1.
- No required wallet, deposit, bet, cash prize, token, NFT, paid attempt or real-money market.
- Never claim that a tap in this game is a real sports result or a valid sports prediction.

## 1. Target experience and share loop

1. A real NFL field-goal attempt is **verified and ingested**. We record the actual attempt distance (preferred), game/clock/score context, and source/version. A user can also choose a verified historical attempt.
2. An event card appears: **“Field Goal Frenzy — 52 yards, Q4, 0:18. Can you make it?”** with explicit “arcade challenge based on a real play.”
3. The user plays instantly on touch, mouse or keyboard: aim, set power, time the kick. Goalposts, ball and feedback animate in original 16-bit style.
4. The server calculates the arcade result under a fixed versioned scoring/physics config. The user's best *legitimate* score is preserved.
5. A shareable scorecard says **“I hit the 52-yarder — beat my score”** and opens that *exact challenge ID* for a friend; no registration needed for one attempt.
6. After playing, the friend may save progress / sign in / challenge another friend. If GM Mode exists, a limited, idempotent amount of **free, nontransferable XP** can be granted. Sharing itself must not buy competitive advantage.

**Primary activation metric:** first completed valid challenge.  
**Primary viral metric:** qualified **new** participants completing a valid challenge per inviting participant, not impressions, opened pages, or share-sheet displays.

## 2. Gameplay v1: Field Goal Frenzy

### Supported modes

- **Historical challenge:** simplest and safest. Derived from a past play with an independently verified distance. Enables a fully working beta before a low-latency live feed.
- **Live-event-derived challenge:** created from a verified newly ingested event and labeled with observation time. It may appear seconds or minutes after the real broadcast. “Live” applies to its source event's game context, not instantaneous synchronization.
- **Practice tutorial:** clearly fictional **practice spot**, not a forged real game or event. May be played offline without competitive score submission.

### Input: minimal

- **Distance:** official recorded field-goal *attempt distance* in yards. If not available, reject that event for public launch rather than inventing it.
- **Context:** league, canonical game_id, play_id/source_event_id, period, clock, teams, score before play, event timestamp and source. Display only verified fields.
- **Weather/wind:** use a **declared neutral arcade environment** by default. Real weather must not be presented or used unless independently verified at that specific play.
- **Outcome:** store the real make/miss as *observed historical fact* only. Never use it to rig an arcade user's outcome.

Football state conversion warning: football play data may encode `yardline_100` from the *offense* to its opponent's goal. A conventional field-goal distance is often approximated as `yardline_100 + 17` (10-yard end zone + 7-yard hold) for normal spotting, **but this is not an official attempt-distance source**; special cases and reported spots may differ. In v1 use the published attempt distance; a later fallback requires independent source verification and clear “estimated” labeling. Quarter/field-side mappings must follow canonical NFL rules, never a naive quarter parity heuristic.

### Controls and difficulty

- Short 2-step interaction: (1) aim left/right, (2) power + release timing. Both can be combined into a swipe for mobile.
- Physics are deterministic from challenge configuration + normalized player input, with transparent scoring rules and bounded jitter if any; score must be reproducible server-side.
- Distance affects difficulty through a **published, tested curve**; all users of the same challenge face the *same conditions*. No pay-to-win, undisclosed stat multipliers or purchased accuracy assistance.
- Result states: `made`, `missed_left`, `missed_right`, `short`, `invalid_attempt`; score 0–1000 on a consistent rubric defined in config version.
- Example scoring proposal: made kick = base completion score + accuracy/precision bonus, capped at 1000; miss = zero completion points with optional practice feedback. Don't award “made” for an invalid frame rate or impossible user input.
- Aim for fast launch and a full 10–30 second play session. The user may retry; leaderboards keep **one validated best score per user per challenge** and never interpret retry count as predictive skill.

### Fairness and challenge lifecycle

- Challenges are generated once from a verified event and frozen at `config_version` + `rules_version` + source-event hash. If source later corrects a distance or identity, **issue a versioned replacement** with an audit trail, do not silently change a score target under existing submissions.
- A public challenge link resolves even after the game, or shows a specific retired/corrected state and directs to a new valid version.
- One **competitive score track per challenge version**. A score from v2 cannot outrank a v1 result if rules differ; show separate leaderboards.
- No secrets or sportsbook history in public challenge URLs. Ensure no querystring token permits forging another user's score.
- Replay protection: server-authoritative result verification, rate limiting, user/session binding, duplicate attempt idempotency, bounded inputs, bot/fraud checks. Anonymous play is allowed but claiming a score requires secure ownership.

## 3. Product surfaces

### Public homepage entry point

A small “Play Today's Moment” or “Can You Make This Kick?” module sits alongside **Research / Props / Forecasts**, not in place of them. When there is no verified current event, show an **actual archived challenge** (clearly dated) or a fictional tutorial. Never fake a live FG.

### Arcade detail screen

- 16-bit pixel stadium and goalposts, ball, movable aim, launch / power meter; dark purple / lime / crown branding.
- Header: real-game context including **data source and observed timestamp**, and a clear label “ARCADE • INSPIRED BY A REAL PLAY”.
- Main button “Kick”, replay after the attempt.
- Score panel: your result / best validated score / challenge high score / number of eligible attempts (if available).
- End card: share URL, retry, choose a different verified kick, visit the live/game detail page.
- Mobile portrait as first-class; desktop and screen-reader accessible alternative controls. Sound opt-in, haptics optional, reduced-motion safe.

### GM Mode handshake (optional later)

The minigame's result record can produce `gm_reward_grant` as a **secondary consumer** using source `arcade_attempt_id` and a versioned, capped rule. This **must not** be required for the arcade to work. Credits/XP affect only fictional careers or cosmetics, not real player forecasts or public “Sharp Rating.” Avoid making a field-goal miss cost money or regress a character.

### Future mini-games, not v1

| Mode | Source-event requirements | Arcade mechanic | Launch condition |
| --- | --- | --- | --- |
| **Deep Ball** | Verified passing play with air distance/target area, team context | Swipe launch angle, time release / accuracy | Only after verified yardage semantics and a tested toy ball model |
| **Breakaway** | Verified rushing play, starting yardline and gain | One-thumb lane change/dodge | Fictional defenders labeled synthetic, not tracking-reconstruction |
| **Goal-Line Stand** | Verified defensive situation, down/distance/spot | Quick reaction / gap selection | Only with reliable state and good game feel |
| **Catch Window** | Verified catch target / broad event class | Timing tap to make an arcade catch | Original animations and rights cleared |
| **Basketball Shot** | Verified NBA shot event distance/spot if licensed and available | Messenger-like flick to shoot | Launch as separate sport-specific config with accurate court coordinates |

**Do not generate a fake 22-player drive replay to make the minigame appear detailed.** If a source lacks exact ball/athlete trajectories, use a stylized fictional visual.

## 4. Canonical event/config contracts (proposed, not present code)

Input ingestion -> validated contextual event -> frozen challenge -> submitted attempt -> server verified outcome -> share/deep link. All UTC times explicit.

```json
{
  "schema_version": "arcade-fg-1",
  "challenge_id": "demo-fg-2026-0001-v1",
  "mode": "field_goal",
  "source_kind": "observed_nfl_play",
  "event_ref": {
    "league": "nfl",
    "game_id": "DEMO_ONLY_GAME",
    "source_event_id": "DEMO_ONLY_EVENT",
    "observed_at_utc": "2026-10-31T20:00:00Z",
    "source_publisher": "demo-publisher",
    "source_revision": "demo-revision"
  },
  "real_play_context": {
    "attempt_distance_yards": 52,
    "period": 4,
    "clock_seconds_remaining": 18,
    "actual_kick_result": null
  },
  "rules_version": "fg-arcade-v1",
  "render_profile": "16bit-original-1",
  "random_seed": 123,
  "content_hash": "demo-not-real-hash",
  "status": "illustrative_only"
}
```

**All values above are invented schema examples. Do not present them as actual NFL events.** For live, accepted source event must have verifiable identity, distance, time and supported event type.

Minimal persisted entities:

| Entity | Fields / invariants |
| --- | --- |
| `arcade_source_event` | canonical game_id; source_event_id and publisher/version; observed timestamp; event type; verified distance; integrity/coverage flags |
| `arcade_challenge` | immutable challenge_id, event_ref, config JSON, game_version, config hash, status, issued_at and superseded_by |
| `arcade_attempt` | unique attempt_id, challenge_id/version, anonymous player secure token or authenticated user_id, normalized inputs / replay evidence, server_score, outcome, verified_at, rules hash, integrity status |
| `arcade_score_best` | unique(player identity, challenge version) best valid attempt id/score; derived from attempts |
| `arcade_share` | public challenge/link token, referring profile/attempt if opted in, expires/status, recipient activation tracking without exposing private identifiers |
| `arcade_reward_ledger` | optional unique reward source + owner + grant version, when GM integration exists |

Identifiers are strict stable IDs, not `player_name + date`. Source read failures are errors/unavailable states. Report count of eligible, quarantined and invalid source events before launching a daily challenge feed.

## 5. Technical implementation strategy

**Proposed components:** `ArcadeMomentRail`, `FieldGoalCanvas` (HTML canvas or lightweight sprite renderer), `KickControls`, `ArcadeScorecard`, `ChallengeShareLanding`, and a small score API. These are names for planning, not existing modules.

- Prefer a tiny deterministic 2D engine. Do **not** block this on Gridiron Physics 3D, Blender rigging, or completing full NFL simulations.
- Start with a local fixed historical fixture and gold-standard tests, then ingest additional verified events. Verify the historical fixture independently before labeling the demo real.
- Client-side prediction can render the kick immediately, but server owns leaderboard score verification from normalized input and versioned physics.
- Pin rules and scoring versions; use deterministic pseudo-random generation only when needed and seeded identically on server.
- Source data may come from existing LP scoreboard / NFL play-by-play *if the event semantics and distance are validated*. Audit real field-goal attempt availability before committing to live triggers.
- Caching: immutable challenge config cache; live event polling bounded per game; no extra per-row downstream calls. Connection loss can permit practice, but cannot issue a “verified” high score offline.
- Do not embed or rehost unlicensed broadcast footage, league marks, player photos or game audio. Original pixel art is preferable.

## 6. Slice plan / priority

| Slice | What ships | Acceptance gate |
| --- | --- | --- |
| **M0 — source audit** | Inspect existing NFL play-by-play and determine verified FG distance coverage; select representative historical events | Record eligible / rejected counts; independently check at least five attempts and unusual field positions |
| **M1 — playable offline prototype** | A fictional 52-yard practice kick with deterministic swipe controls in browser | Works on touch + mouse + keyboard, under 30 s, fun in quick user tests |
| **M2 — observed historical challenges** | Frozen configs from verified FGs, server-validated score, replay/share URL | Same source/config/attempt replays identically; public page shows provenance |
| **M3 — share + compete** | Anonymous challenge deep link, per-event leaderboard, friend attempts | No login needed to try; referral conversion measurement, anti-cheat tests |
| **M4 — live-triggered listing** | Eligible verified in-progress NFL FGs automatically produce challenge cards | Feed delay displayed; no false live/incorrect distance; missing source fails closed |
| **M5 — GM link** | Capped XP / training-credit grants to fictional career, opt-in | No impact to real prediction records, capped, idempotent; game still runs standalone |

**Recommendation:** M0–M3 are the first actual investment. The mini-game and challenge link can demonstrate share-driven acquisition before gamifying every part of Legendary Picks.

## 7. Minimum event analytics / experiment

Track `arcade_tile_seen`, `arcade_opened`, `arcade_started`, `arcade_attempt_submitted`, `arcade_attempt_verified`, `arcade_retry`, `arcade_share_clicked`, `arcade_share_opened`, `arcade_referral_started`, `arcade_referral_verified`, `arcade_gm_reward_granted`.

North star for pilot: **verified new-user attempts generated from each sharer's link**. Also measure start-to-finish conversion, median rounds/person, D1/D7 return, distinct real-game contexts played, latency, moderation/fraud rejection, browser performance, and the effect on returning to /props and /scores.

Do not use inflated impressions or clicks as evidence of viral growth. User tests must check whether ordinary football fans understand **“inspired by the real kick”**, not “I controlled the broadcast.”

## 8. Test-driven acceptance cases

Write these tests before publicly enabling an event feed.

1. `arcade_real_fg_requires_published_attempt_distance` — missing/ambiguous distance never becomes a verified challenge.
2. `arcade_does_not_copy_real_make_miss_into_arcade_result` — real kicker's outcome is observational only; same user inputs score independently.
3. `arcade_challenge_frozen_per_source_revision` — refresh cannot change distance/rules for an existing challenge.
4. `arcade_source_correction_supersedes_not_mutates` — correction creates v2 and v1 remains auditable / retired.
5. `arcade_same_inputs_same_score_same_rules` — deterministic verifier across clients, server and replays.
6. `arcade_score_rejects_impossible_inputs` — off-range timing/aim, tampered payload, invalid seed, forged identity cannot earn verified score.
7. `arcade_posted_results_idempotent` — retries or duplicate HTTP submits don't duplicate attempts, best scores or rewards.
8. `arcade_same_challenge_for_every_recipient` — deep-link invitee gets exact version/hash and equal conditions.
9. `arcade_public_share_redacts_identity` — never expose emails, device tokens, source publisher secrets or private settings.
10. `arcade_verified_live_label_requires_fresh_observation` — stale or missing plays are archived/unknown, never falsely “live now.”
11. `arcade_game_context_matches_source` — period, clock, game id and team attribution match independent published play record; no forged score.
12. `arcade_mobile_keyboard_and_reduced_motion` — controls accessible, no audio without consent, non-animation alternative supported.
13. `arcade_gm_optional_consumer` — mini-game works when GM service is absent; capped reward exactly once if service enabled.
14. `arcade_original_lp_routes_unaffected` — /scores, /props, /predict and model details continue to work.

### Go/no-go bar

Prototype players must understand and complete their first kick without a tutorial wall; recipients can click a share and play immediately; scoring is repeatable, versioned and server-verifiable; game state is sourced, not invented; browser performance is acceptable on an ordinary phone. Publish no fabricated “current” challenges or leaderboards. If the field-goal prototype is not fun and shareable on its own, improve it or stop before making more mini-games.

## 9. Related references

- [GM Mode spec](GM-MODE-SPEC-2026-10-31.md)
- [NFL 2026 game-state rules](../../rules/NFL-2026-GAME-STATE-RULES.md) — canonical interpretation of football field state, not an arcade physics implementation
- [Gridiron contract](../../GRIDIRON-CONTRACT-v1.md) — separate fictional statistical/3D research mode; avoid false claims of game recreation
- [Pixel-art references in PR #27](https://github.com/micahp/legendarypicks/pull/27)
- [Forecast-first / market-first architecture](../../DECISION-forecast-first-leagues-market-first-props-2026-10-20.md)

**This is design research only. No real-game feed, server, database, release, model or deployed UI should be changed as part of this docs commit.**
