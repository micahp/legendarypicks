# Roadmap 2

**Temporary file, created 2026-08-25.** It exists because `docs/ROADMAP.md` is being
rewritten in two places at once: on `dev` (§1 re-measured against prod tonight) and in
Codex's isolated worktree (258 lines changed). Adding new items to either copy would
guarantee a conflict on top of the one already coming.

**Lifecycle:** once Codex's branch is audited, reviewed and landed, everything here moves
into `docs/ROADMAP.md` and this file is deleted. It is not a second roadmap. It is a
staging area with an expiry date.

Checked still means shipped to production, same as the main file.

---

## 0. The merge collision, before anything else

`feat/sport-first-navigation` in `/root/lp-sport-first-nav` is **22 commits, 70 files,
+4,265/-460**, all on copied databases, nothing promoted. Two files collide directly with
what landed on `dev` tonight:

- **`docs/DESIGN-sport-first-navigation.md`** exists in both. I wrote 243 lines on `dev`
  (`c9b512e`); Codex wrote 255 lines on its branch. Same filename, independently authored.
- **`docs/ROADMAP.md`** is heavily edited on both sides.

Resolve those two by hand. Do not let a merge tool pick.

**Codex corrected the design and it was right.** My version said to derive the sport from
`backend/espn_leagues.py`. That file holds only MLS and NCAAF. The complete published ESPN
path registry is **`backend/espn_client/config.py`**, and that is what the implementation
uses. The design doc on `dev` is wrong on this point and should take Codex's version.

---

## 1. Audit Codex's branch, then land it

Everything below is Codex's own claim from its session log, on **copied databases only**.
None of it is promoted, so every number is candidate evidence, not production state.

- [ ] **Audit `feat/sport-first-navigation` (22 commits).** Verify the diagnoses, not the
      "done". Highest-value claims to falsify first, because they are the ones that change
      what we believe about the publisher:
      - **ESPN's tennis scoreboard payload already carries the bracket.** Round names,
        tournament id, bracket relationship, explicit TBD slots for future rounds. If true,
        the Draws tab needs no new endpoint and the open question in the design doc is
        answered. Codex persisted 239 uniquely keyed matches per tour from it.
      - **NFL settlement was a case-sensitivity bug.** ESPN publishes `YDS`, the settlement
        map asked for `Yds`, and the extractor compared labels case-sensitively. Plus
        `field_goals_made` had no mapping while ESPN publishes `made/attempted` as `2/2`.
        Claim: 76 of 80 completed preseason props settled, 1,694 future props untouched.
      - **NCAAF's week query caps at 25 events** while the same published week fetched by
        its calendar date range returns 98. If true, week navigation built the obvious way
        would have shown a quarter of the slate on opening weekend.
      - **MLS and NCAAF scoring plays were read from the wrong key.** The parser read
        `plays`, which is empty for both; NCAAF publishes `scoringPlays` (7 events) and MLS
        publishes `keyEvents` (4 goals). Note the nuance Codex caught: entries inside
        NCAAF's `scoringPlays` omit the redundant `scoringPlay=true` flag, so the collection
        itself is the publisher's filter.
      - **World Cup: 392 null rows split into 267 numeric grades and 125 published DNP
        voids**, with the 14 absent players confirmed rostered-but-unused
        (`appearances=0`, `subIns=0`) from the official summaries rather than inferred from
        our own ingest. The API now distinguishes graded, push, void and pending, which it
        previously did not.
      - **Tennis linkage was start-time drift, not identity failure.** 112 of 142 ATP rows
        had exactly one published two-player match in the adjacent-date window while only 15
        were within 15 minutes of ESPN's court time. Reachable tennis props 547 to 945.
      - **`team_game_stats` MLB rows are residue, not a stalled ingest.** All 16 written in
        one four-second burst on 2026-06-09, every stat column and JSON blob empty.
      - **The migration ledger probe was circular:** the legacy row asked whether a separate
        numbered registry row existed, DEV was already clean so that row correctly never
        existed, and the runner permanently recorded `unknown`.
