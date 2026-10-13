import React from 'react'
import type { FeaturedGame } from './types'
import { asOfText, kickoffText, signed, spreadText } from './format'
import { cardBase, QuietCard, SourceLine } from './CardShell'

const CHIP: Record<string, string> = { win: 'Pick won', loss: 'Pick lost', push: 'Push' }
const cols = 'grid grid-cols-[minmax(0,1fr)_4.4rem_3.2rem] gap-2'

function Row({ name, proj, fin, won }: { name: string; proj: number | null; fin: number | null; won: boolean }) {
  return (
    <div className={`${cols} items-baseline`}>
      <b className={`truncate ${won ? 'font-bold text-zinc-100' : 'font-medium text-zinc-300'}`}>{name}</b>
      {proj == null ? (
        <span className="text-right text-amber-400">n/a</span>
      ) : (
        <span className="text-right text-xl tabular-nums text-zinc-300">{proj.toFixed(1)}</span>
      )}
      <span className={`text-right text-xl tabular-nums ${won ? 'font-bold text-zinc-100' : 'text-zinc-500'}`}>
        {fin == null ? '' : fin}
      </span>
    </div>
  )
}

export default function GameCard({ game }: { game: FeaturedGame | null | undefined }) {
  if (!game) return <QuietCard label="Example game" kind="absent" />
  const home = game.home_name || game.home
  const away = game.away_name || game.away
  const when = kickoffText(game.kickoff_utc)
  const f = game.final
  const chip = game.pick_result ? CHIP[game.pick_result] : null
  return (
    <div className={`${cardBase} flex flex-col gap-2.5`} aria-label="Example game">
      <div className="text-xs text-zinc-400">
        {away} at {home}
        {when ? ` · ${when}` : ''}
      </div>
      <Row name={away} proj={game.proj_away} fin={f ? f.away : null} won={!!f && f.away > f.home} />
      <Row name={home} proj={game.proj_home} fin={f ? f.home : null} won={!!f && f.home > f.away} />
      <div className={`${cols} text-[10px] uppercase tracking-[.06em] text-zinc-500`}>
        <span />
        <span className="text-right">Projected</span>
        <span className="text-right">{f ? 'Final' : ''}</span>
      </div>
      <div className="grid grid-cols-2 gap-x-3.5 gap-y-2 border-t border-zinc-800 pt-2.5 text-sm">
        <div>
          <span className="block text-[11px] uppercase tracking-[.06em] text-zinc-500">Market line</span>
          {game.market_spread == null ? (
            <span className="text-amber-400">n/a</span>
          ) : (
            <span className="tabular-nums">{spreadText(game.home, game.away, game.market_spread)}</span>
          )}
        </div>
        <div>
          <span className="block text-[11px] uppercase tracking-[.06em] text-zinc-500">Our line</span>
          <span className="tabular-nums"><b>{spreadText(game.home, game.away, game.our_margin)}</b></span>
        </div>
      </div>
      {game.pick && (
        <div className="flex flex-wrap items-baseline gap-x-2.5 gap-y-1 border-t border-zinc-800 pt-2.5 text-sm">
          <span>
            <span className="block text-[11px] uppercase tracking-[.06em] text-zinc-500">Our pick</span>
            <b>{game.pick.team} {signed(game.pick.line)}</b>{' '}
            <span className="tabular-nums text-zinc-400">({game.pick.gap.toFixed(1)} points off the line)</span>
          </span>
          {chip && (
            <span className="rounded-full border border-emerald-400/45 px-[9px] py-px text-xs text-emerald-400">{chip}</span>
          )}
        </div>
      )}
      <SourceLine>
        {game.model_label}, locked projection {asOfText(game.source.as_of)}. Line as locked.
      </SourceLine>
    </div>
  )
}
