# PR #29 review evidence

## Iteration 2 · room and in-room data previews

The latest iteration replaces the CSS furniture with a cohesive 16-bit apartment scene and keeps the GM in street clothes. Room objects show data from the existing NFL APIs and open focused previews before offering the full research page. When a feed has no published data, the room says so instead of inventing a score or projection. Career and arcade objects remain visible as future destinations.

- [Desktop room · 1440px](iteration-2/hq-desktop.png)
- [Mobile room · 390px](iteration-2/hq-mobile.png)
- [Interaction recording · 4 seconds](iteration-2/interaction-flow.webm) shows the loaded room, a real prop line and recent game history, then the return to HQ.

### Iteration 2 verification

- Focused Jest: 2 suites and 5 tests passed (`LeagueLocker` and `NflPixelHQ`).
- TypeScript: `tsc --noEmit --pretty false --incremental false` completed with 0 diagnostics.
- Chromium checks at 390×844 and 1440×1000 found no horizontal overflow or hotspot overlap; the smallest mobile hotspot is 44px. Reduced-motion disables the idle animation.
- The in-room previews displayed the API-backed next matchup, published projection values, and a prop line with its source timestamp and six recent results. Existing research routes returned HTTP 200, and the browser reported no page errors.
- The backend props unit test could not run in this environment because its Python interpreter does not have FastAPI installed. The additive `captured_at` field is covered by that test assertion, but still needs execution in the project backend environment.
- PR #29 remains unmerged and undeployed.

The earlier screenshots and interaction recording below document the initial PR revision; they are retained as historical review evidence.

The initial review evidence below is from `feat/pixel-nfl-hq-design`, based on `dev`; nothing was merged or deployed. Its character transition included a helmet, which the iteration above removes.

The initial character sprite used the design posted in the PR comment as its reference and kept the jacket, shirt, chain, locs, and beard across its original outfit states.

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
