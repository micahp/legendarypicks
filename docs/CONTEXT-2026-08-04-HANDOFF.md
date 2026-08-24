# Handoff — 2026-08-04

Branch `dev`, 8 commits ahead of the last push at `1cce908`/`76556d1`. Everything
below was measured today against `backend/data/picks.db` (prod) and
`picks.dev.db` (dev), not remembered.

---

## 1. What landed

| commit | what |
|---|---|
| `f577267` | NBA ESPN ingest paced + backoff, with tests that fail without it |
| `7051d4b` | Ported `plan_mlb_identity_repairs` — the rescued WIP could not even import |
| `1cce908` | MLB rebuild fixture given a prop on a deleted player; 4/4 green |
| `76556d1` | NHL: 14 columns, `ingest_nhl_season_stats.py`, three player types |

Also: restored `backend/scripts/README-merge-nba-identities.md`, which a
delegated session emptied to 0 lines; removed its byte-identical duplicates of
`merge_nba_identities.py`/`test_merge_nba_identities.py` from `backend/` root
(the tracked copies live in `backend/scripts/`), and a 0-byte stray
`backend/picks.dev.db`.

---

## 2. LIVE PROD BREAKAGE — scores and standings are 500

**This is the top item.** Not a code regression; an upstream host is refusing us.

```
/api/nba/games      500      <- the scores page
/api/nba/strength   500      <- standings tab
/api/nfl/strength   500
/api/nhl/strength   500
/api/nba/leaders    200      (serves 2023, see §3)
/api/nhl/leaders    200
```

Traceback from `docker logs legendarypicks-backend-1`:

```
File "/app/espn_client.py", line 172, in games
    d = _get(_SITE.format(path=path) + "/scoreboard" + q, ttl=20)
urllib.error.HTTPError: HTTP Error 403: Forbidden
```

### The host map is the whole story

`backend/espn_client.py:83-86`:

| constant | host | status from this box |
|---|---|---|
| `_SITE` | `site.api.espn.com` | **403** |
| `_CORE` | `site.api.espn.com` | **403** (same host, despite the name) |
| `_COMMON` | `site.web.api.espn.com` | 200 |
| `_SPORTS_CORE` | `sports.core.api.espn.com` | 200 |

Scores and standings both go through `_SITE`. Two other hosts answer fine. So
this is **not** an IP ban on ESPN — it is one host refusing this box.

I said earlier today that ESPN had walled the box outright, based on a check
that only probed `sports.core`. That host recovered on its own; `site.api` did
not. Correction stands: the block is per-host, and it lifts.

### What to do

1. **Make a 403 degrade instead of 500.** An upstream refusal should serve the
   last good payload or an explicit "standings unavailable", never a 500. The
   page currently renders "No data available for NBA", which is the honest
   string over a dishonest cause — it reads as *we have no standings data*
   rather than *we could not reach the publisher just now*.
2. **Move the reads off `_SITE`.** `sports.core.api.espn.com` publishes
   scoreboard and standings collections and answers from here today. This is
   the durable fix; `site.api` recovering is not something we control.
3. Do **not** retry harder. See §5.

---

## 3. NBA league page — what it would take

The page is stale, not broken, and the cause is a contract doing its job.

`backend/league_stats.py:141-144`:

```python
if normalized_league == "nba":
    if int(season) <= 2023:
        return normalized_source == "hoopR"
    return normalized_source == "espn_core"
```

`canonical_population_sql` filters the leaderboard to rows whose source *owns*
that season, and the endpoint takes `MAX(season)` over the survivors.

**`espn_core` has published zero rows. Ever. For any league.**

```
statcast                 mlb   2653
hoopR                    nba    525     <- all season 2023
nflverse_regular_season  nfl    608
nhle.com                 nhl    875
```

So NBA leaders serve 2022-23 (Embiid 33.0 in 68 games) because the only source
allowed to own anything newer has never run. `ingest_nba_stats.py` is the
writer, it is not scheduled, and it cannot complete from this box (§5).

That also explains the 575 NBA "2026" rows a prior session deleted as
unreachable: written by a non-owning source, so the ownership filter excluded
them from every query. Invisible by design, not by accident.

### Current state, measured

