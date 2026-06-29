import { useState, useEffect, useRef } from 'react'
import Head from 'next/head'

/* ---------------- chess (live "moment that matters" test) ---------------- */
type Player = { name: string; rating: number | null; clock: number | null }
type ChessLive = {
  live: boolean
  url?: string
  white?: Player
  black?: Player
  clocks?: { white: number | null; black: number | null }
  winPct?: number | null
  winSwing?: number | null
  moment?: string | null
}

/* ---------------- LoL / MSI pre-game prediction ---------------- */
type Team = { name: string; code: string; image: string | null; rank: number | null; winPct: number; marketPct: number | null; edge: number | null; wins: number | null }
type Match = { startTime: string; state: string; bestOf: number; teamA: Team; teamB: Team; favorite: string; hasMarket?: boolean }
type MSIData = { event: string; model?: string; matches: Match[]; error?: string }

const POLL_MS = 10_000
const PRED_POLL_MS = 60_000

function clock(s: number | null | undefined) {
  if (s === null || s === undefined) return '—'
  const m = Math.floor(s / 60)
  const r = s % 60
  return m > 0 ? `${m}:${String(r).padStart(2, '0')}` : `0:${String(r).padStart(2, '0')}`
}

function fmtTime(iso: string) {
  try {
    return new Date(iso).toLocaleString(undefined, {
      month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit',
    })
  } catch { return iso }
}

