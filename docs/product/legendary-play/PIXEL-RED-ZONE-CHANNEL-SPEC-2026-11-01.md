# Legendary Picks — Pixel Red Zone: always-on 16-bit NFL channel

**Date:** 2026-11-01  
**Status:** Proposed implementation specification; not implemented or approved for production.  
**Home:** NFL War Room TV in draft [PR #29](https://github.com/micahp/legendarypicks/pull/29).  
**Companion:** [Arcade + Training Mini-Games](ARCADE-TRAINING-MINIGAMES-SPEC-2026-11-01.md).  
**Working title:** “Pixel Red Zone” (internal). Public naming needs a trademark review: this is **not the NFL RedZone television broadcast** or a retransmission.

## 0. Product decision

**An always-on, audio-enabled, 16-bit *play-by-play visualization channel* for the active NFL slate.** The user clicks the TV in their fictional GM apartment, sees the running pixel channel in a room overlay, and can enlarge it to immersive/full-screen. The channel follows the most interesting *verified* live situations across games, like a football Red Zone director, without trying to re-create every player or render full Madden drives.

“Always on” means the **channel remains running, updating, and automatically choosing a game while the viewing surface is open**; there is no need to select the next play or launch a simulation each time. It does **not** mean unmuted audio without consent, always-running background CPU on hidden tabs, or pretending to have live coverage when games are off.

**MVP promise:** “Leave the TV on. The pixel field moves with verified NFL play-by-play, and when a touchdown happens, you see and hear a short celebration before the channel follows the next game.”

### What we are NOT building

- Not a pirated NFL RedZone stream, broadcast footage, official commentary relay, or an implied NFL partnership.
- Not a 22-player motion reconstruction, actual receiver routes, collision physics, or a 3D Gridiron simulation. Existing [Gridiron contract](../../GRIDIRON-CONTRACT-v1.md) is for **hypothetical generated game scripts**, a separate product.
- Not predictive: no simulated touchdowns, invented real-player positioning, future-play narration, sportsbook advertising, or trading advice.
- Not a static football stats dashboard with a decorative field; the **channel is the experience**.
- Not tied to GM XP or mini-game rewards to function. The same real-play adapter may later feed [Arcade + Training](ARCADE-TRAINING-MINIGAMES-SPEC-2026-11-01.md).

## 1. UX and interaction contract

### A. Enter from the GM apartment TV

1. In [`components/Leagues/NflPixelHQ.tsx`](../../../components/Leagues/NflPixelHQ.tsx) (prototype lives in PR #29, not necessarily on `dev`), replace the TV's research-only preview with **Watch Pixel Red Zone**.
2. TV remains contextual: when a game is live, display a **verified** matchup, score, and freshness; before kickoff, “Next NFL slate” instead of false “LIVE”.
3. First click opens an **in-room television viewing panel** with the pixel channel and buttons: **Expand**, **Sound on/off**, **Game detail**, **Back to room**.
4. Expand opens a dedicated, linkable route (proposed `/nfl/pixel-red-zone`), which may use the browser Fullscreen API after an explicit button gesture. Full-screen failure keeps the route usable in a full-viewport layout.
5. Leaving expanded view returns to the same room and can preserve the session's pinned game/sound choice. All existing `/scores`, `/props`, `/predict` and game-detail pages remain unchanged.
6. Anyone can watch without a login or wallet. Audio begins **muted**. Clicking “Sound on” may activate audio. The TV click alone should not implicitly enable sound.

### B. Full-screen channel layout (16-bit aesthetic)

```text
┌────────────────────── LEGENDARY PICKS / PIXEL RED ZONE ─────────────────────┐
│  LIVE FROM VERIFIED PBP  ·  LAST UPDATE 23s AGO            🔈  ⛶  ✕         │
│                                                                            │
│                   PIXEL FOOTBALL FIELD / STATE                            │
│     Team A  ─────────────● ball────→  first down / goal line              │
│                Down & distance · possession · clock                       │
│                                                                            │
│  GAME: BUF @ KC        Q3 8:24      BUF 17 – KC 14                         │
│  LAST VERIFIED PLAY: “Run for 9 yards to the 12”                           │
│                                                                            │
│  WATCH NEXT: red-zone alert / recent scoring plays from other games        │
│  [Pin game]   [All games]   [Game details]     EVENT DATA IS DELAYED       │
└────────────────────────────────────────────────────────────────────────────┘
```

**All labels, teams and values in this ASCII sketch are fictitious examples, not an actual game.**

- A crisp **16-bit-inspired 2D football field** with yard stripes, end-zone art, ball/LOS cursor, possession-side marker, first-down stripe when verified, scoreboard, quarter/clock.
- Minimal **sprites/animations tied to verified events**: pixel ball advances from old verified spot to new verified spot, short generic pass/run icon, chain marker changes, possession arrow flips. Do not infer trajectories or real athlete locations from the play description.
- **Scoring moment:** brief 1–3 second touchdown title, pixel crowd flash, scoreboard update, original celebratory audio stinger and caption. Show the actual scored points only from verified source state; the following PAT/2-point try is its **own event**, not an automatic +7. A touchdown corrected/overturned must visibly retract or correct the earlier celebration and state.
- Fumble/interception, field goal (made/missed), punt, sack, timeout, quarter change are **simple state transitions** with relevant pixel icon and authored caption. No elaborate cinematic animation required.
- Multi-game queue beneath or beside main field with current scores and “who is in the red zone.” Allow pinning one game, unpinning, skipping to all games.
- Mobile: landscape-style field inside portrait viewport; readable compact score/ticker; one-tap enlarge; touch targets >=44px; never require a wide desktop layout.
- Accessibility: caption log with source and time; keyboard controls; stop animations under reduced motion; never communicate scoring exclusively by color/sound; do not trap focus in full-screen.

### C. States

`off_air` (no games) → scheduled/next slate; `waiting` (games live, no verified eligible PBP) → honest waiting graphic and scores; `live` → running channel; `event_highlight` → short score/turnover moment; `paused_by_user`; `stale` (last verified observation older than assessed threshold) → display the last known event and age, suspend “Live”; `final` → final score then handoff; `replay` → clearly labeled dated archived session if user explicitly chooses replay.

**No silent automatic replay masquerading as live.** No live games means screen can stay on showing schedule or “off air,” optionally invite selection of an archived highlight.

## 2. Source-of-truth and feasibility audit (mandatory first gate)

### Existing code / measured limits from repo inspection

- [`backend/routers/games/game_detail.py`](../../../backend/routers/games/game_detail.py) currently exposes `GET /api/nfl/game/{game_id}/playbyplay`, built from `espn.summary(...).plays`. The response groups `{clock, text, scoreAway, scoreHome, scoringPlay}` by period.
- [`components/Game/types.ts`](../../../components/Game/types.ts) `PbPPlay` does **not** expose source play IDs, possession, down/distance, spot, source observed timestamp, replay/correction revisions or outcome classifier. Text is not enough to render reliable live field position.
- [`backend/routers/games/scoreboard.py`](../../../backend/routers/games/scoreboard.py) has live scoreboard/snapshot behavior and documented freshness policy; reuse the canonical game's identity and schedule/score if coverage is verified.
- Draft PR #29 adds the clickable TV and an in-room score preview; it is an **integration location**, not proof this Red Zone adapter exists.
- [`docs/rules/NFL-2026-GAME-STATE-RULES.md`](../../rules/NFL-2026-GAME-STATE-RULES.md) governs semantic field orientation, scoring and quarter transitions; **observed game events** are authoritative, not any sampled simulator reducer.

**Before writing animation code, audit actual coverage in the stored/published source** across at least a representative live Sunday slate plus 5–10 historical games with drives including touchdowns, turnovers, reviews and field goals. Report:
- total scheduled/live games, number with PBP, unique stable IDs, missing IDs, duplicate revisions, timestamps, first-seen latency and correction rates;
- valid possession team, offense-relative `yardline_100` or independently verified field side/yardline, down/yards-to-go, play classification, explicit score-after and period/clock;
- whether summary feed exposes these fields (possibly as unexposed raw publisher data); **do not claim available until verified**.
- baseline freshness: time from publisher observation and LP ingress to presentation. Decide live/stale thresholds from the observed distribution, not guesses.

**Fail closed by field**: if an event lacks an authoritative spot, show score/time and a static field with “Ball spot unavailable”; do not deduce ball movement from prose, hash the text as an ID, or guess real plays. Lack of PBP means no play animation, not made-up football.

### Canonical read-only adapter (proposal)

One new normalized **observed** live event channel shared by Red Zone and, later, arcade triggers. Example shape (fictional fixture, **not** a real game):

```json
{
  "schema_version": "lp-observed-nfl-event-v1",
  "game_id": "FIXTURE_GAME",
  "source": {"publisher": "fixture", "play_id": "FIXTURE_PLAY_17", "revision": "1",
             "reported_at_utc": "2026-11-01T18:25:04Z", "observed_at_utc": "2026-11-01T18:25:07Z"},
  "sequence": 17,
  "period": 3,
  "clock": "08:24",
  "status": "live",
  "offense_team_id": "FIXTURE_TEAM_A",
  "defense_team_id": "FIXTURE_TEAM_B",
  "before": {"down": 2, "yards_to_go": 8, "yardline_100": 21,
             "score_home": 14, "score_away": 17},
  "after": {"down": 1, "yards_to_go": 10, "yardline_100": 12,
            "score_home": 14, "score_away": 17},
  "event_type": "rush",
  "score_kind": null,
  "review_state": "confirmed",
  "confidence": {"identity": "verified", "field": "verified", "score": "verified"},
  "display_text": "9-yard rushing play"
}
```

Required implementation semantics:
- Source `play_id` unique **within** `game_id` and `source`; retain revisions; derive stable `event_id` from canonical game + source + publisher play ID. Source version becomes part of revision key, not a new unrelated play.
- Stable IDs from canonical game/player/team joins, never names or arbitrary dates.
- `before` / `after` nullable **independently**, with explicit confidence/provenance per field. The illustrative object above does not assert current raw data supports all fields.
- Keep `occurred_at`, `reported_at`, `ingested_at` distinct; published clock is not an ISO timestamp. Do not invent subsecond event timing for animation.
- Preserve original source score and score deltas. Do not automatically infer +7 for a touchdown, or apply a generic “reset at quarter change.”
- A verified field spot is offense-relative; renderer direction comes from actual offense and explicit field side/attacking end. For a simplified symmetrical field, label **direction as diagrammatic** when true stadium direction is unknown.
- Observe review/overturned/null events; append revisions; update snapshot and retire obsolete animations with a correction notice.
- Store canonical event feed in a compact replayable cache/ledger with stable ordering and deduplication. A UI-facing `GET /api/nfl/pixel-red-zone/events?since=cursor` + snapshot endpoint are **proposed**, not current routes.
- Backfill small bounded windows; push/SSE if operationally appropriate or bounded polling (proposed 5–15 s only after measuring source cadence) with one shared subscription, no per-viewer/publisher requests.

## 3. Channel director: Red Zone selection (deterministic, transparent)

The channel must stay engaging even with 8–12 simultaneous games without manic cuts or invented events.

### Eligibility and priority

1. Only verified **live** NFL games enter the live director. Do not promote scheduled/final events.
2. If eligible **new confirmed scoring event**, show a short replay/celebration and its actual score, then resume the queue. Review pending -> quiet “Under review” state; no premature touchdown horn.
3. Otherwise games with verified current offensive field spot **inside opponent 20** get highest non-scoring priority; between 21–30 is “approaching,” lower priority. Label **red zone** only when official spot and possession allow it to be computed.
4. Break ties with (a) goal-to-go, (b) fewer yards to goal, (c) down number/late clock if verified, (d) last new play recency, then stable game ID. A user **pin** outranks auto-cut, except an optional setting allowing scoring alerts.
5. Minimum dwell **proposed** 8–15 s after changing games unless a confirmed TD occurs. Maximum 1 scoring celebration per unique event revision. Queue and last-highlight display are replay-safe.
6. A score delta by itself with no source scoring play may trigger a **score update card**, not a fake touchdown re-enactment.
7. On no red-zone eligible games, show the most recently active verified game or an “Around the league” grid. No forced random clip or future event.

### Timing and discontinuities

Playback runs on **event transitions**, not 60-second continuous player action. Between plays the channel displays scoreboard, field, recent-event text and subtle idle/crowd animation. Separate UI wall clock and game clock; game clock only changes when the feed states a new value. Events can arrive late or out of order: sort by validated game sequence/period clock and version; do not animate a newer state backward during normal live playback. Late source corrections apply snapshot + visible correction.

End of quarter/halftime/OT and possession after scoring are explicit states. No interpolating across halftime to imply a drive. If the user pins a game, stay there until it ends/unpins, but keep other-game scoring alerts in ticker (unless disabled).

## 4. Audio and commentary design

**Audio is a central part of the feel, without using copyrighted broadcast audio.**

MVP layers:
- **Original/licensed game soundtrack bed** (quiet rhythmic instrumental or stadium ambience), looped with clean asset licenses and a single mix bus.
- **Original arcade SFX**: crowd swell, snap tick, catch tap, kick thud, whistle-like *official play stop cue* only when appropriate, turnover stab, touchdown stinger. Do not reintroduce pinball hits, synthetic squeaks, or unrealistic whistles from earlier 3D tests.
- **Event captions**, displayed visually, are required; optional voice narration should be **short and generated from confirmed structured data**, e.g. “Buffalo, touchdown, rushing play, nine yards.” No scraped announcer quote recycling or invented analysis. A future TTS voice is optional, with voice and pronunciation QA; do not impersonate actual announcers.
- **One audio director**: deduped event IDs, priority, fade/duck music around score call, audio switches only after actual source event confirmed, no overlapping simultaneous teams/streams.
- **Muted by default**. A user tap on **Sound on** enables the AudioContext; detect blocked autoplay and show “Tap to enable sound.” Show master mute/volume and captions always. Respect reduced motion, silent mode, background tabs, and preference. See [MDN autoplay guidance](https://developer.mozilla.org/en-US/docs/Web/Media/Guides/Autoplay).
- Optional **licensed third-party audio embed** is a distinct later feature; [existing sports-audio research](../../sports-audio-broadcasts.md) documents TuneIn/iHeart embedded-player rights/latency. Do **not** extract/rebroadcast station streams, stitch live copyrighted calls into a Red Zone montage, or imply exact synchronization.
- Never play a touchdown cue twice due to re-poll/reconnect; corrections may show a visual correction rather than re-sounding a horn.

## 5. Rendering and application architecture

### Suggested modules (names are proposed, not current code)

- `ObservedNflPbpAdapter`: publisher/raw PBP -> validated typed state + provenance ledger.
- `NflPixelChannelService`: snapshot + cursor updates, broadcaster independent of viewer count.
- `RedZoneDirector`: deterministic multi-game selection and event priority (pure function).
- `PixelFieldRenderer`: scalable canvas/PIXI or lightweight sprite engine, fixed virtual resolution (example 480×270); crisp nearest-neighbor rendering at integer zoom where possible, responsive letterboxing not stretching.
- `PixelEventAnimator`: semantic animations from **confirmed** after-state; does not solve physics.
- `PixelChannelAudio`: optional user-initiated audio bus for original music and SFX.
- `WarRoomTV` entry point and `/nfl/pixel-red-zone` fullscreen route with one reusable player component.
- `ReplayFixtureRunner`: feeds historical frozen events at accelerated time for deterministic QA; explicitly labeled REPLAY.

Render at 16:9 on large screens and letterbox on phones with a deliberate mobile HUD, rather than distorting the art or hiding controls. Prefer simple WebGL/canvas if it saves DOM work, but supply an accessible textual play list. Target ordinary mobile performance with a fixed rendering budget and no constant 60fps when tab is backgrounded. No need to fetch roster photos, external team logos or player sprites for v1.

## 6. Proposed staged implementation (no production write/deploy)

| Gate | Deliverable | Required evidence |
| --- | --- | --- |
| **R0 source audit** | Data manifest & 5–10 immutable real observed game fixtures; measured score/PBP coverage and latency | Stable IDs, possession/spot/score provenance; explicit unavailable cohorts |
| **R1 single-game historical channel** | Pixel field + score/HUD + event stepping + sourced captions | Exact final score, event ordering, corrections, TD + try semantics; no invented tracking |
| **R2 always-on multi-game director** | Automated priority queue, red-zone spot, scoreboard grid, user pin + no-game fallback | Deterministic replay of simultaneous games, bounded churn, event dedupe |
| **R3 audio & room-TV integration** | Original soundtrack/SFX, sound controls, TV-to-expanded view, safe mobile UX | Sound starts only via user interaction; captions, cleanup, focus/fullscreen fallback |
| **R4 live pilot** | Measured live adapter, bounded refresh, freshness UI and auto-cut | Recorded live Sunday with source lag/stale/disconnect report; no false event claims |
| **R5 archive + arcade link** | Replayable highlight/challenge link for qualifying verified plays | Exact source-event hash and version, both consumers agree on same real event |

**Recommended first demo:** one verified historical game with a touchdown, PAT, turnover and FG; minimal pixel field + audio cues. Then expand to the director with concurrent game fixtures. Do not attempt a full 2026 Sunday or “live” claim as the first animation test.

## 7. Acceptance tests to write before implementation

1. `redzone_requires_verified_play_identity`: missing ID/duplicate must not produce two events or a fake animation.
2. `redzone_missing_spot_remains_unknown`: play text or stale score cannot create a ball spot or red-zone alert.
3. `redzone_offense_orientation`: correct side/yardline across possession flips and Q1/Q2 Q3/Q4 boundary; no guessed direction.
4. `redzone_td_requires_confirmed_result`: review/pending score doesn't play TD horn; correction retracts display; PAT separately scored.
5. `redzone_no_duplicate_td_after_reconnect`: event ID + revision + audio cue deduped after polling/reconnect.
6. `redzone_two_game_director_priority`: verified TD interrupts appropriately, red-zone spot ordering correct, tie-break deterministic.
7. `redzone_user_pin_dwell`: pinned game is stable and exceptions explicitly controlled; auto-cut obeys minimum dwell.
8. `redzone_event_sequence_rewind_guard`: out-of-order events don't move the field backward silently.
9. `redzone_live_stale_and_no_games`: no fake live badge; data age visible; off-air/replay labeled.
10. `redzone_exact_score_reconciliation`: source score, updates and final snapshot agree including 2pt/safety.
11. `redzone_audio_gesture_and_cleanup`: mute default, blocked sound fallback, no overlapping audio on switching, stops on unmount.
12. `redzone_fullscreen_route_back`: TV -> overlay -> expanded -> back preserves focus and navigation, gracefully handles fullscreen denial.
13. `redzone_mobile_accessible`: responsive 390px, captions/keyboard/touch, reduced motion and no stretched pixels.
14. `redzone_no_live_simulation_contamination`: synthetic Gridiron fixtures can only render in obvious demo/replay mode, not as observed play.
15. `redzone_latency_and_poll_budget`: bounded requests by game/viewer; no uncontrolled upstream fanout.
16. `redzone_event_shared_with_arcade`: same immutable observed `game_id + play_id + source_revision` resolves into [mini-game spec](ARCADE-TRAINING-MINIGAMES-SPEC-2026-11-01.md) without modifying authoritative PBP.

### Launch blockers

No credible observed PBP spot/possession coverage -> **ship a truthful scoreboard + scoring-events-only channel** until upgraded. No reliable source-event IDs -> no “live” animated play sequence. No allowed music/SFX -> silent channel with captions. No verified attribution -> no purported NFL RedZone affiliation. Never fix coverage by generating imagined football.

## 8. Dependencies, sources, and review decisions

- Repo: [NFL game play-by-play adapter](../../../backend/routers/games/game_detail.py), [PBP component/types](../../../components/Game/PlayByPlay.tsx), [scoreboard read path](../../../backend/routers/games/scoreboard.py), draft [TV/HQ PR #29](https://github.com/micahp/legendarypicks/pull/29).
- Rules: [LP 2026 observed-vs-simulated game-state reference](../../rules/NFL-2026-GAME-STATE-RULES.md); actual published source always controls observed outcome.
- Audio context: [sports broadcast audio research](../../sports-audio-broadcasts.md), [MDN Autoplay](https://developer.mozilla.org/en-US/docs/Web/Media/Guides/Autoplay).
- Art: original, consistent pixel sprites/tiles, avoid real-player likenesses and NFL/RedZone marks without legal clearance.
- Decide by R0: source-event contract eligibility, actual publisher lag distribution, refresh mechanism, live feed usage terms, no-games UX, and whether TTS is needed for v1.

**All screen labels, JSON fixtures, candidate durations and module names are proposals, not current repo behavior. No code/data/deployment changes are authorized by this document.**
