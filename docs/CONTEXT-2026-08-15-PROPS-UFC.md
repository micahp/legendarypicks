# Context Summary — Props Slate and UFC Underdog — August 15, 2026

## Boundary at handoff

- Repository: `/root/legendarypicks`, managed branch `dev`.
- Managed DEV: frontend `:3096`, backend `:8096`, public tunnel
  `https://resume-stress-education-pros.trycloudflare.com/props`.
- No production code/data/service was changed. No managed frontend, backend, or
  tunnel was restarted. Nothing was pushed.
- Preserve the managed worktree's unrelated WIP. It already had tracked edits
  to `README.md`, `TASK-league-mls.md`, `TASK-league-ncaaf.md`,
  `backend/audit_league_stats.py`, `backend/data/esports_team_logos.json`,
  `backend/data/identity-consolidations.jsonl`, and
  `docs/LEAGUE-STAT-GAPS.md`, plus many unrelated untracked task/context files.
  Do not clean, stage, or discard them wholesale.

## Props Slate UI completed

The final August 15 props commits are:

| Commit | Result |
|---|---|
| `a184b1e` | Slate groups by day, then league. |
| `38f80bb` | Day grouping uses browser-local game start date, avoiding UTC rollover. |
| `0cb0976` / `f497abf` | Filter/slate order is `All, UFC, MLS, NBA, NFL, NHL, MLB`; WC is absent. |
| `89eb23e` / merge `29f892d` | Removed only the decorative horizontal rules to the right of Date and League headers; per-league `games · props` text remains. |

Public browser verification at the tunnel found:

- zero `[data-slate-date] .h-px` decorative rules;
- per-league counts still present;
- no page errors.

The only changed Props files for the final visual tweak were `pages/props.tsx`
and `pages/props.test.ts`; the focused slate Jest suite passed 2/2 using the
managed dependency path. The worktree itself lacks a `node_modules` link, so do
not use `npm`, `npx`, or `yarn` from an isolated worktree.

## UFC Underdog source integration completed

### Source facts

- Underdog public endpoint:
  `https://api.underdogfantasy.com/beta/v5/over_under_lines`.
- It is a single unfiltered bulk book. The ingest makes one request per run;
  do not fan out player/fight requests or repeatedly fetch it for comparison.
- Controlled August 15 run: **5 scheduled MMA fights, 10 fighters, 66 balanced
  UFC props** across `significant_strikes`, `submissions`, `knockouts`,
  `fight_time`, and `finishes`.
- Bovada’s current UFC book supplied decision markets, so it is not a direct
  like-for-like market comparison with Underdog's stat/outcome board.
- PrizePicks public access returned HTTP 403 from this host. Sleeper's MMA
  endpoint identified players, not a verified props board. Neither was added as
  a source.

### Identity/write contract now enforced

`backend/ingest_underdog_props.py` now:

1. Persists source-native player and game keys in `player_source_ids` and
   `prop_game_source_ids`.
2. Resolves native keys first, then one exact canonical player name or one
   reviewed `name_alias`.
3. Queues an unresolved native fighter in `unresolved_players`; it never creates
   a `players` row from an Underdog display name and rejects that entire fight.
4. Reuses an existing UFC game through resolved canonical fighter ids, avoiding
   source ordering/name differences.
5. Prints parsed/resolved/rejected/written coverage and exits non-zero if a
   non-empty source board yields zero eligible props.

The current-card exception was independently checked against ESPN's one-request
UFC 330 scoreboard event `600059185` on 2026-08-15:

- ESPN publishes **Kauê Fernandes**.
- Existing Bovada data said `Kaua Fernandes`; Underdog said `Kaue Fernandes`.
- `backend/apply_reviewed_ufc_identity.py --apply` corrects the canonical player
  and all of that player's existing fight labels to `Kauê Fernandes`, retains
  both alternate spellings as aliases, and binds only Underdog native id
  `7c2bea83-5af4-44e3-952a-6b2bcd6f94e9`.
- `backend/bovada_scraper.py` now honors reviewed UFC aliases and, after a
  canonical label correction, finds the existing fight by its resolved fighters
  rather than creating a duplicate game.

### Data applied to managed DEV

- One live DEV run wrote **66/66** Underdog props across **5/5** eligible fights,
  with **10/10** native fighter identities resolved and zero auto-created
  players.
- `Kauê Fernandes` has one bound Underdog key and two preserved aliases.
- The public exact-date slate returned 66 UnderDog props and the canonical
  `Jalin Turner` vs `Kauê Fernandes` matchup (16 combined current props with
  Bovada's two decision lines).
- `PRAGMA quick_check` passed before and after.
- The database has 78 pre-existing `props.player_id` foreign-key residues. The
  disposable clone and this change added none; that legacy repair is out of
  scope.

Focused `backend/test_ingest_underdog_props_identity.py` passed 5/5. It covers
source-key reuse, no player creation for a missing key, reviewed aliases,
conflicting source ids, canonical fight-label correction, and the Bovada
duplicate-game regression.

## DEV scheduler installed (historical; retired 2026-08-24)

Repository units:

- `ops/systemd/legendarypicks-underdog-ufc-props.service`
- `ops/systemd/legendarypicks-underdog-ufc-props.timer`

These units were retired when `run_props_ingest.py` became the provider registry for both
environments. The current units are `legendarypicks-props{,-prod}`.

- Runs at **:07** and **:37** each hour, intentionally offset from the existing
  Bovada DEV refresh.
- A non-blocking `flock` prevents two delayed Underdog runs from overlapping.
- Timeout is 120 seconds; it uses the existing backend venv.
- It does not target production. Do not copy/enable it for production without a
  separate source, data, and release review.

When checking it later, use:

```bash
systemctl status legendarypicks-underdog-ufc-props.timer
systemctl status legendarypicks-underdog-ufc-props.service
journalctl -u legendarypicks-underdog-ufc-props.service --since today
```

The expected successful log shape is a single fetch followed by source and
ingest counts. A non-empty board with zero eligible props is intentionally an
error, not a green no-op.

## Relevant commits and current state

The managed DEV merge commits from this work are:

- `209b813` — source-identity ingestion
- `b375782` — DEV-only scheduled refresh
- `73d17d0` — canonical fighter labels and Bovada duplicate-game protection
- `29f892d` — remove Slate header rules

At handoff, `dev` was local-only and ahead of `origin/dev`; no remote push was
authorized. Recheck the exact ahead/behind state before any later release.

## Do not regress

- Keep the Props Slate day → league order and browser-local date grouping.
- Keep per-league `games · props` counts; only the decorative header rules were
  removed.
- Never resolve a new Underdog fighter by fuzzy display-name matching or create
  a player from the feed.
- Do not restart DEV services/tunnel to publish these data/UI changes; managed
  services read the merged worktree and DEV database already.
- Do not touch production or push without separate authorization.
