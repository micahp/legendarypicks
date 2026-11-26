# TASK — close the 7 UNVERIFIED gates, then write down how to add a league

**Owner:** delegated (deepseek, hermes pane) · Work in `/root/legendarypicks`, absolute DB
paths, never a worktree. `VACUUM INTO` for backups, never `cp`. Commit per slice, do not push.

Prod audit is **0 FAIL** on all four leagues. What is left is 7 UNVERIFIED, and UNVERIFIED
means *nobody has fetched the evidence*, not *the data is fine*. Three different kinds of
work — do them in this order.

---

## 1. `E/qualifier[season]` — nhl — DO THIS FIRST

The manifest currently says:

> `"NONE PUBLISHED that this project could verify -- 40+ GP is convention"`

**Treat that sentence as unverified, not as a finding.** Every previous instance of this
exact shape in this repo turned out to be wrong:

* "no ERA anywhere in this database" — `statsapi.mlb.com`, one request
* "no goalie source at all" — `api.nhle.com/.../goalie/summary`, league-wide, one request
* MLB team/position "needs an ESPN crosswalk" — MLB publishes both itself

Read `.claude/skills/published-first/SKILL.md` §2b first. It names this failure precisely: a
question about *which endpoint someone asked* gets written down as a property of the world,
and then nobody asks again because it looks answered.

So: **enumerate every publisher NHL already has** — `api.nhle.com`, ESPN core, ESPN site —
and read what each actually returns for a qualification/leaderboard rule. Write down the
endpoint, the parameters and the date next to whatever you conclude. If it genuinely is not
published, say so *with the endpoints you asked* so the claim is falsifiable; if it is
published, declare it in the MANIFEST and the check goes green on its own.

## 2. `G/published-identity` — ufc, wc — a fetcher, if a publisher exists

`fetch_identity_names.py` covers mlb/nfl/nhl/nba, each asked of **the publisher that issued
the id we are checking**. Extend it only where that holds. Before writing a fetcher, answer:
what external id do these leagues' rows carry, and who issues it? If UFC rows carry only an
`espn_id`, ESPN is the issuer and the check is answerable. If World Cup rows carry no
publisher id at all, **the honest outcome is that the gate stays UNVERIFIED and you say why** —
do not invent a map to turn a light green.

## 3. `B/position-content` — mlb, nba, ufc, wc — a declaration, not a fetch

Nobody has stated what a position's log must record. NHL has the only declaration and it is
what caught 78 goalies with 64 logged games and zero saves.

Write entries the same way: for each position class, the keys a log must carry for that log to
count as having observed that player, plus a `coverage` share. Ground each key in a field the
publisher actually emits — check the log rows before declaring. A catcher and a shortstop may
not need different keys; if a league genuinely has one class, say that in the entry rather
than omitting it.

**If a league has no `player_game_logs` rows at all, declaring content is meaningless — record
that instead.** `ufc` and `wc` may be that case; measure before writing.

---

## 4. Then update the documentation — this is the point of the task

Micah is comfortable adding a league now. Make that true for the next person.

**`docs/DATA-COVERAGE-CONTRACT.md` §7 "Adding a league"** is the ordered checklist and it is
now out of date. It covers coverage (events, teams, athletes) and says nothing about the seven
checks a league is measured by. Rewrite it so that adding a league is: write the MANIFEST
entry, then satisfy each check in a stated order — and say **what each check needs from the
league** (A: which stats and any per-column coverage floor; B: what a position's log must
record; C: which columns are single-vocabulary and whether a group column is declared;
E: the published qualifier and its unit; G: which publisher issues the id).

Fold in what §7b already learned so it is one document rather than two: the five defect
shapes, **shape 1 before shape 3**, and that **UNVERIFIED is a failure, never a skip**.

State plainly which parts are cheap (the MANIFEST entry is a declaration, minutes) and which
are not (a fetcher needs a publisher that issues ids). The failure mode this prevents is a
league's rows landing before anyone has said what the league claims — which is exactly how
`ufc` and `wc` sat in the database invisible to every check until today.

---

## Done means

* Every one of the 7 is either **green**, or **still UNVERIFIED with the endpoints you asked
  written next to it**. Both are acceptable outcomes; a green light you cannot defend is not.
* `audit_league_stats.py` still reports **0 FAIL** on prod for mlb/nfl/nhl/nba — do not trade a
  FAIL for an UNVERIFIED.
* Full `pytest` green. `diff_databases.py` clean on SCHEMA and SEASONS.
* §7 rewritten so someone who has never added a league can follow it without reading this file.

Report between `===RESULT===` and `===END===`: each of the 7 with its outcome and, where still
unverified, the endpoint asked. Then stop.
