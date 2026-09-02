# Product A & B — what's needed for a finished iOS build

Status: planning note, not a committed roadmap. Companion to
`COMPETITIVE-ANALYSIS-playerx-2026-07-21.md`. Covers the two products chosen on 2026-07-21
(props-vs-projections, and fantasy scoped to esports/streamable sports), their competitors, what LP
already has in the codebase today, and the concrete feature gap + iOS path for each. Competitor
feature claims are from general knowledge, not a live check today — marked **[unverified]** where
I'm not stating something I can confirm from this repo or a source you gave me. Verify before betting
real build time on a claim about what a competitor does or doesn't have.

---

## Product A — Historical props vs. projections

### What it is
Browse upcoming player props, see LP's model projection next to the market line, see how similar
props have historically hit. Consumer research tool, data-dense, no video.

### Known competitors **[unverified — general knowledge, confirm before scoping around any of these]**
- **Outlier.bet** — prop research + EV/edge display + historical trends. Probably the closest
  positioning match to Product A.
- **OddsJam, Props.Cash** — line-shopping and EV tools across sportsbooks.
- **Underdog Fantasy / PrizePicks research companions** — informal research layers around pick'em
  products, not standalone apps.
- **FantasyPros** — projections-vs-actual tracking, longer-established, traditional sports only.

None of these are confirmed to have LP's specific angle (a data API business alongside the consumer
view). That pairing — sell the data AND show it — may be a real differentiator worth stating
explicitly in App Store copy, but confirm no competitor already does this before leaning on it.

### What LP already has (verified from the current repo)
- `prop_games` / `props` tables, Bovada scraper, per-league + WC ingestion crons already running in
  prod (`legendarypicks-props-prod`, 30min/15min timers).
- `/api/props` router, an existing **Props** tab in the nav.
- `player_game_logs` — 111k logs across MLB/NBA/NFL/NHL (per prior session work).
- A two-layer projections model (Bovada-only for MLB, player-stats-based for other leagues) and a
  Model tab.
- Per prior notes: calibration works, but **EV is currently all-zero and CLV is empty** — the
  edge-detection math that would make this genuinely useful isn't finished.

### Feature gap to a finished consumer app
- [ ] **Grading/settlement pipeline** — persist the actual outcome against the locked line so
      "historical hit rate" is a real, queryable number, not a claim.
- [ ] **Fix EV calculation** — currently broken (all-zero). This is the number a user actually wants.
- [ ] **Historical accuracy UI** — hit-rate trend per player/market (sparkline or similar), not just
      today's line.
- [ ] **Search/filter/watchlist** — by player, team, market type.
- [ ] **Auth** — none exists today; required if watchlists persist across sessions/devices.
- [ ] **Push notifications** — alert when a tracked prop's projection diverges from the market line.
      New infra: APNs registration + a push-sending path, nothing like this exists yet.
- [ ] **Monetization decision** — free consumer app funded by the B2B data API, or a subscription
      tier in-app (needs Stripe or Apple in-app-purchase, since Apple requires IAP for
      digital-content subscriptions, not external payment links, for App Store apps).

### iOS path
This is the **low-risk one for Capacitor.** No video, no real-time sync requirement — data
tables/cards/charts wrap cleanly in a WebView with no meaningful UX penalty. This should be the
first thing shipped to the App Store if the goal is "prove mobile distribution matters" cheaply.

New work specific to the iOS build itself:
- [ ] Capacitor project scaffold around the existing Next.js frontend.
- [ ] APNs push plugin + backend endpoint to trigger notifications.
- [ ] App icon, screenshots, privacy policy page (required for submission).
- [ ] **Apple review risk**: even a purely informational props/odds app can draw extra scrutiny as
      "gambling-adjacent" — Apple's guidelines require real-money gambling apps to have specific
      licensing; a pure research/data tool with no wagering should be fine, but confirm the App
      Store Review Guidelines section on gambling before submission, since a rejection here costs a
      review cycle (days).

---

## Product B — Fantasy sports (esports / streamable sports only)

### What it is
Fantasy roster-building + scoring, scoped to titles/sports LP can actually embed a live stream for
(the PlayerX-shaped bet, narrowed).

### Known competitors **[unverified — general knowledge, confirm before scoping]**
- **PlayerX (World Champion Fantasy)** — the direct comp from the pasted pitch. Video + live stat
  overlay + title-tuned scoring + gamification + social, Verizon-backed infra.
