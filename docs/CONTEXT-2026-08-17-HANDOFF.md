# CONTEXT HANDOFF — 2026-08-17 (overnight session)

Supersedes nothing; **continues** `/root/legendarypicks/docs/CONTEXT-2026-08-16-HANDOFF.md` (written 08-16 18:34,
which predates everything below).

Repo: `/root/legendarypicks`, branch `dev`, **87 commits unpushed**.
Working tree: 2 modified data files (`bovada-league-backoff.json`, `esports_team_logos.json`),
plus a pile of untracked `TASK-*` / `RESULT-*` / `PLAN-*` files in the repo root.

---

## 1. The decision that shaped the session: MLS props come from RotoWire/PrizePicks

Micah's call, and it is the right one against the market list. Of the **eleven markets this
league is being built for** — shots, shots on target, passes attempted, goals, goalie saves,
clearances, assists, attempted dribbles, tackles, crosses, fouls:

| source | MLS fixtures | prices how many of the 11 |
|---|---|---|
| Bovada | 14 | **2** (goals, assists) |
| Kambi/Unibet | 32 | **3** (goals, assists, + SOT on 1 fixture of 32) |
| Sleeper | 11 lines | 0 (GK goals_against, not saves) |
| Pinnacle | 696 matchups | 0 (zero player props) |
| **RotoWire/PrizePicks relay** | *see §3* | **7** |

So:
- **Bovada MLS pull REMOVED** from `LEAGUES` in `backend/bovada_scraper.py`. `_parse_mls_props`
  is deliberately **kept** — it is measured and tested, and the league is one line away if the
  relay does not work out. The continent path (`soccer/north-america/united-states/mls`;
  `soccer/usa/mls` 404s) is recorded in the test docstring because rediscovering it cost real
  time once already.
- **Kambi turned OFF**, not deleted. `ingest_kambi_mls_props.py` refuses to run without
  `--enable` and is not scheduled.
- Historical Bovada/Kambi MLS rows are **kept, not deleted**; the reader's source policy selects
  the relay.

**Known consequence, accepted:** between now and the first good relay capture, MLS has no props
at all. Codex's honest "source unavailable" empty state covers it, so it degrades correctly —
but do not be surprised by an empty MLS board.

---

## 2. Respecting free publishers — the night's other theme

Micah: *"respect the api limits. theyre giving it all for free. we can't over call."*
Two paths were rewritten to ask less, and both got **strictly better as instruments** in the
process, which is the point worth carrying forward.

**RotoWire probe** (`backend/monitor_rotowire_soccer.py`, commits `d4b0b8d`, `f3a4915`):
- Reads **our own `prop_games` table first**. If the nearest MLS kickoff is outside a 48h
  window it makes **no HTTP request at all** and records that it skipped, and why.
- Asks for gzip: **1,994,307 → 373,448 bytes**, measured. 81% off for one header.
- Timer 6-hourly (`legendarypicks-rotowire-probe.timer`). A normal MLS week goes from ~168
  calls to roughly 8, clustered where a board can actually exist.
- A **failed fetch is not recorded at all** — a failed read and an empty board must never look
  alike.

**Bovada scraper** (commit `102b146`): per-league adaptive backoff. 3 consecutive empty runs →
6h rest. State in `backend/data/bovada-league-backoff.json` (beside the DB, not in it — it is
operational scheduling, not app data). **Fails open**: a league with no recorded history is
always fetched, because this coupon is how we *discover* that a season started; refusing to look
would make the backoff self-fulfilling. Covered by `test_bovada_backoff.py`.

Rationale, worth keeping: the scraper ran `all` every 30 minutes regardless of season, so UFC
between cards, tennis between tournaments, and MLB/NBA/WC out of season each cost 48 requests a
day to be told "no board" 48 times.

---

## 3. Two errors I made and corrected — SAME SHAPE, twice in one night

Both were **a measurement artifact reported as a property of the thing measured.** This is the
failure mode to watch for; it got past me twice in six hours.

