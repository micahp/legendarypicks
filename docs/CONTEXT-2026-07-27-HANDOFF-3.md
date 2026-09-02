# LP handoff — 2026-07-27 pt.3 (supersedes HANDOFF-2)

**The running roadmap and bug ledger now lives in the repo:
`/root/legendarypicks/docs/ROADMAP.md`.** Read it for the work queue. This file is
session state and decisions only — don't duplicate the roadmap here.

---

> **APPENDED 2026-07-27 (later session) — §1 is CLOSED. Read this before acting on it.**
> 1. **Skill rename — reverted, do not redo.** Renamed to `rams-krug-data-ui`, then Micah
>    reversed the call the same day while it was still unpushed. The commit was dropped;
>    `honest-data-ui` is the settled name.
> 2. **Two servers killed** (approved): `:3095` + `:8095`. See the correction below.
> 3. **The tunnel diagnosis in this file is WRONG.** `:3096` was never the culprit — it is
>    the *correct* surviving frontend, proxying to `:8096` via `.env.local`. The tunnel
>    `https://someone-decorative-wearing-produce.trycloudflare.com` was **live the whole
>    time**, serving real app content and a working `/api/*` proxy. It was not refreshed,
>    deliberately: restarting would have minted a new URL and broken a working one.
>    Micah most likely had the dead `cf3095` URL from 07-14.
> 4. **`b0b659f` pushed.** `origin/dev` == `b0b659f`, verified against the remote.
>
> **The real finding:** `/root/lp-ufc-fight-stats` had been **deleted from disk**, but its
> `next dev` (`:3095`) and uvicorn (`:8095`) kept running out of the deleted directory for
> ~3.8 days — `readlink /proc/PID/cwd` showed `(deleted)`. The O1 port table below reads
> them as a legitimate second dev environment; they were zombies. `:3095` served 500 the
> whole time. Recorded as `reference_lp_dev_tunnel_and_servers`.

## 1. Do these first (Micah's asks, deliberately NOT done — he said write the handoff, don't act)

1. **Rename the design skill.** `honest-data-ui` is not memorable to him. Put the names in
   front: something like `rams-krug-data-ui`. Path today is
   `/root/legendarypicks/.claude/skills/honest-data-ui/SKILL.md`, committed `b0b659f`
   (**unpushed**). Update the memory pointer `project_lp_honest_data_ui.md` after renaming.
2. **Kill two servers** — keep prod and dev only. See ROADMAP O1 for the table of four.
3. **Refresh the tunnel.** He can't reach it. The one `cloudflared` up points at **:3096**,
   not :3095 — that's the likely cause, not staleness. See ROADMAP O2.
4. **Push `b0b659f`.** Everything else is on `origin/dev`.

## 2. What shipped today

**v0.6.8 cut, tagged, pushed** (`cc5a36d`, tag `v0.6.8` on origin). Code-only release by
Micah's explicit choice — prod deploy deferred until after v0.7.0.

Eight commits, `e48de53..b0b659f`:
- NFL per-game stats now **copied** from nflverse's published weekly box score instead of
  re-derived from play-by-play. 2025 postseason exists for the first time (258 player-games).
  All 5,635 rows reconcile to the artifact with **zero** fpts mismatches.
- 2026 schedule ingested — 272 games into a new `nfl_schedule` table.
- `ingest_nfl_logs.py` retired to a schema-only module (it could destroy 5,329 snap +
  1,253 NGS rows on re-run).
- UFC fight-stats ingest rebuilt; WC name resolution fixed.
- `honest-data-ui` design skill added.

**2024 loaded after the release** (285 games, 570 `team_game_results` rows) — uncommitted
data change, dev DB only. Team-stats contract verified still 2025/32 teams/17 games.

## 3. Codex is out until Aug 1

Hit its usage limit mid-task. I took over, reviewed and committed its uncommitted work
myself, and killed a hung pytest it left (11 min at 56% — its sandbox runs `--unshare-net`,
so any network-touching test blocks forever).

