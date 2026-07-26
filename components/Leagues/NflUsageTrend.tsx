import { useNflUsage } from './hooks/useNflUsage'
import type { NflUsageGame } from './types'

const DASH = '—'

// ── formatters ───────────────────────────────────────────────────────
const dec = (d: number) => (v: number | null) => (v == null ? DASH : v.toFixed(d))
/** 0-1 fraction → percent. */
const pct = (v: number | null) => (v == null ? DASH : (v * 100).toFixed(0) + '%')
/** already stored 0-100 (air_yds_share, cpoe, st_pct). */
const pct100 = (v: number | null) => (v == null ? DASH : v.toFixed(1) + '%')
const signed = (d: number) => (v: number | null) =>
  v == null ? DASH : (v > 0 ? '+' : '') + v.toFixed(d)

// ── role ─────────────────────────────────────────────────────────────
// Position decides which columns can ever hold data, and that is a rule about
// the source, not an accident of one player's window: Next Gen receiving is a
// WR/TE feed with zero RB and zero QB rows, and the play-by-play passing block
// only ever fills for a passer. Empty-column pruning still runs underneath, but
// role is what puts a back's rushing before his receiving instead of after it.
type Role = 'qb' | 'rb' | 'wrte' | 'other'

function roleOf(position: string | null | undefined): Role {
  const p = (position || '').toUpperCase()
  if (p === 'QB') return 'qb'
  if (p === 'RB' || p === 'FB') return 'rb'
  if (p === 'WR' || p === 'TE') return 'wrte'
  return 'other'
}

interface Col {
  key: string
  label: string
  /** Raw value — drives both the cell and the is-this-column-dead check. */
  value: (g: NflUsageGame) => number | null
  fmt: (g: NflUsageGame) => string
  /** 0-1 fill for the magnitude bar under share columns. */
  bar?: (g: NflUsageGame) => number | null
}

const c = (
  key: string, label: string,
  value: (g: NflUsageGame) => number | null,
  fmt: (v: number | null) => string,
  bar?: (g: NflUsageGame) => number | null,
): Col => ({ key, label, value, fmt: (g) => fmt(value(g)), bar })

const BANDS: Record<string, Col[]> = {
  Snaps: [
    c('snaps', 'Snp', (g) => g.snaps, dec(0)),
    c('snap_share', 'Snp%', (g) => g.snap_share, pct, (g) => g.snap_share),
    c('st_pct', 'ST%', (g) => g.st_pct, pct100, (g) => (g.st_pct == null ? null : g.st_pct / 100)),
  ],
  Receiving: [
    c('targets', 'Tgt', (g) => g.targets, dec(0)),
    c('target_share', 'Tgt%', (g) => g.target_share, pct, (g) => g.target_share),
    c('adot', 'aDOT', (g) => g.adot, dec(1)),
    c('air_yds_share', 'AY%', (g) => g.air_yds_share, pct100,
      (g) => (g.air_yds_share == null ? null : g.air_yds_share / 100)),
    c('wopr', 'WOPR', (g) => g.wopr, dec(2)),
  ],
  'Next Gen': [
    c('separation', 'Sep', (g) => g.separation, dec(2)),
    c('cushion', 'Cush', (g) => g.cushion, dec(2)),
    c('yac_above_exp', 'YAC±', (g) => g.yac_above_exp, signed(2)),
  ],
  Rushing: [
    c('carries', 'Car', (g) => g.carries, dec(0)),
    c('carry_share', 'Car%', (g) => g.carry_share, pct, (g) => g.carry_share),
  ],
  Passing: [
    c('pass_att', 'Att', (g) => g.pass_att, dec(0)),
    c('cpoe', 'CPOE', (g) => g.cpoe, signed(1)),
    c('epa_per_db', 'EPA/db', (g) => g.epa_per_db, signed(2)),
  ],
  Fantasy: [
    c('fpts_ppr', 'PPR', (g) => g.fpts_ppr, dec(1)),
  ],
}