- [ ] **Re-run the suite against BOTH databases before landing**, not just the copy
      (`feedback_run_the_suite_against_both_dbs`).
- [ ] **Check what the branch does outside the repo.** A split or a new tool that installs
      timers or touches `/etc` is invisible to an import smoke test
      (`feedback_a_split_breaks_things_outside_the_repo`).
- [ ] **Land it, then move this file into `ROADMAP.md` and delete this file.**

---

## 2. Scoreboard defects, both reported 2026-08-25

- [ ] **Back from a game detail loses the day and the league filter.** Diagnosed, not
      guessed: `pages/scores.tsx` **reads** `?date=` and `?league=` into state
      (`pages/scores.tsx:153`) and **never writes state back to the URL**. There is no
      `router.push` or `router.replace` anywhere in the file. So changing the day or the
      league chip leaves the URL at `/scores`, and the browser back button returns to a bare
      `/scores`, which resets to today with no filter.
      Fix is a shallow route write on date and league change so the URL is the state. Two
      traps: `?live=1` is a third piece of state read from the same query and must survive
      the change, and the write has to be `shallow` or every day change refetches the page
      props.
- [ ] **Game detail showed no box score, play-by-play or props for a past MLB game.**
      **The backend is not the cause.** Measured against prod for
      `2026-08-20` game `401816603` (CIN vs STL):
      ```
      /api/mlb/game/401816603/boxscore    200  available=true, 2 teams, 4 player groups
      /api/mlb/game/401816603/playbyplay  200  available=true, 9 periods
      /api/mlb/game/401816603/gameinfo    200  available=true, Great American Ball Park, 15,361
      ```
      So the fault is client side, in the tab fetch or in what the page passes as `gameId`.
      `useTabData` in `pages/game/[league]/[gameId].tsx:186` fetches lazily per tab and
      latches `tabLoaded` **before** the request resolves, so a failed or aborted first
      fetch leaves the tab permanently marked loaded and permanently empty. That is the
      first thing to check.
      **Note the report was made against the pre-deploy frontend.** Prod was rebuilt at
      2026-08-24 20:52 and had been serving v0.8.5 code since 08-21. Reproduce on the
      current build before fixing anything.
- [ ] **Then verify game detail for every league that has it.** `hasDetail` in
      `components/Scores/GameCard.tsx:81` is `NBA, NHL, MLB, NFL, WC, LCUP, MLS`, plus COD
      when it has a verified PandaScore id. Check each, on a past date, not just today.

---

## 3. Scoreboard upgrade

- [ ] **Scoreboard upgrade.** Named 2026-08-25, scope not yet defined. Needs a spec before
      it is work. The two defects in §2 are separate and should not be folded into it.

---

## 4. News

- [ ] **Change "Conversations across leagues" to "Featured".** One string,
      `pages/news.tsx:106`.
- [ ] **Rank what deserves a card using the Innovative Hype article ranking, not the
      current selection.** The engine writes cards well; the problem is which stories it
      picks. Cards keep landing on the same narratives flagged weeks ago, and the open
      question is whether there is genuinely nothing else worth a card or whether selection
      is stuck.
      **Explicitly out of scope: the card writing itself.** Do not change prose generation.
      The deliverable is that the "more news" list becomes trustworthy, so that seeing no
      card means there was nothing to make a card about.
      Source system is `/root/innovative-hype-newsletter`. Read what its ranking actually
      keys on before porting anything, and carry over the lesson already recorded there:
      a ranking that feeds present tense must rank on age
      (`feedback_record_what_you_generated_from`), and a seed is a ranking key rather than a
      search string (`feedback_a_seed_is_a_ranking_key`).
      Related and still open in the main roadmap: `layer='other'` is 72% of prod rows.
      A selection system cannot be trusted while the largest bucket is undefined.
