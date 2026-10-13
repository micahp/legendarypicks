# Player identity across the props pipeline — audit, 2026-09-06

Written after reading all 87 `docs/CONTEXT-*` summaries and measuring both managed databases
read-only. Every number below came from a query run today or a line of code read today.

**Disclosure.** I am not a neutral auditor. I wrote `league_membership.py`, the
`/api/props/ingest` fixture guard, `audit_foreign_fixtures.py` and `ingest_registry.py`
earlier the same day, and I relabelled and folded production rows. Where a finding concerns
those surfaces I have given the measurement rather than the verdict.

---

## The three findings that change what to build next

### 1. The drift is real, and the tools already defend against it. The scripts do not.

`players.id` is a local autoincrement key and the two databases assigned it independently:

```
shared players.id between dev and prod   47,231
naming a genuinely different person       6,558   (13.9%, accent-folded)
duplicate (league, espn_id) within dev         0
duplicate (league, espn_id) within prod        0

id=29174   prod "Max Kepler" (mlb)    dev "Paul George" (nba)
by (prod league, dev league): nfl/nfl 1937, ncaaf/ncaaf 1709, mls/ncaaf 722,
                              ligamx/ufc 295, ncaaf/cs2 227
```

Neither database is corrupt. They are simply not comparable by id.

**Every cross-database tool already knows this.** `migrate_logs_to_prod` compares an
`_identity()` and excludes mismatches (237 today) while remapping by stable key (414);
`migrate_nfl_stats_to_prod` joins `(league, source_player_key, season, game_no)`;
`promote_mls_player_stats` keys on `espn_id` and its docstring says why in as many words;
the UFCStats merges bridge on `espn_id`, never on the source's hex hash.

So cross-database work is **not** where the exposure is. The exposure is single-database
repair, below.

### 2. The exposure is intra-database: 12 scripts delete from `players`, and they disagree

Measured today, rows pointing at a `players.id` that no longer exists:

```
prod   roster_snap 90, player_game_logs 39                      = 129
dev    roster_snap 90, player_game_logs 6, nfl_mock_draft_picks 2 =  98
```

One of those 39 (`player_id=33312`, six MLS logs) aborted the entire MLS log migration with
`KeyError: 33312`, leaving 10,574 real rows unmigrated until it was fixed today.

`spine_merge.py` already solves this correctly and has since 2026-08-24: it discovers
referencing columns from the schema every run, from foreign keys plus the `*player_id`
convention, and deliberately excludes `nfl_adp.espn_player_id` because that holds a
publisher's id. 14 columns carry a `player_id`; only 5 declare a foreign key, so 9 are
unenforced and an orphan raises nowhere.

The superseded per-league dedupers touch 5, 3 and 1 of those columns respectively.

### 3. The real defect is not knowledge. It is that knowledge was stored as prose.

All of finding 2 was measured, solved and written down on 2026-08-24, in
`CONTEXT-2026-08-24.md` §16. Three weeks later:

- all five superseded scripts were still present and runnable
- `AGENTS.md:156` still instructed agents to use `dedupe_mlb.py` / `dedupe_nfl.py`
- `spine_merge.py` was referenced by no unit, no cron, no runner
- the 129 orphans above accumulated
- **and today I wrote `player_merge.py`, a worse copy of `spine_merge.py`, because I never
  found the original.** I deleted it on reading the summary.

This is the same shape as an ingest that exists and is scheduled by nothing. The knowledge
was never the missing part.

---

## What was changed today, and what was only reported

**Changed.** `superseded.py` refuses at the moment of the mistake: the three scripts print
what replaced them, when, why in measured terms, and how to read the old behaviour in git,
then exit 2. Fatal rather than a warning, because a warning on a repair script is read after
the repair has deleted rows. `AGENTS.md` now names `spine_merge.py` and only that.
`migrate_logs_to_prod` now counts and skips an orphan log instead of aborting.

