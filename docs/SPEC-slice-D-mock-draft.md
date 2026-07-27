# SPEC: Slice D — single-player mock draft vs. ADP bots

Status: **specified 2026-07-27, not yet built.** Ships in **v0.7.0** with slice A
(`SPEC-accounts-and-mock-draft.md` §6), **ungated**. Depends on slice A being in first: a
completed draft must save against `device_id` on the server so slice B's claim-on-sign-in
picks it up.

Parent spec: `SPEC-accounts-and-mock-draft.md` §3. Both scope decisions there are already
made — **solo vs. bots**, and **12×15 snake, QB/RB/WR/TE/K + FLEX, no D/ST, no IDP**. This
file is the build-level detail, plus three things the parent spec's numbers get wrong.

---

## 0. Read this before anything else: the pool does not fit

The parent spec justifies 12×15 with *"only 248 players carry a real ADP against 180 picks."*
Measured against `picks.dev.db` on 2026-07-27, that number does not survive contact with the
position filter.

`nfl_adp` season 2026, `active=1`, ADP below the `169.0` sentinel
(`nfl_offseason.py:43` — ESPN parks unranked players at 170.0):

| position | real ADP |
|---|---|
| WR | 64 |
| RB | 50 |
| QB | 27 |
| TE | 25 |
| PK | 15 |
| **draftable total** | **181** |
| LB / S / DE / CB / DT / P (IDP + punters, not draftable) | 60 |
| all positions | 241 |

**181 draftable players for 180 picks.** The 248 in the parent spec is the all-positions
count, and about a quarter of it is defensive players this format explicitly does not draft.

That margin is not a tight fit, it is a broken draft: the final pick of round 15 is
necessarily the single worst-ranked player in the pool, any position run empties that
position outright, and a bot that needs a kicker in round 14 may find none left. It also
means the board's own "no player left worth taking" state gets hit in every single mock.

**Recommendation — extend the pool past the sentinel, ordered by `percent_owned`.** There
are **551** further active QB/RB/WR/TE/PK players carrying `percent_owned > 0` at sentinel
ADP. Ordering is therefore: real ADP ascending, then `percent_owned` descending, then name.
Cap the pool at **300**, which is 180 picks plus a real waiver-ish tail to choose from.

This is a measurement changing a scope decision, not a scope change for its own sake. If
Micah would rather keep the pool strictly ADP-ranked, the alternative is **12×10** (120
picks), which fits inside 181 with room — but ten rounds is not a fantasy draft anyone
recognises, and the roster in §2 does not fit in it.

---

## 1. The second thing the spec gets wrong: our kickers are `PK`, and they are not on the board

Two separate problems, one root:

1. **The position code is `PK`, not `K`** — and `K` is not empty, which is worse than if it
   were. `players` holds **336** NFL rows at position `K` and **0** of them are active;
   `PK` holds **42**, all active. So `position='K' AND active=1` silently returns nothing,
   and `position='K'` without the active filter returns 336 retired kickers. Filter on `PK`.
2. **The draft board never serves kickers at all.** `_SKILL_POSITIONS` in
   `backend/routers/nfl_offseason.py:80` is `("QB","RB","WR","TE","FB")`, and
   `/api/nfl/draft-board` hard-filters to it. So the mock draft **cannot** source its pool
   from the existing draft-board endpoint without either widening that contract or adding a
   second one.

**Recommendation: a separate `/api/nfl/mock-draft/pool` endpoint**, not a widened
`nfl-draft-board-v2`. The board is a research surface with its own pagination, sort and
search; the pool is one flat ranked list of ~300 with no controls. Widening the board to
include kickers would put PK rows in front of every drafter doing research, which is a
product change nobody asked for. R5 ("see R5 before assuming IDP/K") stays open for the
board and is answered only for the mock draft.

Note also that `FB` is in `_SKILL_POSITIONS` but has **0** players with real ADP. Fullbacks
can be excluded from the pool without losing anyone draftable.

---

## 2. Roster and format

12 teams, 15 rounds, snake, PPR (the only scoring the board computes).

Eight starters, seven bench:

```
QB, RB, RB, WR, WR, TE, FLEX (RB/WR/TE), K, then 7 × BE
```

**Positional need is shown, not enforced** (parent spec §3). A user may draft five tight
ends; the roster panel shows the holes. Bots, by contrast, respect need — see §3.

---

## 3. The bots

Bots pick by ADP with jitter so two mocks are not identical, and they respect roster need
so the draft looks like a draft.

