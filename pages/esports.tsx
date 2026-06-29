import { useState, useEffect, useRef } from 'react'
import Head from 'next/head'

type Player = { name: string; rating: number | null; clock: number | null }
type Eval = { cp: number | null; mate: number | null; win_pct: number }
type ChessLive = {
  live: boolean
  gameId?: string
  url?: string
  white?: Player
  black?: Player
  turn?: 'white' | 'black'
  clocks?: { white: number | null; black: number | null }
  material?: number
  eval?: Eval | null
  winPct?: number | null
  winSwing?: number | null
  moment?: string | null
}

const POLL_MS = 10_000

function clock(s: number | null | undefined) {
  if (s === null || s === undefined) return '—'
  const m = Math.floor(s / 60)
  const r = s % 60
  return m > 0 ? `${m}:${String(r).padStart(2, '0')}` : `0:${String(r).padStart(2, '0')}`
}

// Win-probability bar — the hero. White fills from the left; a hairline marks even (50%).
// Width transitions so the bar visibly slides toward whoever is gaining (respects reduced-motion).
function WinBar({ white }: { white: number }) {
  return (
    <div className="relative h-3 w-full overflow-hidden rounded-sm bg-zinc-700/60 ring-1 ring-inset ring-black/40">
      <div
        className="h-full bg-zinc-100 transition-[width] duration-700 ease-out motion-reduce:transition-none"
        style={{ width: `${white}%` }}
      />
      <div className="absolute inset-y-0 left-1/2 w-px -translate-x-1/2 bg-emerald-400/40" />
    </div>
  )
}

function ClockTag({ s }: { s: number | null | undefined }) {
  const low = s !== null && s !== undefined && s <= 20
  return (
    <span className={`font-mono text-sm tabular-nums ${low ? 'text-red-400' : 'text-zinc-300'}`}>
      {low ? '⏱ ' : ''}{clock(s)}
    </span>
  )
}

