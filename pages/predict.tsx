import { useEffect, useState } from 'react'
import Head from 'next/head'
import { getDeviceId } from '../lib/deviceId'

interface Match {
  matchKey: string
  teamA: string
  teamB: string
  title: string
  league: string
  startTime: number | null
  logoA: string | null
  logoB: string | null
  live: boolean
  finished: boolean
  favorite?: { name: string; pct: number } | null
}

interface MyPick {
  matchKey: string
  side: 'A' | 'B'
  createdAt: number
  lockAt: number | null
  settledAt: number | null
  result: 'win' | 'loss' | 'void' | null
  points: number | null
}

interface RecordT {
  wins: number
  losses: number
  voids: number
  streak: number
}

export default function PredictPage() {
  const [matches, setMatches] = useState<Match[]>([])
  const [myPicks, setMyPicks] = useState<MyPick[]>([])
  const [record, setRecord] = useState<RecordT>({ wins: 0, losses: 0, voids: 0, streak: 0 })
  const [loading, setLoading] = useState(true)
  const [submittingKey, setSubmittingKey] = useState<string | null>(null)
  const [crowd, setCrowd] = useState<Record<string, { countA: number; countB: number; total: number; shareA: number | null }>>({})

  const loadPicks = async () => {
    const deviceId = getDeviceId()
    const res = await fetch('/api/esports/picks/me', { headers: { 'X-Device-Id': deviceId } })
    if (!res.ok) throw new Error('failed to load picks')
    const data = await res.json()
    setMyPicks(data.picks || [])
    setRecord(data.record || { wins: 0, losses: 0, voids: 0, streak: 0 })
  }

  useEffect(() => {
    let active = true
    ;(async () => {
      setLoading(true)
      try {
        const [upRes, picksRes] = await Promise.all([
          fetch('/api/esports/upcoming'),
          fetch('/api/esports/picks/me', { headers: { 'X-Device-Id': getDeviceId() } }),
        ])
        if (!upRes.ok) throw new Error('failed to load upcoming')
        const up = await upRes.json()
        const picksData = picksRes.ok
          ? await picksRes.json()
          : { picks: [], record: { wins: 0, losses: 0, voids: 0, streak: 0 } }
        if (!active) return
        setMatches(up.matches || [])
        setMyPicks(picksData.picks || [])
        setRecord(picksData.record || { wins: 0, losses: 0, voids: 0, streak: 0 })
      } catch {
        // leave empty on failure
      } finally {
        if (active) setLoading(false)
      }
    })()
    return () => {
      active = false
    }
  }, [])

  // Fetch the crowd for each match the user has already picked (revealed after a pick).
  useEffect(() => {
    let active = true
    const toFetch = myPicks.map((p) => p.matchKey).filter((mk) => !(mk in crowd))
    if (toFetch.length === 0) return
    ;(async () => {
      const results = await Promise.all(
        toFetch.map(async (mk) => {
          try {
            const r = await fetch(`/api/esports/crowd?matchKey=${encodeURIComponent(mk)}`)
            if (!r.ok) return [mk, null] as const
            const d = (await r.json()) as { countA: number; countB: number; total: number; shareA: number | null }
            return [mk, d] as const
          } catch {
            return [mk, null] as const
          }
        })
      )
      if (!active) return
      setCrowd((prev) => {
        const next = { ...prev }
        for (const [mk, d] of results) if (d) next[mk] = d
        return next
      })
    })()
    return () => {
      active = false
    }
  }, [myPicks, crowd])

  const call = async (m: Match, side: 'A' | 'B') => {
    const deviceId = getDeviceId()
    setSubmittingKey(m.matchKey)
    try {
      await fetch('/api/esports/picks', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'X-Device-Id': deviceId },
        body: JSON.stringify({ matchKey: m.matchKey, side, lockAt: m.startTime }),
      })
      await loadPicks()
    } catch {
      // ignore network errors in F1 skeleton
    } finally {
      setSubmittingKey(null)
    }
  }

  const openMatches = matches
    .filter((m) => !m.finished && m.teamA && m.teamB)
    .sort((a, b) => {
      if (a.startTime == null && b.startTime == null) return 0
      if (a.startTime == null) return 1
      if (b.startTime == null) return -1
      return a.startTime - b.startTime
    })

  const pickByKey = (mk: string): MyPick | null =>
    myPicks.find((p) => p.matchKey === mk) || null

  const hasTotal = record.wins + record.losses + record.voids > 0

  const settled = myPicks
    .filter((p) => p.settledAt !== null)
    .sort((a, b) => (b.settledAt || 0) - (a.settledAt || 0))

  return (
    <>
      <Head>
        <title>Predict — Legendary Picks</title>
        <meta name="description" content="Pick the winner of each match and track your record." />
      </Head>

      <div className="mx-auto max-w-2xl px-4 py-6">
        {/* Header with record */}
        <div className="flex items-center justify-between gap-3">
          <div>
            <h1 className="text-3xl font-extrabold tracking-tight text-zinc-50">Predict</h1>
            <p className="mt-1 text-sm text-zinc-500">Pick the winner. Track your record.</p>
          </div>
          <div className="text-right">
            {!hasTotal ? (
              <span className="text-sm text-zinc-500">Make your first pick</span>
            ) : (
              <div className="flex items-center gap-2">
                <span className="font-mono text-lg font-bold tabular-nums text-zinc-100">
                  {record.wins}–{record.losses}
                </span>
                {record.streak !== 0 && <span className="text-zinc-500">·</span>}
                {record.streak > 0 && (
                  <span className="font-mono text-lg font-bold text-[#22c55e]">W{record.streak}</span>
                )}
                {record.streak < 0 && (
                  <span className="font-mono text-lg font-bold text-[#ff3d71]">L{-record.streak}</span>
                )}
              </div>
            )}
          </div>
        </div>

        {/* Matches */}
        <div className="mt-8 mb-3 text-[10px] font-medium uppercase tracking-[0.18em] text-zinc-500">
          Matches
        </div>

        {loading ? (
          <p className="text-sm text-zinc-500">Loading…</p>
        ) : openMatches.length === 0 ? (
          <p className="text-sm text-zinc-500">No matches to pick right now.</p>
        ) : (
          openMatches.map((m) => {
            const existing = pickByKey(m.matchKey)
            return (
              <div key={m.matchKey} className="rounded-xl border border-zinc-800 bg-zinc-900/40 p-4 mb-3">
                <div className="mb-3 flex items-center justify-between">
                  <div className="flex items-center gap-2 text-[10px] font-medium uppercase tracking-[0.18em] text-zinc-500">
                    {m.title} · {m.league}
                    {m.live ? ' · ' : ''}
                    {m.live && <span className="text-[#ff3d71]">live</span>}
                  </div>
                  <a href="/esports" className="shrink-0 text-[11px] font-medium uppercase tracking-wider text-zinc-500 hover:text-zinc-200">Watch ↗</a>
                </div>
                <div className="flex items-center justify-between gap-3">
                  <TeamLine name={m.teamA} logo={m.logoA} />
                  <span className="text-zinc-600 text-xs">vs</span>
                  <TeamLine name={m.teamB} logo={m.logoB} />
                </div>
                <div className="mt-3">
                  {existing ? (
                    <>
                      <div className="text-sm">
                        <span className="text-zinc-500">You picked </span>
                        <span className="font-semibold text-zinc-50">
                          {existing.side === 'A' ? m.teamA : m.teamB}
                        </span>
                      </div>
                      <CrowdReveal m={m} crowd={crowd[m.matchKey]} />
                    </>
                  ) : (
                    <div className="flex gap-3">
                      <button
                        disabled={submittingKey === m.matchKey}
                        onClick={() => call(m, 'A')}
                        className="flex-1 rounded-lg border border-zinc-700 bg-zinc-800/60 px-3 py-2 text-sm font-semibold text-zinc-200 hover:border-zinc-500 hover:text-zinc-50 disabled:opacity-50 disabled:cursor-not-allowed"
                      >
                        Pick {m.teamA}
                      </button>
                      <button
                        disabled={submittingKey === m.matchKey}
                        onClick={() => call(m, 'B')}
                        className="flex-1 rounded-lg border border-zinc-700 bg-zinc-800/60 px-3 py-2 text-sm font-semibold text-zinc-200 hover:border-zinc-500 hover:text-zinc-50 disabled:opacity-50 disabled:cursor-not-allowed"
                      >
                        Pick {m.teamB}
                      </button>
                    </div>
                  )}
                </div>
              </div>
            )
          })
        )}

        {/* History */}
        <div className="mt-8 mb-3 text-[10px] font-medium uppercase tracking-[0.18em] text-zinc-500">
          History
        </div>

        {settled.length === 0 ? (
          <p className="text-sm text-zinc-500">No history yet.</p>
        ) : (
          settled.map((p) => {
            const parts = p.matchKey.split('||')
            const teamA = parts[0]
            const teamB = parts[1]
            const title = parts[2] || ''
            const pickedTeam = p.side === 'A' ? teamA : teamB
            return (
              <div
                key={p.matchKey}
                className="flex items-center justify-between border-b border-zinc-800/60 py-2 text-sm"
              >
                <span className="text-zinc-300">
                  {pickedTeam} <span className="text-zinc-600">· {title}</span>
                </span>
                <span>
                  {p.result === 'win' && (
                    <span className="font-mono text-[#22c55e]">
                      Won +{(p.points ?? 0).toFixed(1)}
                    </span>
                  )}
                  {p.result === 'loss' && <span className="font-mono text-[#ff3d71]">Lost</span>}
                  {p.result === 'void' && <span className="font-mono text-zinc-500">Void</span>}
                </span>
              </div>
            )
          })
        )}
      </div>
    </>
  )
}