- [ ] **Em dashes are reaching the UI.** 79 files under `components/` and `pages/` contain
      one. Some are in test fixtures and comments, which do not matter; what matters is
      rendered copy and anything the news engine writes. Sweep the rendered strings, then
      put the rule where generation happens so it cannot come back
      (`feedback_no_em_dashes`).

---

## 5. Prediction page

- [ ] **Extend `/predict` from esports-only to all sports plus esports.** Today every fetch
      in `pages/predict.tsx` is an `/api/esports/*` route, so this is a real contract change
      and not a filter.
- [ ] **History and Matches as horizontal tabs spanning the full content width.** Two tabs,
      not a dropdown.
- [ ] **The horizontal title list cannot be scrolled to its end on web.**
      `pages/predict.tsx:260` is `overflow-x-auto` with both scrollbars hidden
      (`[scrollbar-width:none]` and `[&::-webkit-scrollbar]:hidden`), which leaves a desktop
      user with no scrollbar and no wheel affordance. Fix so the end is reachable with a
      mouse, not only by touch drag.

---

## 6. UFC

- [ ] **DraftKings lineup optimizer for UFC.** Note the existing
      `docs/SPEC-ufc-lineup-generator.md`; read it before writing a new spec.
- [ ] **UFC player detail, search, and performance / matchup / model tabs.**

---

## 7. Tennis

- [ ] **ATP and WTA rankings on scoreboard cards.** Full entry with all measurements is in
      `docs/ROADMAP.md` §10 as committed tonight (`e3647c1`). Summary: the tournament seed
      rides on `competitors[].curatedRank.current` in the scoreboard payload we already
      fetch and we discard it at `backend/espn_client/scoreboard.py:270`, along with the
      ESPN athlete id. World rankings are at
      `sports.core.api.espn.com/v2/sports/tennis/leagues/{atp,wta}/rankings`, join on the
      athlete id with no name matching, and are verified against the publishers:
      **WTA 100 of 100 points-exact against `api.wtatennis.com`, ATP 50 of 50 against
      tennisexplorer.com.** 150 is a hard cap, only one week is published so `captured_at`
      must be in the primary key, and every `atptour.com` host is Cloudflare-403 from this
      box.
- [ ] **Tennis sport page with the current tournament's brackets, men's and women's singles
      only.** Codex has already built `/leagues/tennis` on its branch from stored draw data.
      Audit that first rather than starting over.
- [ ] **Tennis player detail.**

---

## 8. Carried from tonight, deferred by decision

- [ ] **Run `spine_merge`.** 259 dev, 447 prod planned. Dev first, one league at a time,
      NFL as the real rehearsal since it is 437 of prod's 447, with the duplicate baseline
      as the before and after measurement. Deferred until after the deploy by Micah's call
      2026-08-24.
- [ ] **547 prod and 293 dev duplicate groups unrepaired.** Frozen by the gate, not fixed.
      Same deferral.
- [ ] **`nfl_published_fantasy_points` drift** between dev and prod.
- [ ] **`backend/picks.db` and `backend/picks.dev.db` are 0-byte strays**, untracked and
      **not gitignored**, so they sit in the path of a `git add -A`. Dated 2026-08-23, not
      created by any session that has looked at them.
- [x] **`batch_pacing` 1.5s to 2.5s. DECLINED** by Micah 2026-08-24. Recorded so it is not
      proposed again.

---

## 9. Production state, so this file does not repeat the last one's mistake

**v0.8.8 deployed 2026-08-24 20:52.** Verified by content: `/app/ingest_scoreboards.py`
in the running container hashes `d5b840308b65efe19c50102a1d6a4d23`, no longer the v0.8.5
`c3aa055ab7fe0b89148c7e5b9e70c1bd` it had served since 08-21. All six API keys present in
the container, Kick included. Rollback images are `*:rollback-pre-v0.8.8`.

This was the first time in three releases that prod received backend code, so the future
slate backoff, the pacing on four fan-outs and the Bovada parser fix all started applying
at 20:52. **Nobody has yet watched a full daytime slate against this build.**
