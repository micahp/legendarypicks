# PR #29 review evidence

This evidence is from `feat/pixel-nfl-hq-design`. The feature branch was rebased on the latest `dev`; nothing was merged or deployed.

The character sprite uses the design posted in the PR comment as its reference. It keeps the jacket, shirt, chain, locs, and beard across the unhelmeted and fictional, unbranded helmet states.

## Before and after

Side-by-side comparisons are available at all three viewport sizes:

- [Homepage · 375px](home-mobile-before-after.png), [NFL HQ · 375px](hq-mobile-before-after.png)
- [Homepage · tablet](home-tablet-before-after.png), [NFL HQ · tablet](hq-tablet-before-after.png)
- [Homepage · desktop](home-desktop-before-after.png), [NFL HQ · desktop](hq-desktop-before-after.png)

Individual captures are in [before](before/) and [after](after/). The after folder also includes the equipped mobile state.

[Interaction recording · 11 seconds](interaction-flow.webm) shows selecting NFL, the helmet transition, entering HQ, and opening NFL Scores from the television.

## Verification

- `next build` passed in an isolated worktree. The project config skips type validation during build, so TypeScript was checked separately.
- `tsc --noEmit --pretty false --incremental false` on the feature branch completed with **0 diagnostics**.
- The same typecheck on a clean `origin/dev` worktree before Next generated its ignored `next-env.d.ts` produced these diagnostics:

  ```text
  components/Leagues/UfcOptimizerTab.tsx(504,14): error TS2322: Type '{ children: string; jsx: true; }' is not assignable to type 'DetailedHTMLProps<StyleHTMLAttributes<HTMLStyleElement>, HTMLStyleElement>'.
    Property 'jsx' does not exist on type 'DetailedHTMLProps<StyleHTMLAttributes<HTMLStyleElement>, HTMLStyleElement>'.
  components/Links.tsx(1,20): error TS2307: Cannot find module '../styles/Home.module.css' or its corresponding type declarations.
  ```

  Copying the same generated `next-env.d.ts` into that baseline produced 0 diagnostics too. The two clean-checkout messages are caused by the missing generated Next type references; they are present in neither the feature branch nor the baseline once both use the same generated file.
- Jest: 3 suites, 6 tests passed (`LeagueLocker`, `NflPixelHQ`, and existing homepage tests).
- Chromium checks at 375×812, 768×1024, and 1440×1000 found no horizontal overflow, overlapping hotspots, or targets below 44px. Reduced motion removes the transition. The room panels and keyboard menu opened correctly; browser console and page errors were 0.
- Existing routes `/props?league=nfl`, `/predict?sport=football&league=nfl`, `/scores?league=nfl`, `/leagues/nfl?tab=model`, and `/nfl/projections` each returned HTTP 200 with their expected page content.

The trophy shelf and arcade console report that career tracking and mini-games are unavailable. The room contains no invented scores, player data, rewards, or team marks. Audio is off and never starts automatically.
