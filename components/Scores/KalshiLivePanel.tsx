import { useEffect, useState } from 'react'

// One tennis tour's live points, read from the trade desk's Kalshi poller through
// /api/{atp|wta}/kalshi-live. The server answers `available: false` with a reason
// whenever the file is missing, torn, stale or the wrong schema; the panel says so
// and never shows an old score as if it were live.

export interface KalshiMatch {
  milestone_id: string
  title: string
  tour: string
  status: string
  finished: boolean
  game_score_p1: string
  game_score_p2: string
  advantage: string
  server_side: '1' | '2' | ''
  sets_p1: string[]
  sets_p2: string[]
  sets_won_p1: number | null
  sets_won_p2: number | null
  p1: string
  p2: string
  polled_at: string
  age_s: number
}

export interface KalshiLive {
  available: boolean
  reason: string | null
  generated_at: string | null
  matches: KalshiMatch[]
}

const POLL_MS = 5_000
const TICK_MS = 1_000
// Past this, a match is dropped from the panel even between polls: no frozen score.
const DROP_OVER_S = 60
// From here, the age label turns to the warning tone.
const AGING_OVER_S = 15

// Age of a reading now: the server's age at fetch time plus the time since the response arrived.
export function ageNowS(match: KalshiMatch, fetchedAtMs: number, nowMs: number): number {
  return match.age_s + (nowMs - fetchedAtMs) / 1000
}

export function visibleMatches(live: KalshiLive, fetchedAtMs: number, nowMs: number): KalshiMatch[] {
  return live.matches.filter((m) => ageNowS(m, fetchedAtMs, nowMs) <= DROP_OVER_S)
}

const dash = (v: string | number | null | undefined) => (v === '' || v == null ? '–' : String(v))

function PlayerLine({ name, serving, setsWon, setGames, point }: {
  name: string
  serving: boolean
  setsWon: number | null
  setGames: string[]
  point: string
}) {
  return (
    <div className="flex items-center gap-3 text-sm">
      <span className="flex min-w-0 flex-1 items-center gap-2">
        <span
          aria-label={serving ? 'serving' : undefined}
          className={`h-1.5 w-1.5 shrink-0 rounded-full ${serving ? 'bg-zinc-200' : 'bg-transparent'}`}
        />
        <span className="truncate text-zinc-200">{name || '–'}</span>
      </span>
      <span className="w-6 text-right font-semibold tabular-nums text-zinc-200">{dash(setsWon)}</span>
      <span className="flex w-24 justify-end gap-3 tabular-nums text-zinc-400">
        {setGames.length ? setGames.map((g, i) => <span key={i}>{dash(g)}</span>) : <span>–</span>}
      </span>
      <span className="w-10 text-right font-semibold tabular-nums text-zinc-100">{dash(point)}</span>
    </div>
  )
}

export default function KalshiLivePanel({ league, active }: { league: 'atp' | 'wta'; active: boolean }) {
  const [live, setLive] = useState<KalshiLive | null>(null)
  const [fetchedAt, setFetchedAt] = useState(0)
  const [failed, setFailed] = useState(false)
  const [now, setNow] = useState(() => Date.now())

  useEffect(() => {
    if (!active) return
    let cancelled = false
    const load = async () => {
      try {
        const r = await fetch(`/api/${league}/kalshi-live`, { cache: 'no-store' })
        if (!r.ok) throw new Error(`HTTP ${r.status}`)
        const body = (await r.json()) as KalshiLive
        if (cancelled) return
        setLive(body)
        setFetchedAt(Date.now())
        setFailed(false)
      } catch {
        if (cancelled) return
        setLive(null)
        setFailed(true)
      }
    }
    load()
    const poll = setInterval(load, POLL_MS)
    const tick = setInterval(() => setNow(Date.now()), TICK_MS)
    return () => {
      cancelled = true
      clearInterval(poll)
      clearInterval(tick)
    }
  }, [league, active])

  if (!active) return null

  const tour = league.toUpperCase()
  let body
  if (failed) {
    body = <p className="py-3 text-sm text-zinc-500">Point scores unavailable: the request failed.</p>
  } else if (!live) {
    body = <p className="py-3 text-sm text-zinc-500">Loading live points…</p>
  } else if (!live.available) {
    body = <p className="py-3 text-sm text-zinc-500">Point scores unavailable: {live.reason}</p>
  } else {
    const rows = visibleMatches(live, fetchedAt, now)
    body = rows.length === 0 ? (
      <p className="py-3 text-sm text-zinc-500">No live Kalshi matches.</p>
    ) : (
      rows.map((m) => {
        const ageS = ageNowS(m, fetchedAt, now)
        const aging = ageS > AGING_OVER_S
        return (
          <div key={m.milestone_id} className="flex items-start gap-3 border-t border-zinc-800 py-3 first:border-t-0">
            <div className="min-w-0 flex-1 space-y-1">
              <PlayerLine name={m.p1} serving={m.server_side === '1'} setsWon={m.sets_won_p1} setGames={m.sets_p1} point={m.game_score_p1} />
              <PlayerLine name={m.p2} serving={m.server_side === '2'} setsWon={m.sets_won_p2} setGames={m.sets_p2} point={m.game_score_p2} />
            </div>
            <span
              title="Updated about every 4 seconds from Kalshi, up to 4 seconds late"
              className={`shrink-0 pt-0.5 text-xs tabular-nums ${aging ? 'text-amber-400' : 'text-zinc-500'}`}
            >
              Kalshi, {Math.round(ageS)}s ago
            </span>
          </div>
        )
      })
    )
  }

  return (
    <section aria-label={`Live points (Kalshi), ${tour}`} className="rounded-2xl bg-zinc-900 px-5 pt-4 pb-2">
      <h2 className="text-base font-semibold text-zinc-200">
        Live points <span className="font-normal text-zinc-500">· Kalshi · {tour}</span>
      </h2>
      {body}
    </section>
  )
}
