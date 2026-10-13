import React from 'react'
import type { Featured, Load } from './types'
import { SectionHeading } from './QuestionsSection'

// 3,909 games, 2010 to 2025 and "15 of 16 seasons" are the fixed backtest in
// docs/RESULTS-market-baseline-2010-2025-2026-10-11.md. The season record is read live.
export default function TrustSection({ featured }: { featured: Load<Featured> }) {
  const rec = featured.status === 'ready' ? featured.data.record : null
  return (
    <section aria-labelledby="h-trust">
      <SectionHeading id="h-trust">Why you can check our numbers</SectionHeading>
      <div className="grid grid-cols-1 gap-[22px] md:grid-cols-3 md:gap-7">
        <div>
          <h3 className="mb-1.5 text-[17px] font-bold">Locked, then never changed</h3>
          <p className="text-sm text-zinc-400">A projection is written once, 90 minutes before kickoff, against the line it was made with. A new injury makes a new forecast. The locked one is the one we grade.</p>
        </div>
        <div>
          <h3 className="mb-1.5 text-[17px] font-bold">Graded after every game</h3>
          <p className="text-sm text-zinc-400">Every line and every forecast is scored when the game ends, wins and losses alike, with its sample size beside it.</p>
        </div>
        <div>
          <h3 className="mb-1.5 text-[17px] font-bold">We show where we trail</h3>
          <p className="text-sm text-zinc-400">
            Over 3,909 NFL games from 2010 to 2025, our game model scored worse than the closing line, and lost to it in 15 of 16 seasons.
            {rec ? ` This season it is ${rec.win}-${rec.loss}-${rec.push} against the line after ${rec.games} graded games.` : ''}
            {rec && rec.games < 50 ? ` ${rec.games} games cannot rank a model.` : ''}
          </p>
        </div>
      </div>
    </section>
  )
}
