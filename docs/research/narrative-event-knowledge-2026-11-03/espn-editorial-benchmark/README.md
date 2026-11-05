# ESPN/AP pregame editorial benchmark (five-game matched sample)

Status: initial five-game research comparison completed November 4, 2026. Does **not** change `core_stories.py`, the deterministic renderer, its scoring thresholds, or production.

## Why this benchmark matters

The current LP deterministic engine is good at combining records and player-form templates, but it sometimes loses the most recent exceptional performance, immediate rematch, or previous head-to-head result. Some matchup previews linked by ESPN are Associated Press / Data Skrive / Sportradar syndicated briefs rather than handcrafted long-form ESPN reporting. Both are useful comparison categories, but they must be distinguished. This seed audit uses **verified AP syndication** and not an independently captured first-party ESPN article body. Direct ESPN game pages were not readable in the research environment.

**Do not copy source text into the product or repository.** Store story URLs, credited publisher, publication/capture times, headline metadata, and short paraphrased editorial annotations. Respect copyright and source terms. ESPN must be a **benchmark only**, not a runtime dependency. The LP server's deterministic pregame generator remains zero-network, zero-model.

## Matched November 4 NBA sample

LP outputs here are the frozen stories in `../deterministic-engine/MULTISPORT_RUN_2026-11-03.md`. That run reports 2026-11-03T16:54:59Z and zero inference/network calls. The three FOX Sports copies show publication at 02:02 a.m. ET; 6abc shows 07:07 a.m. ET, and ABC7 shows 07:06 a.m. PT on November 3. Comparisons below are qualitative, **not blinded ratings** and not a claim of human editorial preference.

| Game / ESPN ID | LP lead and content | AP/Data Skrive lead and content (paraphrased) | Editorial gap |
| --- | --- | --- | --- |
| CLE at OKC / 401909929 | Cleveland 4-3 visits 5-2 OKC; Shai Gilgeous-Alexander scored 23+ in four of five | Shai scored **43** as OKC **beat Cleveland 117-112**, and they immediately meet again | **Wire wins hook**: LP missed spectacular latest performance and immediate same-opponent rematch |
| IND at MEM / 401909927 | Indiana on five-game skid; Jerome's five-game average plus passing mention of 40 | Jerome's **40 points in Memphis's 135-134 OT loss** to New Orleans is the headline | **Wire wins immediacy**: LP treats the signature game as a footnote |
| PHI at DET / 401909922 | Top-four matchup at 7-1 vs 6-1, with Cade Cunningham and Tyrese Maxey form | Matchup of East leaders; Detroit beat Philadelphia **106-93 on Oct. 25**, plus injury availability | **LP wins tone/player context**; wire contributes head-to-head and availability |
| CHA at BKN / 401909925 | Charlotte has dropped four straight and Brooklyn is 1-6 | Charlotte tries to end four-game slide; earlier **110-103** meeting and injuries | **Similar lead**, wire adds specific previous meeting |
| LAL at SAC / 401909934 | Lakers 6-2 against Kings 1-6, Darius Acuff and Luka's 42/45 recent scoring | Luka's latest **42-point game** leads the preview | **Different choice**: compare whether recent star eruption or record mismatch better sells this one |

### Verified wire sources

- CLE at OKC: https://www.foxsports.com/articles/nba/gilgeousalexander-leads-oklahoma-city-against-cleveland-after-43point-game
- IND at MEM: https://www.foxsports.com/articles/nba/jerome-leads-memphis-against-indiana-after-40point-game
- PHI at DET: https://6abc.com/post/pistons-set-play-76ers-wednesday/20010737/
- CHA at BKN: https://www.foxsports.com/articles/nba/charlotte-takes-on-brooklyn-aims-to-halt-4game-slide
- LAL at SAC: https://abc7.com/post/sacramento-hosts-los-angeles-doncics-42-point-game/20010733/

These are matching AP/Data Skrive syndications; **do not silently relabel them first-party ESPN editorial articles**. Official ESPN matchup URLs and article provenance must be confirmed separately before an `espn_verified` label is assigned.

## Repeatable, apples-to-apples evaluation