| check | prod | dev |
|---|---|---|
| A/required-stats | PASS | PASS |
| C/vocabulary[position] | FAIL — `C,F,G` **and** `PF,PG,SF,SG` | FAIL, same |
| C/vocabulary[team] | FAIL — 48 blank | FAIL — 48 blank |
| D/leaders-reach-logs | FAIL — season 2023, 53/525 (10%) | PASS — season 2023, 317/525 (60%) |
| F/identity-crosswalk | FAIL — 269 split | PASS |

`nba_2026_logs`: prod 23,749 · dev 28,731. **We already hold the games.**

A delegated session applied `merge_nba_identities.py` to **dev only** (272
pairs). It works — crosswalk FAIL→PASS, leaders-reach-logs 10%→60%. Note the
season label did not move: it is still 2023. Deduping identities does not make
the leaderboard current.

### The four steps, in order

1. **Apply `merge_nba_identities.py` to prod.** Ready, tests 2/2, verified on a
   prod copy. Takes its own backup and refuses unless you state the counts:
   `--expect-pairs 269 --expect-moved player_stats=261`. *(269 on prod, 272 on
   dev — the spines have diverged; re-plan before applying.)* Independent of
   everything else. **Not applied — your call.**
2. **Get `espn_core` to publish 2025-26.** The blocker. See §5. Without this the
   page stays on 2023 no matter what else is fixed.
3. **Normalise the position vocabulary.** `C,F,G` and `PF,PG,SF,SG` are two
   ingests that do not join. Pick the published one and migrate at the ingest,
   never in a query.
4. **Make the page explain itself.** Per `.claude/skills/honest-data-ui`: while
   the leaderboard is 2022-23, the page must *say* it is 2022-23 and why —
   absence gets the accent, not achievement. A three-year-old leaderboard
   rendered as if current is the actual product defect; the staleness is
   upstream, the silence is ours. Load that skill when writing the spec.

---

## 4. NHL — goalies and defencemen (landed on dev, not prod)

Hockey has three player types. The schema had columns for one.

Every goalie row read `0 goals, 0 assists, 0 shots`. Defencemen had nowhere to
record a block or a hit. It was never a missing publisher — nhle.com publishes
all of it, league-wide, and always has.

Landed: 14 columns, `ingest_nhl_season_stats.py` (goalie/summary +
skater/summary + skater/realtime, ~20 requests for the league vs ~800 for the
per-player endpoint), tests 10/10.

Dev result: `A/required-stats` FAIL→PASS, `B/position-content[G]` FAIL→PASS,
78 goalies, **63,525 saves**. Top: Saros 1,519 · Vejmelka 1,458 · Thompson 1,447.

Also fixed a defect that was corrupting live skater numbers: `ingest_nhl.py`
read `seasonTotals[-1]` with no filter on competition. On Frederik Andersen
that row was the **postseason** (16 GP) while his published regular season was
35 GP, 16-14, .874. Other players' last rows are AHL, Olympic or Swedish league
lines. The new ingest asks for `gameTypeId=2` explicitly and fails closed on a
short page.

### Open, and deliberately red: `B/position-content[D]`

`saves`, `blockedShots`, `hits`, `takeaways`, `giveaways` are **all published
per game** — by `gamecenter/{gameId}/boxscore`, which the log ingest does not
read. The endpoint it does read (`player/{id}/game-log`) publishes none of them.

Verified on game `2025021269`: boxscore gives `saves 26`, `shotsAgainst 27`,
`blockedShots`/`hits` per skater — **and two goalies on one side** (Andersen
26 saves, Bussi 0 saves / 00:00). That last detail is why this matters: a game
is not one goalie, and a derived `saves` is where that assumption gets punished.

`ingest_nhl_logs.py` currently derives `saves = shotsAgainst - goalsAgainst` and
stamps every such row `saves_derived: true`. **That marker exists so the
boxscore pass can find and replace them. Do not widen the pattern.**

**Next:** a boxscore-based per-game ingest. One request per game (~1,312 for a
season) covering every player in that game at once — cheaper than per-player and
it delivers published `saves`, `blockedShots`, `hits`, `takeaways`, `giveaways`
in the same pass. That closes `B/position-content[D]` and replaces the only
derived value in the NHL surface.

Prod still has none of this: the columns do not exist there yet. Run
`migrate_nhl_goalie_columns.py --apply` then `ingest_nhl_season_stats.py`.

---

## 5. ESPN pacing — the hard blocker

`ingest_nba_stats.py` had no pacing: ~520 requests as fast as the socket
allowed, aborting the whole snapshot on the first non-404. It tripped a block
that also took out the live Standings tab, since both use ESPN hosts.

