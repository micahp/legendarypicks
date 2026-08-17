# TASK — unblock the MLB dedupe: 188 `player_stats` key collisions

**Owner:** delegated (reasonix / deepseek-v4-flash)
**Status:** not started
**Written:** 2026-08-05 (early)

---

## Do NOT use a worktree

`scripts/hermes-worktree.sh` symlinks **only** `picks.dev.db`, never `picks.db`. Pointing
`--db` at `data/picks.db` from a worktree makes sqlite **create a new empty database**, and
every step then reports a clean run against nothing.

Work in `/root/legendarypicks`. Use **absolute** DB paths.

---

## Where this stands — read before touching anything

The identity corruption that was blocking this is **fixed and shipped** (v0.7.5). All 317
duplicate `mlbam_id` groups are now genuinely the same person — the count of groups spanning
two *different* people is **0**, down from 124. `dedupe_mlb.py` is finally safe to run.

It still doesn't complete. Tonight's `--apply` on prod **raised and rolled back**:

```
sqlite3.IntegrityError: UNIQUE constraint failed:
  player_stats.player_id, player_stats.league, player_stats.season, player_stats.stat_type
```

**Prod is intact.** Verified after the abort: 2750 mlb players, 317 dup groups, and
`player_game_logs` 146517 / `props` 530932 / `player_stats` 4661 / `roster_memberships` 4537
/ `roster_snap` 97 — every count identical to before. Backup at
`backend/data/picks.db.pre-mlb-dedupe-20260805T010256Z.bak`, `quick_check` = ok.

`roster_sync mlb` was re-run afterwards and is still `identity_incomplete`, 30/30 teams,
**0 applied**, every failure now `ambiguous_normalized_name`. That is expected and is *not* a
regression: the identity repair renamed 223 rows to their published names, which makes the
duplicate pairs collide on name more often than before. The dedupe is the prerequisite. Do
not touch `roster_sync.py`.

---

## The actual defect

**188 of the 317 groups have both rows carrying a `player_stats` row for the same
`(league, season, stat_type)`.** Repointing the duplicate's `player_id` to the canonical id
therefore violates the UNIQUE index, and `dedupe_mlb.py` has no handling for it.

They are **not** complementary rows from two publishers. Both are `source='statcast'` —
two partial pulls of the same player under two different `player_id`s, at different points
in the season:

```
player_id=26553  statcast  games=64  avg=0.278  hr=6  woba=0.346   <- canonical
player_id=29073  statcast  games=86  avg=0.260  hr=8  woba=0.324   <- duplicate, LATER pull

player_id=26559  statcast  games=69  avg=0.216  hr=2  woba=0.274   <- canonical
player_id=29129  statcast  games=90  avg=0.216  hr=3  woba=0.267   <- duplicate, LATER pull
```

So `COALESCE`-merging the two rows would be wrong — it would blend two snapshots of the
same measurement into a number that was never true at any moment. **One row has to win
whole.**

### The rule — use exactly this, do not invent your own

For a colliding `(player_id, league, season, stat_type)`, keep **one** row:

1. higher `games` wins (season-to-date counting stats only grow, so this is the later pull);
2. if `games` ties or either is NULL, the row with more non-NULL stat columns wins;
3. if still tied, the lower `rowid` wins.

Delete the loser. Then repoint as normal. If the winner is the duplicate's row, the
canonical's row is the one deleted — that is correct and intended; the surviving row must
end up carrying the canonical `player_id`.

---

## What to change

`backend/dedupe_mlb.py` only. One commit.

* Resolve collisions **inside the same transaction** as the repoint, before the `UPDATE`
  that would violate the constraint.
* Report the collisions resolved in both dry-run and apply output — a count, plus which
  side won, e.g. `collisions resolved: 188 (canonical kept 41, duplicate kept 147)`.
* **The dry run must not write.** It currently reports `references repointed: {...}` without
  touching anything; keep that property.

**Also fix, same file, same commit — the run currently reports something false:**

* **Drop `predictions` from `REF_TABLES`.** It has **no `player_id` column** at all — it is
  game-level (`game_id`, `league`, `predicted_winner`, `correct`). There is nothing to
  repoint, and listing it only manufactures a reassuring zero.