function TeamLine({ t, fav }: { t: Team; fav: boolean }) {
  return (
    <div className="flex items-center justify-between gap-2">
      <div className="flex min-w-0 items-center gap-2">
        {t.image
          ? <img src={t.image} alt="" className="h-6 w-6 shrink-0 object-contain" />
          : <span className="h-6 w-6 shrink-0 rounded bg-zinc-800" />}
        <span className={`truncate text-sm font-medium ${fav ? 'text-zinc-50' : 'text-zinc-300'}`}>{t.name}</span>
        {t.rank ? <span className="font-mono text-[10px] text-zinc-600">#{t.rank}</span> : null}
      </div>
      <div className="text-right leading-tight">
        <div className={`font-mono text-sm tabular-nums ${fav ? 'text-emerald-300' : 'text-zinc-400'}`}>
          {t.winPct.toFixed(0)}%
        </div>
        {t.marketPct !== null
          ? <div className="font-mono text-[10px] tabular-nums text-zinc-600">mkt {t.marketPct.toFixed(0)}%</div>
          : null}
      </div>
    </div>
  )
}

function MatchCard({ m }: { m: Match }) {
  const a = m.teamA, b = m.teamB
  const aFav = m.favorite === a.code
  const done = m.state === 'completed'
  const live = m.state === 'inProgress'
  const correct = done && a.wins !== null && b.wins !== null ? (a.wins > b.wins) === aFav : null
  const valueTeam = (a.edge ?? -99) >= (b.edge ?? -99) ? a : b
  const valueEdge = Math.max(a.edge ?? -99, b.edge ?? -99)
  const showEdge = !!m.hasMarket && !done

  return (
    <div className="rounded-xl border border-zinc-800 bg-zinc-900/50 p-4">
      <div className="mb-2.5 flex items-center justify-between text-[10px] font-medium uppercase tracking-[0.18em]">
        {live ? (
          <span className="flex items-center gap-1.5 text-red-400">
            <span className="h-1.5 w-1.5 rounded-full bg-red-500 animate-pulse motion-reduce:animate-none" /> live
          </span>
        ) : done ? (
          <span className="text-zinc-500">final</span>
        ) : (
          <span className="text-zinc-400">{fmtTime(m.startTime)}</span>
        )}
        <span className="font-mono text-zinc-600">Bo{m.bestOf}</span>
      </div>

      <TeamLine t={a} fav={aFav} />
      <div className="my-2 flex h-2 w-full overflow-hidden rounded-full bg-zinc-800">
        <div className={aFav ? 'bg-emerald-500' : 'bg-zinc-600'} style={{ width: `${a.winPct}%` }} />
        <div className={aFav ? 'bg-zinc-600' : 'bg-emerald-500'} style={{ width: `${b.winPct}%` }} />
      </div>
      <TeamLine t={b} fav={!aFav} />

      {showEdge ? (
        valueEdge >= 4 ? (
          <div className="mt-2.5 flex items-center gap-2 border-t border-zinc-800 pt-2 text-xs">
            <span className="rounded bg-amber-400/15 px-1.5 py-0.5 font-mono font-semibold text-amber-300">
              EDGE {valueTeam.code} +{valueEdge.toFixed(0)}
            </span>
            <span className="font-mono tabular-nums text-zinc-500">
              model {valueTeam.winPct.toFixed(0)}% vs mkt {valueTeam.marketPct?.toFixed(0)}%
            </span>
          </div>
        ) : (
          <div className="mt-2.5 border-t border-zinc-800 pt-2 text-xs text-zinc-600">
            model ≈ market — no edge
          </div>
        )
      ) : null}

      {done ? (
        <div className="mt-2.5 flex items-center gap-2 border-t border-zinc-800 pt-2 text-xs">
          <span className="font-mono tabular-nums text-zinc-300">Final {a.wins}–{b.wins}</span>
          <span className={correct ? 'text-emerald-400' : 'text-red-400'}>
            {correct ? '✓ pick hit' : '✗ pick missed'}
          </span>
        </div>
      ) : null}
    </div>
  )
}

/* Win-probability bar for the chess card (white fills from the left) */
function WinBar({ white }: { white: number }) {
  return (
    <div className="relative h-3 w-full overflow-hidden rounded-sm bg-zinc-700/60 ring-1 ring-inset ring-black/40">
      <div className="h-full bg-zinc-100 transition-[width] duration-700 ease-out motion-reduce:transition-none"
           style={{ width: `${white}%` }} />
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
  const [msi, setMsi] = useState<MSIData | null>(null)
  const [chess, setChess] = useState<ChessLive | null>(null)
  const chessTimer = useRef<ReturnType<typeof setInterval> | null>(null)
  const predTimer = useRef<ReturnType<typeof setInterval> | null>(null)

  useEffect(() => {
    let alive = true
    const loadPred = async () => {
      try { const r = await fetch('/api/esports/lol/msi/predictions'); const d = await r.json(); if (alive) setMsi(d) } catch {}
    }
    const loadChess = async () => {
      try { const r = await fetch('/api/esports/chess/live'); const d = await r.json(); if (alive) setChess(d) } catch {}
    }
    loadPred(); loadChess()
    predTimer.current = setInterval(loadPred, PRED_POLL_MS)
    chessTimer.current = setInterval(loadChess, POLL_MS)
    return () => {
      alive = false
      if (predTimer.current) clearInterval(predTimer.current)
      if (chessTimer.current) clearInterval(chessTimer.current)
    }
  }, [])

  const wp = chess?.winPct ?? null
  const leaderWhite = wp !== null && wp >= 50
  const leadPct = wp === null ? null : Math.max(wp, 100 - wp)
  const swing = chess?.winSwing ?? null
  const swingMag = swing === null ? 0 : Math.abs(swing)
  const matches = msi?.matches ?? []

  return (
    <>
      <Head><title>Esports — Legendary Picks</title></Head>

      <div className="space-y-8">
        <header className="space-y-1">
          <div className="flex items-center gap-3">
            <h1 className="text-2xl font-extrabold tracking-tight">Esports</h1>
            <span className="inline-flex items-center gap-1.5 text-xs font-semibold text-red-400">
              <span className="h-2 w-2 rounded-full bg-red-500 animate-pulse motion-reduce:animate-none" /> LIVE
            </span>
          </div>
          <p className="text-sm text-zinc-500">Who wins, and the moment it turns.</p>
        </header>

        {/* MSI 2026 — pre-game predictions */}
        <section className="space-y-3">
          <div className="flex items-baseline justify-between">
            <h2 className="text-lg font-bold tracking-tight">MSI 2026 — Win Predictions</h2>
            <span className="font-mono text-[10px] uppercase tracking-wider text-zinc-600">
              {msi?.model ?? 'pre-game'}
            </span>
          </div>
          {msi?.error ? (
            <p className="text-sm text-zinc-500">Schedule unavailable right now — retrying.</p>
          ) : matches.length === 0 ? (
            <div className="grid gap-4 sm:grid-cols-2">
              {[0, 1].map((i) => (
                <div key={i} className="h-32 animate-pulse rounded-xl border border-zinc-800 bg-zinc-900/40 motion-reduce:animate-none" />
              ))}
            </div>
          ) : (
            <div className="grid gap-4 sm:grid-cols-2">
              {matches.map((m, i) => <MatchCard key={i} m={m} />)}
            </div>
          )}
          <p className="text-xs text-zinc-600">
            Prior from expert power rankings (Elo → Bo5). Live gold &amp; objectives take over once a game is in progress.
          </p>
        </section>

        {/* Also live: chess (the moment-that-matters test) */}
        <section className="space-y-3">
          <h2 className="text-sm font-semibold uppercase tracking-[0.18em] text-zinc-500">Also live — Chess</h2>
          <div className="grid gap-5 md:grid-cols-[minmax(0,460px)_minmax(0,340px)] md:justify-center">
            <div className="overflow-hidden rounded-xl border border-zinc-800 bg-ink-900">
              <iframe src="https://lichess.org/tv/frame?theme=auto&bg=dark" title="Live chess board"
                      className="h-[400px] w-full sm:h-[460px]" style={{ border: 'none' }} />
            </div>

            <aside className="space-y-3">
              <div className="rounded-xl border border-zinc-800 bg-zinc-900/50 p-4">
                <div className="flex items-center justify-between text-[10px] font-medium uppercase tracking-[0.18em] text-zinc-500">
                  <span>Top live game</span><span className="font-mono">lichess tv</span>
                </div>
                {!chess ? (
                  <div className="mt-4 space-y-3 animate-pulse motion-reduce:animate-none">
                    <div className="h-9 w-28 rounded bg-zinc-800" />
                    <div className="h-3 w-full rounded bg-zinc-800" />
                  </div>
                ) : !chess.live ? (
                  <p className="mt-4 text-sm text-zinc-500">No featured game right now.</p>
                ) : (
                  <>
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
                          <div className="text-right font-mono text-xs tabular-nums">
                            {swingMag >= 2
                              ? <span className="text-amber-300">{swing! > 0 ? '▲' : '▼'} {swingMag.toFixed(1)} → {swing! > 0 ? 'White' : 'Black'}</span>
                              : <span className="text-zinc-600">steady</span>}
                            <div className="mt-0.5 text-[10px] uppercase tracking-wider text-zinc-600">last moves</div>
                          </div>
                        </div>
                        <div className="mt-3"><WinBar white={wp} /></div>
                      </div>
                    ) : null}
                    <div className="mt-4 space-y-2.5 border-t border-zinc-800 pt-3">
                      {(['white', 'black'] as const).map((c) => {
                        const p = c === 'white' ? chess.white : chess.black
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
              </div>
              {chess?.live && chess.moment ? (
                <div className="rounded-xl border-l-2 border-emerald-500 bg-emerald-500/[0.07] p-4">
                  <div className="text-[10px] font-medium uppercase tracking-[0.18em] text-emerald-400/90">Moment that matters</div>
                  <p className="mt-1 text-sm font-semibold text-emerald-200">{chess.moment}</p>
                </div>
              ) : null}
            </aside>
          </div>
        </section>
      </div>
    </>
  )
}
