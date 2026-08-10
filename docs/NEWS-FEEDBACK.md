# News Feedback — the editor's pass over the news engine

**Status:** LIVE on dev — 2026-08-09 (news is dev-only; not promoted to prod)
**Scope:** `backend/news_feedback.py`, `backend/ingest_league_narratives.py`
(`_editor_marks` + `_log_deletion`), `_core.py` (`news_card_feedback` table).
**Parent:** `docs/PLAN-league-news-engine.md` (the news engine itself).

## 1. What this is — and what it deliberately is not

The news engine turns collected chatter into one card per conversation
(`ingest_league_narratives.py`). The card's framing — what it leads with,
which angle it treats as the story — is a judgment call, and the model
sometimes gets it wrong: it anchored the `ufc-title-fight` card on a
*fighter-safety* editorial tangent instead of the title picture, which read
as a confusing fight recap.

This doc covers the mechanism that steers that judgment — and the record of
when a card vanishes.

**The model, not the human, defines the boundary.** Micah, 2026-08-09:

> i don't want to define it. i don't want to have to define it. i just want
> to come in as an editor every now and then and review topics and say that
> was bad do less of that and this was good do more of this.

So the feedback is **run-level editorial verdicts** — "more of this" / "less
of that" — not a rules engine and not per-article labeling. A verdict on a
specific generated version of a card becomes a few-shot example the next
generation matches against; the model infers the on-theme / off-theme
boundary from the *contrast* between good and bad cards. There is no
hardcoded "safety = tangent" rule. The human never writes a rule; the human
just says good or bad.

**What it is NOT:**

- **Not a fine-tune.** The teaching set lives in the prompt as few-shot
  examples, read from the DB at generation time. DeepSeek is an API; we don't
  train weights. "Like training a model" means the example set grows richer
  with every verdict, and the model's behavior drifts toward it.
- **Not per-article labeling.** The earlier design tried to label individual
  source URLs as positive/negative patterns per conversation. That asked the
  human to *define* the boundary for every article — exactly the work Micah
  refused. The teaching signal is the **whole card** (the framing it chose),
  not which articles it cited.
- **Not auto-protection.** A conversation you've marked good is *not*
  automatically shielded from a batch decline. The chosen workflow is
  lighter: deletions are *logged* (§4) and recoverable by hand (`--serve`),
  reviewed on the human's cadence, not the cron's.

## 2. The teaching signal

A verdict is recorded against a **run** — a single generated version of a
conversation card. Run history (`news_narratives_runs`) appends every
generation and never overwrites, so every version a conversation has ever
had is there, each with an `id`. The same conversation can have a good run
and a bad run (e.g. the Makhachev title-picture run = good; the Pereira
foul-forgiveness run = bad).

At generation time, `ingest_league_narratives.py::_editor_marks(con,
conv_id)` joins `news_card_feedback` to `news_narratives_runs` and builds a
block:

```
Editor marks:
GOOD cards for this conversation — match this kind of framing (more of this):
- Dana White all but confirms Usman Nurmagomedov for the UFC, complicating the lightweight title picture.
BAD cards — do NOT frame it this way (less of this):
- Quillan Salkilld submits Mateusz Gamrot at UFC Vegas 120 as a corner decision prompts a fighter safety debate.
```

This block is prepended to the user prompt in **both** the per-conversation
path (`_generate`) and the batch path (`_generate_batch`, per block). When a
conversation has no marks yet, the block is empty and generation behaves
exactly as before — the loop is opt-in per conversation.

The system prompt's only steer on this is a soft principle:

> The user may have marked prior cards for this conversation GOOD or BAD …
> Infer the boundary from the contrast between the good and bad examples —
> do not apply a fixed rule, and never just echo a bad example's wording.

The model does the pattern-matching; the human supplies the labels.

### Proof it replaces a rule

