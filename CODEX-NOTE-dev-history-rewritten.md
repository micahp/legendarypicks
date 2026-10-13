HEADS UP: `dev` history was REWRITTEN and force-pushed. Do not merge dev again
until you have read this.

WHAT HAPPENED
  v0.9.0 was cut as a MINOR by mistake; the intent was a patch. That tag and its
  GitHub release are deleted. To make the recut honest, the release commit
  0da92be (which set package.json to 0.9.0) was amended to 0.8.10. Amending a
  commit changes its SHA, so all 42 commits stacked on top of it were replayed
  and every one has a NEW SHA.

  old dev tip   8105417
  new dev tip   42c544b   (origin/dev now)

  Tags now: v0.8.10, v0.8.11, v0.8.12. v0.9.0 no longer exists anywhere.

WHY THIS AFFECTS YOU
  Your branch `feat/sport-first-navigation` merged dev at 1b8ce61, absorbing
  those commits under their OLD SHAs. Git now sees two sets of commits with
  identical content and different identities.

  A plain `git merge dev` will therefore try to replay all 42 as new work
  against content your branch already has -- conflicts on every file touched
  twice, across the provider split, the chart rebuild and the props work. Do not
  do that.

  One anchor to orient by, same commit, both histories:
    old  7f120d3  Move the Confidence help to the end of the sort controls
    new  a5b16dc  Move the Confidence help to the end of the sort controls

WHAT TO DO
  Your own commits are fine -- they are yours and are not affected. Only the
  merged-in dev commits are duplicated. Rebase your branch onto the new dev so
  git drops the duplicates:

    git fetch origin
    git rebase --onto origin/dev 1b8ce61 feat/sport-first-navigation

  That replays only YOUR commits made after the merge, onto rewritten dev. If it
  fights you, say so and stop rather than forcing it -- your uncommitted
  prediction-settlement work is worth more than a tidy graph.

  A safety ref exists on the ORIGINAL history: `backup/dev-before-version-rewrite`
  at 8105417, in /root/legendarypicks. Local only, not pushed. Nothing is lost.

WHAT ELSE CHANGED ON DEV WHILE YOU WERE OUT
  - Providers now own separate TABLES: `player_game_logs` is ESPN-only at one
    row per appearance, `player_game_logs_fotmob` is FotMob's, and the view
    `player_game_logs_all` joins them. `routers/props.py` reads the view.
  - `PRAGMA foreign_keys=ON` in `_core._db()`. Both databases are at zero
    violations. A prop naming a nonexistent player now RAISES.
  - Bovada no longer ingests tennis Set Betting, and the stored rows are gone.
  - The board has Confidence and Odds sorts; pick'em books render no price.
  - NFL chart map keys were wrong for all eight markets and are fixed.

  Your settler-proving task (CODEX-TASK-prove-the-settlers.md) still stands and
  is unaffected by any of this.
