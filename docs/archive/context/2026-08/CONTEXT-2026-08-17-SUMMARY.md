# 2026-08-17 — day summary

One day, five passes, one bug shape. This is the index; the detail for passes 1–3
stays in the handoff and it supersedes this file where they disagree. Passes 4–5
happened after the handoff was last written and live here.

| pass | file | covers |
|---|---|---|
| 1 | `CONTEXT-2026-08-17-HANDOFF.md` §1–§8 | MLS props → RotoWire/PrizePicks relay, dedupe_props written, release gates |
| 2 | `CONTEXT-2026-08-17-HANDOFF.md` §9–§15 | late night, 01:00–03:00 — prod MLB June settlement hole closed |
| 3 | `CONTEXT-2026-08-17-HANDOFF.md` §16–§22 | morning, 08:45–09:15 — prod code/schema asymmetry, dev's regrade ruler |
| 4 | this file, §5 | NFL ADP preflight — two migrations that destroy each other |
| 5 | this file, §6 | the news job — a 403 we diagnosed from the wrong publisher's doctrine |

**Units fixed today:** four news units and both NFL ADP units, all now
`Result=success` with active timers, plus `legendarypicks-props` (dev) green off
cdrc's tennis spine.

**Two are still red, and they are one root cause** — verified at 09:45, not assumed:

- `legendarypicks-props-prod` — `exit-code 3`. atp resolved **0 of 192**, wta **0 of
  192**. Prod has no tennis players; §4.6 is the DB-only fix.
- `legendarypicks-props-freshness` — `exit-code 1`, and it is a *consequence*. It
  correctly detected prod props stale at 3.0h, tried to self-heal by starting
  `props-prod`, and died on its own 15s subprocess timeout: `systemctl start` on a
  `Type=oneshot` **blocks until the job finishes**, and that job takes minutes. The
  watchdog is right about the world and wrong about how it waits — `--no-block` is
  the fix. Found while checking this file's claims; not chased.

---

## 1. The finding the whole day reduces to

**Every defect today was a value we derived sitting where the publisher's own value
was available — and every one of them was invisible because the gate over it
asserted *presence* rather than *correctness*.**

Two halves. Neither alone would have cost a day.

| we derived | the publisher already stated it | measured |
|---|---|---|
| a fixture keyed on `(league, date, home, away)` | `espn_event_id` on the same row | 65 duplicate `prop_games` rows; 2,212 props split across twins |
| which of two disagreeing finals is real | `statsapi` line score for the gamePk | 7 conflicts; the later row won **every time** |
| a gamePk from `date ± 1` + club names | `start_time` on the row | 304 rows had none; 4,467 June props unsettled |
| `entity_type` from `players.position` | ESPN signs constructs `-16000 − proTeamId` | all 96 NFL constructs → `unknown`; ADP dead 5h |
| what a Bluesky 403 *meant*, from ESPN's wall doctrine | that same host answering **200** on every other endpoint | 300 requests/run, ~700s sleeping, job killed at 900s |

And the gates that stayed green over all of it:

| gate | what it asserted | what its readers needed |
|---|---|---|
| `_probe_player_entity_type` | `entity_type IS NOT NULL` | 32 rows at `entity_type='team_defense'` |
| `dedupe_prop_games` "stale results cleared" | `a == b or a <= b` — tautological | any wrongly-graded prop still holding a result |
| regrade "same ruler, both sides" | 15/187 before **and** after | that the two sides read the same repaired data |
| `except Exception: pass` around the link | nothing | that the row got an event id at all |
| `news-collect.sh` "a step failing does not abort the next" | that a step **fails** | that a step can **hang** and never return at all |
| `discover_topics.py` exit code | `0` | it had just printed `Stage 2 FAILED — no writes` |

**A derived value never raises. It returns a plausible wrong answer, and a
presence-check over it returns green.** What made each one visible was running the
failing operation and reading its error — `settle_game()` on one June game printed
the real cause after three *measured* "shapes" had all pointed the wrong way.

---

## 2. What is now true on PROD

- **MLB June settles.** 693 settled (5%) → **10,419 (74%)** at the sweep; **10,835 of
  14,110 (77%)** re-measured at 09:20 after the timer had run again. 11,896 props
  settled in the sweep itself. The cause was the 304 missing `start_time`s, not the
  duplicates.
- **No duplicate fixtures, and the ingest cannot recreate them.** `prop_games`
  1,027 → 960, 1,847 props repointed, `ux_prop_games_event` unique index live.
  590 wrong `prop_results` deleted — not redundant but *wrong*, and `settle_game`
  skips a prop that already holds a result, so leaving them freezes the bad grade.
