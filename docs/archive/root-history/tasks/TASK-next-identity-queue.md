# TASK — finish MLB, then measure identity correctness in the other three leagues

**Owner:** delegated (reasonix / deepseek-v4-flash)
**Status:** not started
**Written:** 2026-08-05

Work in `/root/legendarypicks`, absolute DB paths, **never a worktree** (it symlinks only
`picks.dev.db`, so `--db data/picks.db` silently creates an empty database).

Four parts, **in this order**. Each is independently useful — if you get stuck on one,
report it and move to the next rather than stopping the whole queue.

---

## Part 1 — finish the MLB vocabulary on dev, then do prod

Your crosswalk worked: dev's blank `position_group` went **126 → 5**, and
`G/published-identity` still PASSes with **1442** ids checked, up from 1298. The gate
confirming 144 newly-crosswalked ids all name the right person is exactly the closed loop
we wanted.

Two things are left on dev, both small:

* **2 rows still hold ESPN's `RP`/`SP` in `position`** — `id=27525 José Suárez ATH RP
  mlbam=699027` and `id=28922 Jackson Wolf DET SP mlbam=680232`. **Both already have an
  `mlbam_id`**, so the crosswalk is not the problem. Find out why the spine fill left them:
  the likely answer is MLB publishes no `primaryPosition` for them this season, so nothing
  overwrote the stale ESPN value. **If that is the case, the honest fix is to clear the
  stale value, not to keep it** — a position from the wrong publisher's vocabulary is worse
  than no position, because `WHERE position='P'` silently excludes them either way while
  `SP` makes them look populated. Confirm against the API before deciding.
* **5 active rows still blank on `position_group`.** Name them and say why for each.

Then `C/vocabulary[position]` and `C/vocabulary[position_group]` should both go **PASS** on
dev. Only then do prod: prod still has **neither new column**, so run
`backend/migrate_mlb_position_vocabulary.py` against it, then the spine ingest, then
`roster_sync.py mlb`, then the gates. Back up first, `quick_check` = ok, row counts unmoved.

---

## Part 2 — three MLB rows carrying 2,980 props with no publisher id

I measured the rows with **no publisher id at all** across the whole database. There are
seven, none active, and they split into two groups.

**Group A — harmless seed rows.** `id=121 Patrick Mahomes`, `id=122 Jayson Tatum`,
`id=123 Connor McDavid`, `id=124 Auston Matthews`. Consecutive ids, one per league, zero
references in `props`, `player_game_logs`, `player_stats` or `roster_memberships`. Leave
them; just confirm the zero-reference count still holds and say so.

**Group B — real, and one is bad.** All MLB, all with props attached:

```
id=28987  name is EMPTY        2393 props
id=29097  James Outman   MIN    584 props
id=29152  Miles Mastrobuoni SEA   3 props
```

`28987` has **no name at all** — its whole row is `id`, `league`, `active`, `updated_at`.
It is a **bucket for everything the Bovada parser could not resolve**. Its markets say so:

```
total_hits,_runs_and_errors                                   1396   <- a GAME market, not a player prop
earned_runs 176 / strikeouts 136 / outs 124 / hits_allowed 120       <- real player props, nameless
total_hits,_runs_and_rbis___cooper_pratt                             <- the player's NAME is inside the market string
total_bases___cody_bellinger_&_ben_rice_combined                     <- a two-player combo prop
```

So `bovada_scraper.py` is doing three different wrong things and funnelling all of them into
one nameless row. **Investigate and report before changing anything** — I want the shape of
it, not a quick patch:

1. How many of the 2,393 are game-level markets that should never have had a `player_id`?
2. How many are single-player props whose name is sitting in the market string unparsed?
3. How many are genuine multi-player combos that no single `player_id` can represent?

Outman and Mastrobuoni are simpler and are **publishable** — I checked: `James Outman` →
`681546`, `Miles Mastrobuoni` → `670156`, unique matches. They should be crosswalkable by
the same rule your Part 1 work uses. Do that only if it falls out cleanly; otherwise report.

**Do not delete any props.** 2,980 rows of real captured market data.

---

## Part 3 — measure identity correctness for NFL, NHL and NBA

`G/published-identity` is **UNVERIFIED** for all three. That is the same blind spot MLB had:
every row carried an `mlbam_id` and 223 of them named the wrong person. Coverage is fine in
every league — only 7 rows database-wide lack a publisher id — so **correctness is the
open question, not coverage.**

I extended `backend/fetch_identity_names.py` (commit `9ec78e4`) to fetch all four, each from
the publisher that **issued** the id:

* NFL → nflverse `players.parquet`, `gsis_id` → `display_name` (~25k rows)
* NHL → `api.nhle.com` skater **and** goalie summaries (goalies are a separate report with a
  separate name key — this league has three player types)
* NBA → hoopR, newest published season, which is **2023**; it walks back until a file exists

**It has not been run yet.** Run it, commit the regenerated artifact, then run the audit for
each league and report `G/published-identity` **verbatim** for all four.

```
cd backend && venv/bin/python fetch_identity_names.py --season 2026
venv/bin/python audit_league_stats.py --league nfl --db /root/legendarypicks/backend/data/picks.db
#   ... and nhl, nba, mlb
```

**Report the result whatever it is. A red gate here is the point of the exercise** — it is
information we do not currently have. Do **not** repair anything you find; a repair needs its
own task with a backup, and NFL is the only league with two publisher ids on one row, so its
blast radius is the largest in the database. Measure, report, stop.

If a league's fetch fails, the code omits it and records why in `_provenance.errors` — report
that error rather than working around it.

---

## Part 4 — only if Parts 1–3 are done and reported

`A/required-stats[season]` for **NFL** on prod reads `column exists but 0 rows populated:
rush_td, rec_td`. That is v0.7.3's headline feature — "the NFL board can be sorted by
touchdowns" — shipped in code and never ingested to prod. Per
`.claude/skills/published-first/SKILL.md` §2b this is a **surfacing gap, not an acquisition
gap**: the values are already in `player_game_logs` as `rush_td`/`rec_td`. Read that skill
before you touch it, and prefer the publisher's own season total over a rollup of our logs —
§3 records eight defects from exactly that rollup.

Report what you find before running anything against prod.

---

## Out of scope, all four parts

* Deleting props, players, or any row. Nothing in this task deletes.
* `roster_sync.py`, `dedupe_mlb.py`, `repair_mlb_identity_names.py`, the audit's check logic.
* Repairing any identity defect Part 3 uncovers — that is a separate task.
* Docker: no build, no `up`, no restart. Prod is serving live.
* Host config: `/etc`, systemd, timers, cron. **The props timers write to prod every 30 min.**
* `git push`. Commit locally, one commit per slice.

## Report back between `===RESULT===` and `===END===`

Per part: what you ran, what you measured, what you changed, what you deliberately did not.
Gate lines **verbatim**. For Part 3, all four `G/published-identity` lines. Then
`git -C /root/legendarypicks status --short` and `git log --oneline -6`.

Then stop and wait.
