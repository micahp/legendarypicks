# Audit: `feat/sport-first-navigation` at `ff38374`

24 commits, 70 files, +4,265/-460. Built by codex in `/root/lp-sport-first-nav` against
copied databases. Nothing promoted, nothing pushed, nothing merged.

Audited 2026-08-25 against the branch frozen at `ff38374`. Claims were falsified against
publisher payloads cached **before** codex ran wherever possible, so the evidence is
independent of the work being audited.

**Verdict: the diagnoses hold. Land it.** Two things to fix on the way in, one of which is
not codex's doing.

---

## 1. Publisher claims, verified independently

### Tennis draws are in a payload we already fetch. CONFIRMED.

Against `backend/.espn-cache`, cached before the branch existed:

```
699 competitions, EVERY one carrying round.displayName
   Qualifying 1st Round 140 · Qualifying 2nd Round 64 · Qualifying Final 38
   Round 1 226 · Round 2 110 · Round 3 56 · Round 4 16
   Quarterfinal 28 · Semifinal 14 · Final 7
2 distinct tournamentId · 995 TBD competitor slots · 2 bracket links
```

So the Draws tab needs no new endpoint and no new request path. This also closes the open
question left in the `dev` copy of `DESIGN-sport-first-navigation.md`, which said the draw
source was unmeasured.

**Its honesty catch is real and visible in the same data.** There is exactly ONE bracket link
per event and it is `type/1`, the men's draw, advertised even inside the WTA response.
Withholding the WTA link rather than mislabeling it is correct.

### NFL settlement was a case mismatch. CONFIRMED.

ESPN's published NFL boxscore columns, read from production:

```
passing    ['C/ATT','YDS','AVG','TD','INT','SACKS','RTG']
rushing    ['CAR','YDS','AVG','TD','LONG']
receiving  ['REC','YDS','AVG','TD','LONG','TGTS']
fumbles    ['FUM','LOST','REC']
defensive  ['TOT','SOLO','SACKS','TFL','PD','QB HTS','TD']
```

`YDS`, while the map asks for `Yds`. **The fix is the right shape**: it case-folds both sides
rather than hardcoding uppercase, and parses `made/attempted` (`2/2`) by numerator with a
fail-closed on malformed pairs.

**Collision risk checked, and it is safe.** Folding could have widened a match, since `REC`
means receptions in one group and recoveries in another and `YDS` appears in four groups.
`boxscore_extract.py:71` matches the stat category before the labels, so folding inside an
already-scoped group cannot collide.

**Bonus finding, unrelated to the branch:** the same payload publishes `TGTS`, `FUM` and a
per-group `TD`. So targets, fumbles, rushing TDs and receiving TDs are all gradeable on the
publisher side. The only missing half for fumbles is that no book we relay publishes the
prop. That closes both halves of the open question in `ROADMAP-2.md` §3b.

### Scoring plays were read from the wrong key. CONFIRMED by implementation.

The code branches on what each publisher actually exposes: `keyEvents` for soccer,
`scoringPlays` for college football, `plays` elsewhere, with a `prefiltered_scoring` flag
for the nuance that NCAAF's entries omit the redundant `scoringPlay=true` so the collection
itself is the publisher's filter.

### NCAAF's week query caps at 25. NOT INDEPENDENTLY VERIFIED.

Verifying it costs an ESPN request against a budget that was refused twice today, so it was
not spent. The implementation is documented in the docstring and is sound regardless of the
exact cap: NCAAF fetches the calendar's own published start/end dates as a range plus
`groups=80`, re-applies the strict season/type/week filter, and **fails closed when the
published start/end are missing** rather than silently returning a partial slate. NFL keeps
its existing single-week request.

---

## 2. The verification gap, which is about reporting rather than code

Codex reported "100 backend tests pass" and "34 focused tests pass". Both numbers were true
and both surfaces were far smaller than they sounded.