- **`start_time` matches the publisher 334/334** (was 95 disagreeing). Rows missing
  one: 304 → 28 at the backfill (22 unlinked, 6 not published), **24 at 09:20**.
  Dev sits at 28.
- **Unlinked MLB rows 44 → 4**, healed with `link_prop_games.py`.
- **NFL ADP refreshes again.** 11,610 rows, D/ST gate 32/32 with PPR ranks. Both
  `legendarypicks-nfl-adp-prod` and `-dev` exit 0; both timers active.
- **`legendarypicks-props-prod.timer` is running again** (I had stopped it; it missed
  ~2.5h). Exit 3 is an end-of-run report, **not** an abort — MLB never stopped
  ingesting. That corrects §13.
- **News collects again.** `legendarypicks-news-prod` runs the full chain in **252s**
  (collector 21s, narratives 175s, discovery 56s) against an 1800s limit. Bluesky
  requests per run **300 → 3**.

## What is now true on DEV

- **The regrade ruler finally moved: 12/187 → 0/204.** 682 games re-graded, 34 not
  final, 0 errors, 0 disagreements against ESPN's box scores.
- **15 `start_time` rows repaired**, re-verify 599/599 agree. This was the whole
  answer to "why did prod go 24→3 and dev not move" — same ruler, different data.
- **Tennis works** (cdrc, `feat/tennis-spine`): atp/wta players 0 → 300, props 0 → 439,
  and `legendarypicks-props.service` now exits 0 where it had been permanently red.
- 0 duplicate groups, unique index present, 309 tests green across the NFL,
  migration and roster suites.
- **News collects again**: whole job **295s** (collector 59s cold / 20s cached,
  narratives 220s, discovery 55s), where it had been killed at 900s having produced
  nothing. 286 new rows into `news_items`.

---

## 3. The mistake of the day, and it was mine

**I applied a schema change to prod's database that prod's code does not
understand.** `ux_prop_games_event` went live instantly — the DB is bind-mounted —
while `_link_or_fold`, the code that handles that constraint, sits in a 5-day-old
baked image that will never ship, because *we never build for prod, we only do DB
stuff*.

Kept the index rather than dropping it, deliberately: with it, a twin stays
**unlinked**, which a working-directory script can heal. Without it, the twin
becomes a **duplicate**, which brings back split props and wrong-final
contamination. A recoverable failure beats an unrecoverable one.

The check that would have caught it, and that I should run before any future
DB-only change: `docker exec legendarypicks-backend-1 grep -rc "<new symbol>" .`

Saved as `feedback_schema_must_not_outrun_prod_code`.

---

## 4. What is still open

0. **101 commits sit on `dev`, unpushed.** Every fix below exists only in this local
   branch. Working tree also carries 2 modified tracked files and ~18 untracked
   `TASK-*.md`/`RESULT-*.md` specs — read them before any worktree cleanup.
