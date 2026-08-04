# Adding a league: the checks that would have caught the last four failures

Referenced by every `TASK-league-*.md`. It exists so the same holes are not
re-dug per league — each item below is a specific thing that shipped, was green,
and was wrong.

A league is **not done** when its pages render. It is done when the checks below
pass or are red **on purpose, in writing**.

---

## 1. Write the `MANIFEST` entry before the ingest

`backend/audit_league_stats.py` is the runner. Adding a `MANIFEST` entry is the
whole integration — nothing else needs wiring.

**Write it before the data exists.** The manifest is what the league's pages will
claim; deciding that after seeing what an ingest happened to produce is how the
claim becomes "whatever we got". A league with no entry reports **UNVERIFIED**,
never PASS, because "nobody described this league" and "this league is fine" must
never look the same in the output.

```python
"epl": {
    "stat_types": {"season": {
        "required": [...],                     # what a page of this league is not honest without
        "qualifier": {"unit": "...", "published": "..."},
    }},
    "position_content": {"GK": [["saves"]], ...},   # what each position must RECORD
    "single_vocabulary": ["position", "team"],
},
```

Then `verify-gates.sh COV-statset` and raise the expected-failure count in that
gate with the new league's known-red items **named in the commit message**.

## 2. The six questions the manifest makes it ask

| | check | the failure it exists for |
|---|---|---|
| A | required stats exist **and are populated** | `rush_td` was in every NFL game log and in no `player_stats` column, so the leaderboard could not sort by the most-used fantasy stat |
| B | a position's logs carry **that position's** keys | 78 of 90 NHL goalies had game logs and **not one save** — a goalie's log held `goals, assists, pim, toi`. Vejmelka: 64 logged games, zero saves. **The rows looked like coverage** |
| C | one vocabulary per categorical column | `players.position` held `G/F/C` from one ingest beside `PG/SG/SF/PF` from another, over near-disjoint populations. 472 of 525 NBA leaders clicked through to an empty page. NFL has the same split, where `K` and `PK` are both kickers |
| D | leaderboard players are clickable into a game | see C — a leaderboard of dead ends renders identically to a working one |
| E | the qualifier's unit is a column we hold | MLB's published rule is 3.1 PA × team games; ours was `games >= 30`, and `pa` was not a column. A 38-game player led a 112-game season's average |
| F | every publisher can reach the league's players | NBA's two id columns had **zero** rows carrying both, so 269 athletes existed twice — stats on one `players.id`, game logs on another. MLB and NHL carry no `espn_id` at all, which is why MLB has no team or position and no NHL goalie has a save |

## 2b. Decide the publishers BEFORE the ingest

`players` is a spine and **a league is only as good as the number of publishers
that can reach it** — check F measures exactly this. NFL is the only league with
two ids on the same row (16,774 of them) and the only one with team, position,
stat ranks, news and ADP. That is cause and effect, not coincidence.

NBA has two id columns and **zero** rows carrying both: 269 athletes exist twice,
stats on one row and game logs on the other. MLB and NHL carry no `espn_id` at
all, which is why MLB has no team or position and no NHL goalie has ever recorded
a save.

So, before the ingest: **name the publishers this league will have, and what each
one prints.** One publisher is a legitimate choice — it is not a legitimate
accident. Check F reports single-publisher leagues as UNVERIFIED rather than
passing them, so the choice has to be stated. `docs/DATA-SPINE.md`.

## 2c. Count the fields the endpoint publishes against the fields you read

**This is the check that would have caught every gap of 2026-08-04**, and none of
the others would have. Run it:

    ./venv/bin/python audit_field_utilization.py --league <league>

Register the league's endpoints in `ENDPOINTS` **at the same time as its
`MANIFEST` entry**. An endpoint we read and never registered there is a payload
nobody has ever counted.

Five gaps were found that day. Every one was a publisher we were **already
calling**, whose payload we read a fraction of — or an adjacent endpoint of that
same publisher nobody asked:

| recorded as | actually |
|---|---|
| NFL "no such column: `rush_td`, `rec_td`" | in the parquet already on disk: **143 columns published, 19 read** |
| NHL "a defenceman has nowhere to record a block" | `gamecenter/{id}/boxscore` publishes `blockedShots` and `hits` per game |
| NHL "no goalie source at all" | `goalie/summary`, league-wide, one request |
| MLB "no ERA anywhere in this database" | `statsapi.mlb.com`, one request, the whole line |
| NBA leaderboard three years stale | bulk `byathlete`, 578 athletes in 6 pages |

Not one was a missing publisher.

