# TASK — one name collision blocks all 30 MLB rosters

**Owner:** delegated (reasonix / deepseek-v4-flash)
**Status:** not started
**Written:** 2026-08-05

---

## Do NOT use a worktree

`scripts/hermes-worktree.sh` symlinks **only** `picks.dev.db`, never `picks.db`. Pointing
`--db` at `data/picks.db` from a worktree makes sqlite **create a new empty database** and
every check then passes against nothing. Work in `/root/legendarypicks`, absolute DB paths.

---

## Where this stands

The dedupe is **done and verified** on prod: 2750 → 2433 mlb players (−317), player_stats
−188, duplicate `mlbam_id` groups **0**, orphan delta **0**, `quick_check` ok, and
`G/published-identity` still **PASS**. Your Step 8 stop was the right call.

`roster_sync mlb` now gets much further than before — no more `identity_incomplete`, no
`ambiguous_normalized_name` at all — and dies at the contract check instead:

```
roster_membership.RosterContractError: roster snapshot has duplicate canonical player IDs
```

I instrumented `publish_roster_snapshot` to dump the collision. It is **exactly one row out
of 783**:

```
memberships=783  distinct_players=782  duplicate_ids=1

player_id=113  db=(113, 'Max Muncy', team='LAD', mlbam_id=571970, espn_id=None, active=1)
    entry team=LAD  source_player_key=33303
    entry team=ATH  source_player_key=4872686
```

Both ESPN roster entries resolved to the **same** `players` row. They are two different
people. MLB publishes both as `Max Muncy` (`571970` and `691777` — check
`backend/data/published-identity-names.json`), and both rows exist and are correct:

```
id=96   'Max P. Muncy'  team=ATH  mlbam_id=691777
id=113  'Max Muncy'     team=LAD  mlbam_id=571970
```

## The bug

`backend/roster_sync.py` around line 219:

```python
candidates = name_to_rows.get(_normalize_name(name), [])
...
if len(candidates) > 1:        # <- the disambiguation ladder only runs HERE
    narrowed = [c for c in candidates if c["espn_id"] and str(c["espn_id"]) == eid]
    if len(narrowed) != 1:
        narrowed = [c for c in candidates if str(c["team"] or "").upper() == abbr]
    if len(narrowed) == 1:
        candidates = narrowed
```

`_normalize_name` (from `sports_service`) does **not** strip a bare middle initial, so
`'Max P. Muncy'` and `'Max Muncy'` land in **different buckets**. ESPN publishes the ATH
one as plain `Max Muncy`, which finds exactly **one** candidate — id=113, the *Dodger* —
and `len(candidates) > 1` is false, so the team-narrowing that exists precisely for this
case is **never reached**. The wrong match does not raise; it silently assigns the ATH
Muncy the LAD Muncy's `player_id`.

The comment above that block literally says "there are two Max Muncys". The ladder is
correct. It is being bypassed.

## The fix

**Bucket homonyms together so the existing ladder can do its job.** Build `name_to_rows`
on a key that also strips a bare middle initial, and look up with the same key — the same
normalisation `audit_league_stats._identity_name_key` already uses for exactly this reason
(its comment: *"MLB publishes BOTH Max Muncys as 'Max Muncy'"*). Then both rows are
candidates, `len(candidates) > 1` is true, and team-narrowing picks id=96 for ATH and
id=113 for LAD.

Constraints:

* **Do not change `_normalize_name` in `sports_service`.** It is used elsewhere; widening it
  globally is a different, riskier change. Do the extra stripping locally in `roster_sync.py`
  where the index is built and read, so both sides use one key.
* **Do not relax the contract check** in `roster_membership.py`. It caught a real wrong
  match — that is the gate working. Leave it exactly as strict as it is.
* **Do not lower `_MAX_UNRESOLVABLE_SHARE`** or set `LP_ROSTER_MAX_UNRESOLVABLE`.
* If widening the bucket makes some *other* pair newly ambiguous and team cannot separate
  them, that is a correct `ambiguous_normalized_name` and goes to the review queue. Report
  the count; do not force it through.

Add a regression test in `backend/test_roster_sync.py` (or the nearest existing roster test
file) covering the two Muncys: two source entries, plain `Max Muncy` on ATH and LAD, two DB
rows `Max P. Muncy`/ATH and `Max Muncy`/LAD, asserting they resolve to **different**
`player_id`s. A fix without this test will re-break the next time someone touches
normalisation.

Commit:

```
fix(roster): bucket middle-initial homonyms so team-narrowing can separate them
```

---

## Run it

1. Back up prod (`data/picks.db.pre-roster-muncy-<UTC>.bak`), `quick_check` must print `ok`.
2. `venv/bin/python -m pytest test_roster_sync.py -q` (or the file you added to) — green.
3. `LP_DB_PATH=/root/legendarypicks/backend/data/picks.db venv/bin/python roster_sync.py mlb 2>&1 | tail -25`
   Expect `complete`, **30/30 teams**, and MLB active dropping from 2,433 to roughly **783**
   (the number ESPN actually publishes).
4. Re-run the identity gate — it was green before you started and must still be:
   `venv/bin/python audit_league_stats.py --league mlb --db /root/legendarypicks/backend/data/picks.db`
   `G/published-identity` must read **PASS**.
5. Confirm id=96 and id=113 ended up on **different** teams in `roster_memberships`, and
   that both are present.

If step 3 still fails, **report the failure verbatim and stop.** Do not work around it.

---

## Out of scope

* `sports_service._normalize_name`, `roster_membership.py`, the identity gate, other leagues.
* The 168 pre-existing orphans (`props` 78, `roster_snap` 90) — known, not yours.
* Docker: no build, no `up`, no restart. Prod is serving live.
* Host config: `/etc`, systemd, timers, cron. **Note the props timers write to this same DB
  every 30 min** — if a run collides with one, say so rather than retrying blindly.
* `git push`. Commit locally.

---

## Report back between `===RESULT===` and `===END===`

1. Backup filename.
2. The test you added and its result.
3. Step 3's status line **verbatim** and the final MLB active count.
4. Step 4's `G/published-identity` line **verbatim**.
5. Step 5's two rows.
6. Any newly-ambiguous players the wider bucket produced, with counts.
7. `git -C /root/legendarypicks status --short` and `git log --oneline -2`.

Then stop and wait.
