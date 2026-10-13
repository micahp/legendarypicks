import React from 'react'
import type { FeaturedOdds } from './types'
import { asOfText, pct } from './format'
import { cardBase, QuietCard, SourceLine } from './CardShell'

export default function PlayoffOddsCard({ odds }: { odds: FeaturedOdds | null | undefined }) {
  if (!odds) return <QuietCard label="Example playoff odds" kind="absent" />
  return (
    <div className={`${cardBase} flex flex-col gap-2.5`} aria-label="Example playoff odds">
      <div className="text-xs text-zinc-400">Chance to make the playoffs, after week {odds.week}</div>
      <ul className="mt-1 flex flex-col gap-2.5">
        {odds.top.map((t) => (
          <li key={t.team} className="grid grid-cols-[minmax(0,1fr)_auto] items-center gap-x-2.5 gap-y-1 text-sm sm:grid-cols-[9.4rem_1fr_3.4rem]">
            <span className="truncate">{t.team_name}</span>
            <span className="order-last col-span-2 h-2.5 overflow-hidden rounded-full bg-zinc-800 sm:order-none sm:col-span-1">
              <i className="block h-full rounded-full bg-emerald-500" style={{ width: `${Math.min(100, Math.max(0, t.p_playoffs * 100))}%` }} />
            </span>
            <b className="text-right font-medium tabular-nums">{pct(t.p_playoffs, 1)}</b>
          </li>
        ))}
      </ul>
      <div className="text-xs text-zinc-400">
        Top five of {odds.teams_in_run} teams.{odds.sims ? ` ${odds.sims.toLocaleString('en-US')} simulated seasons.` : ''}
      </div>
      <SourceLine>Playoff odds simulation {asOfText(odds.source.as_of)}.</SourceLine>
    </div>
  )
}
