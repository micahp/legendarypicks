# CONTEXT HANDOFF — 2026-07-15 (part 2: bug fixes, FIFA WC props LIVE, broadcast watcher, NEXT: "From the Booth" UI)

Read first on a fresh context. Supersedes CONTEXT-2026-07-15-HANDOFF.md (that session = team stats; DONE).
This session = bug fixes + WC props Phase 1 shipped to preview + broadcast watcher fired.
**NEXT TASK is scoped in Part B below — start there.**

---
## PART A — what shipped this session

### dev HEAD = `dcdad3a` (clean). Commits (newest first):
- `dcdad3a` Merge feat/wc-props → dev (WC props Phase 1)
- `d4e20a9` wc props: Phase 1 display-only lines on /props
- `1fbdfd6` docs: spec for in-board esports picks
- `a56cbd0` predict: label the Pick Desk as **Esports** (badge + copy)
- `e7489a9` wc: **FIFA World Cup** as the league title (keys unchanged)
- `131bedd` footer: league-agnostic disclaimer (was hardcoded NBA)
- `d12b8d3` standings: fix Win% 0.0% + L10 "0 PTS" (NHL had no winPercent stat → derive from wins/GP; strip ", 0 PTS")

### WC props Phase 1 — LIVE on the preview tunnel (NOT prod)
- Reasonix (DeepSeek) built it, I verified end-to-end. 3 files: `backend/bovada_scraper.py` (soccer
  parse + noise filter), `backend/link_prop_games.py` (`_WC_TEAM_MAP`), `pages/props.tsx` (wc filter,
  display-only). MLB untouched.
- **357 WC props** (goals/assists/shots-on-target/shots) for ARG–ENG scraped into the **dev DB**
  (`backend/data/picks.dev.db`; backed up `picks.dev.db.bak-prewc-20260715T182542Z`; MLB still 51229).
- Rerun scraper: `cd backend && LP_DB_PATH=…/picks.dev.db venv/bin/python bovada_scraper.py wc --ingest`.
- **Live at → https://pride-alternative-costume-act.trycloudflare.com/props → WC filter.**
  Preview = worktree `/root/lp-pick-desk` (feat/pick-desk, FF'd to dcdad3a), frontend :3096 + backend
  :8096 (`LP_DB_PATH=…/picks.dev.db`, log /tmp/pd-backend-8096.log). Backend launch: source
  /root/.hermes/.env then `nohup setsid venv/bin/uvicorn sports_service:app --port 8096 --host 127.0.0.1`.
- Phase 2 (settlement) NOT built. Spec: `docs/SPEC-world-cup-props-2026-07-15.md`.

### Other deliverables
- Esports-board picks SPEC (unbuilt): `docs/SPEC-esports-board-picks-2026-07-15.md` — key insight:
  /esports + /predict already share `/api/esports/upcoming` + matchKey, so in-board picks = frontend
  extraction (a `<MatchPick>` + `useEsportsPicks()` hook), no new backend.
- Worktrees: removed 3 dead (frag-score/hermes/yolo). Live: `/root/lp-pick-desk` (preview),
  `/root/lp-wc-props` (feat/wc-props, merged), `/root/lp-prop-repair` (uncommitted WIP, KEEP).
- **API keys were leaked** into transcripts via a /proc/environ misstep, then **scrubbed** (0 remain).
  STILL RECOMMEND ROTATING PandaScore/YouTube/GRID (in /root/.hermes/.env) — scrub ≠ un-exposed.

### Broadcast watcher — FIRED + documented
- Running now (pid ~1179898) on ARG–ENG: `broadcast_alpha.py run <FOX-stream> 20260715_WC_ARGENG`.
- **Runbook: `prediction-market-trading/docs/RUNBOOK-broadcast-watcher.md`**; memory
  `reference_broadcast_watcher_launch`. Gotcha: use `.venv-ba/bin/python` (py3.11); system py3.8
  faster_whisper is BROKEN. FIFA = hand-launch. Kickoff was 19:00 UTC / 3pm ET. FIRE BEFORE KICKOFF.
- **Signals already writing** → `prediction-market-trading/data/broadcast/20260715_WC_ARGENG_signals.jsonl`
  (e.g. momentum/Messi "silent killer", tactical/England). Shape:
  `{type, subject, quote, direction(bullish/bearish), strength(1-3), ts, tag}`.

---
## PART B — NEXT TASK: "From the Booth" — surface live broadcast signals on the WC game detail

**User's ask:** add a section/tab on the WC **game detail** page for the live broadcast signals (the
whisper-pipeline output). User is unsure (a) separate vs woven into the live game-updates feed, and
(b) whether a general fan would even understand raw "signals". Design it with a fan persona.

