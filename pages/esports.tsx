import { useState, useEffect, useRef } from 'react'
import Head from 'next/head'

type Player = { name: string; rating: number | null; clock: number | null }
type ChessLive = {
  live: boolean
  gameId?: string
  url?: string
  white?: Player
  black?: Player
  turn?: 'white' | 'black'
  clocks?: { white: number | null; black: number | null }
  material?: number
  swing?: number
  moment?: string | null
}

const POLL_MS = 10_000

function clock(s: number | null | undefined) {
  if (s === null || s === undefined) return '—'
  const m = Math.floor(s / 60)
  const r = s % 60
  return m > 0 ? `${m}:${String(r).padStart(2, '0')}` : `${r}s`
}

function PlayerRow({ p, up, lowClock }: { p?: Player; up: boolean; lowClock: boolean }) {
  return (
    <div className="flex items-center justify-between gap-3">
      <div className="min-w-0 flex items-center gap-2">
        <span className="truncate font-medium text-zinc-100">{p?.name ?? '—'}</span>
        {p?.rating ? <span className="text-xs text-zinc-500">{p.rating}</span> : null}
        {up ? <span className="text-xs text-emerald-400">▲ up material</span> : null}
      </div>
      <span className={`tabular-nums text-sm ${lowClock ? 'text-red-400 font-semibold' : 'text-zinc-400'}`}>
        {clock(p?.clock)}
      </span>
    </div>
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

  const mat = data?.material ?? 0
  const whiteUp = mat > 0
  const blackUp = mat < 0
  const wLow = (data?.clocks?.white ?? 99) <= 20
  const bLow = (data?.clocks?.black ?? 99) <= 20

  return (
    <>
      <Head><title>Esports — Legendary Picks</title></Head>

      <div className="space-y-6">
        <header className="space-y-1">
          <div className="flex items-center gap-3">
            <h1 className="text-2xl font-extrabold tracking-tight">Esports</h1>
            <span className="inline-flex items-center gap-1.5 text-xs font-semibold text-red-400">
              <span className="h-2 w-2 rounded-full bg-red-500 animate-pulse" /> LIVE
            </span>
          </div>
          <p className="text-sm text-zinc-500">
            The moment that matters, as it happens. Chess first — Dota and CS2 next.
          </p>
        </header>

        <div className="grid gap-5 md:grid-cols-[minmax(0,1fr)_320px]">
          {/* Live board (Lichess TV — the current top game, same source as our read) */}
          <div className="overflow-hidden rounded-xl border border-zinc-800 bg-ink-900">
            <iframe
              src="https://lichess.org/tv/frame?theme=auto&bg=dark"
              title="Live chess"
              className="h-[460px] w-full"
              style={{ border: 'none' }}
            />
          </div>

          {/* Moment-that-matters card */}
          <aside className="space-y-4">
            <div className="rounded-xl border border-zinc-800 bg-zinc-900/40 p-4 space-y-3">
              <div className="text-[11px] uppercase tracking-widest text-zinc-500">Top live game</div>
              {err && !data ? (
                <p className="text-sm text-zinc-500">Live feed unavailable — retrying…</p>
              ) : !data ? (
                <div className="space-y-2 animate-pulse">
                  <div className="h-4 w-3/4 rounded bg-zinc-800" />
                  <div className="h-4 w-2/3 rounded bg-zinc-800" />
                </div>
              ) : !data.live ? (
                <p className="text-sm text-zinc-500">No featured game right now.</p>
              ) : (
                <div className="space-y-2">
                  <PlayerRow p={data.white} up={whiteUp} lowClock={wLow} />
                  <div className="h-px bg-zinc-800" />
                  <PlayerRow p={data.black} up={blackUp} lowClock={bLow} />
                </div>
              )}
            </div>

            {/* The inflection callout — the product thesis, made visible */}
            {data?.live && data.moment ? (
              <div className="rounded-xl border border-emerald-600/40 bg-emerald-950/20 p-4">
                <div className="text-[11px] uppercase tracking-widest text-emerald-500/80">Moment that matters</div>
                <p className="mt-1 text-sm font-medium text-emerald-300">{data.moment}</p>
              </div>
            ) : data?.live ? (
              <div className="rounded-xl border border-zinc-800 bg-zinc-900/40 p-4">
                <div className="text-[11px] uppercase tracking-widest text-zinc-500">Moment that matters</div>
                <p className="mt-1 text-sm text-zinc-500">Even game — watching for the turn…</p>
              </div>
            ) : null}

            {data?.url ? (
              <a href={data.url} target="_blank" rel="noreferrer"
                 className="block text-center text-xs text-zinc-500 hover:text-emerald-400">
                open this game on lichess ↗
              </a>
            ) : null}
          </aside>
        </div>
      </div>
    </>
  )
}