const BAND_ORDER: Record<Role, string[]> = {
  qb: ['Snaps', 'Passing', 'Rushing', 'Fantasy'],
  rb: ['Snaps', 'Rushing', 'Receiving', 'Fantasy'],
  wrte: ['Snaps', 'Receiving', 'Next Gen', 'Fantasy'],
  other: ['Snaps', 'Receiving', 'Next Gen', 'Rushing', 'Passing', 'Fantasy'],
}

/** A column earns its place by holding a non-zero value somewhere in the
 *  window; a band with nothing left disappears with its columns. Role sets the
 *  order, data decides what survives. */
function bandsFor(role: Role, games: NflUsageGame[]) {
  const live = (col: Col) => games.some((g) => (col.value(g) ?? 0) !== 0)
  return BAND_ORDER[role]
    .map((label) => ({ label, cols: BANDS[label].filter(live) }))
    .filter((b) => b.cols.length > 0)
}

// ── headline tiles ───────────────────────────────────────────────────
interface Tile {
  label: string
  get: (g: NflUsageGame) => number | null
  fmt: (v: number | null) => string
}

const TILES: Record<Role, Tile[]> = {
  qb: [
    { label: 'Snap%', get: (g) => g.snap_share, fmt: pct },
    { label: 'Att/g', get: (g) => g.pass_att, fmt: dec(0) },
    { label: 'CPOE', get: (g) => g.cpoe, fmt: signed(1) },
    { label: 'EPA/db', get: (g) => g.epa_per_db, fmt: signed(2) },
  ],
  rb: [
    { label: 'Snap%', get: (g) => g.snap_share, fmt: pct },
    { label: 'Car%', get: (g) => g.carry_share, fmt: pct },
    { label: 'Tgt%', get: (g) => g.target_share, fmt: pct },
    { label: 'PPR/g', get: (g) => g.fpts_ppr, fmt: dec(1) },
  ],
  wrte: [
    { label: 'Snap%', get: (g) => g.snap_share, fmt: pct },
    { label: 'Tgt%', get: (g) => g.target_share, fmt: pct },
    { label: 'WOPR', get: (g) => g.wopr, fmt: dec(2) },
    { label: 'Sep', get: (g) => g.separation, fmt: dec(2) },
  ],
  other: [
    { label: 'Snap%', get: (g) => g.snap_share, fmt: pct },
    { label: 'Tgt%', get: (g) => g.target_share, fmt: pct },
    { label: 'PPR/g', get: (g) => g.fpts_ppr, fmt: dec(1) },
  ],
}

const mean = (vals: (number | null)[]): number | null => {
  const clean = vals.filter((v): v is number => v != null)
  if (!clean.length) return null
  return clean.reduce((a, b) => a + b, 0) / clean.length
}

/** Newer half against older half. Deliberately blunt: an eight-game window
 *  cannot support anything more, and a slope fit would imply precision the
 *  sample does not have. */
function direction(newestFirst: (number | null)[]): 'up' | 'down' | 'flat' | null {
  const clean = newestFirst.filter((v): v is number => v != null)
  if (clean.length < 4) return null
  const half = Math.floor(clean.length / 2)
  const recent = mean(clean.slice(0, half))
  const prior = mean(clean.slice(half))
  if (recent == null || prior == null) return null
  const base = Math.abs(prior) || 0.01
  const delta = (recent - prior) / base
  if (delta > 0.12) return 'up'
  if (delta < -0.12) return 'down'
  return 'flat'
}

/** Plain-English read of the snap workload, so the card opens with what the
 *  player IS before it asks anyone to parse a table. */
function roleLine(role: Role, games: NflUsageGame[]): string | null {
  const s = mean(games.map((g) => g.snap_share))
  if (s == null) return null
  const noun = role === 'qb' ? 'quarterback'
    : role === 'rb' ? 'back'
    : role === 'wrte' ? 'receiver'
    : 'player'
  const weight = s >= 0.75 ? 'Every-down' : s >= 0.4 ? 'Rotational' : 'Situational'
  return `${weight} ${noun}`
}