**Re-armed.** `test_spine_merge`'s column pin is, by its own docstring, "the thing that fails
when the schema grows." It *was* failing, sitting red inside the eight pre-existing suite
failures nobody re-reads — the same disease as an alarm that is red every run. Prod has
gained `player_game_logs_usopen` and `tennis_ranking_snapshots` since the pin was set, dev
also `nfl_published_fantasy_points`. Re-pinned to 18 and 19.

**Reported, not repaired.** The 129 prod and 98 dev orphans still exist. They are safe to
leave (a row that stops joining is invisible rather than wrong) but they are also the
evidence that the ad-hoc path was used, so they should be cleared once, deliberately, with
the count asserted afterwards.

---

## Portable identity: better than expected, except where it is structural

Active players with **no** portable key of any kind (`espn_id`, `mlbam_id`, `nfl_gsis_id`,
`nhl_id`, `nba_id`):

```
prod   41 of 30,603 active   (0.13%)   mls 27, ufc 12, wc 2
dev   377 of 31,502 active   (1.20%)   cs2 227, wc 93, mls 26, ufc 17, valorant 14
```

Dev's number is dominated by esports, which is structural: no ESPN id exists for a CS2 or
Valorant player, so `player_source_ids` is the right home and already covers 253 of dev's
377. Prod's 27 MLS rows are the live blocker: shadow players minted from a sportsbook display
name, `espn_id=None`, `updated_at=None`, 26 of 27 carrying props, and **none has a published
twin to merge into** — so this is not a merge, it is a missing publisher lookup.

---

## Recommendations, in the order I would do them

1. **Clear the 129 + 98 orphans once**, through `spine_merge`, and add the count to a gate so
   it cannot grow again silently. The number is small; the point is the assertion.
2. **Schedule `spine_merge` detection** (not repair) in `ingest_registry`, so duplicate groups
   and orphans are reported on a cadence. `props_coverage.py` already gates suspected
   duplicates and is referenced by a unit; orphans are not gated at all.
3. **Fill the 27 MLS positions from a non-ESPN publisher.** FotMob's team endpoint carries
   `positionId` per squad member, and we already depend on FotMob for MLS appearances. This
   closes the last two release-audit FAILs.
4. **Give `prop_game_merge` the same treatment as `spine_merge`.** Its `_REFERENCING_TABLES`
   is hardcoded with a comment asking the next person to extend it. It is correct today —
   the other 13 `game_id` columns really do hold publisher ids — but its correctness rests on
   a 2026-08-19 verification and a human's memory.
5. **Extend `superseded.py` as the last step of any replacement.** Two entries were added
   today from one context summary; several of the 87 describe replacements whose originals
   may still be runnable.

---

## What I could not answer, and what would settle it

- **Whether any current path still deletes a player without repointing.** I found the twelve
  callers and guarded the three named as superseded, but I did not read the other nine line
  by line. The orphan counts are the symptom; a run of `spine_merge`'s detection on a
  schedule would tell us whether they are still growing.
- **Whether id drift has ever caused a wrong join in production**, as opposed to a refused
  migration. Every cross-db tool checks identity, so I found no path that would, but "I found
  none" is weaker than "there is none".
- **Whether the 6,558 drifted ids matter to anything other than migration.** If nothing else
  compares ids across databases, drift is inert and the correct response is to document it
  rather than renumber anything. Renumbering would be a large, risky change to fix a problem
  that may have no remaining consumer.

## Release-audit status (the reason this started)

```
before   FAIL mls D/leaders-reach-logs   331 of 850 (39%)
after    gone       8,334 logs + 1 player migrated to prod, verified backup,
                    protected tables checksum-unchanged

remaining  FAIL mls C/vocabulary[position]        27 of 1260 blank
           FAIL mls C/vocabulary[position_group]  28 of 1260 blank
           UNVERIFIED mls B/position-content[GK]  no GK game logs at all
```

Blocking leagues (NFL, MLB, NBA, NHL, UFC, NCAAF) pass: 92 checks, 0 failures.