**(a) "PrizePicks carries no MLS."** I read the relay once, at 04:19Z. Both of that day's MLS
fixtures had kicked off at 00:30Z and 02:30Z, and a pick'em board is pulled at lock. There was
no MLS board to be absent. Liga MX was there because Liga MX played that night. I measured at
the one moment the answer was guaranteed empty. **Absence is a statement about when you asked.**
PrizePicks-via-relay is *untested*, not ruled out — and it is the source carrying 7 of 11
markets. The probe in §2 exists to answer it properly.

**(b) "MLS settlement returns 0 settled, all pending."** That was an **already-settled game
re-run** — idempotent zeros read as failure. Settlement **works**: 628 props settled across 5
markets. The 6 stragglers on the game I checked are honest refusals: 4 players with no
`espn_id` (residual name-variant queue), 2 who did not dress. This came **off** the blocker list.

A third, caught mid-build rather than after: Kambi types the player side of a yes/no market
differently per family — `OT_PLAYER_PARTICIPANT` on "First Goal Scorer", not `OT_YES`. My first
pass **silently dropped 720 of 776 outcomes while printing a plausible total** (2,520 → 3,170
after the fix). Unknown outcome types now exit 3.

---

## 4. THE ACTIVE WORK: `backend/dedupe_props.py` — measured, written, NOT YET APPLIED

**The defect.** `/api/props/ingest` INSERTed unconditionally into a table with no UNIQUE
constraint while scrapers ran on 30-minute timers, so an unchanged board was copied in full on
every scrape. On dev: **46,495 duplicate `(game_id, player_id, market, line, side, source)`
groups, 776,752 rows to remove** — essentially all MLB, ~17 copies per prop.

Nothing ever errored. The board reads latest-per-key so it **rendered correctly the whole time**,
while every hit-rate denominator counted the same prop once per scrape. A number that is wrong
on a page users read, produced by a pipeline that looked healthy.

The **mechanism** is already fixed — commit `c11370d` made the endpoint upsert. This script
clears what it already wrote.

**Status: dry run clean, `--apply` RAISED AND ROLLED BACK. Dev is untouched — verified
841,516 props, same as before.** Backup taken first:
`backend/data/picks.dev.db.bak-2026-08-17-dedupe` (363 MB, 00:05).

**Why it raised, and the measurement that resolves it.** `prop_results.prop_id` is
`INTEGER PRIMARY KEY`, so repointing a loser's result onto a winner that already has one raises.
My comment at `dedupe_props.py:116-118` asserted that never happens. It does. Measured
2026-08-17:

- **45,096 of the 46,495 groups carry more than one settled row.**
- **All 45,096 agree** on `(actual_value, hit)`. **Zero disagreements.**

So the merge is safe, and the policy is:
1. Winner = the newest row that carries a `prop_results` row; if none carry one, the newest row.
2. A loser's result whose winner has none → **repoint**.
3. A loser's result whose winner already has one → **compare**. Identical → delete the redundant
   loser row. **Differing → abort loudly.** Never silently pick a side.
4. Same treatment for `prop_odds_snapshots`, which has `UNIQUE(prop_id, side, captured_at)` —
   only 3,526 rows total, but it can collide the same way.

Do **not** keep `MAX(id)` blindly. An earlier ad-hoc pass at the MLS rows did exactly that and
orphaned 3 `prop_results`.

**Not yet done: prod.** `data/picks.db` has 834,075 props and has never had this run. Both DBs,
per standing rule.

---

## 5. Build readiness — what actually gates a cut

Micah asked to push a build. I did not cut one; the known-broken list gates the ship.

**Hard blocker — the standing gate: 2 FAILs** (down from 4 this morning)
- `mls` and `ncaaf` → `C/vocabulary[position]`. ESPN publishes **two levels of one vocabulary in
  one column**: CB and S alongside their own parent DB; AM/CD-R alongside M/D. Clearing them
  needs the `position_group` declaration **and zero blanks** — 47 MLS + 17 NCAAF players still
  have none, and those need **reviewed aliases, not auto-matching**.
- Judgment call available: these are ESPN's vocabulary, not our defect, understood since 08-11.
  Shipping with them **recorded as accepted** is defensible. Micah has not ruled.

