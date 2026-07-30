
export default function StatRankCard(
  props: { statRanks: Record<string, { value: number | null; rank: number | null; label: string }> | null; league: string }
): JSX.Element {
  const stats = props.statRanks
  if (!props.statRanks || !Object.keys(stats).length) {
    return null
  }

  const formatValue = (v: number | null, key: string): string => {
    if (v == null) return '—'
    if (key === 'pass_yds_g' || key === 'rush_yds_g' || key === 'rec_yds_g') return v.toFixed(1)
    if (key === 'ppr_per_game_played' || key === 'fantasy_ppr_g') return v.toFixed(1)
    if (key === 'targets' || key === 'receptions') return String(v)
    if (key === 'pass_td' || key === 'pass_td') return String(v)
    return String(v)
  }

  const formatLabel = (key: string): string => {
    // Map DB stat keys to ESPN-style abbreviations
    const keyMap: Record<string, string> = {
      'pass_yds_g': 'Pass/Y',
      'pass_td': 'Pass TD',
      'interceptions': 'INT',
      'cmp_g': 'Cmp/G',
      'rush_yds_g': 'Rush/Y',
      'carries_g': 'Car/G',
      'rec_yds_g': 'Rec/Y',
      'targets': 'Tgt',
      'receptions': 'Rec',
      'fantasy_ppr_g': 'PPR/G',
    }
    return keyMap[key] || key
  }

  return (
    <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
      {Object.entries(stats).map(([key, data]) => (
        <div key={key} className="bg-zinc-900 border border-zinc-800 rounded-xl px-4 py-3">
          <div className="text-xs uppercase tracking-wide text-zinc-500 mb-1">
            {formatLabel(key)}
          </div>
          <div className="flex items-end gap-2">
            <span className="text-xl font-mono font-bold text-zinc-100 tabular-nums">
              {formatValue(data.value, key)}
            </span>
            {data.rank != null && (
              <span className="text-xs text-zinc-500 font-mono tabular-nums pb-1">
                #{data.rank}
              </span>
            )}
          </div>
        </div>
      ))}
    </div>
  )
}
