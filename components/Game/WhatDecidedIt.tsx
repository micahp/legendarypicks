import { Leader } from './useGameProps'

/**
 * The settled lines that finished furthest from their own number.
 *
 * COLOR. `honest-data-ui` §5: the accent marks absence, not achievement. Nothing here
 * is an achievement of ours — we store both sides of most lines (35 of 51 in game
 * 401816457), so "the over cashed" is a fact about the game, not a call we got right.
 * An earlier pass painted clears green and shorts red, which in this app already reads
 * as hit/miss on the prop chips below and invites the page to be read as a win-loss
 * record we explicitly refuse to publish. Both directions render in the same neutral
 * ink; the tick and the words carry the meaning.
 *
 * DIRECTION is stated in words rather than encoded in a hue — self-evident beats a
 * legend (Krug, §3), and it survives being read in greyscale or by someone colorblind.
 */

// The line sits at a fixed fraction of every track, so the reader learns the shape once
// and can compare cards by eye without reading a digit.
const LINE_ANCHOR = 55

function marketLabel(market: string) {
  return market.replace(/_/g, ' ')
}

function Gauge({ l }: { l: Leader }) {
  const line = Number(l.line)
  const actual = Number(l.actual)
  // A line of 0 has no meaningful ratio to scale against. Show the bar empty rather
  // than substituting a fake denominator that would silently misplace the fill.
  const scalable = Number.isFinite(line) && Number.isFinite(actual) && line > 0
  const rawPct = scalable ? (actual / line) * LINE_ANCHOR : 0
  const pct = Math.min(100, rawPct)
  const over = scalable && actual > line
  const diff = scalable ? actual - line : null

  return (
    <div className="flex flex-col gap-2 pt-4">
      <div className="relative h-8 rounded bg-zinc-800/60 ring-1 ring-inset ring-zinc-700/50">
        <div className="absolute inset-y-0 left-0 rounded-l bg-zinc-500/70" style={{ width: `${pct}%` }} />
        {/* The line itself is the one high-contrast mark: it's the reference every
            other pixel is measured against. */}
        <div className="absolute -top-1 -bottom-1 w-0.5 bg-zinc-100" style={{ left: `${LINE_ANCHOR}%` }} />
        {rawPct > 100 && (
          <span className="absolute right-1.5 top-1/2 -translate-y-1/2 text-[10px] leading-none text-zinc-300">›</span>
        )}
        <span
          className="absolute -top-4 font-mono text-[10px] tabular-nums whitespace-nowrap text-zinc-500"
          style={{ left: `${LINE_ANCHOR}%`, transform: 'translateX(-50%)' }}
        >
          line {line.toFixed(1)}
        </span>
      </div>
      <div className="flex items-baseline justify-between gap-2 text-xs text-zinc-500">
        <div>
          <span className="font-mono text-lg font-bold tabular-nums text-zinc-100">
            {Number.isFinite(actual) ? actual : '—'}
          </span>{' '}
          recorded
        </div>
        <div className="text-right">
          {diff === null ? (
            <span className="text-zinc-500">line 0</span>
          ) : (
            <>
              <span className="font-mono tabular-nums text-zinc-300">
                {diff > 0 ? '+' : ''}{diff.toFixed(1)}
              </span>
              <span className="ml-1 text-zinc-500">{over ? 'over' : 'under'} the line</span>
            </>
          )}
        </div>
      </div>
    </div>
  )
}

export default function WhatDecidedIt({
  leaders, settledLines,
}: { leaders: Leader[]; settledLines: number }) {
  if (!leaders.length) return null

  // No outer frame or panel fill: this sits inside the game detail page, which
  // already supplies the surface. The inner grid keeps its own hairline rules, so
  // the three cells still read as a set without a second box around them.
  return (
    <section className="py-4">
      <div className="mb-3 flex items-baseline justify-between gap-3">
        <h2 className="text-sm font-bold uppercase tracking-wider text-zinc-400">What decided it</h2>
        {/* Sample size on the surface, always (honest-data-ui §4). Three of forty-eight
            is a different claim from three of four. */}
        <span className="font-mono text-[11px] tabular-nums text-zinc-500">
          {leaders.length} of {settledLines} settled {settledLines === 1 ? 'line' : 'lines'}
        </span>
      </div>
      <div className="grid gap-px overflow-hidden rounded-lg border border-zinc-800 bg-zinc-800 sm:grid-cols-3">
        {leaders.map(l => (
          <div key={`${l.player_id}-${l.market}-${l.line}`} className="flex flex-col gap-3 bg-zinc-900 p-4">
            <div className="text-[11px] font-bold uppercase tracking-wider text-zinc-500">
              {marketLabel(l.market)}
            </div>
            <div className="flex min-w-0 items-baseline gap-2">
              <a href={`/player/${l.player_id}`} className="truncate text-base font-semibold hover:text-emerald-400">
                {l.name}
              </a>
              <span className="shrink-0 text-xs text-zinc-500">{l.team}</span>
            </div>
            <Gauge l={l} />
            {/* Which side landed — computed by the endpoint precisely for this panel. */}
            <div className="text-[11px] uppercase tracking-wider text-zinc-500">
              {l.cashed} cashed
            </div>
          </div>
        ))}
      </div>
    </section>
  )
}
