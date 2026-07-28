# SPEC: accounts, with the mock draft as the reason to make one

Written 2026-07-27. Status: **both decisions made 2026-07-27 — Micah agreed to the
recommendation on each. Slices A–D are all unblocked.**

> **"Notes"** throughout this doc means the three marks a user puts on a player from the
> board — their own **rank** number, **watch** (☆), and **fade** (✕). It is the name already
> in the code (`NflDraftNotes`, `lp_nfl_draft_notes`). There is no free-text note field.

Origin: the 2026-07-26 user conversation (see `ROADMAP.md` → *User evidence*). She had no
place to do draft research. The board answers that. This spec is about the next question —
why she'd make an account — and Micah's answer is: **gate a live mock draft behind sign-up,
and nudge toward sign-up at the moments someone is already investing effort.**

---

## 0. The constraint that decides everything else

Today is **2026-07-27**. Real fantasy drafts run **mid-August through Labor Day
(Sept 5–7)**; week 1 opens **Sept 9**. A mock draft is worth nothing after people have
already drafted.

**That is roughly five weeks, and it is the whole scope argument.** Anything in this spec
that cannot land by ~Aug 22 should not be started this season. Accounts are reusable
forever; a mock draft shipped Sept 8 converts nobody until August 2027.

---

## 1. We already have an identity system. Don't build a second one.

`lib/deviceId.ts` mints a UUID into `localStorage` as `lp_device_id` and sends it as the
`X-Device-Id` header. The backend already keys real rows to it:

| surface | storage | keyed by |
|---|---|---|
| UFC picks | `ufc_picks` table | `device_id` |
| Esports pick desk (`/predict`) | server table | `device_id` |
| **NFL draft notes** | **`localStorage` only** | **nothing — never leaves the browser** |

The draft board is the outlier. Its rank/watch/fade live in `lp_nfl_draft_notes` and have no
server row at all.

**So an account is not a new identity — it is a claim over an existing one.** Signing up
should adopt every `device_id` row the browser already owns. That is what makes the nudge
honest: nobody loses work by signing up late, and nobody has to sign up before they know
whether they like the thing.

---

## 2. Sequencing

The order matters more than any individual piece, because getting it wrong orphans the first
cohort's work.

### Phase 0 — put draft notes on the server, keyed by `device_id`. Nothing gated.
`nfl_draft_notes(device_id, player_id, season, rank, watch, fade, updated_at)`, written
through the same `X-Device-Id` header the pick desks use. Keep writing `localStorage` as the
optimistic local copy; the server is the durable one.

Ship this **before** any gating or nudging. It is what turns "sign up to save your work"
from a promise into a fact — the rows already exist, sign-up just puts a name on them. If
gating ships first and claiming ships later, everyone who ranked players in week one loses
it, and they are exactly the users who cared most.

Also fixes R8 on its own: notes now survive a cache clear.

### Phase 1 — accounts.
- **Email magic link.** No passwords: no reset flow, no password storage, no support
  burden, and it is the shortest path from "I want in" to "I'm in".
- On first sign-in, **claim**: every `ufc_picks`, esports pick, and `nfl_draft_notes` row
  carrying this browser's `device_id` gets the user id attached. A device that later signs
  into a second account does not re-claim rows already owned.
- Sessions: httpOnly cookie. `X-Device-Id` keeps working for anonymous users — it is not
  removed, it is the pre-account state.
- Minimum profile: email + a display name. Nothing else until something needs it.

### Phase 2 — the mock draft, gated behind sign-up.

---

## 3. The mock draft

### Decision 1 — **DECIDED 2026-07-27: solo vs. bots for v1.**

Micah said *live* mock draft. Taken literally that means real-time multi-user rooms:
lobbies, matchmaking, websockets, per-pick timers, disconnect handling, autopick on timeout,
and bots to fill seats that never fill. **That is the largest thing this codebase would have
ever built, and it does not fit in five weeks alongside accounts.**

**Recommendation: solo vs. bots for v1.** Not as a compromise — it is genuinely better for
the job it is being hired to do:

- **It is available at 2am with nobody else online.** A lobby that needs 11 other humans is
  empty exactly when a new user first arrives, and an empty lobby converts nobody. Sign-up
  gating only works if the thing behind the gate is *instantly* there.
- No realtime infrastructure, so it can actually ship inside the draft window.
- Bot picks come from `nfl_adp`, which we already have.

Multi-user becomes worth building once v1 proves people finish a mock at all. Design the
draft state so a second human could take a seat later — don't hard-code "seat 1 is you".

### Decision 2 — **SUPERSEDED 2026-07-28: 12×15 snake now includes D/ST.**

Job15 measured the upstream payload and found published ESPN ADP for all 32
D/ST entities. It resolves ESPN's published negative team IDs through the
published `proTeams` map and joins them to the canonical DEF rows. The current
pool contract is 300 players, including all 32 DEF rows, with no null ADP.
Clients must copy those ADPs and must not derive a substitute rank.

The 2026-07-27 decision and measurements below are retained as the historical
record that Job15 corrected:

Measured against `picks.dev.db` today (2026 season):