1. **`start_time` write-once — the one defect confirmed to recur.** `routers/props.py:473`
   and `bovada_scraper.py:856` both guard `if start_time and not game_row["start_time"]`,
   so a publisher revising first pitch can never propagate. That is the +17h/+19h class
   (~20 of prod's 95 disagreements), separate from the +24h rollover class now fixed.
   **Needs a policy call**: last-writer-wins, or overwrite only when the publisher
   disagrees. I recommend the second — it keeps the publisher authoritative and stops a
   stale board overwriting a good instant. Three guards to change.
2. **v0.8.0 blocked** — 2 gate FAILs.
3. ~~`discover_topics.py` Stage 2 fails silently~~ — **FIXED, and it was never a parse
   failure.** See §6b. The model was truncated mid-reasoning and returned an empty
   answer; the message blamed the parser. Two more call sites had the same ceiling.
4. **Bluesky search: the code is done and waiting on a credential Micah must create.**
   The auth path shipped in `ed2e6b2` — `createSession` → `accessJwt` →
   `Authorization: Bearer`, reading `BSKY_HANDLE` / `BSKY_APP_PASSWORD` from
   `/root/.hermes/.env`. Verified to the edge of what a credential-less test can reach:
   with a token present the requests come back **401 from the API** instead of 403 from
   the CDN edge, which proves the header is carried the whole way.

   **The one remaining step is human.** `com.atproto.server.describeServer` reports
   `"phoneVerificationRequired": true`, so account creation needs an SMS I cannot
   receive. Micah: sign up (a dedicated handle, not a personal account), then
   Settings → Privacy and Security → **App Passwords**, then put it in
   `/root/.hermes/.env` as `BSKY_HANDLE=` and `BSKY_APP_PASSWORD=`. An app password is
   scoped and revocable and cannot change the account. Nothing else is needed — the next
   news run picks it up and prints `bluesky: authenticated as <handle>`.

   (`getAuthorFeed` also answers 200 unauthenticated and is a cheaper complement — one
   request per followed account against 100 keyword searches — but it is not a
   substitute for search.)
5. **The unconfigured-ESPN-script gate is unwritten** — 20 of 27 scripts, including
   `bovada_scraper.py`. `link_prop_games.py` already has a working budget guard that
   fired during testing (`REFUSING: 165 requests to one host, ceiling is ~100`); that is
   the model to generalise.
6. **Prod tennis is fixable DB-only, no deploy — and it is now holding two units red.**
   `_resolve_player_for_ingest` is data-driven, so running `ingest_tennis_players.py`
   against `picks.db` would let the stale container resolve them. Measured 09:15:
   **atp 0 of 192, wta 0 of 192** (384, not the 358 the handoff carried). This is what
   makes `props-prod` exit 3, which in turn trips `props-freshness`.
6b. **`props-freshness` self-heal waits synchronously.** `systemctl start` on a
   `Type=oneshot` blocks until the job completes; the watchdog gives it 15s and then
   reports `self-heal failed`. One-line fix (`--no-block`), independent of 6.
7. One residual, too small to chase: **1 prop_games row / 2 props stores team codes**
   (`MIA @ PIT`) instead of names, so its gamePk will not resolve.

---

## 5. NFL ADP — the pass after the handoff was last written

`ingest_nfl_adp.py` had failed **every run since ~04:10** on both DBs with
`D/ST preflight: def_to_pid has 0 entries, expected 32`.

**The preflight was not broken. It fired correctly on broken data.** The break was
two of our own migrations:

- `migrate_player_fantasy_positions.py:114` NULLs `players.position` for rows it
  selects **BY** `entity_type`.
- `migrate_player_entity_type.py` classified **FROM** `players.position`.

Both are individually correct and individually idempotent. **The pair is not.** Run
them in that order and all 96 NFL constructs come back `unknown` — and
`ingest_nfl_adp.py` builds its D/ST team map `WHERE entity_type='team_defense'`.

Generalisable rule: **whenever migration A writes a column B reads, re-running B is
destructive.** Look for that shape before writing either.

Fixed in three commits, all working-directory code, so it reached prod with no rebuild:

- `1c7f503` — classify from ESPN's id encoding (`-16000/-15000/-14000` minus
  proTeamId), a fact the feed states that no migration of ours can empty. Gated on
  `league='nfl'`: two NCAAF team rows (`-15591` CCU, `-14550` FIU) sit inside the same
  numeric window. Second, independent guard: **never downgrade** a classified row to
  `unknown`.
- `7546216` — the manifest probe counted `entity_type IS NULL` only. The rows were
  *populated, just wrong*, so it read `applied` for the entire outage.
- `ce11c39` — deleted `ingest_nfl_adp._entity_type`, a dead second copy of the
  classifier carrying the identical bug.

Verified as a gate, not just as a test: I reconstructed the old classifier and ran the
new test against it — it reproduces the broken state exactly (`{'player': 1,
'unknown': 99}`). Prod 835 rows set, dev 1,235. Both probes read `applied` on both DBs.

Saved as `feedback_migrations_must_not_share_a_column`.

---

## 6. The news job — and the diagnosis Micah had to correct

`legendarypicks-news.service` had been dying at `Result=timeout` since 03:35, having
printed its start line and **nothing else** for 15 minutes.

### What it actually was

I opened this by calling the Bluesky 403 an ESPN-style per-host wall. Micah: *"it's
not an ESPN wall it's wrong querying."* He was right, and the measurement is
unambiguous — same box, same IP, same second:

| endpoint | `public.api.bsky.app` | `api.bsky.app` |
|---|---|---|
| `app.bsky.actor.getProfile` | 200 | 200 |
| `app.bsky.actor.searchActors` (also a **search**) | 200 | — |
| `app.bsky.feed.getAuthorFeed` | 200 | — |
| `app.bsky.feed.searchPosts` | **403** | **403** |

**A volume block refuses the host. This refuses one path.** Two more tells: the 403
returns in 0.11s on a cold first request, and its body is a **BunnyCDN edge page**,
not Bluesky's JSON error envelope — the request never reaches the API.

