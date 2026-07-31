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
}: {
  statRanks: Record<string, StatRank> | null
  title?: string
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
      cmp_g: 'Cmp/G',
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
    <section>
      <h2 className="text-xs font-semibold uppercase tracking-wider text-zinc-500 mb-2">
        {title}
      </h2>
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
        {Object.entries(statRanks).map(([key, data]) => (
          <div
            key={key}
            className="rounded-lg border border-zinc-800 bg-zinc-900 px-3 py-2.5"
          >
            <div className="text-[10px] uppercase tracking-wide text-zinc-500">
              {formatLabel(key)}
            </div>
            <div className="mt-0.5 text-lg font-mono font-bold tabular-nums text-zinc-100">
              {formatValue(data.value, key)}
            </div>
            {data.rank != null && (
              <div className="text-[10px] tabular-nums text-zinc-500">
                {rankOrdinal(data.rank)}
              </div>
            )}
          </div>
        ))}
      </div>
    </section>
  )
}
