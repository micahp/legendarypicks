# Cutoff-safe player result and rematch follow-up

- Run date: November 5, 2026
- Base PR head: `ab87c0af659205a21fb55a9b9b5d4b6b4f0eb289`
- Source: Legendary Picks development database opened read-only
- Generation: zero network calls and zero model calls

This follow-up addresses the missing joins identified in the five-game ESPN-linked AP/Data Skrive review. NBA player logs are joined to archived scoreboard finals by exact ESPN event ID. The collector accepts only completed regular-season final snapshots captured before the story cutoff, whose event start also precedes that cutoff. It does not fetch current data to fill historical gaps.

## Replayed outputs

| Matchup | Deterministic preview after the join | Fact now surfaced |
| --- | --- | --- |
| Cleveland at Oklahoma City | Shai Gilgeous-Alexander scored 43 in the Thunder's 117-112 win over the Cavaliers, and Oklahoma City hosts Cleveland again. | Same-opponent rematch and 43-point game lead the preview. |
| Indiana at Memphis | Indianapolis has dropped five straight at 2-6 entering its matchup with Memphis, which is 6-1. Indianapolis's Tyrese Haliburton is averaging 8.8 assists over his last five, while Ty Jerome scored 40 in the Grizzlies' 134-135 overtime loss to the Pelicans. | The 40-point game is tied to Memphis's loss and overtime result. Indiana's losing streak remains the lead. |
| Philadelphia at Detroit | Two of the NBA's top four teams meet in Detroit, where the 6-1 Pistons host the 7-1 76ers. Cade Cunningham is averaging 25.6 points and 6.8 assists over his last five for Detroit, while Tyrese Maxey scored 38 in the 76ers' 109-104 win over the Hornets on Oct. 31. Detroit already beat Philadelphia 106-93 on Oct. 25. | Maxey's recent standout performance has its game result, and the prior meeting follows the player context. |
| Charlotte at Brooklyn | Charlotte has dropped four straight at 3-5 entering its matchup with Brooklyn, which is 1-6. Brandon Miller scored 39 in the Hornets' 110-103 win over the Wizards on Oct. 26. Charlotte already beat Brooklyn 110-103 on Oct. 21. | Miller's 39-point game is dated and tied to the win; the previous meeting supplements the losing-streak lead. |
| Los Angeles Lakers at Sacramento | The 6-2 Lakers bring a two-game winning streak to Sacramento, where the Kings sit at 1-6. Darius Acuff Jr. scored 38 in the Kings' 105-136 loss to the Grizzlies on Oct. 31, while Luka Doncic scored 42 in the Lakers' 138-117 win over the Heat. | Both recent standout games are tied to their results, including Luka's 42-point Miami game. |

The generated prose and full cutoff-filtered input bundles are preserved in [`fact-join-followup.json`](fact-join-followup.json), including selected evidence, omitted facts, independent audit gates, and pastel rubric scores. All 60 audit checks passed, and the current rubric marked all five stories eligible with scores from 92 to 99. The new scorer recognizes the 43-point same-opponent rematch as the Cleveland at Oklahoma City lead, adds recent game results for six player performances, and adds the two previous-meeting results that had been omitted from Philadelphia at Detroit and Charlotte at Brooklyn. The pastel grader now requires both new result-claim gates and uses version `lp-story-quality-v1.1.0`.

## Injury data limitation

The development database contains 14,740 rows in `injury_reports`, all tagged as NFL and sourced from nflverse. It contains no archived NBA injury reports. The `players.injury_status` and `players.last_news_date` fields are mutable current player data, not timestamped NBA snapshots for the November 3 cutoff. The replay did not use those fields or make injury claims. Adding injury context requires a prospective, timestamped NBA injury snapshot source.

## Verification and limits

`python3 -m py_compile story_engine.py story_engine_audit.py story_rubric.py test_story_engine.py test_story_engine_runtime.py test_story_rubric.py` passed, and `pytest -q test_story_engine.py test_story_engine_runtime.py test_story_rubric.py` passed with 70 tests. The database was opened in read-only mode. No service, production path, or database was changed.

This is a five-game curated diagnostic replay against the same cases that motivated the changes. It is not a held-out evaluation, has no blind human ratings, and does not establish general preference or production readiness. The wire references remain AP/Data Skrive syndications, not ESPN staff previews. The production feature flag remains disabled by default.
