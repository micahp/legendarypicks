# LegendaryPicks Context Summary — 2026-08-09

## Current release state

- Production release/tag: `v0.7.10` at `e55ee1725944e9148b60c09b79c4a5d2b23e0d84` (`release/ewc-v0.7.10`). This is the EWC production release built after the CoD scoreboard hotfix lineage.
- Managed DEV: `/root/legendarypicks`, branch `dev`, HEAD and `origin/dev` at `08d21334038b7aee4cda7f8505a4181e6dc37f91`.
- DEV is ahead of production. Do not assume the full current DEV state is promoted merely because EWC reached production.
- No further DEV merge, production promotion, tag move, database write, or managed-service restart is authorized by this handoff.

## What landed on DEV today

The current DEV history contains:

1. `4d677e4` — merge league news engine into DEV.
2. `92bdc6e` — merge Leagues Cup into DEV.
3. `f8620d4` — show the live minute on soccer game detail.
4. `2d706f4` — merge EWC esports into DEV.
5. `e5c3cf2` — track all EWC games instead of a five-game subset.
6. `1be39cf` — publish the complete 24-title EWC catalog.
7. `3dd20e7` — initial mobile EWC navigation simplification.
8. `08d2133` — replace that navigation with the requested horizontally scrollable title-tile row.

The later all-games, 24-title, and mobile title-row commits are DEV-only relative to `v0.7.10` and still require QA before any production promotion.

## EWC branding ownership

- Reasonix task: `/root/reasonix`.
- Assignment: finish the remaining EWC/esports branding, centered on official branding for all 24 game/title tiles and any directly related incomplete EWC branding states.
- Constraints: official EWC/game assets only; no invented or AI-generated brand logos; isolated worktree from current `origin/dev`; preserve concurrent WIP.
- Required handback: branch, commit, exact changed files, tests/build evidence, visual evidence where practical, and remaining risks.
- Reasonix is not authorized to merge, deploy, tag, restart managed services, or modify live databases.

## New-leagues worktree

- Worktree: `/root/lp-new-leagues`
- Branch/HEAD: `feat/new-leagues` at `5fa190d7abb28ed4010114d039e8a019c06853d0`
- Integrated history includes the news engine, Leagues Cup, EWC, MLS/NCAAF foundations, and the soccer live-minute fix.
- Current worktree state is not clean: tracked `backend/data/esports_team_logos.json` is modified and `backend/venv` is untracked. Treat both as existing WIP; do not delete, overwrite, or stage them incidentally.
- Separate MLS/NCAAF source worktree remains `/root/lp-league-mls-ncaaf` on `feat/league-mls-ncaaf` at `2d6ab86`.

## Managed checkout safety

- `/root/legendarypicks` must remain on `dev` because managed DEV runs from it.
- It has existing WIP: tracked `backend/data/esports_team_logos.json` plus many untracked task, log, database, context, and sketch files.
- Do feature work in a new isolated `/root/lp-*` worktree and stage only explicit task-owned paths.
- Do not apply or drop mixed stashes wholesale. Do not use destructive checkout/reset commands against existing work.
- Do not run `npm`, `npx`, or `yarn` in isolated worktrees; use the already installed binaries from `/root/legendarypicks/node_modules` when needed.

## DEV tunnels — verified today

- Managed DEV (`localhost:3096`): <https://resume-stress-education-pros.trycloudflare.com> — HTTP 200.
- New leagues (`localhost:3105`): <https://coat-develop-rooms-prague.trycloudflare.com> — HTTP 200.
- Supervisors:
  - `legendarypicks-dev-tunnel.service`
  - `legendarypicks-new-leagues-tunnel.service`
- Exactly two `cloudflared tunnel --url` processes were present when this summary was written, one for each origin. Do not start duplicate manual tunnels or put them in tmux.
- Quick-tunnel hostnames are ephemeral. Re-read each service journal if a URL stops resolving rather than assuming this document's hostname is permanent.

## QA and next decisions

1. QA the current DEV EWC page, especially all 24 title tiles, the horizontally scrollable mobile row, full game coverage, status/title filtering, standings logos, and match team logos.
2. Review Reasonix's branding branch independently; do not infer correctness from a passing build alone.
3. Keep the news feature out of any production promotion unless the user explicitly re-authorizes it as ready.
4. If promoting EWC follow-ups, define an explicit allowlist or release commit so unrelated DEV/news changes are not accidentally bundled.
5. Re-verify production, DEV, and candidate URLs independently; HTTP 200 proves reachability, not UI correctness.

## Useful branch/worktree references

- `/root/lp-ewc-prod` — `release/ewc-v0.7.10` at `e55ee17`.
- `/root/lp-hotfix-cod` — `hotfix/cod-scoreboard-v0.7.9` at `93133c7`.
- `/root/lp-ewc-promotion` — `integration/ewc-dev-20260809` at `2d706f4`.
- `/root/lp-ewc-all-games` — `feat/ewc-all-games` at `e5c3cf2`.
- `/root/lp-ewc-24-titles` — `fix/ewc-24-title-catalog` at `1be39cf`.
- `/root/lp-ewc-mobile-nav` — `fix/ewc-mobile-navigation` at `3dd20e7`.
- `/root/lp-ewc-title-row` — `fix/ewc-scrollable-title-row` at `08d2133`.

## Verification snapshot

At summary time:

- `dev == origin/dev == 08d2133`.
- `v0.7.10 == e55ee17`.
- Both tunnel services were active under systemd.
- Both public tunnel roots returned HTTP 200.
- The managed checkout's existing WIP was left untouched.
