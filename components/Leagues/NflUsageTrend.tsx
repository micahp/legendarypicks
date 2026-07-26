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

interface UsageCol {
  key: string
  label: string
  /** Raw value, used both to render and to decide whether the band is alive. */
  value: (g: NflUsageGame) => number | null
  fmt: (g: NflUsageGame) => string
}

// Same phase-band treatment as the game log, for the same reason: a flat
// receiving-only list left an RB reading `3 snaps, 5%, 0 targets, 6.1 PPR` \u2014
// six of ten columns dead and the fantasy points arriving from nowhere. Bands
// no game in the window touched are dropped rather than shown as zeros.
// Box-score counting stats (rec/yds/TD, rush yds/TD) stay out: this table is
// opportunity, the game log is production, and that split is the whole axis
// the restructure is built on.
const USAGE_BANDS: { label: string; cols: UsageCol[] }[] = [
  { label: 'Snaps', cols: [
    { key: 'snaps', label: 'Snp', value: (g) => g.snaps, fmt: (g) => fmt(g.snaps, 0) },
    { key: 'snap_share', label: 'Snp%', value: (g) => g.snap_share, fmt: (g) => fmtPct(g.snap_share) },
  ] },
  { label: 'Receiving', cols: [
    { key: 'targets', label: 'Tgt', value: (g) => g.targets, fmt: (g) => fmt(g.targets, 0) },
    { key: 'target_share', label: 'Tgt%', value: (g) => g.target_share, fmt: (g) => fmtPct(g.target_share) },
    { key: 'adot', label: 'aDOT', value: (g) => g.adot, fmt: (g) => fmt(g.adot) },
    // air_yds_share is stored 0-100, unlike the 0-1 shares beside it, so it
    // formats itself rather than going through fmtPct. The column has always
    // been a percentage; it just never printed the sign.
    { key: 'air_yds_share', label: 'AY%', value: (g) => g.air_yds_share,
      fmt: (g) => (g.air_yds_share == null ? '\u2014' : g.air_yds_share.toFixed(1) + '%') },
    { key: 'wopr', label: 'WOPR', value: (g) => g.wopr, fmt: (g) => fmt(g.wopr) },
  ] },
  { label: 'Rushing', cols: [
    { key: 'carries', label: 'Car', value: (g) => g.carries, fmt: (g) => fmt(g.carries, 0) },
    { key: 'carry_share', label: 'Car%', value: (g) => g.carry_share, fmt: (g) => fmtPct(g.carry_share) },
  ] },
  { label: 'Fantasy', cols: [
    { key: 'fpts_ppr', label: 'PPR', value: (g) => g.fpts_ppr, fmt: (g) => fmt(g.fpts_ppr) },
  ] },
]

/** A column earns its place by having a non-zero value in the window. Pruning
 *  is per column, not per band: Elliott has a target or two, so the Receiving
 *  band survives, but he has no NGS coverage at all and aDOT/AY%/WOPR would be
 *  eight rows of dashes under a header that promises data. A band with nothing
 *  left disappears with its columns. */
function pruneBands(games: NflUsageGame[]) {
  const live = (c: UsageCol) => games.some((g) => (c.value(g) ?? 0) !== 0)
  return USAGE_BANDS
    .map((b) => ({ ...b, cols: b.cols.filter(live) }))
    .filter((b) => b.cols.length > 0)
}

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
  const bands = pruneBands(games)
  // The footer must not advertise a metric whose column was just pruned — a
  // WOPR sparkline over a table with no WOPR column contradicts itself.
  const liveCols = new Set(bands.flatMap((b) => b.cols.map((c) => c.key)))
  const trendRows = TREND_METRICS.filter((m) => liveCols.has(m.key))

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
      <div className="overflow-x-auto [scrollbar-width:none] [&::-webkit-scrollbar]:hidden">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-zinc-800/60 text-[10px] uppercase tracking-wider text-zinc-600">
              <th colSpan={2} />
              {bands.map((b) => (
                <th
                  key={b.label}
                  colSpan={b.cols.length}
                  className="py-2 px-3 text-center font-medium border-l border-zinc-800"
                >
                  {b.label}
                </th>
              ))}
            </tr>
            <tr className="border-b border-zinc-800 text-[11px] uppercase tracking-wider text-zinc-500">
              <th className="py-2 px-3 text-left font-medium">Wk</th>
              <th className="py-2 px-3 text-left font-medium">Opp</th>
              {bands.map((b) => b.cols.map((c, i) => (
                <th
                  key={b.label + c.key}
                  className={`py-2 px-3 text-right font-medium ${i === 0 ? 'border-l border-zinc-800' : ''}`}
                >
                  {c.label}
                </th>
              )))}
            </tr>
          </thead>
          <tbody>
            {games.map((game, i) => (
              <tr
                key={i}
                className="border-b border-zinc-800/50 hover:bg-zinc-800/30 transition-colors"
              >
                <td className="py-2 px-3 font-mono tabular-nums text-zinc-400">
                  {game.week != null ? game.week : '—'}
                </td>
                <td className="py-2 px-3 text-zinc-300">{game.opponent ?? '—'}</td>
                {bands.map((b) => b.cols.map((c, ci) => {
                  const v = c.value(game)
                  return (
                    <td
                      key={b.label + c.key}
                      className={`py-2 px-3 text-right font-mono tabular-nums ${
                        v ? 'text-zinc-300' : 'text-zinc-600'
                      } ${ci === 0 ? 'border-l border-zinc-800' : ''}`}
                    >
                      {c.fmt(game)}
                    </td>
                  )
                }))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* Trend summary */}
      {trendRows.length > 0 && (
      <div className="px-5 py-4 border-t border-zinc-800 space-y-1">
        {trendRows.map(({ key, label, format: getter }) => {
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
      )}
    </div>
  )
}
