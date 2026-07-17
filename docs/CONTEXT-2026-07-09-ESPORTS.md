# Context summary — esports work, 2026-07-09

Branch: `feat/live-discounts` (all changes pushed to origin). Repo: `/root/legendarypicks`.

## What shipped today

- **`02b90f9` fix(esports): reconcile reschedules and purge map markets** — finalizes the uncommitted
  esports work from `HANDOFF-2026-07-09-ESPORTS.md`. 43 matcher assertions pass; live API on `:8095`
  verified: 293 matches / 204 finished / 88 scheduled / **2 unknowns** (the two RES qualifiers) / **0 LMap**.
- **`c126994` fix(esports): group Scheduled/Results by stable calendar day** (committed earlier same day)
  — fixes the Scheduled-tab grouping bug (out-of-order days, same day under multiple headings, Today not
  first). `groupByDay` in `pages/esports.tsx` groups by a stable local-date key; Scheduled asc / Results desc.
- **`da50f70` docs(esports): document flipped-logo audit + open follow-ups** — behavior doc.

## Behavior verified in live `/api/esports/upcoming`
- `Prestige Esports v Vasteras Esport` → finished, winner B, score 1–2 (United21 fixture-scoped bridge, no global alias).
- `Leo Team v Prestige` / `LEO v Prestige Academy` (psId 1568951) → scheduled Jul 10 13:30 UTC, no longer a false final.
- Two RES qualifiers (`Arch v Virtus.pro`, `Metanoia Wolves v Bounty Hunters`) → re-keyed to correct 2026 labels, still `resultUnknown` (absent from PandaScore; qualifier sourcing deferred per user).
- No emitted `teamA`/`teamB`/`favorite.name` contains `LMap`; two-sided map-market rows dropped from carry + store.

## Open follow-ups (documented, NOT fixed — user said skip both)
1. **LEO/Prestige Academy duplicate card.** Two source rows (Bovada + PS, same `psId=1568951`, same start) emit as TWO Scheduled cards; `_cluster`'s `same_ps_id` branch doesn't reliably union a Bovada+PS twin. Same gap leaves a stale `resultUnknown` store key un-popped.
2. **Flipped team logos (population-wide).** Strict audit of 293 live matches found **28 with A/B logo reversals** (e.g. `BetBoom Team v Team Falcons`, `Xtreme Gaming v GamerLegion`, `Aurora v Nigma Galaxy`, `Parivision v Vici Gaming`, `1Win v Virtus.Pro`). Not a first-card glitch. Root cause: per-side logo fill (`slate.py` ~L899) only writes when a side is empty, so a crest from a prior PS match with a different orientation freezes flipped. Fix: re-align every emitted pair against canonical PS crests and OVERWRITE, not fill-if-empty.

## Environment notes
- Dev backend runs on `127.0.0.1:8095` (bound localhost per deploy rules). Frontend `:3095` proxies to it via `API_PROXY_TARGET` in `.env.local`.
- Do NOT commit generated files: `backend/data/esports_results.json`, logs, `.hermes/`. Untracked user files left alone.
- Matcher suite: `backend/venv/bin/python3 backend/routers/esports/matcher_assertions.py` (all 43 pass).
- Scheduled/Results tab switch works in a real browser (headless click in the agent browser tool does not toggle it — verify visually, not via automation).

## Next priorities when resumed
- Pick up open follow-up #1 (LEO duplicate) and/or #2 (flipped logos) — both need code fixes + matcher assertions.
- Frontend: render a "result unavailable" label for `resultUnknown` (currently reads as a bare Final).
