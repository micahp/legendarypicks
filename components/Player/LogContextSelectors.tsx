import { leagueLabel, seasonLabel } from '../Leagues/presentation'
import type { PlayerLogContext } from './types'

export default function LogContextSelectors({
  contexts,
  league,
  season,
  onChange,
}: {
  contexts: PlayerLogContext[]
  league: string
  season: number | null
  onChange: (league: string, season: number) => void
}) {
  if (!contexts.length || season == null) return null

  const leagues = Array.from(new Set(contexts.map(context => context.league)))
  const seasons = contexts
    .filter(context => context.league === league)
    .map(context => context.season)
    .sort((a, b) => b - a)

  return (
    <fieldset className="flex flex-wrap gap-3" aria-label="Game log filters">
      <label className="flex flex-col gap-1 text-[11px] font-semibold uppercase tracking-wider text-zinc-500">
        League
        <select
          aria-label="League"
          value={league}
          disabled={leagues.length === 1}
          onChange={event => {
            const nextLeague = event.target.value
            const nextSeason = Math.max(
              ...contexts
                .filter(context => context.league === nextLeague)
                .map(context => context.season),
            )
            onChange(nextLeague, nextSeason)
          }}
          className="rounded-md border border-zinc-700 bg-zinc-900 px-3 py-2 text-sm font-medium normal-case tracking-normal text-zinc-200 disabled:text-zinc-500"
        >
          {leagues.map(option => (
            <option key={option} value={option}>{leagueLabel(option)}</option>
          ))}
        </select>
      </label>
      <label className="flex flex-col gap-1 text-[11px] font-semibold uppercase tracking-wider text-zinc-500">
        Year
        <select
          aria-label="Year"
          value={season}
          disabled={seasons.length === 1}
          onChange={event => onChange(league, Number(event.target.value))}
          className="rounded-md border border-zinc-700 bg-zinc-900 px-3 py-2 text-sm font-medium normal-case tracking-normal text-zinc-200 disabled:text-zinc-500"
        >
          {seasons.map(option => (
            <option key={option} value={option}>{seasonLabel(league, option)}</option>
          ))}
        </select>
      </label>
    </fieldset>
  )
}