// ── sparkline ────────────────────────────────────────────────────────
/** Single series, single hue, most recent bar emphasised — the endpoint is the
 *  thing being read. Reads left-to-right in time; games arrive newest-first.
 *
 *  Scaled to the series' own range off a zero baseline, not to the metric's
 *  theoretical domain. A target share that moves between 21% and 37% is eight
 *  identical stubs against a full 0-100% axis, which hides the only thing a
 *  sparkline is for. Zero stays in the domain so the bar heights remain
 *  proportional rather than a magnified wiggle. */
function Spark({ values }: { values: (number | null)[] }) {
  const chrono = [...values].reverse()
  const nums = chrono.filter((v): v is number => v != null)
  if (!nums.length) return <div className="h-6" />
  const lo = Math.min(0, ...nums)
  const hi = Math.max(0, ...nums)
  const span = hi - lo || 1
  const lastIdx = chrono.map((v, i) => (v == null ? -1 : i)).filter((i) => i >= 0).pop()
  // Where zero sits in the plot. CPOE, EPA and YAC± cross it; the shares never
  // do, which collapses this to a plain baseline chart for them.
  const zero = (-lo / span) * 100
  const diverging = lo < 0
  return (
    <div className="relative h-6" aria-hidden="true">
      {diverging && (
        <div className="absolute inset-x-0 border-t border-zinc-700/70" style={{ bottom: `${zero}%` }} />
      )}
      <div className="absolute inset-0 flex items-stretch gap-[2px]">
        {chrono.map((v, i) => {
          const isLast = i === lastIdx
          const neg = v != null && v < 0
          const tone = v == null ? 'bg-zinc-800'
            : isLast ? (neg ? 'bg-red-400' : 'bg-emerald-400')
            : 'bg-zinc-600'
          const size = v == null ? 2 : Math.max((Math.abs(v) / span) * 100, 3)
          return (
            <div key={i} className="relative flex-1">
              <div
                className={`absolute inset-x-0 ${tone} ${neg ? 'rounded-b-[2px]' : 'rounded-t-[2px]'}`}
                style={neg
                  ? { top: `${100 - zero}%`, height: `${size}%` }
                  : { bottom: `${zero}%`, height: `${size}%` }}
              />
            </div>
          )
        })}
      </div>
    </div>
  )
}

function TrendChip({ dir }: { dir: 'up' | 'down' | 'flat' | null }) {
  if (dir == null || dir === 'flat') return null
  const up = dir === 'up'
  return (
    <span className={`text-[10px] leading-none ${up ? 'text-emerald-400' : 'text-red-400'}`}>
      {up ? '▲' : '▼'}
    </span>
  )
}

// ── component ────────────────────────────────────────────────────────
interface Props {
  playerId: number
  season?: number
  /** The component was built standalone, so it renders its own identity line.
   *  Mounted under a page that already names the player, that is a duplicate —
   *  pass false there. Kept opt-out rather than removed so the component still
   *  stands on its own elsewhere. */
  showHeader?: boolean
}

const SHELL = 'rounded-xl border border-zinc-800 bg-zinc-900'