| | finding |
|---|---|
| Players with a **real** ADP | **248** (the other 1,392 sit at ESPN's 170.0 undrafted sentinel) |
| Kickers | **PK: 15 with real ADP** — covered |
| IDP | LB 22, DE 12, S 11, CB 9, DT 6 with real ADP — ESPN ships IDP prices |
| **D/ST** | **none, at all** — team defenses are not players, so they are not in `players` |
| Depth chart | offense only (QB/RB/WR/TE/FB) — no K, no defense |

Two consequences:

1. **248 ranked players is just barely enough.** A 12-team × 15-round draft is **180 picks**.
   It fits, but with ~68 players of margin, so bots run out of a credible ordering near the
   end and the last rounds will feel thin. Anything larger than 12×15 does not fit at all
   until R3 (daily ADP snapshots) has been running.
2. **There is no D/ST entity.** A standard league drafts one per team — 12 picks we cannot
   currently represent.

**Recommendation: v1 is a 12-team, 15-round snake, QB/RB/WR/TE/K + FLEX, no D/ST, no IDP.**
Say so on the setup screen rather than silently omitting a position people expect to draft.
Adding D/ST later is 32 synthetic rows plus an ADP source we do not have yet — it is a small
job, but it is a *data* job, not a UI one. Note that R5 (`--all-positions`) is **not** a
prerequisite unless IDP leagues are in scope.

### What makes it ours

The mock draft should draft **from the availability board**, not from a generic ADP list.
That is the entire differentiator: while you are on the clock, the same amber strip that
made the board click is right there — you can see that the guy you're about to take played
8 of 17. No other mock draft tool shows you that at the moment of the pick. Reuse
`NflDraftRoom`'s row rendering rather than building a second player list.

### Minimum for it to be worth gating

- Setup: team count (fixed 12 for v1), your seat, scoring (PPR only — it is what the board
  computes).
- Snake order, a visible clock, autopick on timeout using ADP.
- Bots pick by ADP with a small random jitter, so two mocks are not identical.
- Your roster fills visibly as you draft; positional need is shown, not enforced.
- **A results screen at the end** — this is what gets shared, and it is the only part that
  travels. Reuse the availability read: "your roster averaged 14.2 of 17 games available."
- The completed draft is saved to the account. That is the payoff for having signed up.

---

## 4. The sign-up nudges

Micah's ask: when someone types a custom rank, or clicks watch/fade, show a tooltip that
says sign up, with a link.

**Recommendation: let the action succeed, then nudge. Do not block the click.**

Those three actions work anonymously today. Making them require an account is a *regression*
for every current visitor, and it inverts the order that actually persuades: someone who has
ranked twelve players has something to lose and a reason to care. Someone who clicked a star
once has neither, and a wall at that moment reads as a toll booth on a page they were still
deciding about. The board is what made the conversation easy — it should stay the part that
asks nothing.

So:

- **On the action** — a quiet, dismissible inline hint next to the control the first time it
  is used per session: *"Saved on this device. Sign up to keep it →"*. Truthful after Phase 0
  (the row is on the server, tied to the browser, and will be lost if the browser is) and it
  states a fact rather than a demand.
- **At investment** — once someone has, say, 10+ notes, a persistent but non-modal banner
  above the board: *"You've ranked 12 players. They're tied to this browser — sign up and
  they follow you."* This is the high-intent moment.
- **At the gate** — the mock draft is the one place with a real wall, and it should be an
  honest one: *"Mock drafts save to your account. Sign up — it takes an email and nothing
  else."*

Never more than one nudge visible at a time. Dismissal persists.

**Agreed 2026-07-27**: nudge after the action, no hard block on rank/watch/fade. The hard
block stays available as a later change if the nudge under-converts, but it costs the
anonymous browsing that produced the good conversation in the first place.

---

## 5. Out of scope for v1

Leagues with friends, keeper/dynasty, auction drafts, trades, in-season roster management,
password auth, OAuth/social login, mobile app. None of these are needed for the loop
*"research on the board → mock draft it → sign up to keep the result."*

---

## 6. Slices, in order

| # | slice | ships |
|---|---|---|
| A | `nfl_draft_notes` server table + `X-Device-Id` read/write, `localStorage` becomes cache | **v0.7.0** — closes R8 |
| D | Mock draft: setup → snake w/ ADP bots → results screen, **ungated**, saved to `device_id` | **v0.7.0** — the draft-window bet |

**Build-level specs, written 2026-07-27:** `SPEC-slice-A-draft-notes.md` and
`SPEC-slice-D-mock-draft.md`. Slice D's spec **corrects two numbers in §3 of this file** —
the draftable pool is 181, not 248, once IDP and punters are excluded, and our kickers are
`PK` and are not served by the draft board at all. Read it before starting D.
| B | Magic-link auth, session cookie, claim-on-sign-in across all device-keyed surfaces | **v0.8.0** — accounts exist |
| C | Nudges (inline hint, investment banner) + the mock-draft sign-up gate | **v0.8.0** |

**Release split decided 2026-07-27.** v0.7.0 = A + D single-player + the NFL schedule API,
then a prod deploy. v0.8.0 = B + C + **multiplayer** mock draft, and the gate lands with
them. So D ships ungated first: a single-player draft reaches people inside the draft
window, and we learn whether anyone finishes one before charging a sign-up for it.

Because D ships before B, its results **must** be saved against `device_id` on the server
(not `localStorage`), so slice B's claim-on-sign-in picks up completed drafts along with
notes and picks. A mock draft stranded in a browser is the exact mistake slice A exists to
fix.

Both decisions are now made, so **nothing here is blocked**. Order still holds: A before C
(a nudge that says "sign up to keep it" is only true once the rows are on the server), and
B before D (the mock draft saves to an account).