```
candidate score = adp * (1 + jitter),  jitter ~ uniform(-0.10, +0.10)
```

then take the best-scoring player the bot can still roster. A ±10% band on ADP moves a
player about ±3 picks at the top of round 2 and about ±18 at the end — reordering
neighbours without producing an obviously insane pick, which is the failure mode that makes
a mock feel fake.

**Need rules for bots, in order:**

1. Never draft a position it has already filled to its maximum (2 QB, 3 TE, 2 K, 6 RB, 6 WR
   — bench-inclusive ceilings, not starter counts).
2. From round 12 on, if a starting slot is still empty, restrict to positions that fill it.
   Otherwise the 12 bots collectively leave every kicker on the board and the user's results
   screen compares their roster against eleven teams with no kicker.
3. Otherwise, best available by jittered ADP.

**Determinism: seed the RNG per draft and store the seed with it.** A draft that cannot be
replayed cannot be debugged from a bug report, and the seed costs one column.

**Autopick for the user on timeout uses the same function with zero jitter** — best
available that fills a need. A timeout must never be worse than the bots' logic.

---

## 4. Where the draft actually runs

**Recommendation: the draft engine is a pure client-side module; the server persists
state.** Not because it is architecturally purer, but because slice B and multiplayer are
v0.8.0 and the draft window closes ~Aug 22.

- `lib/mockDraft/engine.ts` — pure functions, no React, no fetch: `nextPick(state)`,
  `applyPick(state, playerId)`, `autopick(state)`, `isComplete(state)`. Seeded RNG passed
  in, never `Math.random()` inline.
- The React layer owns the clock and the rendering only.
- The server stores draft state and does not referee it.

Keeping the engine pure and free of DOM/React is the entire hedge: multiplayer in v0.8.0
lifts these functions to Python or a Node worker and makes them authoritative. If the
picking logic is entangled with component state, that becomes a rewrite inside the season.

**Accept that a solo mock is cheatable.** There is no opponent and no prize; a
server-authoritative solo draft would cost per-pick round trips and buy nothing. Say so
here so it is not rediscovered as a bug.

---

## 5. Persistence

Saved against `device_id` from the first pick, not at the end. A draft abandoned in round 9
is still evidence about whether people finish these — which is the entire measurement this
slice exists to take.

```sql
CREATE TABLE IF NOT EXISTS nfl_mock_drafts (
    id          TEXT PRIMARY KEY,      -- uuid, minted client-side at setup
    device_id   TEXT    NOT NULL,
    user_id     INTEGER,               -- NULL until slice B claims it
    season      INTEGER NOT NULL,
    seat        INTEGER NOT NULL,      -- 1..12
    teams       INTEGER NOT NULL DEFAULT 12,
    rounds      INTEGER NOT NULL DEFAULT 15,
    seed        INTEGER NOT NULL,
    status      TEXT    NOT NULL,      -- 'active' | 'complete' | 'abandoned'
    created_at  INTEGER NOT NULL,
    updated_at  INTEGER NOT NULL,
    completed_at INTEGER
);
CREATE TABLE IF NOT EXISTS nfl_mock_draft_picks (
    draft_id   TEXT    NOT NULL,
    pick_no    INTEGER NOT NULL,       -- 1..180, absolute
    team_no    INTEGER NOT NULL,       -- 1..12
    player_id  INTEGER NOT NULL,       -- players.id
    auto       INTEGER NOT NULL DEFAULT 0,
    created_at INTEGER NOT NULL,
    PRIMARY KEY (draft_id, pick_no)
);
CREATE INDEX IF NOT EXISTS idx_mock_drafts_device ON nfl_mock_drafts(device_id, season);
```

Picks are rows, not a JSON blob: the results screen and any future "what did people take at
1.05" question are both `GROUP BY` queries, and a blob makes them a migration.

`user_id` nullable from day one, same reasoning as `SPEC-slice-A-draft-notes.md` §3.2 —
slice B claims with an `UPDATE`, not an `ALTER TABLE`.

**API** (contract `nfl-mock-draft-v1`, snake_case, `X-Device-Id` required on all):

| method | path | purpose |
|---|---|---|
| `GET` | `/api/nfl/mock-draft/pool?season=2026` | the ~300-player ranked pool |
| `POST` | `/api/nfl/mock-draft` | create; body `{season, seat, seed}` → `{id}` |
| `POST` | `/api/nfl/mock-draft/{id}/picks` | append picks; idempotent on `pick_no` |
| `GET` | `/api/nfl/mock-draft/{id}` | resume — draft + picks |
| `GET` | `/api/nfl/mock-drafts` | this device's drafts, for a resume/history list |