### Correction, made the same session — search is RECOVERABLE

I first wrote that `searchPosts` was closed to us "permanently, at any rate, from any
address." Micah pushed back that search is the only part of Bluesky worth having, which
sent me back to measure the thing I had asserted instead of tested:

| request | result |
|---|---|
| `api.bsky.app` `searchPosts`, no header | **403**, BunnyCDN edge page |
| `api.bsky.app` `searchPosts`, `Authorization: Bearer <malformed>` | **401 `{"error":"BadJwt","message":"poorly formatted jwt"}`** |
| `bsky.social` `com.atproto.server.createSession` | **401** (fake creds) — endpoint live |

A malformed token gets a **real ATProto error**, which means the request passes the edge
and is auth-checked by the API. The gate is on being *unauthenticated*, not on us.
`createSession` with an app password → `accessJwt` → `Authorization: Bearer` restores it.
**That needs a Bluesky account and a credential — Micah's call, so it is written up, not
done.** It is now §4.4 and it is a live option, not a dead end.

What I actually fixed was the job bleeding 300 requests a day into that wall. **I did not
restore the search data, and saying "fixed" without that distinction was the error.**

Line 226 of `ingest_league_news.py` shows the identical mistake made on 2026-08-06:
that 403 was "fixed" by swapping `public.api.bsky.app` → `api.bsky.app`. Both refuse
it. **Answering a refusal by changing hosts, before establishing what the refusal
means, is how a wrong diagnosis gets written into the code as a comment that the next
reader trusts.**

### The two defects underneath

**1. A retry ladder that assumed transience.** `retry_waits=(2, 5)` over 100 queries =
**300 requests and ~700s of sleeping every run**, to relearn a permanent refusal. That
is what pushed the job past its 900s unit timeout. `host_budget` was `0` — literally
"this publisher has no ceiling" — on a provider hosting us for free.

**2. A hang is not a failure.** Both news scripts promised "a step failing does NOT
abort the next" and neither could keep it, because a step that hangs never fails. The
collector took the whole job down and the narrative and discovery steps were never
reached. And there was **no journal output at all** to diagnose it from: stdout through
`tee` is block-buffered, so the one artifact naming the stuck step died in the buffer
with the process.

### Fixed, in three commits

- `60ccc20` — stop after 3 consecutive refusals, name how many queries were skipped,
  print what was spent; `host_budget` 0 → 120.
- `306cb77` — `run_step` time-budgets each step and always returns 0, in a shared
  `scripts/news-lib.sh` rather than copied into both scripts. Python runs `-u`.
  `news-x-collect.sh` got the same treatment **though it was green**: its 08:19 run
  took 585s against `TimeoutStartSec=600` — 15 seconds of margin — against a ~1100s
  worst case for 17 handles. It was about to start failing the same way.
- `2c1762f` — the four news units existed **only in `/etc`**, so the `TimeoutStartSec`
  900 → 1500 change had no home in the repo. Mirrored into `ops/systemd/`, matching the
  convention the other units already follow. (`-prod` was already 1800, which is
  precisely why prod succeeded on the same script that killed dev.)

### Measured, before and after

| | before | after |
|---|---|---|
| collector | 8min+, killed | **59s** cold / 20s cached |
| whole job (dev) | never completed | **295s** |
| whole job (prod) | — | **252s** |
| Bluesky requests/run | ~300 | **3** |

The `run_step` mechanism was proved on a synthetic hang, not just reasoned about: the
hung step was killed at its budget, **the later step still ran**, and the script exited 0.

Saved as `feedback_free_provider_call_policy` — including Micah's policy, stated this
session: *"we have to have a policy on [requesting] from free providers, we have to
respect them and not over call."*

---

## 6b. `discover_topics` — the message named the wrong culprit

`Stage 2 FAILED (model returned nothing parseable) — no writes`, every night, exit 0.
The model parsed fine. **It never answered.** Reproduced with the error surfaced:

    finish_reason: length
    usage: completion_tokens 4000, of which reasoning_tokens 4000
    content len: 0

`reasoning_effort=high` spends the ceiling **before** the answer, so a ceiling the
reasoning alone can exhaust returns an empty string. At `max_tokens=24000`:
`finish_reason='stop'`, reasoning 6362, completion 7085, **14 of 14 candidates judged**.
`max_tokens` is a ceiling, not a spend — unused budget is not billed. We were paying for
4000 reasoning tokens a night and discarding the result.

**Three layers, each of which hid the next:**

