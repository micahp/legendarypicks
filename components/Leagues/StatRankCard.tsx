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
  season,
  games,
}: {
  statRanks: Record<string, StatRank> | null
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
        {/* h3, not h2. This card is nested inside the player overlay, whose
            own title — the player's name — is the h2. Two h2s in one dialog is
            wrong for a screen reader and it is what broke REG-render: the gate
            reads the dialog's heading to prove the overlay opened on the row it
            clicked, and a second h2 made that locator ambiguous. The sibling
            section directly below this one already uses h3. */}
        {/* One line, title case. This was two shouted lines — LEAGUE RANKINGS
            over 2025 REGULAR SEASON · N=16 GAMES — above a grid of ranks that
            says what it is without being told twice. The sample size is not
            thrown away, it is on the hover: it qualifies the ranks rather than
            competing with them for the band. */}
        <h3
          className="text-[11px] font-medium tracking-wide"
          title={games != null ? `n=${games} games` : undefined}
        >
          {season != null ? `${season} Regular Season` : 'Regular Season'}
        </h3>
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