**Verify its output, don't take it.** Everything it claimed checked out when I tested it
independently — but I also caught a real defect it introduced: it deleted
`from ingest_nfl_logs import ensure_table` and inlined a copy of the schema **missing
`idx_pgl_team_game` and `idx_pgl_team_season_game`**, the two v0.6.7 indexes that took the
usage endpoint from a full scan to an indexed lookup. On a fresh DB where that ingest ran
first, the table would have been created without them. Fixed in `6c97016`.

## 4. The product decision — availability

Micah approved an availability-first draft board as v0.7.0. **His framing is sharper than
mine and should govern:** availability is *"what happens when players get injured or
suspended or go to jail."* The board's job is to help someone draft accounting for those
**and snap share** — not a statistics exercise, a "will this guy be on the field" exercise.
A healthy player in a timeshare is a different risk from an injured starter and the board
must distinguish them.

The evidence, two seasons, measured off `picks.dev.db`:

| player | 2024 | 2025 | PPR when played | PPR per team game |
|---|---|---|---|---|
| Rashee Rice | 3/17 | 8/17 | 19.5 | **6.3** |
| Christian McCaffrey | 4/17 | 17/17 | 22.1 | 13.7 |
| Anthony Richardson | 11/17 | 2/17 | 12.7 | **4.9** |
| Tyreek Hill (2025 only) | — | 4/17 | 13.4 | **3.2** |

Every fantasy site shows the "when played" column. McCaffrey is the case for two seasons:
4/17 alone says avoid, 17/17 alone says safe, together they say recovered.

**Signature design rule (approved): the accent colour marks absence, not achievement.**
Everything present renders quiet; the one saturated colour is reserved for games not played.
Direction is instrument, not magazine — depth chart / box score / Braun.

Also approved: **2024 can render in the UI without the availability calculation** — don't
block the 2024 display on it.

## 5. Things I got wrong this session, so you don't repeat them

- **I gave Codex a relative `LP_DB_PATH=picks.dev.db`.** That silently creates an empty
  database; a 0-byte `/root/legendarypicks/picks.dev.db` already exists from someone doing
  exactly this. Always the **absolute** path
  `/root/legendarypicks/backend/data/picks.dev.db`.
- **My first availability query was 2025-only**, and Micah caught it. It wasn't just a query
  bug — `team_game_results` had **zero 2024 rows**, so 2024 availability was uncomputable
  until I loaded it.
- **I asserted the handoff's framing that `prop_games` / `game_context` were "missing 2026"
  and needed the schedule.** Neither is a schedule table: `props.game_id` is a foreign key
  into `prop_games` and `settle_props.py` settles from it; `game_context` is a post-game
  snapshot of attendance and officials. Seeding either would have put junk in front of
  settlement. Checked before building rather than after — keep doing that.

## 6. State

- `origin/dev` = `cc5a36d` + tag `v0.6.8`. Local `dev` = `b0b659f`, **one commit unpushed**.
- Working tree clean apart from that. Untracked: `docs/ROADMAP.md` (new, commit it),
  the two `docs/TASK-*.md` specs I wrote for Codex, and Codex's untracked
  `run_wc_prop_history_ingest.py` + test, which I never reviewed.
- Suite: **249 passed, 4 failing** — 3 are a `nfl_adp` fixture gap, 1 is MLB league-stats.
  See ROADMAP B4/B5.
- Prod: v0.6.7, still serving the old NFL numbers.
- Cached artifacts (reuse, don't refetch):
  `/tmp/claude-0/-root/f9798c80-dc52-45bd-ba98-be25c4818df0/scratchpad/` — the parquets;
  `/tmp/claude-0/-root/216fe60b-8e78-4980-b68f-3f01fad247d3/scratchpad/games.csv`.

## 7. The lesson worth keeping

Yesterday's was *check whether the value is published before fixing a derivation.* Today's is
the same shape one level up: **check what the component is for before feeding it data.**
Three tables were named as "missing the 2026 schedule"; only one was a schedule table. And
the draft board Micah asked me to build **already existed** — ranking on the wrong number,
labelling itself a projection, with the availability variable already computed internally
and thrown away. The work was never "build it." It was "find out what's already there."