Append picks in **batches** — one bot round is 11 picks and does not need 11 requests.
Idempotent on `(draft_id, pick_no)` so a retry after a flaky response cannot double-draft.

A `POST` of picks for a draft whose `device_id` does not match the header is **404**, not
403: a device should not be able to probe which draft ids exist.

---

## 6. UI — designed against `.claude/skills/honest-data-ui`

Load that skill before touching any of this. The rules below are it, applied; where this
section and the skill disagree, the skill wins.

### 6.1 What makes it ours

The differentiator is the parent spec's, and it is the whole reason to build this rather
than send people to an incumbent: **you draft from the availability board.** While on the
clock, the same amber strip that made the board land on a first-time viewer is right there
— you can see the guy you are about to take played 8 of 17.

Reuse, do not rebuild:

- `DraftPlayerRow` (`components/Leagues/NflDraftRoom.tsx:243`) for the pool list.
- `AvailabilityStrip` (`:427`) unchanged — this is the differentiator, it must render
  identically to the board.
- `StatValue` (`:397`) for the stat cells.

If a second player-row renderer appears in this slice, the differentiator has been lost to a
copy-paste and the two will drift.

### 6.2 ⛔ The accent is spoken for. Do not use it for draft chrome.

Signature rule, skill §5: **the one saturated colour on the page marks absence, not
achievement.** A draft room wants to shout in colour at four different things — you're on
the clock, this is your pick, this player was just taken, the timer is low. Every one of
those would collide with the strip and, worse, would train the reader that amber means
"attention" rather than "he wasn't on the field."

- **On the clock / your turn:** weight, position and a rule. Not colour.
- **Your picks in the pick ledger:** a left rule or a fill one step lighter than the card,
  the same two-tone move the app already makes between `ink-900` and `zinc-900`.
- **Drafted / unavailable players:** reduce, don't tint — dim and strike the row.
- **The clock:** tabular figures, and it may change weight under 10s. It may not go red.

### 6.3 ⛔ 24 of the 181 draftable players have no NFL sample, and 15 of them are kickers

This is the defect this section exists to prevent, and it is not hypothetical. Measured on
`picks.dev.db`, of the 181 draftable players with real ADP, **24 have zero rows in
`player_game_logs`** — including **Jeremiyah Love at ADP 17.5**, a first-round pick.

Two different causes that must not be shown the same way:

1. **Rookies** — Love, Carnell Tate, Jordyn Tyson, Makai Lemon, KC Concepcion, Kenyon Sadiq.
   No NFL sample because they have not played an NFL game.
2. **Kickers — we simply do not ingest them.** `player_game_logs` for 2025 holds **one** row
   for **one** kicker against 42 active `PK` players. Cameron Dicker, Jason Myers and
   Ka'imi Fairbairn are established starters, not rookies, and they have no logs.

**Rendered naively, both groups get an availability strip that reads "played 0 of 17."** For
a rookie that is a claim about the player that is false. For Cameron Dicker it is simply
wrong — he played. This is the exact failure the skill bans twice over: rookies read "no NFL
sample," never zero (§4), and absence is a claim about *us*, not the player.

**Required:**

- The pool contract carries the board's existing `sample: 'full' | 'thin' | 'none'`, and
  `none` renders as a neutral **"No NFL sample"** — grey, not accent, and visibly distinct
  from a played-zero-games strip.
- Rookies get **"Rookie — no NFL sample."** The reason is the information.
- Kickers get **"Kicker games not tracked"**, which is a statement about our data, not the
  player. Do not dress it up. If that reads badly next to a kicker we are asking someone to
  draft, the honest fix is to ingest kicker logs, not to hide the gap — file it, don't
  paper over it.
- A dash for no data, never a `0`, and visibly different from one (skill §2).

### 6.4 The results screen

The only part that travels, so it is the part worth getting right — and the part most likely
to launder a conditional average into a projection.

- **The roster, by slot.** Scan-first: slot label, player, position, availability strip. A
  reader should rank their own picks by shape before reading a digit.
- **The availability read, stated as history and not as a forecast.**
  ✅ *"Your 2026 picks missed 34 of a possible 255 games last season."*
  ❌ *"Your roster averages 14.2 of 17 games available"* — present tense, no season named,
  and it reads as a claim about the season being drafted. Skill §4: never label something a
  projection that is not one. The parent spec's phrasing is the wrong one; this supersedes it.
