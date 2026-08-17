# TASK — close MLB out

**Owner:** reasonix / deepseek-v4-flash · **Written:** 2026-08-05

You've earned a shorter spec. Goal, constraints, done. Figure out the rest.

---

## The decision that changed

I had you write `position = NULL` when MLB publishes the group-level `OF`. **That was
wrong and it's my error.** ESPN and MLB *both* publish `OF` for Cristian Pache
(`mlbam_id=665506`) — it's a fact about him, not a gap. I made the data bend to satisfy
`C/vocabulary[position]`, which is backwards: **a gate is a check, not a spec.**

So:

* `position` holds **what the publisher published**, `OF` included. Drop the NULL rule.
* `position_group` carries the parent. Anyone wanting all 129 outfielders filters on that.
* **`C/vocabulary[position]` has to learn the parent/child model** — a published parent
  value alongside its children is legitimate *when the league declares a group column*.
  Without one it's still the old defect, so keep failing that case.

To be clear about why the check is changing: its model of the world was wrong, not its
verdict inconvenient. Don't loosen anything else while you're in there.

## Also close out

* dev's 2 rows still holding ESPN's `SP`/`RP` in `position` — `id=27525 José Suárez` and
  `id=28922 Jackson Wolf`. Both have an `mlbam_id`, so it isn't the crosswalk. Find out
  why the spine fill skipped them; if MLB publishes no position for them, a stale value
  from the wrong publisher's vocabulary is worse than none — clear it.
* dev's 5 active rows blank on `position_group`. Name them and say why.
* Then **prod**: it has neither new column yet. Migrate, spine fill, `roster_sync mlb`,
  gates. Back it up first.

## Done means

`C/vocabulary[position]`, `C/vocabulary[position_group]`, `C/vocabulary[team]` and
`G/published-identity` all **PASS on both databases**, full `pytest` green, row counts
unmoved, and prod's MLB endpoints still answering. That's the whole bar.

## Constraints

Back up before writing to prod. Commit per slice, don't push. No Docker, no host config
(`/etc`, systemd, cron) — and note the props timers write to prod every 30 min, so if a
run collides with one, say so rather than retrying. Don't touch `roster_sync.py`'s other
three leagues, `dedupe_mlb.py`, or `repair_mlb_identity_names.py`.

Out of scope and staying that way: the NBA 269 `identity-crosswalk` splits, the 15 NFL/NHL
name-form variants, the five unmeasured leagues (`atp` `ufc` `wc` `wnba` `wta`), the 168
pre-existing orphans. All measured, all bounded, none on fire.

Report between `===RESULT===` and `===END===`: gate lines verbatim for both DBs, what you
changed in the check and why, the 7 rows above resolved, `git log --oneline -4`. If
something doesn't hold, say so plainly — a real red beats a green you had to arrange.