export default function EsportsPage() {
  const [data, setData] = useState<ChessLive | null>(null)
  const [err, setErr] = useState(false)
  const timer = useRef<ReturnType<typeof setInterval> | null>(null)

  useEffect(() => {
    let alive = true
    const load = async () => {
      try {
        const r = await fetch('/api/esports/chess/live')
        const d = await r.json()
        if (alive) { setData(d); setErr(false) }
      } catch {
        if (alive) setErr(true)
      }
    }
    load()
    timer.current = setInterval(load, POLL_MS)
    return () => { alive = false; if (timer.current) clearInterval(timer.current) }
  }, [])

  const wp = data?.winPct ?? null
  const leaderWhite = wp !== null && wp >= 50
  const leaderName = wp === null ? null : (leaderWhite ? data?.white?.name : data?.black?.name)
  const leadPct = wp === null ? null : Math.max(wp, 100 - wp)
  const swing = data?.winSwing ?? null
  const swingMag = swing === null ? 0 : Math.abs(swing)

  return (
    <>
      <Head><title>Esports — Legendary Picks</title></Head>

      <div className="space-y-6">
        <header className="space-y-1">
          <div className="flex items-center gap-3">
            <h1 className="text-2xl font-extrabold tracking-tight">Esports</h1>
            <span className="inline-flex items-center gap-1.5 text-xs font-semibold text-red-400">
              <span className="h-2 w-2 rounded-full bg-red-500 animate-pulse motion-reduce:animate-none" /> LIVE
            </span>
          </div>
          <p className="text-sm text-zinc-500">
            The moment that matters, as it happens. Chess first — Dota and CS2 next.
          </p>
        </header>

        <div className="grid gap-5 md:grid-cols-[minmax(0,460px)_minmax(0,340px)] md:justify-center">
          {/* Live board — the current top game on Lichess TV, updating in real time */}
          <div className="overflow-hidden rounded-xl border border-zinc-800 bg-ink-900">
            <iframe
              src="https://lichess.org/tv/frame?theme=auto&bg=dark"
              title="Live chess board"
              className="h-[400px] w-full sm:h-[460px]"
              style={{ border: 'none' }}
            />
          </div>

          {/* The instrument: live win-probability readout + the moment */}
          <aside className="space-y-3">
            <section className="rounded-xl border border-zinc-800 bg-zinc-900/50 p-4">
              <div className="flex items-center justify-between text-[10px] font-medium uppercase tracking-[0.18em] text-zinc-500">
                <span>Top live game</span>
                <span className="font-mono">lichess tv</span>
              </div>

              {err && !data ? (
                <p className="mt-4 text-sm text-zinc-500">Live feed dropped. Reconnecting…</p>
              ) : !data ? (
                <div className="mt-4 space-y-3 animate-pulse motion-reduce:animate-none">
                  <div className="h-9 w-28 rounded bg-zinc-800" />
                  <div className="h-3 w-full rounded bg-zinc-800" />
                  <div className="h-4 w-2/3 rounded bg-zinc-800" />
                </div>
              ) : !data.live ? (
                <p className="mt-4 text-sm text-zinc-500">No featured game right now — check back in a minute.</p>
              ) : (
                <>
                  {/* Hero win-probability readout */}
                  {wp !== null ? (
                    <div className="mt-3">
                      <div className="flex items-end justify-between">
                        <div>
                          <div className="text-[10px] uppercase tracking-[0.18em] text-zinc-500">
                            {leaderWhite ? 'White' : 'Black'} to win
                          </div>
                          <div className="font-mono text-5xl font-bold leading-none tabular-nums text-zinc-50">
                            {leadPct!.toFixed(0)}<span className="text-2xl text-zinc-500">%</span>
                          </div>
                        </div>
                        {/* Momentum tick — which way the game is trending */}
                        <div className="text-right font-mono text-xs tabular-nums">
                          {swingMag >= 2 ? (
                            <span className="text-amber-300">
                              {swing! > 0 ? '▲' : '▼'} {swingMag.toFixed(1)} → {swing! > 0 ? 'White' : 'Black'}
                            </span>
                          ) : (
                            <span className="text-zinc-600">steady</span>
                          )}
                          <div className="mt-0.5 text-[10px] uppercase tracking-wider text-zinc-600">last moves</div>
                        </div>
                      </div>
                      <div className="mt-3">
                        <WinBar white={wp} />
                      </div>
                    </div>
                  ) : null}

                  {/* Players */}
                  <div className="mt-4 space-y-2.5 border-t border-zinc-800 pt-3">
                    {(['white', 'black'] as const).map((c) => {
                      const p = c === 'white' ? data.white : data.black
                      return (
                        <div key={c} className="flex items-center justify-between gap-3">
                          <div className="flex min-w-0 items-center gap-2">
                            <span className={`h-2.5 w-2.5 shrink-0 rounded-full ring-1 ring-zinc-600 ${c === 'white' ? 'bg-zinc-100' : 'bg-zinc-800'}`} />
                            <span className="truncate text-sm font-medium text-zinc-100">{p?.name ?? '—'}</span>
                            {p?.rating ? <span className="font-mono text-xs text-zinc-500">{p.rating}</span> : null}
                          </div>
                          <ClockTag s={p?.clock} />
                        </div>
                      )
                    })}
                  </div>
                </>
              )}
            </section>

            {/* Moment that matters — the inflection, the product's whole point */}
            {data?.live ? (
              data.moment ? (
                <section className="rounded-xl border-l-2 border-emerald-500 bg-emerald-500/[0.07] p-4">
                  <div className="text-[10px] font-medium uppercase tracking-[0.18em] text-emerald-400/90">
                    Moment that matters
                  </div>
                  <p className="mt-1 text-sm font-semibold text-emerald-200">{data.moment}</p>
                </section>
              ) : (
                <section className="rounded-xl border-l-2 border-zinc-700 bg-zinc-900/40 p-4">
                  <div className="text-[10px] font-medium uppercase tracking-[0.18em] text-zinc-500">
                    Moment that matters
                  </div>
                  <p className="mt-1 text-sm text-zinc-500">Even game — watching for the turn.</p>
                </section>
              )
            ) : null}

            {data?.url ? (
              <a
                href={data.url}
                target="_blank"
                rel="noreferrer"
                className="block rounded-lg py-1 text-center font-mono text-xs text-zinc-500 hover:text-emerald-400 focus-visible:outline focus-visible:outline-2 focus-visible:outline-emerald-500"
              >
                open this game on lichess ↗
              </a>
            ) : null}
          </aside>
        </div>
      </div>
    </>
  )
}
