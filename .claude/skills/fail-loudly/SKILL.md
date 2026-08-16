---
name: fail-loudly
description: MUST load before writing any ingest, any join between tables, any code with a `try/except: pass`, any "best-effort" step, or any surface that renders whatever it was handed. Encodes the one shape behind every defect in docs/BACKLOG-holes.md — the system degrades instead of erroring, so a broken thing produces a plausible output and nobody finds it until someone takes a count. Triggers on "0 ingested", "best-effort", "don't block the pipeline", a bare except, a LEFT JOIN that feeds a page, an empty state, a default value, "it renders fine", and on any question that starts "why is this empty".
---

# Fail loudly

Load this before writing anything that can partially succeed.

It exists because on 2026-08-12 an audit of this app found **29 defects, and not
one of them had ever raised an error.** Every single one produced output of the
right shape — a number, a page, a green run — while being wrong or empty. They
were invisible until something counted rows.

---

## 1. The governing principle

> **A system that degrades instead of failing does not have fewer bugs. It has
> the same bugs, undiscovered, plus the time you spent not finding them.**

Silent degradation feels like robustness. It is the opposite: it converts a
loud, cheap, immediate failure into a quiet, expensive, permanent one. The
pipeline keeps running, the page keeps rendering, the test keeps passing, and
the defect accrues interest.

**The tell is always the same: the output is plausible.** Nothing looks broken,
because a degraded system is specifically designed to produce something that
does not look broken.

---

## 2. The four places it happens here, with the measurements

### 2a. The ingest that reports a number instead of an error

`bovada_scraper.py` scrapes ATP and WTA correctly. `_parse_tennis_props` reads
moneyline, total games, set betting and win-a-set. Every prop is then discarded,
because `players` holds **zero atp/wta rows**, so identity resolution cannot
attach them to anyone.

The run prints:

```
Ingesting WTA into http://127.0.0.1:8100...
  Iga Swiatek @ Elina Svitolina: 0 ingested
```

`0 ingested` is not an error. It is a count. It scrolls past in a log nobody
reads, on a timer, every 30 minutes, and has done for as long as tennis has
existed in this app. Measured cost: **169 players rejected, Swiatek 244 times,
101 `prop_games` rows carrying 0 props.** A working data feed, thrown away, with
a status line that reads like success.

> **Rule.** An ingest that resolves 0 of N must exit non-zero, or at minimum
> print a line that says `REJECTED 169 players — no atp/wta rows in players`. A
> count of zero is a finding, not a result.

### 2b. `try/except: pass` on the step that makes data reachable

`routers/props.py` links a `prop_game` to its ESPN event on a best-effort basis:

```python
try:
    espn_id = link_prop_game(con, game_row, espn_games)
    ...
except Exception:
    pass  # crosswalk is best-effort; don't block ingest
```

The intent is good — a crosswalk failure should not lose the props. The effect
is that when ESPN is walled, the link never happens, nothing is recorded, and
the props land in a table where **the page that serves them joins on the id that
was never written.** Measured: MLS 2 of 15 games linked, 714 props unreachable;
UFC 0 of 36 on dev; and **57,392 settled MLB props on dev that no game page can
reach.**

> **Rule.** "Best-effort" is fine. **Silent** best-effort is not. If a step can
> be skipped, the skip must be recorded — a column, a counter, a log line with a
> number in it — so the gap is queryable later. `except: pass` deletes the
> evidence that anything was skipped.

### 2c. The render that substitutes instead of refusing

6,818 players carry a game log and a blank `position`. Position decides which
columns a game log renders. A blank one does not produce an error or an empty
state; it produces **a generic table**, which reads as coverage. NCAAF is 5,897
of those — 49% of the league.

This is the sibling of the goalie case in `honest-data-ui`: a goalie's skater
line is four true numbers that answer nothing anyone opened the page for.

> **Rule.** A surface missing the field that decides its shape must say so, not
> pick a default shape. See `.claude/skills/honest-data-ui/SKILL.md` §4.

### 2d. The gate that answers a question you did not ask

`verify-gates.sh` never read `LP_DB_PATH` — its knob is `LP_GATE_D`, defaulting
to **prod**. Running it with the obvious variable set produced
`14 of a known 21`, a confident number about a database nobody meant to grade.
It did not warn. It could not: it had no idea a different database was intended.

Same shape one level up: the leagues hub read the coverage registry and hid
NCAAF, while `/api/players/search` had no such gate and returned 7 NCAAF players
per query. **A rule enforced on one surface only is not enforced.**

> **Rule.** When a tool has a knob, make the wrong knob refuse. When a rule has
> more than one surface, derive it from one source both surfaces read.

### 2e. The allowlist that decides trust, checked by NAME

`_core.SOCIAL_SOURCES` is the list of feeds whose items are posts rather than
reporting. Everything downstream asks one question — `source not in
SOCIAL_SOURCES` — and treats the answer as **"this is a verified publisher."**

It said `("bluesky", "x-search")`. The collector writes tweets with
`source = "x"`. **855 rows.** Every tweet in the corpus was therefore a verified
publisher: eligible to be shown to the writer as published reporting, eligible
to become a source chip a reader would click as a receipt. A tweet carrying a
false claim was read as a publisher and served as fact (Micah, 2026-08-12).