* **Stop swallowing `sqlite3.OperationalError` in the repoint loop — let it raise.** All five
  remaining `REF_TABLES` (`player_game_logs`, `props`, `player_stats`, `roster_memberships`,
  `roster_snap`) are verified to have a `player_id` column, so nothing legitimate can raise
  there; a future missing or misspelled table name must fail loudly instead of printing `0`.

  Together these close a real hole: `references repointed: {'predictions': 0}` reads as
  "checked, nothing to do" when the truth is "never checked". A count that cannot fail is not
  evidence.

Report but do **not** fix:

* **168 pre-existing orphans**, present right now with no dedupe applied: `props` **78**,
  `roster_snap` **90** rows whose `player_id` matches no row in `players`. These are not
  yours to fix tonight, but the post-apply orphan check must not be allowed to hide behind
  them — measure orphans **before and after** and assert the delta is **0**, not that the
  total is 0.

Commit message:

```
fix(dedupe): resolve player_stats key collisions before repointing

Also drop `predictions` from REF_TABLES (no player_id column — game-level)
and let the repoint loop raise instead of swallowing OperationalError, so a
missing table fails loudly rather than reporting a repoint count of zero.
```

---

## Run it, in this order

1. **Back up prod**, record the filename, `pragma quick_check` must print `ok`.
2. **Record before-counts**: mlb players, dup mlbam groups, and row counts for
   `player_game_logs`, `props`, `player_stats`, `predictions`, `roster_memberships`,
   `roster_snap` — plus the orphan count per table.
3. **Dry run.** Expect 317 groups, 317 rows merged, 188 collisions resolved. If the numbers
   differ materially, **stop and report** — do not apply.
4. **Apply.**
5. **Verify.** All of these, and every one must hold:
   * `dup mlbam groups` = **0**
   * orphan delta vs step 2 = **0** per table
   * `players` count down by exactly **317**
   * `player_stats` down by exactly the number of collisions resolved, and **no other table's
     count changed at all** — repointing moves rows between players, it never deletes them
   * `pragma quick_check` = ok
   If any fails, **stop and report**; step 1's backup is the restore path.
6. **Re-fill the spine** — the fill keys by `mlbam_id` in a dict, so for a duplicate pair
   only one row ever got `team`/`position` and the survivor may be the one that missed out:
   ```
   venv/bin/python ingest_mlb_spine_identity.py --season 2026 \
     --db /root/legendarypicks/backend/data/picks.db
   ```
7. **Re-run the identity gate** — it was green before you started and must still be:
   ```
   venv/bin/python audit_league_stats.py --league mlb \
     --db /root/legendarypicks/backend/data/picks.db
   ```
   `G/published-identity` must read **PASS**. A dedupe that deletes the wrong row of a pair
   would show up here.
8. **Re-run roster_sync** — the payoff:
   ```
   LP_DB_PATH=/root/legendarypicks/backend/data/picks.db venv/bin/python roster_sync.py mlb 2>&1 | tail -25
   ```
   Expect `complete`, 30/30, and MLB active dropping from 2,750 to roughly **785**.
   If it still says `identity_incomplete`, **that is a valid answer** — report the
   unresolvable count and the reasons, and stop.

**Do NOT** lower `_MAX_UNRESOLVABLE_SHARE`, set `LP_ROSTER_MAX_UNRESOLVABLE`, or edit the
matching logic. The floor is the safety property; making it pass by moving it writes a wrong
roster.

---

## Out of scope

* Any file other than `backend/dedupe_mlb.py`.
* `roster_sync.py`, the identity gate, `repair_mlb_identity_names.py`, other leagues.
* Fixing the 168 pre-existing orphans or the `predictions` column gap — report only.
* Docker: no build, no `up`, no restart. Prod is serving live.
* Host config: `/etc`, systemd units, timers, cron.
* `git push`. Commit locally.
* Deleting any backup.

---

## Report back, between the literal markers `===RESULT===` and `===END===`

1. Backup filename.
2. Before vs after counts, side by side, including orphans per table.
3. Collisions resolved, split by which side won.
4. Step 7's `G/published-identity` line **verbatim**.
5. Step 8's status line **verbatim** and the final MLB active count.
6. The 168 pre-existing orphans, restated with their per-table numbers (report only), and
   confirmation that `predictions` no longer appears in the repoint output at all.
7. `git -C /root/legendarypicks status --short` and `git log --oneline -2`.

If a step failed, say which, and say what you did **not** do because of it. A partial run
reported honestly beats a clean-sounding summary. Then stop and wait.
