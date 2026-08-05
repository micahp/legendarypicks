# How the data is set up, and why every league is a different quality

Measured against prod `backend/data/picks.db`, 2026-08-04.

Short version: **`players` is a spine, and a league is only as good as the number
of publishers that can reach it.** Every gap documented this week is downstream of
that one fact, and until 2026-08-04 nothing measured it.

---

## 1. The shape

```
              players                    ← one row per PERSON. the spine.
              ├─ id            (ours)
              ├─ espn_id       ─┐
              ├─ mlbam_id       │  one column per PUBLISHER
              ├─ nfl_gsis_id    │  that can reach this person
              ├─ nhl_id         │
              └─ nba_id        ─┘
                   ▲
                   │  everything joins on players.id
     ┌─────────────┼─────────────┬──────────────┐
 player_stats  player_game_logs  props    nfl_adp / projections / …
 (season roll)  (per game)    (markets)
```

`player_stats` is keyed `UNIQUE(player_id, league, season, stat_type)` — the
canonical key, migrated 2026-08-03. `player_game_logs` is per game.

**A publisher can only contribute to a league if the spine carries its id.** That
is the whole mechanism. There is no name matching anywhere in the join path, on
purpose: a wrong join key does not raise, it misses, and it once dropped 178
players silently.

## 2. What each league actually has

| league | rows | espn_id | legacy id | carry BOTH | verdict |
|---|---|---|---|---|---|
| **NFL** | 26,931 | 18,697 | 25,007 gsis | **16,774** | healthy |
| **NBA** | 1,063 | 521 | 541 nba_id | **0** | split |
| **MLB** | 2,750 | **0** | 2,747 mlbam | — | single publisher |
| **NHL** | 877 | **0** | 875 nhl_id | — | single publisher |
| UFC | 47 | 45 | — | — | single publisher |
| WC | 63 | 61 | — | — | single publisher |

Read that table next to the symptom list and every line matches:

- **NFL is the only league with a real crosswalk**, and it is the only league with
  team, position, stat ranks, news, ADP, projections and a tabbed player page.
  Not a coincidence — those come from *different publishers reaching the same row*.
- **NBA has two ids and no overlap at all.** 269 athletes exist twice: hoopR's
  historical stats on one `players.id`, ESPN's current game logs on another. That
  is why 472 of 525 leaders click through to an empty page.
- **MLB carries no `espn_id`.** ESPN is what publishes team and position, so
  `players.team` is 89% blank and `players.position` is **100%** blank. It is not
  an ingest bug; there is no id with which to ask.
- **NHL carries no `espn_id`.** The nhle.com feed we do have is skater-shaped, so
  a goalie's game log holds `goals, assists, pim, toi` and **no goalie has ever
  recorded a save**.

## 3. So: are we ready to add leagues?

**Not on the current spine, no** — and the reason is now measurable rather than a
feeling.

Adding a league today means picking one publisher and inheriting whatever that
publisher happens to print. That is how MLB ended up with Statcast exit velocity
and no RBI, and how NHL ended up with 90 goalie rows carrying skater columns.
Neither was a decision anybody made; both were a consequence of a single id
column, taken at ingest time, never revisited.

The three things that make a league good are, in order:

1. **More than one publisher reaching the same row.** Everything rich about NFL
   follows from this and nothing else does.
2. **A stat manifest written before the ingest** — what the league's pages will
   claim, decided in advance rather than inferred from whatever arrived.
3. **A qualifier in the publisher's own unit** — plate appearances, innings,
   attempts — not `games`, which cannot proxy for any of them.

All three are now enforced. `audit_league_stats.py` check **F** fails a league
whose id columns are populated but disjoint — the condition immediately *before*
the damage, which is the one a new league can still act on. Checks A–E cover the
rest. `docs/NEW-LEAGUE-CHECKLIST.md` requires the manifest be written first, and
all four `TASK-league-*.md` carry it.

## 4. Repairing what exists

| gap | fix | state |
|---|---|---|
| NBA 269 split identities | `backend/scripts/merge_nba_identities.py` | ported, tested, verified on a prod copy — **not applied to prod** |
| NBA leaders serve 2023 | `publish_nba_season_identities.py` + a rollup over the 23,749 NBA 2026 log rows we already hold | on `codex/nba-v1`, not ported |
| NBA two position vocabularies | normalization pass | not started |
| MLB no team/position | needs an `espn_id` crosswalk for MLB, **or** `players.team` from our own `player_game_logs` (0 blank of 49,144) | not started |
| MLB no PA/AB/ERA on the leaderboard | PA/H/R/RBI are in the logs already; **AB and ERA are published nowhere we hold** | not started |
| NHL no goalie stats | new ingest — no existing source | not started |
| NFL no rush_td/rec_td column | in every log, aggregation only | not started |

`docs/LEAGUE-STAT-GAPS.md` has the detail and the ordering.

## 5. The rule worth remembering

> A row's existence says a person was observed. It does not say **who observed
> them**, or what that observer prints. Ask the second question at ingest time,
> because after that it is a repair.

---

## CORRECTION — 2026-08-04: MLB never needed an ESPN crosswalk

The rows above stand as measured. The **diagnosis** for MLB below them was
wrong, and it is worth keeping the wrong version visible because it is a
repeatable mistake: a missing value was attributed to a missing publisher
without ever asking the publisher the league already has.