- **The same figure for the 12-team field**, so the number has a comparison rather than
  floating free.
- **Both figures must exclude the no-sample players from the denominator and say how many
  were excluded** — with 24 of 181 carrying no logs, and a kicker on all 12 rosters, a
  silent exclusion changes the headline number. State `n`.
- **Best and worst value vs. ADP**, as *picked at 47, ADP 31* — the two numbers, not a
  computed "value score" that hides its arithmetic.
- **PPR is declared on the surface** (skill §4), not assumed. It is the only scoring the
  board computes and the results are meaningless without it.
- **A durable URL**, because a link is how this gets shared.

### 6.5 Restraint

Rams via the skill: the data is the ornament. No gradients behind numbers, no card shadows
doing a rule's job, no trophy iconography on the results screen. A draft board is closer to
a depth chart than to a poster — the vernacular is roster sheets, box scores and injury
reports, not sports-marketing italics. Tabular figures everywhere numbers stack, consistent
decimals, and the whole page verified by screenshot rather than by the element just edited.

---

## 7. Verification — what "done" means

1. **Complete a full 180-pick draft in the browser** and assert 180 rows in
   `nfl_mock_draft_picks`, no duplicate `player_id` across the draft, every team holding
   exactly 15. Not "the UI looked right" — query SQLite.
2. **The pool never runs dry.** Simulate 200 drafts headless against the engine; assert
   every one completes and that no team finishes with an unfilled *starting* slot. This is
   the direct test of §0 and it must run before the pool size is called settled.
3. **Determinism.** Same seed, same seat, same autopicks → identical pick list. Assert on
   the array, not on a screenshot.
4. **Resume.** Reload mid-draft; the board comes back at the right pick with the right
   rosters.
5. **Device isolation.** A second `X-Device-Id` gets 404 on the first device's draft id.
6. **The no-sample states, on the real 24.** Draft Jeremiyah Love and any kicker, and assert
   neither renders a "0 of 17" strip anywhere — pool row, roster panel, results screen.
   Check the empty and rookie states explicitly; per the skill, that is where dishonesty
   hides. This is a screenshot check by a human, not an assertion on a string.
7. **Headless render, per AGENTS.md §10** — setup, on-the-clock, and results, asserting zero
   `pageerror`s and real data in each. A 200 is not acceptance.
8. **Payload** — measure the pool response and the resume response, and put the numbers in
   the commit message (`docs/DEV-STANDARDS.md`). ~300 players with availability strips is the
   biggest single payload on the site; if it is heavy, trim fields, not players.

Backend tests: `backend/test_nfl_mock_draft.py`, `LP_DB_PATH` pointed at a `tempfile` before
importing the router (`test_esports_predict_api.py:15`). Engine tests sit with the frontend
under `jest`.

---

## 8. Out of scope

Multiplayer, lobbies, websockets, per-pick timers against real humans (all v0.8.0 with
slice B). Auction. Keeper/dynasty. Trades. Custom scoring, custom team counts, custom roster
shapes. D/ST and IDP — **we have no D/ST entity at all**. Any gate or sign-up prompt (slice
C).

---

## 9. Open, needs a decision

1. **The pool fix in §0** — extend past the ADP sentinel with `percent_owned`, or shrink the
   draft. Recommendation is to extend; this is the one item that blocks starting.
2. **Clock length**, and whether the clock even runs in v1. A solo drafter has nobody to
   wait for, so a timer only adds pressure and an autopick path to test. Recommendation:
   ship with a **visible but generous 90s clock**, because the parent spec names autopick as
   minimum scope and because a clock is what makes it feel like a draft.
3. **Where it lives in the UI** — a tab on `/leagues/nfl` beside the draft board, or its own
   route `/mock-draft`. Recommendation: its own route, linked from the board. A draft is a
   full-screen focused task, not a tab you skim.
4. **Do we ingest kicker game logs before shipping, or ship "not tracked"?** §6.3: 42 active
   kickers, one has a 2025 log row. Every mock draft puts a kicker on all 12 rosters, so
   this gap is on every results screen. Ingesting is the honest fix and is an ingest-script
   change, not a product one; shipping the neutral label is the cheap one and is still
   honest. Recommendation: **ship the label for v0.7.0, file the ingest** — the draft window
   is the constraint and a kicker's availability is not why anyone drafts one.
