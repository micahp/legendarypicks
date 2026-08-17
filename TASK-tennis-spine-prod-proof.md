# TASK — prove the tennis spine actually fixes PROD, on a copy of prod

## The question, and it is the only question

`backend/ingest_tennis_players.py` exists on `feat/tennis-spine` and **works on dev**.
Measured 2026-08-17 10:00:

    dev  players atp=150 wta=150 (all 300 carry an espn_id)
    dev  legendarypicks-props.service: atp resolved 186 of 192, wta 168 of 192, EXIT 0

Prod has **zero** tennis players, so `legendarypicks-props-prod.service` is RED:

    prod players atp=0 wta=0
    prod atp: resolved 0 of 192 scraped   wta: resolved 0 of 192 scraped   EXIT 3
    prod prop_games atp=134 wta=163, carrying 0 props between them
    prod unresolved_players (atp+wta) = 247

**Does running the spine against prod's data actually turn that green?** Answer it
with evidence. Do not assume it transfers from dev — dev's spine was built while
dev's props were being scraped, and the two databases hold different name sets.

## Work here, and only here

    worktree:  /root/lp-tennis-spine          branch: feat/tennis-spine
    python:    /root/legendarypicks/backend/venv/bin/python   (use it; do NOT pip install)
    scratch:   /tmp/tennis-prod-proof/        (make it; put the DB copy here)

**You may create or modify exactly these:**

- `/root/legendarypicks/RESULT-tennis-spine-prod-proof.md`  (your report — the deliverable)
- anything under `/tmp/tennis-prod-proof/`

**Explicitly forbidden — no exceptions:**

- **`/root/legendarypicks/backend/data/picks.db` (the PROD database). Read-only, always.**
  Open it with `sqlite3.connect('file:...picks.db?mode=ro', uri=True)` and nothing else.
  Every write in this task goes to your copy in `/tmp/tennis-prod-proof/`.
- `backend/data/picks.dev.db` — read-only too. Another job writes it every 30 minutes.
- Any host config: `/etc`, systemd units, timers, cron. A worktree does not isolate
  these. Do not touch them **even to test** — do not `systemctl start` anything.
- Any file in `backend/` other than reading them. This task writes no production code.
- `git commit`, `git push`, `git merge`, branch changes. Leave the tree as you found it.

## Non-negotiables

1. **Read `.claude/skills/published-first/SKILL.md`, `.claude/skills/fail-loudly/SKILL.md`
   and `.claude/skills/espn-request-budget/SKILL.md` first.** They are short and they are
   the house rules. The third one matters here: ESPN's limit is a request COUNT per host
   (~100), not a rate, so state the count you will spend before you spend it.
2. **Never invent an identity.** If a name does not resolve, it does not resolve. Report
   it. Creating a player row from a Bovada display name is the exact defect that put 531
   shadow players into prod MLS.
3. **Print both sides of every count.** `resolved 186 of 192`, never `resolved 186`.
4. **Zero is a finding.** So is 6-of-192. Report the shortfall, do not round it away.
5. **A number you did not measure does not go in the report.** If you could not run
   something, say which command and what stopped you.

## Do this

    mkdir -p /tmp/tennis-prod-proof
    cp /root/legendarypicks/backend/data/picks.db /tmp/tennis-prod-proof/prod-copy.db

**Step 1 — baseline the copy.** Count atp/wta players, prop_games, props, and rows in
`unresolved_players`. These are your "before" numbers.

**Step 2 — run the spine against the copy.**

    cd /root/lp-tennis-spine/backend
    LP_DB_PATH=/tmp/tennis-prod-proof/prod-copy.db \
      /root/legendarypicks/backend/venv/bin/python ingest_tennis_players.py

Paste its real output. State the ESPN request count it spent, per host.

**Step 3 — the actual deliverable: do prod's REJECTED names now resolve?**

This is the question, and it does not need an API server or a scrape. Prod already
recorded every name it threw away, in `unresolved_players` (247 rows, atp+wta). Take
those exact names and run each through the real resolver against your copy:

    from _core import _resolve_player_for_ingest

Report `resolved N of 247`, broken down by league. For every name that still fails,
list it — with a one-line reason if you can tell (absent from ESPN's list? a spelling
the diacritic-folding does not reach? a doubles pairing rather than a player?).

**Step 4 — would `props-prod` exit 0?** Read the exit rule in `backend/bovada_scraper.py`
(it exits 3 when a league resolves 0 of N). Given your step-3 numbers, state plainly
whether prod would exit 0, and at what resolution rate. Quote the code that decides it.

**Step 5 — what it would cost to apply for real.** One paragraph: the exact command,
which rows it writes, whether it is idempotent on a re-run, and whether anything about
it depends on code that is NOT in prod's container. (Prod runs a 5-day-old image and
gets DB changes but never a rebuild. `ingest_tennis_players.py` would be run from the
working directory, but `_resolve_player_for_ingest` runs INSIDE the container — check
whether the container's copy is data-driven or needs code it does not have. This is the
single most important line in your report.)

## Definition of done

`/root/legendarypicks/RESULT-tennis-spine-prod-proof.md` exists and contains:

- the before/after counts from steps 1–2, as real pasted output
- `resolved N of 247` from step 3, by league, with every failure listed
- a yes/no on step 4 with the deciding code quoted
- the step-5 paragraph, especially the container question
- `md5sum /root/legendarypicks/backend/data/picks.db` taken at the START and at the END
  of your run, both pasted, proving you did not write to prod

Do not apply anything to prod. Do not commit. Report and stop.