Before this loop existed, a hardcoded prompt rule enumerated tangents
("fighter safety, officiating, a corner decision … is a TANGENT"). That rule
was too rigid — sometimes an editorial *is* the narrative (a "fighter
safety" conversation would want that angle). The rule was removed.

Verification (2026-08-09): run #71 (the Salkilld/safety-tangent card) was
marked **bad**. UFC was regenerated. The deadspin safety article was *still
in the anchor pool* — the only thing steering the model away from the safety
framing was the bad-mark. The output was a title-picture card (Nurmagomedov
signing → Makhachev clash → Prates hint), not the tangent. Few-shot from a
single verdict replaced the rule.

## 3. The CLI — `backend/news_feedback.py`

The editor's handle. CLI-only (no frontend) — matches a terminal-first
review. Set `LP_DB_PATH` to the dev DB (the cron's wrapper does this
automatically; for manual runs use
`LP_DB_PATH=backend/data/picks.dev.db`).

| Command | What it does |
|---|---|
| `--conv ufc-title-fight --list` | List that conversation's runs, newest first, each with `id`, timestamp, narrative preview, source count, and any verdicts already applied. This is how you find a run `id`. |
| `--run 72 --verdict good --note "title picture, not safety"` | Record an editorial verdict on a run. `verdict` is `good` or `bad`. The note is free text. Prints a confirmation and how many marks the conversation now has. |
| `--run 71 --verdict bad --note "safety tangent, confusing"` | The "less of that" verdict. |
| `--serve 72` | Promote run 72's card to the **served** `news_narratives` row for that conversation — "do more of this" made immediate, without waiting for the next cron. |
| `--conv ufc-title-fight --show` | Review the marks for one conversation, newest first, with the run narrative each mark refers to. |
| `--status` | Per-conversation good/bad counts across the board — quick "what have I reviewed" scan. |
| `--deletions` | Print the deletions log (§4) — the full served cards a run wiped. |

**Verdict semantics.** `good` → the run's narrative becomes a positive
few-shot example (match this framing). `bad` → a negative example (do not
frame it this way). Verdicts are append-only audit rows in
`news_card_feedback`; the few-shot takes the latest good (≤3) and latest bad
(≤2) per conversation. There is no "change your mind" — just record a new
verdict; the marks shown are most-recent-first, and you can `--serve` a
different run if your read changes.

## 4. The deletion log — "some are missing now"

A conversation that the model declines (chatter deemed unrelated, or a parse
failure) wipes its **served** card from `news_narratives`. That delete is
the mechanism behind "the run-history API has some that are missing now" —
the card stops rendering even though every version is still in run history.

Every such delete is now logged. `_log_deletion(con, conv, reason)` reads
the served row *before* the delete and appends its full content to
`data/news-deletions.log`:

```
[2026-08-10 03:35:14] DELETED conv=nba-kawhi-cap league=nba reason=model-declined
  served-since: 2026-08-09 22:31:59
  narrative: Kawhi Leonard salary-cap circumvention allegations draw banishment calls
  fan_voice: ...
  paragraph: ...
  sources: [...]
  source_count: 2
```

`reason` is one of:

- `model-declined` — the model returned `narrative: null` (chatter genuinely
  unrelated). This is the model's judgment, not a failure.
- `model-failure` — the model returned nothing parseable after retry (single
  path only; a full batch failure keeps all existing cards and logs nothing).

Read it during review with `news_feedback.py --deletions`. If a good card
vanished, recover it: `--conv X --list` → find its run `id` → `--serve <id>`
(and optionally `--run <id> --verdict good` so the model favors it next
time and is less likely to decline it again).

The log path is `LP_NEWS_DELETIONS_LOG` (env-overridable), defaulting to
`backend/data/news-deletions.log`. The cron (`scripts/news-collect.sh`) runs
the ingest from `backend/`, so the same path is used — no cron change was
needed.

## 5. The review workflow

This is the cadence Micah asked for — "come in as an editor every now and
then," not a constant loop:

1. **Open the news page** (dev `:3096` → `:8096`). Read the served cards.
2. **`news_feedback.py --deletions`** — see what the last cron wiped, with
   full text. Restore anything good that vanished (`--serve`).
3. **For each served card worth judging:** `--conv X --list` → `--run <id>
   --verdict good|bad --note "..."`.
4. Walk away. The next cron generation reads your marks as few-shot and
   drifts toward "more of this / less of that."

You are not committing to review every card every time. The marks accumulate;
conversations with no marks generate exactly as they did before this feature
existed.

## 6. Schema

```sql
CREATE TABLE news_card_feedback(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  run_id INTEGER NOT NULL,            -- -> news_narratives_runs.id
  conv_id TEXT NOT NULL,
  verdict TEXT NOT NULL,              -- 'good' | 'bad'
  note TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL DEFAULT (datetime('now')));
CREATE INDEX idx_ncfb_run ON news_card_feedback(run_id);
```

The teaching set is **derived** — `news_card_feedback` joined to
`news_narratives_runs` at generation time. There is no separate
examples table: a `news_conv_examples` per-URL table was built then dropped
the same day (2026-08-09) as the wrong granularity — it asked the human to
define the boundary per article, which is the work this feature exists to
avoid. Run history is the single source of card content; the feedback table
only holds the labels.

## 7. Operational notes

- **Dev-only.** News (and this feedback loop) live on `picks.dev.db`
  (`:8096`). Promoting to prod requires migrating the `news_narratives`,
  `news_narratives_runs`, and `news_card_feedback` schema onto prod
  `picks.db` first. See [feedback_dev_fix_prod_never_ran].
- **DeepSeek.** `_editor_marks` adds tokens to the prompt; the batch
  `max_tokens` is 10000 to keep the now-larger batch JSON parseable. DeepSeek
  is cheap — do not starve reasoning or tokens to save cost.
- **No keys printed.** `news_feedback.py` writes only to the local DB and
  log; it makes no network calls.
- **Not committed to a fine-tune cadence.** There is no retraining step. The
  "training" is the slow growth of `news_card_feedback`; a conversation with
  3 marks steers generation, a conversation with 0 marks is untouched.

## 8. Follow-ons (not built)

- **Good-mark protection from silent deletion.** Currently a batch decline
  wipes the served card even for a conversation you've marked good (you
  recover it from the log + `--serve`). If that proves annoying, the decline
  path can skip the delete when the conv has a `good` verdict and keep the
  last good version serving. Chosen against for now in favor of the
  human-driven log-and-restore workflow.
- **In-loop topic add.** The strongest topics are ones Micah gives verbally;
  they currently become `CONVERSATIONS` entries by a code edit. A DB-backed
  conversations table + an `--add-topic` flag would let a new topic enter
  without touching Python.
- **Verdict on the served card vs. a run.** Today verdicts target a specific
  run (version comparison via run history). A "this *current* card is bad"
  shorthand that resolves to the served run's id is a small UX nicety.