> "MLB carries no `espn_id`. ESPN is what publishes team and position, so
> `players.team` is 89% blank and `players.position` is **100%** blank."

The symptom was real. The cause was not. **MLB publishes team and position
itself**, on the endpoint we were already using for identity:

```
statsapi.mlb.com/api/v1/sports/1/players?season=2026
  -> 1,347 people, each with `primaryPosition` and `currentTeam`
```

`backend/ingest_mlb_spine_identity.py` fills both. On dev this took
`players.position` from 100% blank to **0% blank on active players**, in one
vocabulary (1B 2B 3B C CF DH LF OF P RF RP SP SS TWP), and `team` likewise.
Every remaining blank belongs to a player MLB does not publish for the season —
a retired player has no current team, and blank is the honest answer there.

The same mistake covered the counting stats: ERA, AB, PA, IP and the rest were
recorded as "published nowhere we hold" and are all published by
`statsapi.mlb.com/api/v1/stats?stats=season&group=hitting|pitching`. See the
correction in `LEAGUE-STAT-GAPS.md`.

**What this changes about the spine argument.** "A league is only as good as
the number of publishers that can reach its players" still holds. What does not
hold is treating `espn_id` as the only route — MLB's own publisher reaches its
own players perfectly well, and was never asked. Before recording a value as
unreachable, ask every publisher the league already has.

An `espn_id` crosswalk for MLB is still worth having, but it is no longer what
stands between this league and a team or a position.

---

## ADDENDUM — 2026-08-04 (evening): the spine held ids that named the wrong person

§5 says a row's existence does not tell you who observed the person. This is the
sharper version, and it cost more:

> **An id on a row is a claim that the row is that person. It had never been
> checked.** On 223 prod rows and 167 dev rows it was false.

```
id=26551  name='Eiberson Castellano'  mlbam_id=703607   MLB publishes 703607 = Henry Bolte
id=26571  name='Mason Miller'         mlbam_id=702616   MLB publishes 702616 = Jackson Holliday
id=26588  name='Walker Buehler'       mlbam_id=669236   MLB publishes 669236 = Jeremiah Jackson
```

Everything in §1 keys on these ids. A wrong one does not raise — it mis-joins,
silently, and it converts every id-keyed *repair* into a corruption.
`dedupe_mlb.py` documents a shared `mlbam_id` as "provably the same person";
**124 of 317 duplicate groups were two different people.** A merge would have
repointed 408,610 prop rows and 26,491 game logs onto the wrong players and then
deleted the originals. What stopped it was a `player_stats` UNIQUE constraint
firing on 188 collisions — luck, not design.

### Root cause: Statcast's `player_name` is the PITCHER

`backend/ingest_statcast.py`, before commit `b03b9c9` (2026-06-15 18:49):

```python
name = pitcher_id_to_name.get(batter_id)
if not name:
    name = group["player_name"].dropna()
    name = name.iloc[0] if len(name) > 0 else None   # <- the first PITCHER faced
```

`player_name` is the pitcher's name on every pitch row. A two-way player hits the
first lookup; a pure batter falls through and inherits the name of whoever threw
their first pitch. `player_id` still came from `batter_id`, which is correct — so
the row keeps the right id and acquires a stranger's name, with no error anywhere.

The fingerprint, measured rather than argued:

* 208 of 216 bad rows changed **name only** between the 06-15 and 06-24 backups.
  `mlbam_id` moved on **0** rows — the ids were never the corruption.
* **201 of 203** resolvable wrong names belong to a **pitcher**; **203 of 203**
  true owners of the id are position players (C 36, LF 29, RF 27, CF 24, 2B 24,
  3B 22, SS 18, 1B 14, DH 8, OF 1). Zero pitchers among the owners.
* Not a positional shift: over the 2,271 placeholder rows in id order, offset 0
  scores 1072 correct and every offset from −5 to +5 scores **0**.

`b03b9c9` fixed the forward path — batters resolve from `batter_id` against the
spine, no name guessing — but never repaired what was already written. The pass
that copied these names from `player_stats` onto `players.name` is **not in git**;
it was an ad-hoc command. That is precisely when a gate beats a root cause.

### The gate and the repair

* **Gate:** `audit_league_stats.py` check **`G/published-identity`**. Every
  external id must carry the name its own publisher gives it, against the
  committed snapshot `backend/data/published-identity-names.json` (refresh with
  `fetch_identity_names.py`). A league with no snapshot reports **UNVERIFIED,
  never PASS** — a guess wearing a green badge is worse than a red one.
* **Repair:** `backend/repair_mlb_identity_names.py`, **id-first**. It takes the
  published name for each `mlbam_id` and writes nothing else. **Never repair by
  name match — name matching is what caused this.**
* **Result (v0.7.5):** 223 prod / 167 dev names changed, **0** `mlbam_id` writes,
  every row count in `players`, `player_game_logs`, `props`, `player_stats` and
  `predictions` identical before and after. Gate G green on both databases.
  Duplicate `mlbam_id` groups that are two different people: **124 → 0.**

### What this adds to the rule

> A publisher's column may describe a **different entity** than the row you are
> writing. A plausible name in a plausible column is not evidence that it belongs
> to your row. Read the field semantics at ingest — and assert the pairing, because
> an id that joins cleanly to the wrong person is indistinguishable from a correct
> one until something measures it against the publisher.
