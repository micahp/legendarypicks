# Game-story prompt evals

Saved prompts, saved outputs, and a runner that replays one against the other.

```
prompts/   the grounding as it was at a point in time, one file per version
runs/      dated model outputs, appended to and never overwritten
```

Run it from `backend/`:

```bash
# every saved version against the current model
venv/bin/python eval_story_prompt.py

# one version, several models
venv/bin/python eval_story_prompt.py --prompt v3-winning-percentage \
    --model deepseek/deepseek-v4-flash-0731 \
    --model nvidia/nemotron-3-ultra-550b-a55b --runs 5

# snapshot a fresh prompt from a real game, to start a new version
venv/bin/python eval_story_prompt.py --capture mlb:401816594 --as v4-my-change
```

It calls a real model and costs real money. It is a developer tool; nothing schedules it. At
`flash-0731` prices a full replay is a fraction of a cent.

---

## Why this exists

On 2026-08-19 the grounding changed three times in one afternoon. Each change was tested by
generating three blurbs, reading them, and throwing them away. That is a memory, not a
comparison: the next person had no way to see what the old prompt produced, or to tell a real
improvement from a lucky sample.

**A prompt is code. It should diff like code.**

---

## The versions, and what each one fixed

Every fix has the same shape: **a field we already had was missing from the prompt, and the
model filled the gap rather than leaving it empty.** None of these were model defects.

### v0-baseline

The prompt as it stood. Three defects, all found by reading output against the facts:

```
"Wednesday's 3-1 home loss"          the game was TUESDAY
"Trout: 5 hits/runs/RBIs in his      it was five games ago, on Aug 13
 last game"
"leads the AL West by half a game"   nothing in the facts said that
```

### v1-dated-results

ESPN publishes `gameDate` on every `lastFiveGames` event and we discarded it, so the grounding
listed five results with no dates. Every model tested named a weekday and every one was wrong
(DeepSeek said Wednesday, Nemotron said Monday, it was Tuesday).

```
L 3-1 vs LAA (MLB) [Tue Aug 18]; L 3-2 vs SEA (MLB) [Sun Aug 16]; ...
```

**The trap:** ESPN's instant is UTC and the calendar day is not. `2026-08-19T00:10Z` is the
evening of Tuesday the 18th in the US, so printing the UTC date would have baked the exact
off-by-one in permanently and made it look authoritative. Use the scoreboard's DST-aware New
York rule, which is already how every game in the store is bucketed.

### v2-dated-player-form

The worst of the three, because it inverts the claim a story leads with.

Player form was a bare array under the heading "most recent first" (the player name and
separator are elided in these samples):

```
... last 5 total_hits,_runs_and_rbis: [0, 0, 1, 1, 5]
```

Ground truth, newest first: `Aug 18 -> 0, Aug 16 -> 0, Aug 15 -> 1, Aug 14 -> 1, Aug 13 -> 5`.
So the 5 was five games ago and Trout was cold. **Three different models read it backwards**
and called the 5 his last game, turning a slump into a hot streak.

Sports game logs are universally printed oldest-first, so a header saying otherwise loses to
the convention. Dating each value removes the ordering question entirely:

```
... last 5 total_hits,_runs_and_rbis: Aug 18 0, Aug 16 0, Aug 15 1, Aug 14 1, Aug 13 5
```

### v3-winning-percentage

`0.5 win%` was read as "leads the AL West by half a game" in two of three runs, and Liquid made
the same misread as "a +0.5 win percentage edge". A bare `0.5` next to a division lead reads as
games-back to anyone who knows the sport. Now `.500 winning percentage`, and `differential`
became `run differential`.

---

## The result, from `runs/`

Same model, same game, v0 against v3:

```
v0   "Mike Trout broke out with 5 hits, runs and RBIs in his last game"    WRONG
v3   "Mike Trout has been quiet since an Aug 13 outburst"                  right
v3   "Alvarez going 0-for in total bases on Aug 18 after a 5-base game     right, and only
      Aug 14"                                                              possible with dates
```

---

## Reading a run file

`unsupported numbers` flags digits in the answer that appear nowhere in the grounding. It is a
**tripwire, not a grade**: it catches invented scores and averages, and it cannot catch a
misread ordering or a wrong weekday, which were the two worst defects here. Read the text.

Two lessons worth carrying to any prompt work:

1. **Grade against the WHOLE prompt.** The first pass at this graded against the first 900 of
   1,442 grounding characters and called several correct statements hallucinations.
2. **A model handed no value will produce one anyway.** Asked directly, `flash-0731` says it
   does not know today's date, while `nemotron-3.5-lightning` confidently answers "Friday, May
   24, 2024". The fix for a confabulated field is to supply the field.