Nothing could detect this. The rows were present, well-formed and correctly
classified in every other respect. The only thing wrong was a string that was
never added to a tuple, and the failure of that string to be there looks
*exactly* like a feed that is genuinely a publisher.

Note the two tempting non-fixes:

* **Add `"x"` to the tuple.** Fixes 855 rows, leaves the mechanism — the next
  feed anyone adds is one forgotten string away from being trusted, and the
  person adding it will not know this list decides trust.
* **Trust the guard alone.** A shape check that silently corrects the column
  means the list is never corrected, and every other reader of that column
  (there were seven) keeps the bug.

> **Rule.** A list that decides TRUST may never be keyed on a name alone.
> Check the shape of the thing as well — our posts all carry an `[@handle]`
> prefix and a social host in the URL — and **report the disagreement** so the
> list gets fixed rather than quietly compensated for. `is_social()` refuses;
> `social_leaks()` prints. Both, or you get one bug back later.
>
> Corollary: an allowlist is safer inverted. "Is this a publisher?" answered by
> *absence* from a list fails open — anything unknown is trusted. Prefer a
> question that fails closed.

### 2f. The rank that has no opinion about time, and the rewrite that has no record

Two halves of one failure, both found on the news cards 2026-08-12.

**The rank.** `_load_chatter` scores anchors on topic-word overlap. A feature
written *about exactly this conversation* therefore scores highest — and the
best such article MLS has is a 2025 ESPN piece, "How Leagues Cup is becoming a
hotbed for global scouting". It supplied the card's one-sentence hook, so in
August 2026 the app announced that the Leagues Cup "becomes a global scouting
stage". Micah: *"as if that article didn't come out last year. Leagues Cup is
already a proving ground and them signing him is proof. it's maturing."*

Every item already carried its publish date, and the prompt already said
`MIND THE DATES`. That was not enough, and the reason generalises: **a fact
placed among nine other facts is something the consumer has to act on.** The
items are now printed under `DEVELOPMENTS` and `BACKGROUND` headers, and
`stale_anchor()` reports any card that cites only background while fresh
reporting was in front of it.

**The rewrite.** Nothing recorded what a served card was built from, so "did
anything change since last night?" was unanswerable — and the only available
answer was to generate it again. Every run rewrote every card: new title, new
prose, same story, no error, no signal. A headline that moves nightly while the
story stands still trains the reader that a change means nothing, which is the
exact opposite of what a news surface is for. Fixed with `pool_key` — a hash of
the shown item urls plus the editor marks — stored on the row and compared
before generating.

> **Rule.** If a ranking feeds something that speaks in the present tense, age
> is part of the rank, not a footnote you pass along and hope gets read.
>
> **Rule.** Anything that regenerates must record what it generated FROM. A
> pipeline that cannot tell "unchanged" from "not checked" will do the
> expensive thing every time and call the churn an update. Print the count:
> `14 cards (11 unchanged, not rewritten)`.

---

## 3. Writing it so it fails loudly

1. **Count both sides of every join, and print the pair.** `matched 280 of 300`
   is a fact. `matched` is not. A silent miss is the default failure of every
   join in this codebase — see `published-first` §3, where a wrong team code
   dropped 178 players for months.
2. **Zero is a finding.** Any pipeline stage whose output is 0 should say so
   distinctly from a stage that produced rows. `0 ingested` on 101 games is not
   the same event as `0 ingested` because there were no games.
3. **Never `except: pass` around something that writes.** Catch, record, continue
   — a counter and a log line at minimum. The exception is evidence; discarding
   it discards the only proof the step ran.
4. **Absence must not render.** If a denominator, a position, a season key or a
   join key is missing, refuse the element rather than substituting a default.
   A fabricated default is indistinguishable from a real value downstream.
5. **Fail closed on "cannot check".** `league_offering.offered_leagues()` returns
   only the shape-exception leagues when there is no registry, because "we could
   not check" must not open the whole players table. Evidence unavailable is a
   FAIL, never a pass and never a skip (`published-first` §6).
6. **A green gate is a claim about its surface.** Read what the assertion
   actually asserts before believing it. 1,187 tests passed the entire time all
   29 of these defects existed.
7. **Say the zero.** Print the count of every check even when it is zero —
   `Checks: 0 social leaks, 0 cards naming an uncited outlet`. A log that only
   speaks up on failure cannot distinguish "clean" from "never ran", which is
   the state the news collector was in for its entire existence.
8. **Two lists that must agree will drift.** If a prompt numbers one list and a
   resolver indexes another, they are the same list or they are a bug. Ours
   drifted the moment dedupe removed an item, and the receipts it attached
   pointed at real articles that did not say the thing being cited — a wrong
   citation, which is worse than none, and invisible in every count.

---

## 4. Before you call it done

- Name the loud failure you added. "It won't silently do X any more" with the
  mechanism, not "added error handling".
- If the change can partially succeed, say what it prints when it does.
- Run `backend/league_feature_matrix.py` if you touched a league surface. It
  exists because none of this was visible until something took the counts:

  ```
  venv/bin/python league_feature_matrix.py --db data/picks.db --compare data/picks.dev.db
  ```

- `docs/BACKLOG-holes.md` is the standing list. Add to it rather than fixing
  silently — a defect nobody wrote down is one that gets rediscovered.
