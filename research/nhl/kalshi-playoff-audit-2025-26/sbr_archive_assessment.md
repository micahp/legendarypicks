# Sportsbook Reviews Online NHL archive: source check

Checked 2026-10-14. The [archive index](https://www.sportsbookreviewsonline.com/scoresoddsarchives/nhl/nhloddsarchives.htm) links 16 season pages from 2007–08 through 2022–23. The season pages expose HTML tables (not spreadsheet downloads on the pages inspected) with two team rows per game. Fields include date, rotation number, venue side, team, period scores, final score, opening and closing moneylines, and totals; puck-line columns appear in newer seasons, while older page schemas vary.

## Coverage sampled from page tables

| Season page | Games represented | Coverage observation |
| --- | ---: | --- |
| 2007–08 through 2021–22 | 806–1,401 per season, depending on lockout/shortened seasons | Tables extend through late-season dates; 2021–22 has 1,401 games through June 26, including postseason games. |
| 2022–23 | 342 | Page ends November 27, 2022; this is partial season coverage. |
| 2023–24 onward | No odds tables found | Direct URL-pattern checks for 2023–24, 2024–25, 2025–26, and 2026–27 returned generic site pages without an NHL season table. |

The archive is a substantially broader historical market-data candidate than the 80 Kalshi playoff events. The year-slug URL pattern works for published seasons, but a successful HTTP response alone does not establish that a season exists: newer slugs currently return a generic page, not odds data. The published tables could support a later broad market benchmark after row parsing, official-game matching, line-field auditing, and completeness checks. This check did not download or ingest the full tables, establish licensing for commercial use, or validate odds settlement conventions. It is market data only; it does not address historical goalie confirmations, injuries, or other pregame lineup knowledge.

Inspected sample pages: [2021–22](https://www.sportsbookreviewsonline.com/scoresoddsarchives/nhl-odds-2021-22), [2022–23](https://www.sportsbookreviewsonline.com/scoresoddsarchives/nhl-odds-2022-23), and the linked [2007–08](https://www.sportsbookreviewsonline.com/scoresoddsarchives/nhl-odds-2007-08) page.
