# How the data is set up, and why every league is a different quality

Measured against prod `backend/data/picks.db`, 2026-08-04.

> ## ⚠ CORRECTION — re-measured against prod 2026-08-11
>
> The §2 table below and three of the diagnoses drawn from it are **stale**. The
> mechanism it describes is still exactly right; several of its facts are not. Re-measured
> on the same file, same query, one week later:
>
> | league | rows | espn_id | legacy | BOTH | was |
> |---|---|---|---|---|---|
> | NFL | 26,947 | 18,713 | 25,007 | 16,774 | ~unchanged |
> | NBA | 871 | 649 | 541 | **320** | was "**0** — no overlap at all" |
> | MLB | 2,451 | **783** | 2,449 | 783 | was "carries **no** `espn_id`" |
> | NHL | 1,072 | **1,048** | 875 | 853 | was "carries **no** `espn_id`" |
> | UFC | 49 | 47 | — | — | 47 |
> | WC | 63 | 61 | — | — | 63 |
> | MLS | 888 | **357** | — | — | was 1,236, "the whole spine carries `espn_id`" |
> | NCAAF | 11,914 | 11,914 | — | — | was 15,029 |
>
> **The three headline diagnoses that are no longer true.** Each drove a stated
> consequence, and the consequences moved with them:
>
> - *"MLB carries no `espn_id`… `players.team` is 89% blank and `players.position` is
>   100% blank."* MLB now carries 783 `espn_id`s, and team/position are **45% blank**,
>   not 89%/100%. The MLB identity work this cycle (`03d906b`, `4f405db`) is why.
> - *"NHL carries no `espn_id`."* NHL now carries 1,048 of 1,072 — the most complete
>   crosswalk after NFL. Team is 0% blank and position 2 rows blank.
> - *"NBA has two ids and no overlap at all."* 320 rows now carry both.
>
> **MLS and NCAAF counts fell** because these are prod numbers and the promotions were
> partial: MLS excluded 520 identity-mismatched ids, and dev holds 1,240 MLS / 20,926
> NCAAF against prod's 888 / 11,914. Prod NCAAF also has **zero** `player_stats`,
> `team_game_results`, `team_game_stats` and `team_stats_coverage` — the missing coverage
> row is what keeps the league off the hub, and as of 2026-08-11 off search too
> (`backend/league_offering.py`).
>
> **MLS is no longer "the whole spine carries `espn_id`"** — 357 of 888 on prod. Any plan
> that assumed a complete MLS crosswalk needs re-checking against the number, not this
> sentence.
>
> Left in place below rather than rewritten, so the evolution is readable. Treat every
> number past this box as "true on 2026-08-04" and re-measure before planning on it —
> that is the point of §2b of the published-first skill, applied to this file.

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
| **MLS** | 1,236 | 1,236 | — | — | single publisher (ESPN) |
| **NCAAF** | 15,029 | 15,029 | — | — | single publisher (ESPN) |

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

**MLS and NCAAF (added 2026-08-06/07) are currently single-publisher (ESPN)**
(checklist F/identity-crosswalk): the whole spine carries `espn_id` — 1,236
MLS rows and 15,029 NCAAF rows, every one keyed by ESPN's athlete id — and no
second publisher has been wired to them yet. For NCAAF a second publisher is
permitted: Micah's 2026-08-06 "DO NOT use cfbd key" was scoped to the news
engine only (confirmed 2026-08-07 — see CORRECTION below), and the provider
audit recommends CFBD `/games/players` as the NCAAF log source (~1-6
calls/season vs 888 ESPN summaries). The ESPN-only spine is a build state, not
a locked decision. What ESPN does NOT print for these leagues, so what they
will never have until a second publisher lands:

- MLS: no advanced metrics in the log feed (xG/xA, possession-adjacent player
  stats); the summary publishes saves/goalsConceded/shotsFaced for keepers but the
  ingest does not yet map them (GK saves gap — documented in LEAGUE-STAT-GAPS).
- NCAAF: no tackle/sack/defensive keys are mapped by the log ingest (offense-only
  scope, declared in the MANIFEST), and no playing-time qualifier is published.
- Both: ESPN publishes team + position + news, so unlike MLB/NHL these leagues DO
  get team/position/news; what they lack is the *cross-publisher* richness (a
  second id column, ADP-style external feeds) that only a second publisher brings.

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

---

## CORRECTION — 2026-08-07: the NCAAF "single-publisher" was not a deliberate choice

§2 called MLS and NCAAF "deliberately single-publisher (ESPN)... a choice, not
an accident." For NCAAF that framing was wrong. The reasoning behind it was
Micah's 2026-08-06 "DO NOT use cfbd key" — which, on the record, was scoped to
the **news engine**: it was said right after CFBD was confirmed to have no
/news endpoint, and the same message's O(1)-player-lookup rule is a news-engine
rule too. Micah confirmed 2026-08-07: **news-only**.

What that means for the pipeline: CFBD is permitted for NCAAF logs. The provider
audit (PROVIDER-AUDIT-2026-08-06.md) recommends it as the log source
(`GET /games/players?year=&seasonType=regular&classification=fbs`, free tier,
~1-6 calls/season vs 888 ESPN summaries), and it publishes defensive stats
(tackles/sacks) the ESPN summaries lack. The current ESPN-only spine stands as
measured — but it is a build state, not a decision. **RESOLVED 2026-08-07: the
NCAAF log ingest lands on CFBD** — `ingest_cfbd_logs.py` re-sourced the 2025
FBS season (888 games, 56,577 rows, 100% linked, defensive stats mapped, ~139
calls total). ESPN summaries remain the team backfill/reconcile source.