1. `_core._deepseek_chat` had a bare `except Exception: return None`. A missing key, a
   401, a 402, a 429, a 90s timeout and a truncated answer were **one indistinguishable
   value**. The API had put `finish_reason` and the token accounting in the response and
   the except threw them away. Now still returns `None` (a request-path caller must not
   be made to raise) but prints the real reason — verified against a bad key: it prints
   the API's own 401 message.
2. `max_tokens=4000` at **three** call sites. `_BATCH_MAX_TOKENS=24000` already sat two
   hundred lines above one of them with the reason written on it — *"10000 truncated 13
   cards"* — and never reached the other two. `ingest_league_narratives:1455` was worse:
   its retry loop called the empty answer "unparseable" and burned the same doomed
   ceiling a second time.
3. `run()` returned like any other path, so `main()` exited 0 and systemd recorded
   `Result=success` for a run that wrote nothing.

And a gap I opened myself: `run_step` returns 0 unconditionally so later steps still run,
which would have swallowed discover's new exit 1 one layer up. `finish()` splits the two
requirements the script owes — **keep going, then report** — and was proved on a failing
middle step: the third step ran, the script exited 1 naming the failure.

Commits `ae6d8b2`, `d0148f8`, `8cbfde5`, `1794281`. Stage 2 now runs: **2 of 14
proposed** on the first real run.

---

## 7. Process notes — what actually cost time today

**Run the failing operation and read its error.** Three separately *measured* causes of
the June hole were all wrong. One `settle_game()` call printed the real one. Measurement
is not diagnosis — a shape you can count is still a hypothesis.

**A named cause is a hypothesis until the fix moves the number.** I wrote "the
duplicates are the mechanism behind prod's June hole" into two docstrings before
measuring the partition: 827 on rows never linked, 4,467 on linked rows with no final
score, 2,212 on duplicated rows, 6,618 on rows already linked/unique/final. **The
duplicates were 16%.** Both docstrings now state the partition instead of the claim.

**Same ruler means the same *data*, not just the same script.** Dev's regrade sat at
15/187 before and after for two sessions. Nothing was wrong with the ruler — I had
repaired prod's rows and never run the same repair on dev, so it kept re-deriving from
an 18.4h-wrong instant.

**"Fix landed on dev, prod never ran it" has an inverse, and I hit both in one day.**
Prod got a schema change dev's code had; dev never got a data repair prod had. Both DBs
answer 200, so nothing detects either.

**A tautological assertion is worse than no assertion.** I wrote
`deleted_results == len(ids) or deleted_results <= len(ids)` — it cannot fail. Replaced
with a query that asks the table whether any wrongly-graded prop still holds a result.
Ask the data, not the counter that records what this run *believes* it did.

**Ask the publisher instead of aborting.** Rule 4 was right to refuse to guess between
two disagreeing finals, but a disagreement is a question, not a dead end. `statsapi`
answered all 7 — and answered them the same way my independent measurement had
predicted, which is what made it safe to apply.

**Delete the second copy.** A dead, unused, wrong duplicate of a classifier sat in the
tree waiting for its first reader. Duplicates are traps, not spares.

**Before concluding anything about a 403, hit a different endpoint on the same host.**
One call separates "we are blocked" from "this endpoint is closed", and they have
opposite fixes. I skipped it and imported ESPN's per-host-wall model onto Bluesky;
Micah corrected it. A model that fits one publisher is a hypothesis about the next.

**Load the project skill BEFORE diagnosing, not after being told.** Micah had to say
"espn skill" while I was already three measurements into an ESPN-adjacent 403. The
skill's §1 corollary — *"do not write a retry ladder that assumes a 403 is
transient"* — is the exact defect I was staring at, and `paced_http.RETRYABLE` has
included 403 the whole time. `ls .claude/skills/` first; a memory file is not the skill.

**A green unit is a claim about its exit code.** `discover_topics.py` printed
`Stage 2 FAILED — no writes` and exited 0, so systemd, the timer and `Result=success`
all agree it worked. Same family as the presence-checking gates in §1.

**An error message is a hypothesis its author wrote before the failure happened.**
"model returned nothing parseable" had been printing nightly and was wrong: nothing was
unparseable, the answer was empty. The three distinct causes behind it were collapsed
into one string by a bare `except`. Read what the failing call actually returned before
trusting the label on it.

**"Fixed" must name what was restored.** I said I fixed the Bluesky problem. I fixed the
job wasting 300 requests a day; I did **not** restore the search data, which is the part
worth having. Micah caught the elision, and the second measurement showed search is
recoverable with auth. Stopping a bleed and restoring a capability are different claims
and they need different words.