### Design decision (done — grounded in the frontend-design skill + persona)
**Persona:** a soccer fan following ARG–ENG — checks score/play-by-play, maybe listening to the FOX
audio (ListenLive is already on the page). NOT a trader; "bullish tape / strength 3" means nothing.
But the signal's `quote` is genuinely great fan content ("Messi's a silent killer…").

**Recommendation:** a **dedicated tab named "From the Booth"** (NOT "Live Signals"/"Tape") that
**co-locates the ListenLive audio player at the top** with a running feed of **quote cards** below.
Rationale:
- **Naming from the user's side** (skill): it's "what the commentators are saying" — universally
  understood. Hide all trader vocab.
- **Co-locating audio + feed = one coherent "booth" surface** (the signature element), which resolves
  the user's "floating separate" discomfort better than a bare signals list, and better than
  interleaving into Play-by-Play (ESPN pbp is real-time; transcribed insight lags ~60s; soccer pbp is
  sparse; mixing muddies provenance). Each surface does ONE job: Play-by-Play = factual events;
  From the Booth = color/insight + listen.
- **Card design:** the QUOTE is the hero (big, readable), a subject chip (Messi / England), a
  match-clock timestamp, and an **INFORMATIVE TAG** — a plain-language chip naming what the moment
  IS. The tag is the *what*, the quote is the *why/color*. **NO trader vocab** ("bullish/strength 3");
  fan language only.
  - **Tag taxonomy (two kinds):**
    - *Event tags* (factual, unambiguous — anchor the timeline): **Goal · Penalty awarded · VAR review
      · Red card · Yellow card · Substitution · Big chance · Injury stoppage · Kickoff/HT/FT.**
    - *Read tags* (insight from the commentary): **Momentum: [Team]** (a directional chip in fan terms
      — "England pushing", NOT "bullish ENG") **· Tactical shift · In form / struggling · Fitness
      concern · Pressure building.**
  - **Why VAR/penalty tags matter to the thesis:** during a VAR review the scoreboard hasn't changed
    but the broadcast+crowd are electric — a "VAR review — goal under review" card is the purest
    example of "the booth tells you what the scoreboard doesn't." High-value, totally understandable.
  - **Tag SOURCE = hybrid (decision #8 below):** *event* tags are far more reliable from the ESPN
    play-by-play feed the page ALREADY fetches (goal/pen/card/sub/VAR) than from ASR — merge those as
    anchor cards; *read* tags + quotes come from the whisper extractor. One unified, tagged timeline.
    Requires: extend the DeepSeek extractor prompt to emit a fan-facing tag + momentum-side (or map
    its current `type`/`direction` → these tags in the endpoint).
- **Empty/pre-game state** (invitation, not mood): "Nothing from the booth yet — insights appear as
  the broadcast calls the game."
- Filter to fan-relevant types (momentum/tactical/injury/lineup), strength ≥ 2, newest first.

### Build plan
**Backend** — new `GET /api/wc/{gameId}/booth`:
- Resolve gameId (ESPN WC event id) → broadcast tag `<YYYYMMDD>_WC_<AWAY><HOME>` via team abbrevs
  (reuse `_WC_TEAM_MAP` from link_prop_games.py) + the game's date.
- Read `/root/prediction-market-trading/data/broadcast/<tag>_signals.jsonl` (cross-repo file read —
  simplest; note the coupling), filter + shape cards, return newest N.
**Frontend** (`pages/game/[league]/[gameId].tsx` + `components/Game/`):
- `Tab` type is `'boxscore'|'playbyplay'|'info'` (components/Game/types.ts:40); add `'booth'`,
  WC-gated, to `TAB_DEFS` (gameId page:19). WC already has `hasGameTabs` + `usesPerTabEndpoints`.
- Add a fetch branch in `useTabData` (gameId page ~178) for the booth endpoint.
- New `<BoothFeed>` component: ListenLive at top + quote cards. Move/duplicate ListenLive here.

### Open decisions for the user (ask before building)
1. Tab name: **"From the Booth"** (rec) vs "Commentary" vs "Mic'd Up".
2. Dedicated tab (rec) vs interleave into Play-by-Play.
3. Show the subtle momentum cue at all, or pure quotes only (max understandability)?
4. Backend: direct cross-repo jsonl read (rec, fast) vs sync signals into LP data dir.
5. Signal types + strength threshold to surface.
6. Pre-game: enrich the existing game summary in place, or a pre-game state of the Booth tab (or both)?
7. Do the 30-min competitive scan first (is anyone public doing broadcast-audio→insight)?
8. Tag source: hybrid (ESPN pbp for event tags + extractor for read tags) vs extractor-only? And
   extend the extractor prompt to emit fan tags/momentum-side, or map its existing fields in the API?

### STRATEGIC FRAME (user, 2026-07-15) — treat this as the flagship, not a toy
This game-detail surface is the **prototype/POC of what may be LP's most compelling SELLABLE
feature.** Design + build it to that bar. The thesis:
- **The product = the broadcast, structured.** A Whisper pipeline turns live human commentary into
  timestamped, typed insight (lineups, momentum, tactical, injuries) — the class of "why" no
  box-score/data feed carries. That's the differentiator.
- **Plausible novelty / moat (VALIDATE, don't assert):** I'm not aware of a public consumer product
  doing live-broadcast-audio → structured insight. Adjacent players are different: Stats
  Perform / Sportradar sell EVENT data; "AI commentary" tools GENERATE speech. The reverse — ingest
  real commentary → extract soft signals as a user-facing feature — appears unseen publicly (user
  suspects others may keep it internal). **TODO: a 30-min competitive scan before over-investing**
  (per the "recon-before-building" lesson). Moat compounds via the labeled corpus ("booth said X →
  outcome Y") accumulated over games.
- **Scaling story (cheap):** audio streams are free/cheap and Whisper runs on our box, so this
  generalizes to any broadcast we can capture — every sport, not just WC. The WC game is just the POC.
- **Monetization may be an API (fits LP Phase-2 prop-outcome data-API thesis) — but build the UI
  FIRST regardless.** User: "I'm not gonna test an API by looking at JSON responses." The
  game-detail surface is the **evaluation + demo harness for the underlying insight API**: it's how
  WE judge signal quality (good insight vs noise, at a glance) and how a BUYER is sold (a live demo,
  not a schema). So the backend endpoint IS the nascent API; the UI is its shop window + QA lens.
  **Design requirement that follows:** make signal QUALITY legible in the UI — surface enough
  (quote + subject + time + a quiet confidence/momentum cue) that a viewer can immediately tell a
  sharp read from filler. If the UI makes quality obvious, the API is demoable and sellable.

### COMPETITIVE SCAN RESULT (2026-07-15, DONE — resolves decision #7)
**Sanity check confirmed:** data APIs (Sportradar/Genius/Stats Perform) are populated by OBSERVING the
event at the source — a global network of in-venue **human scouts** (~100 events/soccer match) +
increasingly **computer-vision** camera tracking (thousands of quantitative points). Incumbents are
shifting scouts → CV. So "watching the source" is real; for tier-1 it's now a camera, not a person.

**Verdict — genuine whitespace, but be precise about WHERE (and the tech is NOT the moat):**
- CROWDED / solved (don't compete): (1) commentary GENERATION, data→AI speech (WSC Sport, Resemble,
  ElevenLabs, camb.ai, Stats Perform AI previews) = the OPPOSITE of us; (2) event-extraction from
  commentary → stats/live-ticker (academic: arxiv 2307.10303, GPT-4+Whisper tickers) — redundant with
  existing event APIs, reinforces "get events from ESPN pbp, not ASR"; (3) captioning (Omniscien);
  (4) fan/CROWD-sentiment momentum (Genius "Engage", Polymarket×UFC Fan Prediction Scoreboard,
  Polymarket×MLS) — different SOURCE (crowd/betting, not the broadcast).
- WHITESPACE (found NO commercial product): extracting the **soft/qualitative layer from the live
  BROADCAST commentary** — the professional's momentum read, tactical color, fitness/body-language,
  the VAR-moment electricity — surfaced as a fan feed / API tied to the game. Incumbents capture the
  WHAT (events + tracking, via camera); nobody productizes the WHY that lives only in the commentary.
- Honest read: not "kept secret" so much as **unbuilt commercially** (incumbents chase CV/quantitative
  data-rights; soft color is a fan-engagement/content play, not a data-rights play). Opportunity for a
  scene-native small player, NOT a defended fortress.
- **Positioning line:** *"They capture the WHAT — events + tracking, increasingly by camera. We capture
  the WHY — the broadcast's live read a camera can't see and nobody productizes."*
- **Moat reality-check:** thin technically (Whisper+LLM = commodity). Defensibility must come from
  (a) framing/UX that makes soft signal legible+trustworthy, (b) the labeled corpus (booth-said-X →
  outcome-Y) compounding over games, (c) scene-native distribution (geoppls), (d) breadth of cheap
  broadcast coverage. **Validate DEMAND before over-investing — the tech isn't the moat.**

### NEXT-NEXT FEATURE (user, 2026-07-15) — "Narrative vs. Data" divergence layer (the EV play)
The context panel (shipped) is the INGREDIENTS. The feature we don't have yet: **auto-detect where the
booth's narrative DISAGREES with the data/market, and surface those divergences as directional
micro-trends** — that's the "helps us know what's gonna happen" / positive-EV layer, not just showing
quotes. For each booth claim, check vs live data (possession, shots, xG when available, the market
line): when they diverge, flag "booth says X, data says Y, lean Z."
- **Two divergence directions:** (1) data contradicts the pre-game script (run of play rewrites the
  prior); (2) booth sees something before the data/market shows it (a soft lead).
- **ARG–ENG worked example (23', 0-0):** pre-game script = "England dominate, ARG sit deep & counter";
  DATA inverted it — ARG 57% possession, out-passing ENG 142-105, ENG collapsed to 42%; the booth then
  REVISED to match ("Messi's influence growing") → lean ARG/Messi before the market reprices (caveat:
  0 shots, control≠chances). Secondary: "England tired" now CONVERGING w/ data (watch a 60'+ fade);
  "street fight" vs a cagey 0-shot game → base-rate tilts draw/pens (COL–SUI pattern).
- **NON-NEGOTIABLE / honest:** LOG every divergence → outcome (labeled corpus) to learn WHICH patterns
  actually predict. Our own corpus already showed raw tape leads price only 36% — so divergences are
  TRACKED HYPOTHESES, not asserted edges, until the corpus proves them. That corpus is also the moat.

### The surface is a MATCH-LIFECYCLE narrative (not only a live feed)
User add: *everything said BEFORE kickoff should improve the game summary we already have.* So the
booth pipeline feeds TWO things, one coherent story across the match lifecycle:
1. **PRE-GAME → enrich the existing game summary/preview.** Fold pre-match booth insight (confirmed
   lineups, tactical preview, injury/fitness, storylines) into the WC detail summary so our preview
   beats a generic ESPN one. The pre-game signals are ALREADY being captured (the watcher runs from
   pre-game). Don't silo them — the summary is the pre-game view of "From the Booth."
2. **LIVE → the "From the Booth" feed** (quote cards, as designed above).
3. (Later) **POST-GAME → a recap timeline** of the key booth moments.
So "From the Booth" = the running broadcast narrative; the game summary is its pre-game head.

### Token-saving note (user's framing)
The design thinking above is DONE — next session should confirm the 5 decisions and build, not
re-derive. Real signals are already in the jsonl (use them, don't mock).

### Running processes / cleanup state
- Preview: :3096 frontend + :8096 backend (KEEP). Prod: :3100/:8100 (untouched). Throwaway
  :8097/:3097 test servers TORN DOWN.
- Watcher pid ~1179898 still transcribing ARG–ENG (will stop at stream end / ~240min cap).

---
## PART C — SHIPPED 2026-07-15: WC game-context / "From the Booth" / prop-tied Read (LIVE on tunnel)
The Part B design got BUILT this session on the WC game detail (`/game/wc/760515` = ARG–ENG POC).
**Live on the preview tunnel; dev HEAD `6945e06`; NOT on prod.**

**What's live:**
1. **Game Context panel** (`components/Game/WCContext.tsx`) replaces the AI story (`GameStory`) on WC
   detail — leads with **"The Read"**, then form + most-likely-goalscorer per team.
2. **"The Read"** = DeepSeek (`deepseek-chat`) synthesis of the booth reads + ESPN data + Bovada props
   into 3-4 **takeaway-first** intel lines. Each line can carry a **prop chip**: `{player, market,
   line, lean}` where lean ∈ back/fade/watch (green/red/zinc). This is the **bettor's-co-pilot**
   vision: booth (why) + data (ground truth) + Bovada prop (the bet).
3. **"From the Booth" tab** (`components/Game/BoothFeed.tsx`) — WC-only tab: ListenLive audio + full
   timeline of tagged reads, refresh 30s. Raw quotes = the receipts.
4. **Backend** `GET /api/wc/{gameId}/context?limit=N` (`backend/wc_context.py`, route in
   `routers/games.py`). Returns `{headline,status,teams(+form),top_scorers,read[],insights[]}`.
   Reads the broadcast signals jsonl cross-repo (`LP_BROADCAST_DIR`), the WC props DB, ESPN summary.

**ACCURACY GUARDS (hard-won from the Gordon episode — do not weaken):**
- **Match facts (score, scorer, subs, cards, who started) come ONLY from ESPN `keyEvents`/rosters** —
  never the transcript. The extractor emits soft signals only and MISSES goals; events must come from
  ESPN. (We missed the Gordon goal because it was transcribed but never a signal.)
- **Full-sentence context / timeframe:** commentary mixes live action with background/history in one
  breath. Never promote a historical phrase to a live fact. (I told the user "Gordon came off the
  bench" — the booth meant his role in PRIOR rounds; he STARTED today. The team sheet wins.)
- **Per-team stats are labeled explicitly** in the synthesis prompt (name+home/away+numbers together)
  to stop home/away mixups (a read once gave Argentina England's possession %).
- Names normalized to the match roster (fuzzy last-name); insights de-duped on the quote.

**Commits (dev):** `a5e6a17` context+panel → `3a0f2ea` booth tab → `4be8383` name-norm/dedup →
`c782b39` The Read synthesis → `9649077` prop-tie+data-authoritative → `6945e06` per-team stat labels.

**Divergence corpus:** `prediction-market-trading/data/broadcast/divergence_corpus.jsonl` — first
entries logged this session (Gordon narrative→outcome = HIT; live prop leans = pending, grade at FT).
The whole thesis needs this corpus to prove divergence beats base-rate (tape alone was only 36%).

**Remaining polish / next:** (1) give From-the-Booth cards mini-insight headlines too (user asked,
not yet done); (2) grade the corpus at FT + accumulate across games; (3) expand prop board beyond
anytime-scorer (shots-on-target/assists); (4) generalize past this one POC game; (5) the espn_event_id
on WC prop_games is empty — game→tag currently maps via teams+date.

### EVENING UPDATE — Codex takeover, corpus graded, DISCOUNT PLAY shipped (dev HEAD `fb1b4fa`, clean)
**Codex drove for a stretch (all on dev; prod untouched):** `941b4d5` copied The Read into the Booth
tab → `437a83b` moved player props into their own **Props tab** (Tab type now includes `'props'`) →
`d878ccf` gave all 40 Booth cards individualized headline + analysis + only-OPTIONAL grounded player
props (`_enrich_insights`) → `f268d21` scoped WC props by ESPN event id + a 15-min Bovada refresh/link
timer. Codex also tried `7c1a7e1` (heavy generic market-opportunity engine: new `wc_market_quotes`
table + Bovada 3-way scraper + live_discounts) — user said UNDO → `b124768` fully reverted it.
**DO NOT re-apply 7c1a7e1 — design simple.**
- **Infra running (Codex):** `broadcast-alpha-wc.service` (systemd auto `watch-wc`: opens FOX audio
  ~45min pre-kickoff, derives tag from ESPN) + `legendarypicks-wc-props.timer` (15-min Bovada refresh).
  Booth watcher runbook: `prediction-market-trading/docs/RUNBOOK-broadcast-watcher.md`.
- **User hard rule:** READ every changed file IN FULL before editing.

**ARG–ENG FINAL 2–1** (Gordon 55'; Enzo 85' [Messi assist]; Lautaro 90'+2' [Messi assist]).
**Corpus graded** (`divergence_corpus.jsonl`): Gordon narrative→outcome = **HIT** (genuinely
foreshadowed); Kane fade +150 = **HIT**; Messi back +150 = **MISS** (0G/2A). Enzo +800 "watch" scored
but = **COINCIDENCE, not credited** — no signal foreshadowed it (the honesty check that matters; I
overclaimed "the intel called it" and the user caught it → [[feedback_no_assumptions_first_principles]]).
Net: 1 genuine signal-driven tell (Gordon); prop leans 1–1; the comeback (Enzo/Lautaro) was NOT called.

**DISCOUNT PLAY shipped (`fb1b4fa`, wc_context.py ONLY — minimal, no over-build):** The Read no longer
FORCES a prop. Each line MAY carry an optional **play** = a DISCOUNT: a market-priced-unlikely outcome
the booth's NEW INFO makes more likely than the line implies (the market underweights the info). A play
is **player** (to score), **team** (to win/Draw), or **none** (default; most lines). Team odds come
FREE from ESPN `pickcenter` moneyline (no table/scraper — the anti-`7c1a7e1`). **Player props KEPT**
(additive — removing them is why 7c1a7e1 was reverted). Grounding: a play may name a signal-subject
player OR one of the two teams/Draw. Philosophy = the trading bot's value-discount: confluence of a
real market discount + a structural booth signal; NOT favorites, NOT price-extreme, skip value traps
([[feedback_buy_only_value_discounts]]). Frontend UNCHANGED — the chip reuses `{player,market,line,lean}`
so a team play renders "Argentina to win +900". **Verified:** ARG-to-win +900 play fires on a
trailing-but-dominating sim; the settled game forces no play. **Real test = the next LIVE WC game**
(auto-captured by the service).

**Current dev HEAD `fb1b4fa`, clean. Preview `/root/lp-pick-desk` :3096/:8096. Prod untouched.**
**Next:** (a) surface the play's rationale on the chip; (b) accumulate the corpus across live games (the
real validation); (c) expand player markets (SoT/assists); (d) note ESPN `pickcenter` moneyline may be a
PRE-MATCH snapshot (not live) — a live 3-way line source would sharpen team plays.
