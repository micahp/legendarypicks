function rankOrdinal(n: number): string {
  const s = ['th', 'st', 'nd', 'rd']
  const v = n % 100
  return n + (s[(v - 20) % 10] || s[v] || s[0])
}

interface StatRank {
  value: number | null
  rank: number | null
  label: string
}

export default function StatRankCard({
  statRanks,
  title = 'Regular Season Stats',
  season,
  games,
}: {
  statRanks: Record<string, StatRank> | null
  title?: string
  season?: number | null
  games?: number | null
}) {
  if (!statRanks || !Object.keys(statRanks).length) return null

  const formatValue = (v: number | null, _key: string): string => {
    if (v == null) return '\u2014'
    // If close to an integer, show the integer; otherwise 1 decimal
    if (Math.abs(v - Math.round(v)) < 0.01) return String(Math.round(v))
    return v.toFixed(1)
  }

  const formatLabel = (key: string): string => {
    const keyMap: Record<string, string> = {
      pass_yds_g: 'Pass Yds/G',
      pass_td: 'Pass TD',
      interceptions: 'INT',
      cmp_g: 'Comp/G',
      rush_yds_g: 'Rush Yds/G',
      carries_g: 'Car/G',
      rec_yds_g: 'Rec Yds/G',
      targets: 'Tgt',
      receptions: 'Rec',
      fantasy_ppr_g: 'PPR/G',
    }
    return keyMap[key] || key
  }

  return (
    <section className="overflow-hidden rounded-xl border border-zinc-700 bg-zinc-900">
      <div className="bg-orange-600 px-3 py-2 text-center text-white">
        <h2 className="text-[11px] font-bold uppercase tracking-[0.12em]">
          {title}
        </h2>
        {season != null && (
          <p className="mt-0.5 text-[9px] font-medium uppercase tracking-wide text-orange-100">
            {season} regular season{games != null ? ` · n=${games} games` : ''}
          </p>
        )}
      </div>
      <div className="grid grid-cols-4 divide-x divide-zinc-800">
        {Object.entries(statRanks).map(([key, data]) => (
          <div
            key={key}
            className="min-w-0 px-2 py-3 text-center sm:px-3"
          >
            <div className="truncate text-[9px] font-medium uppercase tracking-wide text-zinc-500 sm:text-[10px]">
              {formatLabel(key)}
            </div>
            <div className="mt-1 font-mono text-lg font-bold tabular-nums text-zinc-100 sm:text-xl">
              {formatValue(data.value, key)}
            </div>
            {data.rank != null && (
              <div className="mt-0.5 text-[10px] tabular-nums text-zinc-500">
                {rankOrdinal(data.rank)}
              </div>
            )}
          </div>
        ))}
      </div>
    </section>
  )
}
