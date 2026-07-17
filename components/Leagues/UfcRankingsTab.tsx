import { WEIGHT_CLASS_LBS } from './presentation'
import type { UFCRanked, UFCRankings } from './types'

interface UfcRankingsTabProps {
  rankings: UFCRankings | null
  loading: boolean
  error: string | null
}

export default function UfcRankingsTab({ rankings, loading, error }: UfcRankingsTabProps) {
  return (
    <>
      {error && (
        <div className="bg-red-500/10 border border-red-500/20 rounded-lg px-4 py-3 text-red-400 text-sm">
          {error}
        </div>
      )}

      {loading ? (
        <div className="space-y-4 animate-pulse">
          <div className="h-6 bg-zinc-800 rounded w-48" />
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            {[...Array(4)].map((_, index) => (
              <div key={index} className="h-48 bg-zinc-800 rounded-xl" />
            ))}
          </div>
        </div>
      ) : rankings ? (
        <Rankings rankings={rankings} />
      ) : (
        <div className="text-center py-12 text-zinc-500 text-sm">
          No UFC rankings available.
        </div>
      )}
    </>
  )
}

function Rankings({ rankings }: { rankings: UFCRankings }) {
  return (
    <div className="space-y-8">
      <section>
        <div className="flex items-center gap-3 mb-4">
          <span className="text-[10px] text-emerald-500/60 bg-emerald-500/10 px-2 py-0.5 rounded font-bold uppercase tracking-widest">
            Pound-for-Pound
          </span>
          <span className="text-[10px] text-zinc-600 uppercase tracking-wider">
            The best across all weight classes
          </span>
        </div>
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
          <RankedList title="Men's" fighters={rankings.pound_for_pound.men} />
          <RankedList title="Women's" fighters={rankings.pound_for_pound.women} />
        </div>
      </section>

      <section>
        <div className="flex items-center gap-3 mb-4">
          <span className="text-[10px] text-zinc-500 bg-zinc-900 px-2 py-0.5 rounded font-bold uppercase tracking-widest border border-zinc-800">
            Divisions
          </span>
        </div>
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
          {rankings.divisions.map(division => (
            <DivisionCard key={division.division} division={division} />
          ))}
        </div>
      </section>
    </div>
  )
}

function RankedList({ title, fighters }: { title: string; fighters: UFCRanked[] }) {
  return (
    <div className="bg-zinc-900/80 border border-zinc-800/80 rounded-xl overflow-hidden">
      <div className="px-4 py-2.5 border-b border-zinc-800/60 flex items-center gap-2">
        <span className="text-[11px] font-semibold text-zinc-300 tracking-wider">{title}</span>
      </div>
      <ol className="divide-y divide-zinc-800/40">
        {fighters.map(fighter => (
          <li
            key={fighter.rank}
            className={`flex items-center gap-3 px-4 py-2 text-sm ${
              fighter.champion ? 'bg-emerald-500/5' : ''
            }`}
          >
            <span className={`w-5 text-right text-xs tabular-nums font-medium ${
              fighter.champion ? 'text-emerald-400' : 'text-zinc-600'
            }`}>
              {fighter.champion ? '♛' : fighter.rank}
            </span>
            <span className={fighter.champion ? 'text-emerald-300 font-semibold' : 'text-zinc-300'}>
              {fighter.fighter}
            </span>
          </li>
        ))}
      </ol>
    </div>
  )
}

function DivisionCard({ division }: { division: UFCRankings['divisions'][number] }) {
  const pounds = WEIGHT_CLASS_LBS[division.division]
  return (
    <div className="bg-zinc-900/80 border border-zinc-800/80 rounded-xl overflow-hidden group">
      <div className="px-4 pt-4 pb-1">
        <div className="flex items-baseline gap-2">
          <span className="text-3xl font-black text-zinc-200 tabular-nums tracking-tight">
            {pounds}
          </span>
          <span className="text-xs text-zinc-600 font-medium uppercase tracking-widest">LBS</span>
        </div>
        <h3 className="text-[11px] font-semibold text-zinc-500 uppercase tracking-wider mt-0.5">
          {division.division}
        </h3>
      </div>
      {division.champion && (
        <div className="mx-4 mt-2 mb-1 flex items-center gap-2 px-3 py-2 rounded-lg bg-emerald-500/5 border border-emerald-500/10">
          <span className="text-emerald-400 text-xs">◆</span>
          <span className="text-sm text-emerald-300 font-semibold">{division.champion}</span>
        </div>
      )}
      <ol className="px-4 pb-3 pt-1 space-y-0.5">
        {division.ranked.map(fighter => (
          <li
            key={fighter.rank}
            className="flex items-center gap-3 text-sm group-hover:text-zinc-300 transition-colors"
          >
            <span className="w-5 text-right text-[11px] tabular-nums text-zinc-600 font-medium">
              {fighter.rank}
            </span>
            <span className="text-zinc-400">{fighter.fighter}</span>
          </li>
        ))}
      </ol>
    </div>
  )
}