- **Underdog Fantasy, PrizePicks** — huge scale, pick'em-style (over/under on a stat line), not
  roster fantasy, not stream-integrated.
- **DraftKings/FanDuel** — dominant traditional DFS UX pattern; not esports-native, not
  stream-integrated on-screen.
- Historical esports-fantasy attempts (e.g., Vulcun-era products) — mostly defunct; the category has
  not had a durable breakout winner yet, which is either a warning sign (hard to make work) or an
  opening (nobody's cracked it), and I can't tell you which from here. **[genuinely unverified — this
  needs real market research, not something I can assess]**
- Twitch/YouTube's own on-stream "predictions" — free, built into the platform, real competitive
  pressure on any paid engagement layer sitting next to the same video.

### What LP already has (verified from the current repo)
- **Esports stream resolver** — YouTube-default/Twitch-fallback, team-matched, live-state aware.
  Shipped, tested, this session's memory confirms it works.
- **Esports data**: PandaScore + GRID API integration (match-level data), separate from the ESPN
  client used for traditional sports.
- A simple **pick'em** (predict the winning side) — not roster/scoring fantasy.
- The **WC Booth Intelligence engine** (episode/phase-aware, evidence-grounded commentary synthesis)
  — built for World Cup/soccer, not yet ported to esports titles. **CoD's context endpoint is still
  on the old flat schema** (found this session while auditing `BoothFeed.tsx`) — porting Booth
  Intelligence to esports is real, uncosted work, not a copy-paste.

### The feature gap — this is the big one
Unlike Product A, there is **no existing fantasy-scoring subsystem at all.** This is closer to a new
product than an extension.

- [ ] **Title-specific scoring engine** — needs per-player, per-game live stat granularity (kills,
      assists, objectives, economy, etc.) from PandaScore/GRID, not just match results. **Open
      question, needs a spike**: do these APIs actually expose *live, in-progress* player-level stats
      at low enough latency for real-time scoring, or only post-match summaries? This determines
      whether the whole product is technically feasible on the current data vendors.
- [ ] **Roster/lineup building UI** — draft, salary cap, or however the mechanic is scoped.
- [ ] **Contest/league mechanics** — create/join a contest, leaderboard, scoring updates.
- [ ] **Video-synced live stat overlay** — stats updating next to/on the stream in real time.
- [ ] **Real-money vs. points-only decision** — real-money fantasy sports is state-by-state
      regulated in the US (varies by jurisdiction); a points-only, non-cash model (PlayerX's
      positioning) sidesteps that regulatory surface entirely. This is a decision only you can make,
      not a default I should assume — it changes legal review scope, payment infra, and audience.
- [ ] **Gamification** — avatars, themes; a real engagement lever PlayerX called out explicitly.
- [ ] **Push notifications** — score/event updates during a live match.
- [ ] **Auth + persistent rosters.**

### iOS path — higher risk than Product A
The open question from the competitive-analysis doc still stands: **does a WebView-wrapped video
player hold up for a synced live-stat overlay?** Plain HLS video in a WKWebView is generally fine
(iOS renders it close to natively) — the risk is specifically the *overlay staying in sync* with
low perceived latency while the WebView also runs the rest of the app. This needs a technical spike
before committing to Capacitor for this surface:
- [ ] Build a minimal test: video element + a stat ticker updating every few seconds inside a
      Capacitor WebView on an actual iOS device, measure perceived lag and battery/CPU behavior
      during a real live match.
- [ ] If it holds up: Capacitor path is viable here too, same infra as Product A.
- [ ] If it doesn't: this is the product that would justify a React Native (native video component)
      or full-native build instead — meaningfully more work, only worth it if the spike shows the
      WebView approach genuinely fails.

---

## Sequencing recommendation

Product A is smaller, has no unresolved technical risk, and reuses infrastructure that's already in
prod. Product B has a real open technical question (live per-player esports data granularity) and a
real legal-scope decision (real-money vs. points) before it's even fully scoped, on top of being a
new subsystem rather than an extension.

Ship Product A to iOS first via Capacitor — it validates "does mobile distribution matter" cheaply
and fast, on the product with the least unknowns. Use that as the forcing function to answer
Product B's two open questions (PandaScore/GRID live-data granularity, and real-money-vs-points)
before committing engineering time to the fantasy-scoring engine itself.