1. **Sample** upcoming NFL/NBA games within a consistent pregame interval (e.g., 24-48 hours before kickoff). Save event ID, matchup, league, kickoff, LP generated-at, engine version, cutoff timestamp, and evidence IDs.
2. **Capture ESPN presentation** at the same cutoff. Archive article headline, canonical URL, credited writer/wire, published and modified timestamps, exact capture time, and short semantic annotations; do not ship or commit copyrighted full article text. Classify `ap_data_skrive_wire`, `espn_staff_preview`, `espn_scoreboard_auto`, or `no_preview`. A game page containing only odds/stats is not a written preview. Do not turn an API summary into fictional editorial copy.
3. **Prevent temporal leakage.** If the ESPN piece was published after LP's cutoff, mark `later_publication` and exclude it from same-cutoff rankings. Do not incorporate future injuries, same-day results, or newly learned starters into a retroactive LP comparison.
4. **Evaluate independently.** For the same game, score LP and the external preview for: primary hook choice, standout player inclusion, recent game/result context, head-to-head/rematch significance, opponent-specific stakes, readability/natural fan tone, and supported factual claims. Mark `not_applicable` for unavailable content. Provide a short reason for each comparison. Do not call the existing deterministic grader's headline-match heuristic an independent editorial judgment.
5. **Use blind editorial ratings** on a smaller human-reviewed subset, with generator/source identity hidden until scoring. Record whether the viewer prefers LP, external, or tie; preserve the reason.
6. **Diagnose missing facts vs prioritization.** For every lost hook, distinguish `missing_data`, `candidate_not_extracted`, `candidate_ranked_too_low`, `copy_template_failure`, and `article_later_than_cutoff`. The distinction determines the actual engineering change.
7. **Keep the production path free of ESPN requests and LLM calls.** An offline research collector may capture preview metadata with compliant throttling, caching, and provenance. Match by ESPN event ID plus team codes, not guessed names.
8. **Track trends by engine version** in the append-only quality ledger. Report hook recall and preference separately from factual audit pass rate and the six pastel rubric dimensions. Never optimize exclusively for ESPN imitation: human preference and zero unsupported claims remain the product standard.

## Initial five-game results

The five frozen November 4 NBA stories were replayed from their saved fact bundles with the current PR renderer. All five regenerated stories exactly match the frozen outputs, and the independent audit passed all 50 checks across the five stories. The sample is curated and unblinded; no human preference ratings were collected.

| Measure | Result |
| --- | ---: |
| Matched games | 5 NBA |
| Source type | 5 AP/Data Skrive/Sportradar syndications; 0 ESPN staff previews |
| Source publication time before LP generation | 5 of 5 |
| Renderer replay matched frozen story | 5 of 5 |
| Independent LP claim-audit checks | 50 of 50 passed |
| Main hook alignment | 2 same, 2 partial, 1 different |
| Wire stories with head-to-head/rematch context | 3; LP used it in 0 |
| Wire pages with injury lists | 5; injury facts were absent from all 5 LP input bundles |
| Blind human ratings | 0 |

The clearest gap is story selection and joining the facts. Cleveland at Oklahoma City had cutoff-safe evidence for Shai Gilgeous-Alexander's 43-point game and Oklahoma City's 117-112 win over Cleveland, but LP led with the teams' records and a generic scoring trend. Indiana at Memphis included Ty Jerome's 40 points but omitted that the performance came in a one-point loss; the overtime detail was not in the LP input. The Philadelphia-Detroit and Charlotte-Brooklyn bundles had the prior meeting scores, but the renderer did not select those facts for their top-four and losing-streak leads. The Lakers-Sacramento story included Luka Doncic's 42 and 45 points, but not the latest game's opponent and result. The linked stories' injury lists could not be compared as supported engine output because the story-engine bundles contained no injury facts.

All five linked pages identify Associated Press syndication, with Data Skrive and Sportradar attribution. Three are hosted by FOX Sports; the other two are on ABC local affiliate pages carrying ESPN branding/copyright. None is an ESPN staff-authored preview, so this is an ESPN-linked wire benchmark, not a direct comparison to ESPN editorial writing. The pages show publication times before the LP run, but were reviewed on Nov. 4; no immutable page captures or modified timestamps are available. Publication timing passes, while exact article-content-at-cutoff verification remains incomplete.

The per-game review is in [`results.md`](results.md); [`results.json`](results.json) preserves source metadata, replay checks, claim-audit results, and gap diagnoses in machine-readable form. No full article text is stored. These results are diagnostic only: the sample cannot establish overall preference, representativeness, or product quality.

## Cutoff-safe fact-join follow-up

The five fact-join cases have been implemented on PR #30's research branch and replayed against the same cutoff-filtered inputs. The generated stories, full fact bundles, selected evidence, per-claim audit results, and limitations are in [`fact-join-followup.md`](fact-join-followup.md) and [`fact-join-followup.json`](fact-join-followup.json).

The implementation joins NBA player logs to archived finals by exact ESPN event ID, adds supported prior-meeting results, and lets a 40-point latest performance against the upcoming opponent lead the story. All 60 independent audit checks passed, and all five outputs were eligible under the revised pastel grader. Injury availability remains missing because the development database has NFL injury reports only and no archived NBA injury snapshots. Current player injury fields were not used retroactively.

The sample remains curated and unblinded, with no human preference ratings. It is a diagnostic follow-up, not evidence of general quality or production readiness. Reference fixtures: `matched_sample.jsonl`.

**Gate:** The initial five-game seed comparison is complete. It is not full ESPN coverage, does not contain first-party ESPN staff previews or immutable historical article captures, and has no blind human ratings. Do not treat it as a general preference result.
