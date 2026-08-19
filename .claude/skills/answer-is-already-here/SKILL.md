---
name: answer-is-already-here
description: MUST load the moment you are about to say "I can't", "blocked", "needs X", "unverifiable from here", "questions for Micah", or to hand a question back instead of answering it, and before reporting any diagnosis you reached by reasoning rather than by looking. Encodes the repeated failure where a host 403s, a tool is unavailable, or a fact seems unknowable, and the answer was already on this box: in a cache, a payload, a log, an error message, or git. Triggers on 403, blocked, rate limited, "cannot fetch", "no access", "I don't have", "would need", "let me know", "open question", any competitor or third-party research, any "why is prod different", and any moment you are about to escalate rather than measure.
---

# The answer is usually already here

You are a capable agent on a box with the data on it. The most expensive failure in this
repo is not being wrong. It is **stopping one step short and handing the question back**,
when the answer was already in reach.

Micah's words, 2026-08-19: *"the answer might be right in front of your face."*

## 1. The shape

You hit a wall. The wall is real. You report the wall.

But the wall was in front of **one path to the answer**, and you treated it as the wall in
front of **the answer**. Those are different, and the difference is usually one more step.

Measured, all on 2026-08-19:

| the wall | what I reported | where the answer actually was |
|---|---|---|
| `espn.com` 403s, archive.org unfetchable | "five questions for Micah" | ESPN's site runs on the same scoreboard payload we already fetch. Their **field set is their card contract**, sitting in `/cache/espn`. It named records, probables, broadcast, headlines, leaders, venue, all of which we were discarding. |
| a skill file might be modified | ran `find /`, which timed out | `git status` answered it in 40ms |
| a revert had no recorded reason | wrote a plausible reason into the handoff as fact | asking got the real one in one sentence, and it was completely different |
| a test failed in the suite, passed alone | patched fixtures twice | the error said `no such table: prop_games` from the first run |
| prod showed bad data, dev did not | theorised a disk-cache TTL, twice | reading the failure branch showed an expired entry served with no age limit |

**Four of those five were answerable without leaving the box.** The fifth needed one question,
asked directly, instead of a fabricated answer.

## 2. The ladder. Walk all of it before you escalate.

1. **Do we already have the artifact?** Caches (`/cache/espn`), the databases, snapshot
   tables, log files, `git show`, a previous payload. A publisher that refuses you now may
   have answered an hour ago and the response is on disk.
2. **Is the thing I want a property of something I already fetch?** A vendor's UI is built
   on their API. Their **field set is their contract**. You do not need their HTML to learn
   what they consider card-worthy; you need the payload you already have.
3. **Did the error already say it?** Read the actual message, in full, before forming a
   theory. `no such table: prop_games` is the diagnosis, not a symptom to reason around.
4. **Is there a second door?** A different host, a different endpoint, a narrower command.
   `git status` instead of `find /`. `sports.core.api` instead of `site.api`.
5. **Can I measure it instead of concluding it?** Run the failing thing. One
   `settle_game()` call beat three measured-but-wrong causes. See
   `feedback_run_the_failing_operation`.
6. **Only now**: say what is blocked, what you tried, and the single question that unblocks
   it.

## 3. Escalating is allowed. Escalating early is the defect.

This is not "never ask". A blocked thing with a one-sentence question is a good outcome.
The rule is what must be true first:

- You walked §2 and can say what you tried at each rung.
- The question is **specific and cheap to answer**, not a list of five that offloads the
  thinking.
- You are asking for a **fact only they have** (a preference, a decision, what a competitor's
  app shows on their phone), not a fact the box holds.

> "espn.com 403s, so tell me what ESPN's scoreboard looks like" is offloading.
> "Is Sleeper's ordering live-first or chronological?" is a real question. Only one of those
> survived §2.

## 4. Never fill a gap with a plausible story

If you could not find it, say you could not find it. **Do not write a reasonable-sounding
explanation and let it harden into fact.** On 2026-08-17 a session invented a technical
reason for a revert; it read as fact for a day and shaped a whole design document before
anyone checked. See `feedback_explain_infra_before_building`.

An unexplained thing is a question to ask. It is not a gap to fill.

## 5. Before you call it done

- Did I say "can't", "blocked", "would need", or "open question"? If so, walk §2 again and
  name the rung I stopped at.
- Am I reporting something I **looked at**, or something I **reasoned to**? Prefer the
  former, and label the latter as a hypothesis.
- Is my "open question" a fact this box holds? Then it is not a question, it is a task.
- Sibling skills: `published-first` (the value is probably published, do not compute it),
  `espn-request-budget` (a 403 is a fact about one host at one moment, never about the world).
