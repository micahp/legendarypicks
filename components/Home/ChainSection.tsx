import React from 'react'
import type { Featured, Load } from './types'
import { SectionHeading } from './QuestionsSection'
import { asOfText, kickoffText, marketLabel, pct, shortDate, spreadText, weekdayText } from './format'

function Link4({ n, title, children, source }: { n: string; title: string; children: React.ReactNode; source?: string | null }) {
  return (
    <article className="relative flex min-w-0 flex-col gap-1.5 rounded-xl border border-zinc-800 bg-zinc-900 px-5 py-[18px]" title={source || undefined}>
      <span className="text-[11px] uppercase tracking-[.08em] text-emerald-400">{n}</span>
      <h3 className="text-lg font-bold">{title}</h3>
      <div className="mt-1.5 flex flex-col gap-1 border-t border-zinc-800 pt-2.5 text-sm">{children}</div>
    </article>
  )
}

const city = (name: string) => (name.includes(' ') ? name.split(' ').slice(0, -1).join(' ') : name)

const Nums = ({ children }: { children: React.ReactNode }) => (
  <div className="mt-0.5 flex flex-wrap gap-x-4 gap-y-1 tabular-nums text-zinc-300">{children}</div>
)
const Big = ({ children }: { children: React.ReactNode }) => <b className="text-xl text-zinc-100">{children}</b>
const Small = ({ children }: { children: React.ReactNode }) => (
  <small className="mt-1 text-xs leading-[1.45] text-zinc-400">{children}</small>
)

function Skeleton() {
  return <div className="min-h-[13rem] rounded-xl border border-zinc-800 bg-zinc-900" data-state="loading"><div className="m-5 h-4 w-1/3 rounded bg-zinc-800" /></div>
}

export default function ChainSection({ featured }: { featured: Load<Featured> }) {
  if (featured.status === 'error') return null
  const heading = <SectionHeading id="h-chain">From the player to the playoffs</SectionHeading>
  if (featured.status === 'loading') {
    return (
      <section aria-labelledby="h-chain">
        {heading}
        <div className="grid grid-cols-1 gap-3.5 md:grid-cols-4">
          {[0, 1, 2, 3].map((i) => <Skeleton key={i} />)}
        </div>
      </section>
    )
  }
  const { player, game, market, season } = featured.data.chain
  const cards: React.ReactNode[] = []

  if (player) {
    const m = player.matchup
    const day = weekdayText(m?.start_time ?? null)
    cards.push(
      <Link4 key="player" n="The player" title="What he is likely to do" source={`Player game logs, ${asOfText(player.source.as_of) ?? ''}`}>
        <b>{player.player}</b>
        {m && <span className="text-zinc-400">{m.away} at {m.home}{day ? `, ${day}` : ''}</span>}
        <Nums><span><Big>{player.projection}</Big> projected {marketLabel(player.market)}</span><span><Big>{player.line}</Big> line</span></Nums>
        <Small>
          Our projection is a recency-weighted average of his last {player.games} games, set against today&apos;s line.
        </Small>
      </Link4>,
    )
  }
  if (game) {
    const home = game.home_name || game.home
    const away = game.away_name || game.away
    const lockDay = shortDate(game.source.as_of ?? null)
    cards.push(
      <Link4 key="game" n="The game" title="What the score will be" source={`${game.model_label}, ${asOfText(game.source.as_of) ?? ''}`}>
        {game.proj_home != null && game.proj_away != null
          ? <b>{city(away)} {game.proj_away.toFixed(1)}, {city(home)} {game.proj_home.toFixed(1)}</b>
          : <b>{away} at {home}</b>}
        <span className="text-zinc-400">{lockDay ? `Locked ${lockDay}, before kickoff` : 'Locked before kickoff'}</span>
        <Nums>
          <span><Big>{spreadText(game.home, game.away, game.our_margin)}</Big> our line</span>
          {game.our_total != null && <span><Big>{game.our_total.toFixed(1)}</Big> total</span>}
        </Nums>
        <Small>
          Built from team offense and defense rated against the schedule each team has played.
          {game.final ? ` The game ended ${Math.max(game.final.home, game.final.away)} to ${Math.min(game.final.home, game.final.away)}.` : ''}
        </Small>
      </Link4>,
    )
  }
  if (market && market.model_p_home_win != null) {
    cards.push(
      <Link4 key="market" n="The market" title="A fair price for every line" source={`${asOfText(market.source.as_of) ?? ''}`}>
        <b>{market.home_name || market.home} to win</b>
        <span className="text-zinc-400">model against the market</span>
        <Nums>
          <span><Big>{pct(market.model_p_home_win)}</Big> model</span>
          <span><Big>{pct(market.market_p_home_win)}</Big> market</span>
        </Nums>
        <Small>The spread, the total and each prop get the same treatment: our probability beside the price, and the gap between them.</Small>
      </Link4>,
    )
  }
  if (season) {
    cards.push(
      <Link4 key="season" n="The season" title="Where it ends up" source={`Playoff odds simulation, ${asOfText(season.source.as_of) ?? ''}`}>
        <b>{season.top.team_name} {pct(season.top.p_playoffs, 1)}</b>
        <span className="text-zinc-400">to make the playoffs</span>
        {season.sims != null && <Nums><span><Big>{season.sims.toLocaleString('en-US')}</Big> simulated seasons</span></Nums>}
        <Small>
          {season.sims != null ? `The remaining schedule played out ${season.sims.toLocaleString('en-US')} times from the games already played.` : 'The remaining schedule played out many times from the games already played.'}{' '}
          {season.next.map((t) => `${city(t.team_name)} ${pct(t.p_playoffs, 1)}`).join(', ')}.
        </Small>
      </Link4>,
    )
  }
  if (cards.length === 0) return null
  return (
    <section aria-labelledby="h-chain">
      {heading}
      <div className="grid grid-cols-1 gap-3.5 md:grid-cols-4">{cards}</div>
    </section>
  )
}
