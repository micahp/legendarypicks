import { useNflUsage } from './hooks/useNflUsage'
import type { NflUsageGame, NflUsageTrend } from './types'

function fmt(v: number | null | undefined, decimals = 1): string {
  if (v == null) return '\u2014'
  return v.toFixed(decimals)
}

function fmtPct(v: number | null | undefined): string {
  if (v == null) return '\u2014'
  return (v * 100).toFixed(1) + '%'
}

function trendIcon(dir: 'up' | 'down' | 'flat' | null): string {
  if (dir === 'up') return '\u25B2'
  if (dir === 'down') return '\u25BC'
  if (dir === 'flat') return '\u25C6'
  return '\u2014'
}

function trendColor(dir: 'up' | 'down' | 'flat' | null): string {
  if (dir === 'up') return 'text-emerald-400'
  if (dir === 'down') return 'text-red-400'
  return 'text-zinc-500'
}

/** CSS sparkline bar: relative height within a visible range. */
function sparkBar(value: number | null, rangeMax: number, color: string): string {
  if (value == null || rangeMax <= 0) return '0%'
  const pct = Math.min((value / rangeMax) * 100, 100)
  return pct.toFixed(0) + '%'
}

const TREND_METRICS: { key: keyof NflUsageTrend; label: string; format: (g: NflUsageGame) => number | null }[] = [
  { key: 'snap_share', label: 'Snap%', format: (g) => g.snap_share },
  { key: 'target_share', label: 'Tgt%', format: (g) => g.target_share },
  { key: 'wopr', label: 'WOPR', format: (g) => g.wopr },
]

const COLUMNS = [
  { label: 'Week', key: 'week', align: 'left', fmt: (g: NflUsageGame) => g.week != null ? String(g.week) : '\u2014' },
  { label: 'Opp', key: 'opponent', align: 'left', fmt: (g: NflUsageGame) => g.opponent ?? '\u2014' },
  { label: 'Snaps', key: 'snaps', align: 'right', fmt: (g: NflUsageGame) => fmt(g.snaps, 0) },
  { label: 'Snap%', key: 'snap_share', align: 'right', fmt: (g: NflUsageGame) => fmtPct(g.snap_share) },
  { label: 'Tgt', key: 'targets', align: 'right', fmt: (g: NflUsageGame) => fmt(g.targets, 0) },
  { label: 'Tgt%', key: 'target_share', align: 'right', fmt: (g: NflUsageGame) => fmtPct(g.target_share) },
  { label: 'aDOT', key: 'adot', align: 'right', fmt: (g: NflUsageGame) => fmt(g.adot) },
  { label: 'AY%', key: 'air_yds_share', align: 'right', fmt: (g: NflUsageGame) => fmt(g.air_yds_share, 1) },
  { label: 'WOPR', key: 'wopr', align: 'right', fmt: (g: NflUsageGame) => fmt(g.wopr) },
  { label: 'PPR', key: 'fpts_ppr', align: 'right', fmt: (g: NflUsageGame) => fmt(g.fpts_ppr) },
]

interface Props {
  playerId: number
  season?: number
  /** The component was built standalone, so it renders its own identity line.
   *  Mounted under a page that already names the player, that is a duplicate —
   *  pass false there. Kept opt-out rather than removed so the component still
   *  stands on its own elsewhere. */
  showHeader?: boolean
}

export default function NflUsageTrend({ playerId, season, showHeader = true }: Props) {
  const { data, loading, error } = useNflUsage(playerId, season)

  // ── loading ────────────────────────────────────────────────────────
  if (loading) {
    return (
      <div className="animate-pulse space-y-3 rounded-xl border border-zinc-800 bg-zinc-900 p-5">
        <div className="h-5 w-48 rounded bg-zinc-800" />
        <div className="h-4 w-64 rounded bg-zinc-800" />
        <div className="space-y-2">
          {[...Array(4)].map((_, i) => (
            <div key={i} className="h-8 rounded bg-zinc-800" />
          ))}
        </div>
      </div>
    )
  }

  // ── error ──────────────────────────────────────────────────────────
  if (error) {
    return (
      <div className="rounded-xl border border-zinc-800 bg-zinc-900 p-5 text-zinc-500 text-sm">
        {error}
      </div>
    )
  }

  // ── empty ──────────────────────────────────────────────────────────
  if (!data || data.games.length === 0) {
    return (
      <div className="rounded-xl border border-zinc-800 bg-zinc-900 p-5 text-zinc-500 text-sm">
        No usage data for this season
      </div>
    )
  }

  const { games, averages, trend, name, position, team, season: resolvedSeason } = data

  return (
    <div className="rounded-xl border border-zinc-800 bg-zinc-900">
      {/* Header */}
      {showHeader && (
        <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1 px-5 pt-5 pb-3">
          <span className="text-zinc-100 font-semibold text-base">{name}</span>
          <span className="text-zinc-500 text-sm">{position}</span>
          <span className="text-zinc-500 text-sm">{team}</span>
          <span className="text-zinc-600 text-xs">{resolvedSeason}</span>
        </div>
      )}

      {/* Table */}
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-zinc-800 text-xs uppercase text-zinc-500">
              {COLUMNS.map((col) => (
                <th
                  key={col.key}
                  className={`py-2 px-3 font-medium ${
                    col.align === 'right' ? 'text-right' : 'text-left'
                  }`}
                >
                  {col.label}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {games.map((game, i) => (
              <tr
                key={i}
                className="border-b border-zinc-800/50 hover:bg-zinc-800/30 transition-colors"
              >
                {COLUMNS.map((col) => (
                  <td
                    key={col.key}
                    className={`py-2 px-3 ${
                      col.align === 'right'
                        ? 'text-right font-mono tabular-nums text-zinc-300'
                        : 'text-zinc-400'
                    }`}
                  >
                    {col.fmt(game)}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* Trend summary */}
      <div className="px-5 py-4 border-t border-zinc-800 space-y-1">
        {TREND_METRICS.map(({ key, label, format: getter }) => {
          const metrics = games.map(getter)
          const avg = averages[key]
          const dir = trend[key]
          // games arrive newest-first (matching the table), but a sparkline has to
          // read left-to-right in time or it contradicts the trend arrow beside it.
          const spark = [...metrics].reverse()
          const max = Math.max(...metrics.filter((v): v is number => v != null), 0.01)
          return (
            <div key={key} className="flex items-center gap-3 text-xs">
              <span className="text-zinc-500 w-12 text-right tabular-nums">{label}</span>
              {/* Mini sparkline */}
              <div className="flex items-end gap-px h-4 flex-1 max-w-[120px]">
                {spark.map((v, i) => (
                  <div
                    key={i}
                    className="flex-1 bg-emerald-400/30"
                    style={{ height: sparkBar(v, max, 'emerald') }}
                  />
                ))}
              </div>
              <span className="text-zinc-400 tabular-nums">
                {avg != null ? (key === 'wopr' ? avg.toFixed(3) : fmtPct(avg)) : '\u2014'}
              </span>
              <span className={`${trendColor(dir)} text-[10px]`}>
                {trendIcon(dir)}
              </span>
            </div>
          )
        })}
      </div>
    </div>
  )
}