**Makes shipped numbers wrong (P0 by the backlog's own scale)**
- The duplicate rows in §4. This is the one I would insist on before a build.

**A choice to make consciously**
- `legendarypicks-props.service` exits 3 every 30 minutes because tennis resolves 0 of 310.
  That is deliberate and correct — it has been broken the whole time — but shipping a
  permanently-red unit trains people to ignore it. Either the tennis spine lands, or we accept
  red **and write down why**. The `/root/lp-tennis-spine` worktree and spec are ready and unstarted.

**Latent, bit me 3× today**
- `test_leagues_hub_assertions.py` does a **live ESPN fetch at import**, so when ESPN's budget is
  spent the entire suite hard-errors at collection. It collects fine right now (1,487 tests), but
  it would abort `release.sh` mid-cut on a bad day.

**Not blockers, just state**
- MLS 2026 log backfill paused at **147 of ~350** matches (stopped to free ESPN budget for prod
  repairs). Resumable.
- RotoWire publisher work is on codex's unmerged worktree, staying there per Micah.

---

## 6. Prod repairs applied earlier today (snapshot taken first)

MLS season stats 0 → 332 · `entity_type` set on 13,008 rows · NCAAF positions 5,738 → 180 blanks ·
MLS spine 357 → 1,096 published players · shadow players 531 → 51, with 1,751 props moved onto
real identities.

---

## 7. Next actions, in order

> **SUPERSEDED for items 1–3 — see §9–§12, written later the same night (02:00–03:00 CDT).**
> Items 1–3 are DONE on both DBs. Items 4–5 still stand.

1. ~~**Fix `dedupe_props.py` collision policy** per §4, re-run dry, `--apply` to dev, reconcile.~~ done
2. ~~**Run it against `data/picks.db`** (prod) with its own snapshot first. Both DBs.~~ done
3. Re-run the suite against **both** DBs.
4. Then put the build decision back to Micah: the 2 gate FAILs accepted-and-recorded, or cleared.
5. Watch the relay probe series — the first read that can carry evidence is the **08-19 23:30Z**
   slate, 7 fixtures; boards typically post 24–48h ahead, so Tuesday. If PrizePicks lists MLS,
   the market coverage goes 2/11 → 9/11 through a source that already answers from this box.

## 8. Commits this session (newest first)

```
102b146 fix(props): stop asking free APIs for answers they already gave, and settle on one MLS source
f3a4915 fix(probe): ask only when there is something to see, and ask smaller
d4b0b8d feat(props): probe the RotoWire relay on a timer, because one read cannot answer the question
5fa5647 feat(mls): second prop publisher — Kambi/Unibet, and the market list it still cannot fill
3c0e3ff docs: record the four defects behind the MLS props gap, and what each league actually holds now
6c7e4d9 fix(props): count every player minted from a sportsbook name
8052df3 fix(ncaaf): set the published position when minting a player, instead of promising a backfill
c0a4281 feat(settlement): grade the five MLS markets a single published stat cannot answer
dee26a3 feat(soccer): read all 15 published per-player stats, derive the first goal, and make a season backfill resumable
c11370d fix(props): refresh a re-scraped prop instead of writing a second copy
0814472 fix(identity): fold the stored name too, so a diacritic stops hiding a player
d0b3b05 feat(mls): scrape all 8 Bovada MLS player markets, and report what was not ingested
```

---
---

# LATE-NIGHT PASS — 2026-08-17, 01:00–03:00 CDT

Appended, not merged into the above. §1–§8 were written before any of this.

Repo `/root/legendarypicks`, branch `dev`, now **98 commits unpushed**.

## 9. Prod MLB props: the settlement hole is closed

The headline. Prod MLB props, before → after tonight:

| month | before | after |
|---|---|---|
| 2026-06 | 693 settled / 14,124 unsettled (**5%**) | 10,419 / 3,691 (**74%**) |
| 2026-07 | 12,372 / 5,030 (71%) | 13,669 / 3,104 (81%) |
| 2026-08 | 17,724 / 2,100 (89%) | 16,298 / 3,248 (83%) |

`prop_games` 1,027 → 962 · `props` 54,764 → 53,148 · settlement sweep settled **11,896**
(5 errors, 1,564 unmappable, 6,686 pending).

## 10. The June cause — and the wrong answer I published first

**I got this wrong once and it is worth recording as a wrong answer, not just a right one.**
I wrote into `_core.py` and `dedupe_prop_games.py` that the duplicate `prop_games` rows *were*
prod's June hole. Micah asked me to confirm numbers, and the partition falsified it:

| bucket | props | game rows |
|---|---|---|
| never linked (no espn_event_id) | 827 | 16 |
| linked, no final score stored | 4,467 | 86 |
| linked, final, **row is a duplicate** | 2,212 | 68 |
| linked, final, unique — **unexplained** | **6,618** | 78 |

Duplicates were **16%**, not the cause. Both docstrings now state the partition instead of the
claim. The real cause came from running settlement on one of the 78 and reading what it said:

```
MLB gamePk not found for Miami Marlins@Philadelphia Phillies on 2026-06-15 (start_time=none)
```

`_fetch_mlb_gamepk` needs `start_time`. Without one it searches day−1/day/day+1, **a series
plays the same two clubs on consecutive days**, it gets 2–3 matches and fails closed — correctly,
because the alternative is grading against the wrong game. Prod had **304 MLB rows with no
start_time**. That is the June hole. Filling them is what fixed it.

**Method note worth keeping:** the first three things I "found" were shapes (a +24h histogram, a
duplicate count, a market-name pollution). None was the cause. The cause appeared the moment I
ran the failing operation and read its error string. Run the thing that is failing.

## 11. What was actually done, in order

1. **`repair_mlb_player_identity.py`** (new, `6c025c2`). Settlement builds its MLB lookup from
   `mlbam_id IS NOT NULL AND != 0`, so a prop on a row without one is outside the query that
   grades anything. Prod had 380 such props, dev 406, across exactly two rows:
   - **James Outman existed twice** — id 26852 (mlbam 681546, 70 game logs, **0 props**) and
     id 29097 (**no mlbam**, 51 props). MLB Stats publishes exactly one James Outman. Merged onto
     the published id. **Keyed on the id, not the name**: prod has four *other* MLB name
     collisions (two Max Muncys, Jared Joneses, Gabriel Rodriguezes, Luis Castillos) that are
     genuinely different people, and the script fails closed if the rows aren't the expected shape.
   - **id 28987 had no name at all** — a bucket holding 329 props: 152 `total_hits,_runs_and_errors`
     (a *game-level* market that never had a player) and ~177 unresolved call-ups (Cooper Pratt,
     Sean Keys, Kohl Drake…) collapsed together, distinct people made indistinguishable. Deleted,
     matching what the ingest already does — `bovada_scraper.py:774` (`a703f29`, 08-10) drops
     unattributable props, and the row's last capture is 08-10, so the mechanism was already shut.
     Resolving those names instead would mint players from sportsbook display names: the exact
     shape that put 531 shadow players into prod MLS (§6).
   - Result: MLB props on a player with no mlbam_id **380 → 0** (prod), **406 → 0** (dev).
     Verified by settling three of Outman's games on a copy — 3 props each, previously 0.

2. **`--resolve-finals`** on `dedupe_prop_games.py` (`8582ac7`). The merge aborted on 7 prod
   groups whose rows disagreed about the final score. Rule 4 is right to refuse a guess, but a
   disagreement is a question. Asked MLB Stats for all 58 MLB duplicate groups: **every one has
   exactly ONE real published game across both dates**, so they are true duplicates (this also
   retro-confirms the dev merge). In all 7 conflicts the **later**-dated row matches the
   publisher and the earlier row holds *the previous day's* score — graded against the wrong
   fixture. Fail-closed on every ambiguity; uses `statsapi` (authoritative for MLB, free against
   the ESPN budget). It also **deletes the loser's 590 `prop_results`**, because `settle_game`
   skips a prop that already holds a result, so a wrong grade left in place is permanent.

3. **Backfill ran clean.** The gate that refused all night now passes honestly:
   **334 checked, 334 agree, 0 disagree** (was 95 disagreeing). Filled 219; MLB rows missing
   `start_time` **304 → 28** (22 unlinked, 6 not published).

4. **`_link_or_fold`** in `routers/props.py` (`61e6cf4`) — see §12.

Also: `regrade_props.py` on prod, disagreements **24/285 → 3/285**. Dev `dedupe_props` applied
(props 64,773 → 63,871) after the regrade cleared its grade conflicts.

## 12. "Will this come up again on the next ingest?" — measured, not assumed

Reproduced each path against a copy of prod rather than reasoning from the code.

| defect | recurs? | why |
|---|---|---|
| duplicate `prop_games` rows | **no, self-healing** | see below |
| nameless-player bucket | **no** | `bovada_scraper.py:774` drops unattributable props; API path's `_resolve_player_for_ingest` **never** silently creates — it queues to `unresolved_players` and returns None |
| shadow player with no mlbam | **no, via props** | same resolver. The now-deleted Outman shadow was how exact-name matching kept feeding it; with it gone the match lands on the row that has the id |
| **`start_time` is write-once** | **YES — still open** | `routers/props.py:473` and `bovada_scraper.py:856` both guard `if start_time and not game_row["start_time"]`. A publisher **revising** first pitch can never propagate. This is the +17h/+19h class (~20 of prod's 95), distinct from the +24h day-rollover class |

**The duplicate path in detail**, because my own index created a new failure mode:

- The index is **partial**, so the ingest can still INSERT a day-early twin with a blank event id — confirmed allowed.
- The ingest then links it in place, and that UPDATE now raises `IntegrityError` — confirmed.
- Both call sites wrapped it in `except Exception: pass`, so **the twin survived permanently UNLINKED** — no event id, settlement never resolves a gamePk, every prop stranded, and indistinguishable from a fixture ESPN hasn't published. Silent. I introduced this with the index; `61e6cf4` fixes it.
- `_link_or_fold` now repoints the props onto the row already holding the id and drops the twin. Verified: returns the surviving row id, prop lands on it, 0 duplicate groups.
- The nightly `link_prop_games.py` folds any that slip through — verified end-to-end on a copy (orphan folded, prop repointed, 0 duplicate groups).

**So: no, with one exception — a revised first pitch still cannot land.** That is the next fix.

Bonus finding: `link_prop_games.py` already has its own ESPN request-budget guard and it
**fired** during this test (`REFUSING: 165 requests to one host, ceiling is ~100`). That is the
class of protection the unwritten gate (§13) is meant to generalise.

## 13. Still open

- **`start_time` write-once** — the one confirmed recurrence. 3 guards to change, and it needs a
  policy: last-writer-wins, or only-if-the-publisher-disagrees.
- **Dev's regrade ruler did not move**: 15/187 before *and* after, while prod went 24/285 → 3/285.
  Same script, same ruler, opposite behaviour. Unexplained.
- **`legendarypicks-props-prod.timer` is STOPPED** — I stopped it at 00:47 to protect the ESPN
  budget and have **not restarted it**. Its service is `failed`: rejected all 358 ATP/WTA props,
  "nothing in players matched". Prod has no tennis players; dev does. (Same root as §5's
  permanently-red unit.)
- **The unconfigured-ESPN-script gate is unwritten** — 20 of 27 scripts importing `espn_client`
  set no disk cache, `bovada_scraper.py` among them. `paced_http`'s pause is now self-describing
  (`9e2951e`), but nothing stops the next script being written without a cache.
- 1 prod row (`id 9`) stores team **codes** (`MIA @ PIT`) not names, so its gamePk won't resolve.
  2 props. Not chased.
- **v0.8.0 still BLOCKED**: 2 gate FAILs, now **98 commits unpushed**.

## 14. Commits this pass (newest first)

```
61e6cf4 fix(props): fold a day-early twin at ingest instead of swallowing the constraint
8582ac7 feat(props): resolve duplicate-game final-score conflicts from the publisher
6c025c2 fix(mlb): repair the two player rows props could never settle against
9e2951e fix(regrade): an unreachable ruler must not abort the repair, or exit 0
979eb7e feat(props): merge prop_games rows that are the same published event, and forbid the recurrence
6dc1773 fix(props): drop the reverted spend-ledger calls from the start_time backfill
fe82812 Revert "fix(http): count the per-host request budget across processes, not per interpreter"
3c1558b feat(props): repair start_times that disagree with the publisher, and cache the sweep
481d6d3 fix(tests): move the live-ESPN leagues-hub checks into a test function
205c66d feat(props): collapse the duplicate prop rows a non-upserting endpoint wrote
```

`6b01fd1` (cross-process spend ledger) was **reverted** at Micah's instruction (`fe82812`);
the disk-cache half was kept because it paid for itself immediately — it took the repair
sweep from 31 requests to 0.

> **CORRECTED 2026-08-18.** This paragraph originally said the ledger "was built on a
> misreading of Micah's '100 limit per call'". **Nobody was told that.** The revert commit
> carries no reason, and that sentence was invented here to fill the gap. It then read as
> fact for a day and shaped a whole design document before anyone checked it.
>
> Micah's actual reason, given 2026-08-18: *"I reverted it because first of all I didn't
> understand what you were doing, and I thought we could just do the 100 limit each call and
> it would be fine."*
>
> Two things follow. The change was never explained before it landed, and reverting
> something you cannot evaluate is correct. And his per-call model is coherent: it is
> exactly what `HOST_BUDGET = 100` per process does, and it holds whenever one job talks to
> a host at a time. It fails only because the cap is per JOB while the limit is per HOST.
>
> **A revert with no recorded reason is a question to ask, not a gap to fill with a
> plausible story.** See `docs/DESIGN-request-budget.md` §1.

## 15. Backups taken tonight (prod, in order)

`data/picks.db.bak-2026-08-17-` + `starttime` · `regrade` · `identity` · `gamemerge` · `backfill` ·
`presettle`, plus each script's own `.pre-schema-*.bak`. Dev: `-gamemerge`, `-dedupeprops`, `-identity`.

---

# MORNING PASS — 2026-08-17, 08:45–09:15 CDT

Continues §9–§15. Written while the third dev regrade was still running (§18).

## 16. Prod runs 5-day-old code, and I put a schema change under it

**The mistake of the night, and it is mine.** `legendarypicks-backend-1` (Docker, `127.0.0.1:8100`,
what `LP_API_BASE` points at) **bakes its code into the image** — only `backend/data` and `docs`
are bind-mounted. Up 5 days. Inside the container:

    docker exec legendarypicks-backend-1 grep -c "_link_or_fold" /app/routers/props.py
    0

So last night I applied `ux_prop_games_event` to **prod's DB** (bind-mounted, therefore live)
while `_link_or_fold` — the code that handles that constraint — **is not deployed and will not
be**. Micah, this morning: *"we never build for prod we only did db stuff."* That is the rule,
and it means **a schema change must never get ahead of the code that understands it.** Write
that down; it is the general lesson, not a one-off.

**Effect while it stood:** the ingest inserts a day-early twin (allowed — the index is partial
and blank ids are exempt), then links it in place, `IntegrityError`, and both call sites in the
*stale* container wrap that in `except Exception: pass`. The twin survives **unlinked** — no
event id, settlement never resolves a gamePk, props stranded, and indistinguishable from a
fixture ESPN has not published. Silent.

**Decision: keep the index.** Weighed both ways —

| | twins become | props | recoverable? |
|---|---|---|---|
| drop the index | duplicate rows | split across two rows | only by the merge, and the wrong-final contamination returns |
| keep it | unlinked rows | stranded on one row | **yes** — `link_prop_games.py` runs from the working dir, so it HAS the fold |

Keeping it is strictly better *provided something runs the linker against prod*. **There is no
linker timer.** That gap is now the open risk (§19).

**Healed the existing damage, DB-side only, no deploy:**
`link_prop_games.py --league mlb` against `picks.db` (cache-served, budget clean):
40 linked · `prop_games` **962 → 960** (two folded by the fold path) · unlinked MLB **44 → 4** ·
duplicate groups **0**. Exposure before the heal was 3 rows / 302 props, **all predating the
index** — so the stale container never actually produced new damage.

## 17. Timers

- **`legendarypicks-props-prod.timer`** — I stopped it at 00:47 to protect the ESPN budget and
  **restarted it 08:51**; it had missed ~2.5h (5 runs). Important correction to §13: **exit 3 is
  an end-of-run report, not an abort.** MLB kept ingesting the whole time — last capture
  `11:14:12Z`, i.e. the 06:15 run. There was never a props outage.
  Under the live scrape immediately after: `prop_games` 962 → 964, **0 duplicate groups**.
- **`legendarypicks-props.timer` (dev)** — active, healthy, last run 08:30 **exit 0**.

## 18. Dev's disagreements: dev never got the repair prod got

§13 asked why dev sat at **15/187 before AND after** while prod went 24/285 → 3/285. Answer, and
it is the inverse of [[feedback_dev_fix_prod_never_ran]]: **I repaired prod's `start_time` rows
last night and never ran the same repair on dev.** Same script, same ruler, different data — the
regrade kept faithfully re-deriving grades from a wrong instant.

Evidence: every disagreement is a 2026-08-16 game showing `graded=0.0` against a real ESPN value.
Game 1065 (event 401816561, Rangers @ Athletics) stored `2026-08-16T01:40Z`; ESPN publishes
`2026-08-16T20:05Z` — **18.4h off**, so `_fetch_mlb_gamepk` matched a *different* game and graded
all 110 props against the wrong box score. Players absent from it graded 0. `--verify` on dev:
**15 rows disagree**.

Repaired: 15 rows (offsets **+24h ×5**, +23.95h, +23h, +21.1h, +18.5h, +18.4h, +17.8h, and four
sub-hour revisions), re-verify **599/599 agree, 0 disagree**. Backfill then filled 56 more;
dev MLB rows missing `start_time` → **28**. Dev also: `prop_games` 1,087, 0 duplicate groups,
index present. **Third regrade running — its number is the test of whether the ruler moves off 15.**

## 19. Tennis — cdrc's branch works, and prod can be fixed WITHOUT a deploy

`feat/tennis-spine` @ `/root/lp-tennis-spine`, commit `0487bdb` (370-line
`backend/ingest_tennis_players.py` + 153 lines of tests). §5's "ready and unstarted" is **stale**.
It works on dev:

| | before | now |
|---|---|---|
| dev atp/wta `players` | 0 | **300** |
| dev tennis props | 0 of 310 | **439** |
| dev props service | exit 3, RED every 30 min | **exit 0** — atp 186/192, wta 168/192 |

Prod is still 0 players / 0 props — correct, the spec is dev-only.

**Worth knowing, given §16:** clearing prod's red unit does **not** need a container rebuild.
`_resolve_player_for_ingest` is **data-driven** — it reads `players` from the bind-mounted DB. So
running `ingest_tennis_players.py` against `picks.db` once the branch merges would let the *stale*
container resolve tennis names. DB-only, which is the only kind of prod change we make.

## 20. Other units failing, timers active (so they retry and fail on a loop)

- `legendarypicks-nfl-adp.service` **and** `legendarypicks-nfl-adp-prod.service` —
  `RuntimeError: D/ST preflight: def_to_pid has 0 entries, expected 32` at
  `ingest_nfl_adp.py:217`. A fail-closed preflight doing its job. **NFL ADP has not refreshed
  since ~04:10/04:15.** Given NFL is the forced product focus (07-25 §1), this is the highest-value
  open item after §19's linker gap.
- `legendarypicks-news.service` — failed on **timeout**, not exit code. Last 03:50.

## 21. Open, in priority order

1. **No linker timer for prod** — the mitigation §16 depends on is manual. Either add one, or
   accept that stranded rows accumulate until someone runs it.
2. **`start_time` write-once** — still the one confirmed recurrence (`routers/props.py:473`,
   `bovada_scraper.py:856`, UFC ~1027). **Undecided:** last-writer-wins vs only-overwrite-on-
   publisher-disagreement. I recommend the latter. Note §16: the two API-path guards live in the
   container, so fixing them changes nothing in prod until a release — the scraper-side one does take effect.
3. **NFL ADP preflight** (§20) — both dev and prod down ~5h.
4. Unconfigured-ESPN-script gate — 20 of 27. `link_prop_games.py`'s guard is the model; it fired
   correctly during last night's testing.
5. `legendarypicks-news` timeout.
6. v0.8.0: 2 gate FAILs, **98 commits unpushed**.

## 22. Backups added this pass

prod `data/picks.db.bak-2026-08-17-link` · dev `data/picks.dev.db.bak-2026-08-17-starttime`
(on top of §15's list).
