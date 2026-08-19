# TASK: method of victory, live-above-the-date, and the homepage

For the reasonix pane. Written 2026-08-19 from Micah's direction. Three independent items;
**do them in this order** and commit each separately.

Read `.claude/skills/honest-data-ui` before item 3, and `.claude/skills/answer-is-already-here`
before deciding anything is unavailable.

---

## Item 1: every final says HOW it ended

**The rule, in Micah's words:** if a game is final you show the score, and **if there is no
score you show the method of victory.** We did this for tennis (WALKOVER). UFC is the same
problem and is currently unhandled.

Today a finished UFC fight renders `FINAL` and a winner, and nothing else:

```
state=post  status=Final  status_detail=Final  period=3  clock='1:24'
home: {abbrev:'J. Wells', score: None, record:'14-4-1', winner: true}
```

**ESPN already publishes the method and we discard it.** Measured 2026-08-19 off the
`ufc/scoreboard` payload for 2026-08-15:

```
competitions[].details[]  ->  {"id":"20","text":"Unofficial Winner Submission"}
                              {"id":"21","text":"Unofficial Winner Kotko"}      # KO/TKO
competitions[].format     ->  {"regulation":{"periods":3}}                      # 3 or 5
competitions[].status     ->  {"period":3,"displayClock":"1:24"}
```

So the work is parsing, not acquisition. **Do not add a request.**

Build:

1. Parse the method out of `details[]` in `espn_client/ufc.py` onto the normalized game as
   `outcome_method` (a clean label: `KO/TKO`, `Submission`, `Decision`, `Draw`, `No Contest`,
   `DQ`). ESPN's text is prefixed `Unofficial Winner ` and its KO/TKO spelling is literally
   `Kotko`; normalise both. **Log an unrecognised type id rather than silently dropping it**,
   and add it to a mapping table a human can read.
2. A fight that goes the distance has no finish detail. Derive `Decision` from
   `status.period == format.regulation.periods` and a clock at the end of the round. If you
   cannot tell, emit nothing, not a guess.
3. Also carry `outcome_round` and `outcome_clock` so the card can read `SUB · R3 1:24`.
4. Frontend: where a final currently shows a score, a final with **no score** shows the
   method. Same slot, same weight. Follow `GameCard.getStatusLabel`, which is where the
   tennis WALKOVER already lives.

**Then audit every other league for the same gap.** The question is: *is there any state
where we render FINAL and the reader still cannot tell what happened?* Known candidates,
confirm each against real data rather than assuming:

- tennis: retirement mid-match, and a walkover (walkover already handled)
- soccer (MLS, LCUP, WC): a knockout decided on penalties or after extra time. A 1-1 that
  actually ended 4-3 on penalties is a wrong scoreboard, not a missing label.
- MLB: a suspended or postponed game that later resumed
- NHL: OT and SO, which change what the score means
- any league: forfeit, abandoned, no contest

Report what you found per league with the evidence, including the leagues that turned out
to be fine.

---

## Item 2: live sections sit above the date and ignore it

**The bug:** the live section renders *below* the date control, so a reader who has navigated
to a previous date cannot see that something is live **right now**. A live game is a fact
about the present, not about the date being browsed.

Build:

- Move the live section **above** the date control in `pages/scores.tsx`.
- It renders **regardless of the selected date**, and it is not affected by the arrows.
- When nothing is live it renders **nothing at all**, no header and no empty state. At 09:50
  on a weekday that is the normal case.
- When the reader is on a past date and something is live, the section is the thing that
  tells them so. Consider a quiet "jump to today" affordance on it; do not build a second
  date control.

**Do NOT re-add the "Cheap Quality, Live" discounts widget to `/scores`.** It was removed
today (`v0.8.3`) because it sat above the scoreboard showing nine of last night's games at
one cent each. Micah's note referred to both sections; the live-games section is
unambiguously right to move, the discounts widget is a separate decision he has not made.
**Leave it on `/plays` and ask before touching it.**

---

## Item 3: the homepage leads with the wrong thing

**Micah's reasoning:** the homepage currently sends people first to the scoreboard, second to
predictions, with prop data third. But **props and prop history are the primary value: the
most differentiated, most valuable, most dopamine-giving surface we have.** The homepage
should nudge there.

Build:

- Rework `pages/index.tsx` so **props is the primary call to action.** Scoreboard and
  predictions become secondary.
- Surface the other things we actually have, so the homepage stops under-selling the
  product: **news, live esports, mock drafts.**
- The props nudge should say what is behind it. "Props" alone is a noun; the differentiator
  is the **history**, that we say how the line landed. Lead with that.

Constraints, from `.claude/skills/honest-data-ui`:

- **Do not put a number on the homepage you cannot source.** If you show a prop count or a
  settled count, it comes from a query, never a hardcoded figure, and it is absent rather
  than zero when we cannot read it.
- Hierarchy through position and space, not chrome.
- Do not invent a marketing voice. Say what the thing is.

**This one is a design change, so screenshot the result and put the image in the report.**
Do not describe it in prose only.

---

## Scope and verification, all three items

Commit each item separately. Do not push.

Do not touch: `paced_http.py`, `scoreboard_store.py`, `league_activity.py`,
`ingest_scoreboards.py`, `routers/live_discounts.py`, any systemd unit, `/etc`, cron, or any
database.

**Do not spend more than 5 ESPN requests for the whole task**, and declare the count before
you run anything. Everything in item 1 is parsing a payload shape that is documented above;
capture one payload per league you need and work offline from it.

Report both suite numbers, never one:

```
venv/bin/python -m pytest -q
LP_DB_PATH=data/picks.dev.db venv/bin/python -m pytest -q
```

Baseline: **1614 passed / 1 failed** on the prod DB (the long-standing
`test_story_form_season` MLS case). The dev DB run sometimes shows a second failure in that
same file which passes in isolation; it is order-dependent against the live database the
timers write to, and it is not yours.

**Verify item 2 in the empty window.** Load `/scores` when nothing is live and confirm the
section renders nothing rather than an empty header. Three separate defects this month were
verified mid-slate and were wrong every morning.
