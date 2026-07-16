# SPEC — Call of Duty League page (`/cod`) — 2026-07-16

Status: **spec / ready to build.** Owner of the build: Codex (scope-locked — see guardrails). CoD is
already on the board and picks (commit `46e7984`); this is the dedicated CDL desk that the esports
product direction (`docs/ESPORTS-PRODUCT-DIRECTION.md`) uses as the flagship model.

## Why
`/esports` is the all-titles watch board. CDL fans (and our pick/value thesis) want ONE focused CDL
home: the live broadcast, today's slate, results/standings, rosters, and picks — with the pieces that
actually move a line (roster changes, form) surfaced. Real receipt for the thesis: on 2026-07-16 the
Whisper booth caught "Falcons made a roster change two weeks ago… let go of one, welcoming a rookie…
filling Pred's shoes… everybody's writing these guys off" while the market had them ~7%; they ran to
~50%. Surfacing that intel is the point of this page.

## Route & data (NO new pipeline)
- **Route:** `pages/cod.tsx` → `/cod`. (Not `/leagues/[league]` — that route is ESPN team-stats, a
  different system; do not touch it.)
- **Data source:** the EXISTING `/api/esports/upcoming`, filtered client-side to `title === "Call of
  Duty"`. Everything the board already emits (state, live, finished, watch, score, winner, favorite,
  prominence, startTime, league) is present. Do NOT add a backend endpoint in Phase 1.

## Phase 1 — build this (all from `/api/esports/upcoming`, CoD-filtered)
Sections top-to-bottom:
1. **Featured broadcast (hero).** Reuse the EXISTING featured-stream behavior from `pages/esports.tsx`
   (`LiveNow` + `LiveCard featured` — the stream-scoped FINAL-in-place + Up Next just shipped on dev
   `274edbb`). Do NOT reimplement it — import/lift the existing components; if they aren't exportable,
   the smallest change is to export them from `esports.tsx` and reuse. Filter the slate to CoD.
2. **Today on the stream.** The CoD matches grouped by their `streamKey` (see `streamKeyOf` in
   `esports.tsx`) and ordered by `startTime` — the running order of the broadcast (live → up next →
   later). Each row: teams + logos, state chip (Live/Final/scheduled), score/winner, favorite %.
3. **Results.** Finished CoD matches, most-recent first (teams, final score, winner bright/loser dim —
   match the board's existing styling).
4. **Standings (derived).** A simple win–loss table computed CLIENT-SIDE from finished CoD matches in
   the slate (group by team, count winners). Label it "Championship — results so far" (not an official
   standings API). If the slate has too few finished matches to be meaningful, hide the section.
5. **Make your pick.** CoD already flows into `/predict`. Phase 1: a labelled link/CTA to `/predict`
   filtered/anchored to CoD (or embed the existing pick component if trivially reusable). Do NOT build
   a new pick ledger — reuse what exists.

### Styling
Match `/esports` and the existing cards EXACTLY (zinc/mono, the same `LiveCard`/`Eyebrow`/`SectionHeader`
components). No new visual language. No decorative dots.

## Phase 2 — rosters + roster-change intel (SPEC ONLY here; do NOT build without sign-off)
The differentiator, but it needs a roster data source that is NOT yet wired — so it is explicitly OUT
of the Phase-1 build to avoid guessing:
- **Teams & rosters:** each CDL org with its current starting four.
- **Recent roster changes (the alpha):** "dropped X · added Y (rookie) · N days ago", surfaced as a
  badge on the team and on its matches. Source candidates to evaluate (do not assume one works —
  verify): PandaScore `/teams/{id}/players` + a diff over time, or the Whisper booth reads, or a
  curated table. Pick after recon; needs its own spec + sign-off.

## Scope guardrails (Codex: obey exactly)
- **Create only:** `pages/cod.tsx` (+ a tiny CoD-filter helper if needed, co-located).
- **You MAY export existing components** from `pages/esports.tsx` (e.g. `LiveNow`, `LiveCard`) to reuse
  them — that is the ONLY permitted edit to `esports.tsx`, and it must be additive (add `export`, change
  nothing else). If reuse needs more than an `export`, STOP and write the blocker to
  `docs/CODEX-QUESTIONS-cod-league.md` — do not restructure `esports.tsx`.
- **Do NOT touch:** `backend/**` (no new endpoints in Phase 1), `slate*.py`, `streams.py`, the esports
  state machine, `_canon_team`/matcher, `pages/leagues/**`, `pages/game/**`, or any shared util.
- **Do NOT assume.** If the spec is ambiguous or a needed value/field isn't in `/api/esports/upcoming`,
  do NOT invent it — STOP and append the question to `docs/CODEX-QUESTIONS-cod-league.md`.
- **Verify:** `npm run build` (or the dev server) compiles; `/cod` renders CoD live/slate/results with
  real data from `/api/esports/upcoming`. Report what you verified.
