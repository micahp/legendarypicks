# ESPN-linked AP wire benchmark results

**Run:** 2026-11-04, using the curated five-game November 4 NBA sample.

**Frozen LP snapshot:** generated at `2026-11-03T16:54:59Z` on PR head `cc5695849a9454c58ca7bfd78031dde8552ded9f`.

**Replay:** PR head `88abf4b12c6fb3021c1e636ef0c3d05a6ba06a06`; renderer SHA-256 `2791cd0fd723de721859b5d64dacd50646b6b6aed7697d5dedc24b1fa1924e92`.

## Method and result

I replayed each saved LP fact bundle through the current PR renderer, compared its frozen story with the linked AP wire brief using short paraphrases, and ran `story_engine_audit.audit_story` against the same cutoff-filtered facts. All five stories replayed byte-for-byte, and all 50 independent audit checks passed. The article review was unblinded and is not a fan preference study.

The numerical hook claims in all five wire briefs match the saved cutoff facts. The Memphis overtime detail is also supported by the [NBA game summary](https://www.nba.com/game/nop-vs-mem-0022600165), although overtime was not included in the story-engine input. Injury lists were not independently checked against an injury source.

All five pages identify Associated Press syndication with Data Skrive and Sportradar attribution. Three are hosted by FOX Sports; two appear on ABC local affiliate pages with ESPN branding/copyright. None is an ESPN staff-authored preview.

| Matchup | LP story angle | Wire focus, paraphrased | Result and gap diagnosis |
| --- | --- | --- | --- |
| [Cleveland at Oklahoma City](https://www.foxsports.com/articles/nba/gilgeousalexander-leads-oklahoma-city-against-cleveland-after-43point-game) | Team records, then Shai Gilgeous-Alexander's 23-plus scoring in four of five | Shai's 43 points in OKC's 117-112 win over Cleveland before the rematch | Different lead. The 43-point log and same-opponent result were present in LP evidence but not extracted into the story. |
| [Indiana at Memphis](https://www.foxsports.com/articles/nba/jerome-leads-memphis-against-indiana-after-40point-game) | Indiana's five-game skid; Ty Jerome's average and a 40-point mention | Jerome scored 40 in Memphis's overtime loss; the wire uses winner-first 135-134, or 134-135 from Memphis's perspective | Partial hook match. LP mentions 40 but not the loss. The score and result are in its facts; overtime is absent from LP input. The [official NBA game summary](https://www.nba.com/game/nop-vs-mem-0022600165) confirms the final and Jerome's 40. |
| [Philadelphia at Detroit](https://6abc.com/post/pistons-set-play-76ers-wednesday/20010737/) | Top-four teams, with Cade Cunningham and Tyrese Maxey form | Eastern Conference leaders; Detroit's 106-93 win on Oct. 25; injury list | Same lead category. Prior-meeting results were in LP evidence but unused; injury data was absent from engine input. |
| [Charlotte at Brooklyn](https://www.foxsports.com/articles/nba/charlotte-takes-on-brooklyn-aims-to-halt-4game-slide) | Charlotte's four-game losing streak and both records | Same four-game slide; prior 110-103 meeting; injury list | Same lead. Prior-meeting result was in LP evidence but unused; injury data was absent from engine input. |
| [Los Angeles Lakers at Sacramento](https://abc7.com/post/sacramento-hosts-los-angeles-doncics-42-point-game/20010733/) | Records and streak, plus Darius Acuff Jr. and Luka Doncic's 42 and 45 | Luka's latest 42-point game in a 138-117 win over Miami | Partial hook match. LP includes the 42-point game but omits its opponent/result, which were available in the cutoff bundle. |

Hook alignment was the same in 2 games, partial in 2, and different in 1. Relevant player facts appeared in four LP stories. The wire briefs provided previous-meeting context in three games, and LP selected none of those head-to-head results. All five wire pages listed injuries, but the deterministic engine inputs had no injury facts.

Hook labels are descriptive: **same** means both leads use the same main story; **partial** means the wire's key player or team fact appears in LP prose but is secondary or missing its specific game context; **different** means LP uses a different lead and omits the wire's distinguishing event.

## Timing and limits

The visible article publication timestamps precede the LP run in all five cases: FOX pages show Nov. 3 at 2:02 a.m. ET, 6abc shows 7:07 a.m. ET, and ABC7 shows 7:06 a.m. PT. Those timestamps establish publication before LP generation. The pages were reviewed on Nov. 4; exact capture times and modified timestamps were not exposed, and immutable copies from the LP cutoff were not saved. This does not prove that every page's content was unchanged at the precise LP cutoff.

This is a curated five-game, unblinded diagnostic comparison. It makes no human preference or general quality claim. The external material is AP/Data Skrive syndicated writing, not first-party ESPN staff copy. No article body text is stored. Machine-readable per-game metadata, paraphrases, audit results, and diagnoses are in [`results.json`](results.json).