**Why nothing else catches it.** Row counts were healthy. The endpoint returned
200. The gates were green. A whitelist that drops 124 of 143 columns looks
exactly like a whitelist that drops none — the data arrives on every run and is
discarded before anyone looks. There is no count that distinguishes those two.

**Low utilisation is not itself a defect.** These are bulk requests; the unread
fields cost nothing. It is a *discovery* metric. **The unread field NAMES are the
deliverable** — read that list and ask, for each name, whether a document
somewhere says we do not have it.

Two habits that follow from it:

1. **A key whitelist is where data goes to die.** If an ingest has a
   `STAT_KEYS`/`REQUIRED_COLUMNS` set, its size relative to the payload is a
   number someone must have looked at once, on purpose.
2. **Ask the publisher's OTHER endpoints before concluding anything.** NHL's
   `player/{id}/game-log` genuinely does not publish blocks or hits. The same
   host's `gamecenter/{id}/boxscore` does. The gap was never "the NHL", it was
   "the one URL we happened to call". Write the endpoint next to the gap or the
   gap is unverified — see `.claude/skills/published-first/SKILL.md` §2b.

## 2d. Apply the migration, do not merely write it

`roster_sync.py` could not run **on either database** for its entire existence:
`migrate_roster_snapshots.py` was written, reviewed, committed, and never
applied. The job died on `missing table roster_snapshots` before it reached a
roster, and `players.team` was blank league-wide as a result — read for months as
a data-acquisition problem.

A migration in the repo is not a migration in the database. For each one:
`--check` against **both** `picks.db` and `picks.dev.db`, and record the result.

## 3. Find the published qualifier, or record that there is none

Every league publishes its own minimum, in its own unit — plate appearances,
innings, attempts, made shots. **Games is not a proxy for any of them**; a pinch
hitter and a leadoff man play the same number of games.

Known, with sources in `docs/LEAGUE-STAT-GAPS.md` §2:

| league | qualifier |
|---|---|
| MLB | 3.1 PA × team games (502/162); pitching 1.0 IP × team games |
| NBA | 58 games; FG% 300 FGM, 3P% 82 3PM, FT% 125 FTM |
| NFL | passer rating 14 att × team games; per-game ~50% of games |
| NHL | **none this project could verify.** 40+ GP is convention, and convention is recorded as UNVERIFIED rather than laundered into a rule |

If you cannot find one, the manifest says so and the check reports UNVERIFIED.
Do not invent a threshold and do not adopt somebody's blog post as a rule.

## 4. The design pass is part of the league, not a follow-up

Load `.claude/skills/honest-data-ui/SKILL.md` **before writing the spec**, and
the `frontend-design` skill before building. What the NFL got and every other
league did not, until 2026-08-04:

- **A game log is a table with columns**, not a run of `key value key value`
  pairs. If ranking two rows requires reading them, it is not done. Declare the
  league's columns from the keys its logs actually carry.
- **Rate stats render the way the sport publishes them.** Baseball is `.336`,
  three decimals, no leading zero — a one-decimal default rendered three hitters
  twelve points apart as `0.3` each and the column stopped ranking anybody.
- **Sample size is on the surface.** `recent_games` is the last 25, not the
  season. The header says `last 25 of 82 played`.
- **A dash is not a zero.** `—` means we have no value; `0` means the value is
  zero. They must be visibly different.
- **A position with no data says so.** Never render a substitute. A goalie's
  skater line is four true numbers that answer none of the questions a goalie's
  page is opened to ask, and a populated table reads as coverage. Absence is a
  claim about us, not about the player.
- **Name the condition on every average.** If you cannot say what it is
  conditional on, you do not understand it well enough to display it.

## 5. Before calling it done

- [ ] `MANIFEST` entry written, and written **before** the ingest ran
- [ ] league registered in `audit_field_utilization.py`'s `ENDPOINTS`, run, and
      **every unread field name read out loud** against the gaps we claim (§2c)
- [ ] every migration this league needs `--check`ed against **both** databases,
      not just written (§2d)
- [ ] categorical columns judged against a **published** vocabulary, never a
      heuristic — `fetch_position_vocabulary.py`; a gate that infers meaning from
      string length will fail leagues that are fine and miss ones that are not
- [ ] any enrichment job (one that only ADDS fields) fails per-row, not per-
      league; only a snapshot-replace may abort wholesale
- [ ] `verify-gates.sh COV-statset` run, every red item named in writing
- [ ] published qualifier found and recorded, or recorded as none
- [ ] game log renders as a table, verified in a browser at **375px and 1440px**
- [ ] every position's empty state checked — including the one with no data
- [ ] `F/identity-crosswalk` green, or the single-publisher choice stated in writing
- [ ] `docs/LEAGUE-STAT-GAPS.md` updated with what this league does not have