function TeamLine({ name, logo }: { name: string; logo: string | null }) {
  return (
    <div className="flex items-center gap-2 min-w-0">
      {logo && <img src={logo} alt="" className="h-6 w-6 rounded-sm object-contain" />}
      <span className="text-sm font-semibold text-zinc-100 truncate">{name}</span>
    </div>
  )
}

function CrowdReveal({ m, crowd }: { m: Match; crowd?: { countA: number; countB: number; total: number; shareA: number | null } }) {
  if (!crowd) return null
  if (crowd.total >= 5) {
    const favSide = crowd.countA >= crowd.countB ? 'A' : 'B'
    const favName = favSide === 'A' ? m.teamA : m.teamB
    const favPct = Math.round(((favSide === 'A' ? crowd.countA : crowd.countB) / crowd.total) * 100)
    return (
      <div className="mt-3">
        <div className="mb-1 flex items-center justify-between text-[11px] text-zinc-500">
          <span>Fans favor <span className="text-zinc-300">{favName}</span></span>
          <span className="font-mono tabular-nums">{favPct}%</span>
        </div>
        <div className="h-1.5 w-full overflow-hidden rounded-full bg-zinc-800">
          <div className="h-full bg-zinc-400" style={{ width: `${favPct}%` }} />
        </div>
      </div>
    )
  }
  if (m.favorite) {
    return (
      <div className="mt-3 text-[11px] text-zinc-500">
        Bovada favors <span className="text-zinc-300">{m.favorite.name}</span>
        <span className="font-mono tabular-nums"> · {m.favorite.pct}%</span>
      </div>
    )
  }
  return (
    <div className="mt-3 text-[11px] text-zinc-600">Be the first to pick this one.</div>
  )
}
