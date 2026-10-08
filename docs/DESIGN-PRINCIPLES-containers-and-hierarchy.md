# Design principles: containers, separators and hierarchy

Written 2026-10-08 from three inputs Micah brought together. Applies to every Legendary Picks surface
and to the mockups and pages we design around it. Sits beside `.claude/skills/honest-data-ui/SKILL.md`
(what a surface may show); this doc is about how a surface is put together.

## Sources

1. **ESPN Soccer Scores, desktop, 10-07** (Discord image cache, `~/.hermes/cache/images/img_ace5b6164f94.webp`).
   Micah's read: they do not use a card for every item. There is one card per group of items: each league on
   the day, the title and date section, "Latest Soccer Videos", "Soccer News". A league with one game that day
   still gets its own card. Inside a card, a thin line separates the items. Today's date sits outside the cards.
2. **Zander Whitehurst (@zander_supafast), "stop doing X" videos**: stop adding borders, stop adding
   containers (no cards in cards), stop centering text, stop making every button primary, stop multi-column
   mobile menus, stop "Are you sure?" modals, and build hierarchy from size, weight, colour and proximity.
3. **Our own games-list mockup, v6** (https://claude.ai/artifact/RapFXfAZUwbjjCW6TTiJq8): a phone column with no
   boxes at all; group labels ("Underway", "This afternoon", "Tonight"), whitespace and a hover tint do the
   separating. Reference set alongside it: Clutch Time (10-07 screenshots, same cache), which separates games
   with a thin line and labels groups ("Watching", "Following", "Now") with no cards.

## Where they disagree, and the rule that settles it

ESPN draws cards; Zander says remove containers; v6 and Clutch Time use none. They agree on the thing that
matters: **a container marks a group, never an item.** ESPN's card is a league, not a game; Zander's target is
the card around every item and the card inside a card; v6 and Clutch Time get the grouping from labels instead.

### The rules

1. **One container level, and only for a group.** A container (a panel or card) holds a set of things that
   belong together: a league on a day, the videos module, the news module, a game's box score. Never wrap a
   single item in its own card because it is an item. Never put a card inside a card.
2. **A group keeps its container even with one item.** ESPN's Liechtenstein v Gibraltar sits alone in its
   league card because the card is the league. Consistency of the group beats saving a box.
3. **Items inside a group are separated by a hairline or by space, not by boxes.** ESPN uses a 1 px rule
   between games; v6 uses space plus a hover tint. Pick one per surface and keep it.
4. **The container edge is a surface shift, not an outline.** Prefer a panel tint against the page
   (LP dark: `--lp-panel #18181b` on `--lp-bg #0f0f11`) over a stroked border. Borders are the noise Zander
   removes; the honest-data-ui skill already says no shadow doing a rule's work.
5. **Page context lives outside the containers.** The page title and the date being shown ("Wednesday,
   October 7, 2026") sit above the groups, left-aligned, not inside a card and not centred.
6. **The group title lives inside its container, at the top** (ESPN "Women's International Friendly",
   "USL League One"), left-aligned, in the label style, not as a separate floating header with its own rule.
7. **Left-align text; right-align numbers in a column.** Names, labels and copy share one left edge.
   Scores, prices and times share one right edge, tabular figures. No centred text blocks.
8. **Hierarchy from size, weight, colour, proximity.** The winner's row reads in full ink and the loser's
   dimmed (Clutch Time, our final cards); emphasis by weight or colour, never by adding a line or box.
   Related facts sit close; unrelated ones get space.
9. **One primary action per surface.** Everything else secondary or tertiary; rarely-used actions behind
   "More". Buttons say the action ("Watch on Fox One", "Delete folder", "Keep editing"), never "Yes"/"OK".
10. **Single column on phones.** Pills scroll on one line; menus are one column with group labels; no
    multi-column menus.
11. **Side modules are groups too.** On desktop a right rail of modules (ESPN's videos and news) is fine;
    each module is one container with hairline-separated items.

## Audit of the scoreboard today (`pages/scores.tsx`, `components/Scores/GameCard.tsx`, dev 10-08)

| What it does now | Rule | Change |
|---|---|---|
| Every game is its own bordered, rounded card in a two-column grid | 1, 4 | One panel per league (NBA, MLB, NHL...) with the games as rows inside it, separated by a hairline |
| The league name floats above the grid with a long rule beside it | 6 | League name at the top inside its panel, no separate rule |
| The date and its arrows are centred between the hero and the leagues | 5, 7 | The full date ("Thursday, October 8, 2026") left-aligned above the first league panel; arrows beside it or in the day strip |
| The live hero card has a green left bar | 4, honest-data-ui §5 | Remove the bar; the accent colour is reserved for absence. "LIVE" status and the score carry it |
| Desktop shows two columns of game cards | 11 | A main column of league panels; a right rail can hold modules (news, live audio) later |
| Card content is left-aligned with time/score right | 7 | Keep: this already follows the rule |
| The radio row sits at the right with the station name | 9 | Keep: one quiet control, not a primary button |

The game rows themselves (team names left, score or time right, Preseason and radio on a quiet bottom line)
already follow rules 7 to 9 and move into the league panels unchanged.

## For mockups and artifacts we publish

The same rules apply to pages we build outside the app (retro pages, desks, mockups): a container per group,
hairlines inside, context outside, left-aligned text, one primary action. The 10-05/06/07 retro pages use a
bordered card per agent reflection, which is a group (one agent's reflection) and passes; their tables are
already separated by hairlines.
