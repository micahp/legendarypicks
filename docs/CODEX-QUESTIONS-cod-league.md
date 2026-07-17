# Codex questions — CoD league page

## Blocking Phase 1 questions from the real API response — 2026-07-16

1. **How should a finished match with no resolvable stream key appear in “Today on the stream”?** The real `/api/esports/upcoming` response currently includes finished CoD match `Paris Gentle Mates vs Toronto KOI`, but its `watch` value is only `{ platform: "web", url: "https://www.youtube.com/@CODLeague/live", channel: null, embedUrl: null }`. The existing `streamKeyOf` therefore returns `null`. The section specification explicitly includes a `Final` state chip, so should this match be omitted from the stream running order, rendered in a separate ungrouped block, or associated with the active CDL YouTube stream by some provided field?

2. **What exact minimum makes the derived standings meaningful enough to show?** The real CoD slate currently has one finished match. Please specify the minimum number of finished matches (or minimum team coverage) required by “If the slate has too few finished matches to be meaningful, hide the section.”

3. **What exact `/predict` URL should the CoD CTA use?** The current `pages/predict.tsx` does not read a query parameter or URL hash and has no CoD anchor, while this task forbids editing that page. Should Phase 1 link to plain `/predict`, use a specified inert query/hash for future support, or wait until `/predict` supports a real CoD filter?

No implementation files were edited before stopping on these questions.

---

## ANSWERS — 2026-07-16 (resume /cod Phase 1 with these)

**Root cause of all three:** a finished match's `watch` degrades to a bare web link
(`@CODLeague/live`), so it loses its stream key and can't be grouped onto its broadcast. The backend
is being fixed to emit a **stable `streamKey` + `eventId` that survive finishing** (from the PandaScore
`streams_list` raw_url and `serie.id`, both of which persist on past matches). Build against these
fields; they are additive and null-safe.

### A1 — finished match with no derivable stream key
Group it into "Today on the stream" running order by the new backend **`streamKey`** field (NOT by
`watch`, which is gone once finished), and render it with the `Final` chip in place — same stream, in
sequence. **Never** associate a finished match to a stream by title/league string: the league string
is unstable across a match's life (`"Cdl Championship"` scheduled → `"Call of Duty League —
Championship 2026 (Playoffs)"` finished) and a title-only guess could grab a *Challengers* final.
**Fallback (streamKey still null):** render it in a separate, ungrouped "Results" list below the
stream — do not guess it onto a broadcast.

### A2 — minimum finished matches for derived standings
Show derived standings only when the finished set is meaningful:
**≥ 3 finished matches AND ≥ 4 distinct teams with a result.** Below that, hide the section.
(Current slate = 1 finished match → hidden.) Rationale: a "standings" table built from one result is
noise; ~half a bracket having played is the floor for it to read as real.

### A3 — /predict CTA URL
Link to **`/predict?title=cod`** — an inert, forward-compatible query param. `pages/predict.tsx`
ignores the query string today, so it degrades to plain `/predict` now; when a title filter is added it
will filter on the match `title` field (`"Call of Duty"`), and `cod` is the slug that maps to it. Do
**not** edit `predict.tsx`.

**Resume:** once the backend `streamKey`/`eventId` fields land (in progress, same session), build
Phase 1 grouping on `streamKey`. No other blockers.

---

## PHASE 1 VERIFICATION — 2026-07-16

- Per the user's instruction, **no production build was run**. Next's development server compiled
  the client and server successfully, including `/cod`, with `API_PROXY_TARGET` set to the fixed
  preview backend at `http://127.0.0.1:8096`.
- Verified through the development tunnel at
  `https://directed-alot-deliver-rows.trycloudflare.com/cod`; navigation returned HTTP 200 and the
  rendered document title was `Call of Duty League — Legendary Picks`.
- The tunneled `/api/esports/upcoming` response returned four real `title === "Call of Duty"`
  matches: one live, two finished, and one scheduled. All four carried
  `streamKey: "twitch:callofduty"` and `eventId: 9881`.
- The rendered page had one featured live card and mounted the real YouTube embed for FaZe Vegas vs
  G2 Minnesota. In the headless verification browser, YouTube displayed its sign-in/bot challenge
  inside the iframe; the page and embed source itself loaded without a page error.
- "Today on the stream" rendered one `twitch:callofduty` group with all four games ordered by
  `startTime`: Paris Gentle Mates vs Toronto KOI (Final), Los Angeles Thieves vs Riyadh Falcons
  (Final), FaZe Vegas vs G2 Minnesota (Live), then OpTic Texas vs Miami Heretics (Scheduled).
- "Results" rendered the two finished games most-recent first: Los Angeles Thieves vs Riyadh
  Falcons, then Paris Gentle Mates vs Toronto KOI, with final scores and winner/loser emphasis.
- "Championship — results so far" was correctly hidden because the real slate had only two finished
  matches, below the specified minimum of three finished matches and four distinct teams.
- The "Make a CoD pick" CTA resolved to exactly `/predict?title=cod`.
- The browser check reported no console errors and no uncaught page errors.
- Repeated the rendered-page check at a 390px mobile viewport; all sections and the same four real
  matches rendered, and the document width remained 390px (no horizontal overflow).

**Assumptions forced:** none. Phase 1 uses the supplied exact title filter, backend `streamKey`, the
specified standings threshold, and the specified `/predict?title=cod` target.