export default function NflUsageTrend({ playerId, season, showHeader = true }: Props) {
  const { data, loading, error } = useNflUsage(playerId, season)

  if (loading) {
    return (
      <div className={`${SHELL} p-6 animate-pulse space-y-4`}>
        <div className="h-4 w-40 rounded bg-zinc-800" />
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
          {[...Array(4)].map((_, i) => <div key={i} className="h-20 rounded-lg bg-zinc-800" />)}
        </div>
        <div className="space-y-2">
          {[...Array(4)].map((_, i) => <div key={i} className="h-7 rounded bg-zinc-800" />)}
        </div>
      </div>
    )
  }

  if (error) {
    return <div className={`${SHELL} p-6 text-sm text-zinc-500`}>{error}</div>
  }

  if (!data || data.games.length === 0) {
    return <div className={`${SHELL} p-6 text-sm text-zinc-500`}>No usage data for this season</div>
  }

  const { games, name, position, team, season: resolvedSeason } = data
  const role = roleOf(position)
  const bands = bandsFor(role, games)
  const tiles = TILES[role].filter((t) => games.some((g) => t.get(g) != null))
  const line = roleLine(role, games)
  const weeks = games.length

  return (
    <div className={SHELL}>
      {showHeader && (
        <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1 px-6 pt-6">
          <span className="text-base font-semibold text-zinc-100">{name}</span>
          <span className="text-sm text-zinc-500">{position}</span>
          <span className="text-sm text-zinc-500">{team}</span>
          <span className="text-xs text-zinc-600">{resolvedSeason}</span>
        </div>
      )}

      {/* Summary before detail: what the player is, then the numbers. */}
      <div className="px-6 pt-5 pb-4 flex flex-wrap items-baseline gap-x-2">
        {line && <h3 className="text-[15px] font-medium text-zinc-200">{line}</h3>}
        <span className="text-xs text-zinc-500">
          last {weeks} game{weeks === 1 ? '' : 's'} &middot; {resolvedSeason}
        </span>
      </div>

      {tiles.length > 0 && (
        <div className="px-6 pb-5 grid grid-cols-2 sm:grid-cols-4 gap-3">
          {tiles.map((t) => {
            const series = games.map(t.get)
            return (
              <div key={t.label} className="rounded-lg border border-zinc-800 bg-zinc-950/40 px-3.5 py-3">
                <div className="flex items-center justify-between gap-2">
                  <span className="text-[10px] uppercase tracking-[0.12em] text-zinc-500">{t.label}</span>
                  <TrendChip dir={direction(series)} />
                </div>
                <div className="mt-1 font-mono text-xl tabular-nums text-zinc-100 leading-none">
                  {t.fmt(mean(series))}
                </div>
                <div className="mt-2.5">
                  <Spark values={series} />
                </div>
              </div>
            )
          })}
        </div>
      )}

      <div className="overflow-x-auto border-t border-zinc-800 [scrollbar-width:none] [&::-webkit-scrollbar]:hidden">
        <table className="w-full text-sm">
          <thead>
            <tr className="text-[10px] uppercase tracking-[0.12em] text-zinc-600">
              <th colSpan={2} />
              {bands.map((b) => (
                <th key={b.label} colSpan={b.cols.length}
                    className="border-l border-zinc-800 px-3 pt-3 pb-1.5 text-center font-medium">
                  {b.label}
                </th>
              ))}
            </tr>
            <tr className="border-b border-zinc-800 text-[11px] uppercase tracking-wider text-zinc-500">
              <th className="px-3 pb-2 text-left font-medium">Wk</th>
              <th className="px-3 pb-2 text-left font-medium">Opp</th>
              {bands.map((b) => b.cols.map((col, i) => (
                <th key={b.label + col.key}
                    className={`px-3 pb-2 text-right font-medium ${i === 0 ? 'border-l border-zinc-800' : ''}`}>
                  {col.label}
                </th>
              )))}
            </tr>
          </thead>
          <tbody>
            {games.map((g, gi) => (
              <tr key={gi} className="border-b border-zinc-800/50 last:border-b-0 hover:bg-zinc-800/30 transition-colors">
                <td className="px-3 py-2.5 font-mono tabular-nums text-zinc-400">{g.week ?? DASH}</td>
                {/* No vs/@ — home_away is NULL on every NFL row, and the old
                    renderer printed "@" for all of them, calling home games away. */}
                <td className="px-3 py-2.5 text-zinc-300">{g.opponent ?? DASH}</td>
                {bands.map((b) => b.cols.map((col, ci) => {
                  const v = col.value(g)
                  const fill = col.bar?.(g)
                  return (
                    <td key={b.label + col.key}
                        className={`px-3 py-2.5 text-right align-middle ${ci === 0 ? 'border-l border-zinc-800' : ''}`}>
                      <span className={`font-mono tabular-nums ${v ? 'text-zinc-200' : 'text-zinc-600'}`}>
                        {col.fmt(g)}
                      </span>
                      {/* Magnitude bar: one hue, sequential, so a column of
                          shares can be scanned without reading every digit. */}
                      {fill != null && (
                        <span className="mt-1 block h-[3px] w-full overflow-hidden rounded-[1px] bg-zinc-800">
                          <span className="block h-full rounded-[1px] bg-emerald-400/70"
                                style={{ width: `${Math.min(Math.max(fill, 0) * 100, 100)}%` }} />
                        </span>
                      )}
                    </td>
                  )
                }))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}