---

## ADDENDUM — 2026-08-16: the props feed was minting its own spine, and the resolver was folding one side only

Four defects found in one pass, while putting MLS player props on a live board.
They are one family: **every one of them produced a plausible output**, and none
raised. Recorded here rather than only in commit messages because §5's rule needs
the new instances.

### 1. A sportsbook display name is not an identity

Prod carried **531 MLS `players` rows with no `espn_id`, no game logs and props
attached** (dev 183 before repair). They were shadow copies of athletes already in
the spine, so `prop -> player -> game_log` joined for none of them: the props
existed, the players existed, and the two were different rows.

The minting code **is not in git history at all** — no MLS player insert was ever
committed. It was written and run off-repo, against both databases. That is its own
finding, and it is the second time (see `feedback_agents_left_prod_code_untracked`):
after any session that touched data, `git status` is not optional.

`_wc_direct_ingest` in `bovada_scraper.py` is the same shape, legitimately, for the
World Cup — that spine really is name-matched, Phase 1, with no ESPN id to resolve
against. What was wrong is that a mint printed **exactly like a match**. It is now
counted and named in the run report, at zero too.

Everything else routes through `/api/props/ingest`, whose resolver never creates:
an unresolved name lands in `unresolved_players` where it can be read.

### 2. The resolver folded accents off one side of the comparison

`_resolve_player_for_ingest` normalised the INCOMING name — lowercase, strip
punctuation, strip accents — and then compared it to the STORED name unfolded. So
`Thomas Muller` from Bovada never matched `Thomas Müller` as ESPN publishes him.

Measured on the MLS board: **53 of 74 unresolved names had an exact same-team match
already in the spine**, differing only by a diacritic or a capital — Christian
Ramírez, Andrés Cubas, Albert Rusnák, Jesús Ferreira, Kim Kee-Hee. Re-ingesting the
same board after folding both sides took resolution from **1,322 of 1,461 to 1,438**.

This is the §5 rule again, one level in: a wrong join key does not raise, it misses.
The fold is deliberately NOT in `name_alias` — that table is for reviewed judgment
calls ("Matt" for "Matthew") and holds 2 rows. A diacritic is not a judgment call.

### 3. The props table had no upsert, and the scrapers run every 30 minutes

`/api/props/ingest` INSERTed unconditionally into a table with no UNIQUE constraint.
Dev held **47,827 `(game_id, player_id, market, line, side, source)` groups with more
than one row.** The board reads latest-per-key so it rendered correctly the whole
time, while every hit-rate denominator counted the same prop once per scrape.

The two leagues that bypass the API (`wc`, `ufc`) were the two that stayed clean —
their direct-DB paths had always done the existing-row check.

**Still outstanding: the pre-existing duplicates outside MLS have not been cleaned.**
The mechanism is fixed; the backlog is not.

### 4. We were reading 4 of 15 published stats, and 2 of 8 published markets

Bovada publishes **eight** player-attributed MLS markets (1,464 outcomes across 14
fixtures). We ingested two. ESPN publishes **15 per-player stats** on a soccer
summary. We read four.

Those two gaps were the same gap. `To be Shown a Card` could not be ingested because
no card column existed to settle it — and the card column did not exist because
nobody had asked ESPN for it. The publisher had already answered.

`First Goal Scorer` (332 outcomes) needed something a box score cannot give: ORDER.
`keyEvents` carries each goal with its scorer and a clock, in the same document we
were already fetching for the stat lines.

> **The rule this adds.** A league's coverage is not "what we ingest", it is "what we
> ingest ÷ what the publisher publishes", and until you take that ratio you cannot
> tell a thin league from a thin read. MLS looked like a thin league for nine days.

### What MLS holds now

| | before | after |
|---|---|---|
| Bovada player markets | 2 | 8 (5 canonical + a 3-line goal ladder) |
| props on the board | 714, captured 08-07..08-09, never refreshed | 1,542 refreshed every 30 min |
| refreshed by a timer | no timer covered MLS | the existing `all` timer — `mls` was simply absent from `LEAGUES` |
| stats per game log | 4 | 16 (15 published + derived `first_goal`) |
| markets settlement can grade | goals, assists | + card_shown, goal_or_assist, first_goal_scorer |
| shadow players (dev) | 183 | 0 |
| 2026 game logs | 0 | backfilling (511 published events, chunked against ESPN's per-host ceiling) |

### Two things left standing

- **`roster_season()` in `roster_membership.py` infers a season from a timestamp**
  with a hardcoded month rule. That is the same class as the `_SEASON = {"mls": 2025}`
  constant fixed on 2026-08-16 — a definition inferred rather than read. It has not
  been changed; nothing has measured it wrong yet.
- **47 MLS and 17 NCAAF players still carry no position.** The MLS 47 are genuine name
  variants needing reviewed aliases (Bovada's "Matthew Edwards" vs ESPN's "Matt
  Edwards"); the NCAAF 17 are on no roster any publisher we read carries.