Now paced (`LP_ESPN_MIN_INTERVAL`, default 0.5s) with backoff over 403/429/5xx
honouring `Retry-After`. **It is still not enough:**

| pacing | how far it got |
|---|---|
| 1.0s | 143 of 643 athletes |
| 2.0s | 21 (delegated session) |
| 5.0s | 0 rows after 10+ min |

Slower pacing is not converging, which means this is not a simple rate ceiling —
the box is on a low-trust bucket and a *sustained* series is what trips it,
regardless of gap.

**Do not just raise the interval again.** What is actually needed:

1. **Resumability.** Every failed run re-burns the athletes it already fetched.
   A payload cache keyed `(season, espn_id)` would let a run continue instead of
   restarting from zero — this alone may make a slow trickle viable.
2. **A different egress.** The durable answer. `lm-api-reads.fantasy.espn.com`
   still answers, which is why the D/ST fantasy ingest worked fine.
3. Bulk endpoints over per-athlete ones where they exist —
   `site.web.api.espn.com/apis/common/v3/.../statistics/byathlete` answered 200
   today and returns many athletes per call. Worth testing as a replacement for
   the 643-request loop.

---

## 6. MLB identity reconciliation — verified, blocked on regeneration

The rescued WIP now runs. Its missing import (`plan_mlb_identity_repairs`) was
never lost — it was tracked on four `codex/*` branches. Both documented test
failures were one gap in the fixture, not two bugs: no prop sat on a player the
plan deletes, so the test named "preserves props" never exercised preservation.

Real run, prod as candidate and dev as the clean reference (prod has 317
duplicate MLBAM groups; dev has 0), against 1,347 official MLB People:

```
corroborated_crosswalks   210      source_players_to_delete  422
post_assignment_merge     419      props_to_repoint          152
unresolved_identities    1127      (not guessed -- queued)
```

Applied to an isolated copy: 517,008 props before and after, 152 repointed,
integrity ok, duplicate groups **317 → 0**.

**Why it cannot land yet:** it archives all 2,653 MLB `player_stats` rows for
regeneration, and `D/leaders-reach-logs` goes PASS → *"no player_stats rows at
all"*. Applying to prod without a regeneration path takes the MLB leaderboard
offline.

### The regeneration is also the fix for three other red gates

`statsapi.mlb.com/api/v1/sports/1/players?season=2026` publishes, in one call,
everything I had previously written off as underivable:

- **Batting**: PA 215, AB 184, H, R, RBI, 2B, 3B, BB, K, SB, TB, HBP, SF,
  .299/.391/.467/.858
- **Pitching**: ERA 3.57, IP 128.2, W 9, L 5, SV 0, WHIP 1.19, ER 51
- **`primaryPosition` and `currentTeam` per player**

That last one overturns a documented conclusion. `docs/DATA-SPINE.md` says MLB
has no team/position because ESPN publishes those and we hold no `espn_id`.
**MLB's own API publishes both.** It never needed an ESPN crosswalk. Correct
that doc.

So: write an MLB season-stats ingest on statsapi. It regenerates what the
rebuild archives, and in the same pass flips `A/required-stats[batting]`,
`A/required-stats[pitching]`, `C/vocabulary[team]` and both `E/qualifier`
checks — which fail today only because the columns to measure them do not exist.

---

## 7. Order I would take these

1. **Scores/standings 500** — live, user-visible, and §2 step 1 is small.
2. **MLB statsapi ingest** — unblocks the reconciliation and flips five gates.
3. **NHL: migrate + ingest on prod** — done and verified on dev, just needs running.
4. **NBA merge to prod** — ready, awaiting your go, re-plan for prod's 269.
5. **NHL boxscore per-game pass** — kills the last derived value.
6. **NBA `espn_core`** — gated on §5, which is an infrastructure problem, not a code one.

## Standing warnings

- **Never `git worktree remove` without reading the branch.** Not for safety —
  branches survive — but because `codex/nba-v1` had root-caused the NBA identity
  split on July 29 with a tested repair, and a day was spent rediscovering the
  symptom. Check unmerged branches for prior art before diagnosing.
- **After any delegated session: `git status`.** Today it left a duplicate
  script at the wrong path, a 0-byte stray DB, and emptied a README.
- ~1.1G still on disk and not mine to delete: `/root/lp-db-backups` (376M),
  three `lp-v070-test*.db` (561M).