```
run 1  unittest in the worktree      1,116 ran   38 errors   ModuleNotFoundError: pytest
run 2  those 38 modules via venv       578 pass  4 skipped  6 xfailed  0 FAIL
run 3  after pip install pytest      1,086 ran    8 errors   ModuleNotFoundError: httpx
run 4  after pip install httpx       1,190 ran    OK, 0 errors, 3 skipped
```

**Thirty-eight modules never loaded at all**, and codex knew: its own log says *"this
worktree has no pytest installation. I'm converting the two small regression checks to the
repository's standard-library unittest shape so verification does not require installing
anything."* That resolved the two files it was writing and left the other 38 silently absent
from every run it reported.

**Three of the unloaded modules are its own new tests for this branch's work:**
`test_tennis_draws`, `test_cleanup_empty_mlb_team_game_stats`, `test_game_props_results`.

**There is no defect behind the gap.** All 578 pass, and the full suite is now
`Ran 1190 tests ... OK`. This is `feedback_a_green_gate_is_a_claim_about_its_surface`: read
the surface, not the number. `pytest` and `httpx` are now installed for the system
interpreter so the worktree can run the whole suite.

---

## 3. Findings to act on

### 3a. The NCAAF week route reads ESPN from the SERVING path, with a 20 second TTL

`espn_client/nfl.py:101` is `espn_client._get(url, ttl=20)` on the week-games read, which a
page load reaches.

**This is not a regression codex introduced.** `dev` already had `ttl=20` on the same line
for NFL. But the branch **widens its blast radius on the worst possible date**:

- NFL's request is one `week=` query. **NCAAF's is `dates={start}-{end}&limit=1000&groups=80`**,
  a whole week of up to 99 games, a far larger response.
- **NCAAF opens 2026-08-29**, the one dated item on the roadmap and the traffic peak.
- Today that same budget was refused twice, and **13 of those refusals landed on uvicorn**,
  the live serving path (`CONTEXT-2026-08-24.md` §11).

A 20 second TTL means every page load more than 20 seconds apart spends a publisher request
from the request handler. Raise the TTL for the NCAAF path, or serve it from the store the
way the tennis draws route does, before opening weekend. Related and already recorded:
`feedback_serving_path_must_not_enforce_a_batch_budget` is the sibling shape.

### 3b. Two files conflict, both docs, no code

```
docs/DESIGN-sport-first-navigation.md
docs/ROADMAP.md
```

Nine conflicting hunks, and nothing else. Resolve both by hand.

**On the design doc, take codex's version on one specific point.** The `dev` copy says to
derive the sport from `backend/espn_leagues.py`. That file holds only MLS and NCAAF. The
complete published ESPN path registry is `backend/espn_client/config.py`, which is what the
implementation uses. The `dev` copy is wrong there.

---

## 4. Clean

- **No out-of-repo changes.** Every changed path is in-tree, and the diff contains no new
  reference to systemd, cron, `.timer`, `.service` or `/etc`. This was the failure shape of
  the 2026-08-18 split, so it was checked rather than assumed.
- **The tennis serving route is DB-only**, as claimed: *"this serving route never calls
  ESPN."*
- **No new name-keyed trust list.** The new membership checks are on league keys, not on
  publisher-supplied names.
- Worktree clean at `ff38374`, both copied databases pass `PRAGMA quick_check`.

---

## 5. Not audited

Claims left unverified because they need either an ESPN request or a full re-derivation, and
none of them gate the merge:

- The World Cup split of 392 null rows into 267 numeric grades and 125 published DNP voids.
  The method described is sound (roster participation read from the official summaries, not
  inferred from our own ingest) but the numbers were not recomputed.
- The tennis start-time drift measurement, 112 of 142 ATP rows having exactly one candidate
  match in the adjacent-date window.
- The MLS catch-up counts and the migration ledger rehearsal.

All of them are candidate-only numbers on a copied database. **None of them are production
state**, and the branch does not claim they are.
