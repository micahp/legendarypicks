import { useEffect, useMemo, useState } from 'react'
import { useRouter } from 'next/router'
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

interface TitleOption {
  slug: string
  label: string
  match_count: number
  live_count: number
  result_count: number
  next_start: number | null
}

interface PredictSlate {
  schema_version: string
  selected_title: { slug: string; label: string }
  titles: TitleOption[]
  matches: Match[]
  match_count: number
  has_more: boolean
  building: boolean
  error: string | null
  source: string | null
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

const EMPTY_RECORD: RecordT = { wins: 0, losses: 0, voids: 0, streak: 0 }

// Derive a title-scoped record from the (cross-title) picks list — the picks
// API reports one aggregate record, not one per esports title.
function recordForTitle(picks: MyPick[], titleLabel: string): RecordT {
  const scoped = picks
    .filter((p) => p.matchKey.split('||')[2] === titleLabel && p.settledAt !== null)
    .sort((a, b) => (a.settledAt || 0) - (b.settledAt || 0))

  let wins = 0, losses = 0, voids = 0
  for (const p of scoped) {
    if (p.result === 'win') wins++
    else if (p.result === 'loss') losses++
    else if (p.result === 'void') voids++
  }

  let streak = 0
  for (let i = scoped.length - 1; i >= 0; i--) {
    const r = scoped[i].result
    if (r === 'void') continue
    if (streak === 0) { streak = r === 'win' ? 1 : -1; continue }
    if ((streak > 0 && r === 'win') || (streak < 0 && r === 'loss')) streak += streak > 0 ? 1 : -1
    else break
  }
  return { wins, losses, voids, streak }
}

export default function PredictPage() {
  const router = useRouter()
  const urlTitle = typeof router.query.title === 'string' ? router.query.title : undefined

  const [slate, setSlate] = useState<PredictSlate | null>(null)
  const [loading, setLoading] = useState(true)
  const [fetchError, setFetchError] = useState<string | null>(null)
  const [reloadTick, setReloadTick] = useState(0)

  const [myPicks, setMyPicks] = useState<MyPick[]>([])
  const [submittingKey, setSubmittingKey] = useState<string | null>(null)
  const [crowd, setCrowd] = useState<Record<string, { countA: number; countB: number; total: number; shareA: number | null }>>({})

  const loadPicks = async () => {
    const deviceId = getDeviceId()
    const res = await fetch('/api/esports/picks/me', { headers: { 'X-Device-Id': deviceId } })
    if (!res.ok) throw new Error('failed to load picks')
    const data = await res.json()
    setMyPicks(data.picks || [])
  }

  // Slate fetch — keyed on the URL's ?title= (alias or canonical slug, passed
  // straight through to the backend, which resolves it) plus a manual retry tick.
  useEffect(() => {
    // Wait for Next's client-side query parsing to settle — otherwise a direct
    // load of /predict?title=cod fetches once with urlTitle undefined (wrong
    // default-title slate flashes in) and again once router.isReady catches up.
    if (!router.isReady) return
    let active = true
    ;(async () => {
      setLoading(true)
      setFetchError(null)
      try {
        const qs = urlTitle ? `?title=${encodeURIComponent(urlTitle)}` : ''
        const res = await fetch(`/api/esports/predict${qs}`)
        if (!res.ok) {
          const body = await res.json().catch(() => null)
          throw new Error(body?.detail || `Failed to load predict slate (${res.status})`)
        }
        const data: PredictSlate = await res.json()
        if (!active) return
        setSlate(data)
      } catch (e) {
        if (!active) return
        setFetchError(e instanceof Error ? e.message : 'Failed to load predict slate')
      } finally {
        if (active) setLoading(false)
      }
    })()
    return () => { active = false }
  }, [router.isReady, urlTitle, reloadTick])

  // Picks load independently of the selected title (cross-title record/history).
  useEffect(() => {
    let active = true
    ;(async () => {
      try {
        await loadPicks()
      } catch {
        if (active) setMyPicks([])
      }
    })()
    return () => { active = false }
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
    return () => { active = false }
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

  const selectTitle = (slug: string) => {
    router.push({ pathname: '/predict', query: { title: slug } }, undefined, { shallow: true })
  }

  const selectedLabel = slate?.selected_title.label
  const pickByKey = (mk: string): MyPick | null => myPicks.find((p) => p.matchKey === mk) || null

  const record = useMemo(
    () => (selectedLabel ? recordForTitle(myPicks, selectedLabel) : EMPTY_RECORD),
    [myPicks, selectedLabel]
  )
  const hasTotal = record.wins + record.losses + record.voids > 0

  const settled = useMemo(
    () => myPicks
      .filter((p) => p.settledAt !== null && (!selectedLabel || p.matchKey.split('||')[2] === selectedLabel))
      .sort((a, b) => (b.settledAt || 0) - (a.settledAt || 0)),
    [myPicks, selectedLabel]
  )

  const selectedTitleOption = slate?.titles.find((t) => t.slug === slate.selected_title.slug)

  return (
    <>
      <Head>
        <title>Predict — Legendary Picks</title>
        <meta name="description" content="Pick the winner of each esports match and track your record." />
      </Head>

      <div className="mx-auto max-w-2xl px-4 py-6">
        {/* Header with record */}
        <div className="flex items-center justify-between gap-3">
          <div>
            <div className="flex items-center gap-2">
              <h1 className="text-3xl font-extrabold tracking-tight text-zinc-50">Predict</h1>
              <span className="rounded-full border border-emerald-500/30 bg-emerald-500/10 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wider text-emerald-400">Esports</span>
            </div>
            <p className="mt-1 text-sm text-zinc-500">Pick the winner of each esports match. Track your record.</p>
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

        {/* Title pills — horizontally scrollable, URL-driven selection */}
        <div className="mt-6 flex gap-1.5 overflow-x-auto pb-1 [scrollbar-width:none] [&::-webkit-scrollbar]:hidden">
          {(slate?.titles || []).map((t) => {
            const active = t.slug === slate?.selected_title.slug
            return (
              <button
                key={t.slug}
                type="button"
                onClick={() => selectTitle(t.slug)}
                className={`shrink-0 rounded-full border px-3 py-1.5 text-[12px] font-medium transition-colors ${
                  active
                    ? 'border-emerald-500/40 bg-emerald-500/15 text-emerald-300'
                    : 'border-zinc-800 bg-zinc-900/60 text-zinc-500 hover:text-zinc-300'
                }`}
              >
                {t.live_count > 0 && <span className="mr-1 text-emerald-400">●</span>}
                {t.label}
                {t.match_count > 0 && <span className="ml-1 opacity-60">{t.match_count}</span>}
              </button>
            )
          })}
        </div>

        {/* Visible fetch error, distinct from "no matches" */}
        {fetchError && (
          <div className="mt-4 flex items-center justify-between gap-3 rounded-lg border border-red-500/30 bg-red-500/10 px-4 py-3 text-sm text-red-300">
            <span>{fetchError}</span>
            <button onClick={() => setReloadTick((t) => t + 1)} className="shrink-0 font-medium text-red-200 hover:text-red-100">
              Retry
            </button>
          </div>
        )}
        {!fetchError && slate?.error && (
          <div className="mt-4 rounded-lg border border-amber-500/30 bg-amber-500/10 px-4 py-3 text-sm text-amber-300">
            {slate.error}
          </div>
        )}

        {/* Matches */}
        <div className="mt-6 mb-3 text-[10px] font-medium uppercase tracking-[0.18em] text-zinc-500">
          {selectedLabel ? `${selectedLabel} matches` : 'Esports matches'}
        </div>

        {loading ? (
          <div className="space-y-3" role="status" aria-label="Loading matches">
            {Array.from({ length: 4 }).map((_, i) => (
              <div key={i} className="animate-pulse rounded-xl border border-zinc-800 bg-zinc-900 p-4" style={{ opacity: 1 - i * 0.18 }}>
                <div className="flex items-center justify-between gap-4">
                  <div className="flex-1 space-y-2">
                    <div className="h-3.5 w-1/3 rounded bg-zinc-800" />
                    <div className="h-3 w-1/2 rounded bg-zinc-800/70" />
                  </div>
                  <div className="h-8 w-24 rounded-lg bg-zinc-800" />
                </div>
              </div>
            ))}
          </div>
        ) : !fetchError && slate && slate.matches.length === 0 ? (
          slate.building ? (
            <p className="text-sm text-zinc-500">Still loading the latest esports slate — check back in a moment.</p>
          ) : (
            <p className="text-sm text-zinc-500">
              No open {selectedLabel || 'esports'} matches right now.
              {selectedTitleOption?.next_start ? (
                <> Next match {new Date(selectedTitleOption.next_start).toLocaleString(undefined, { month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' })}.</>
              ) : null}
            </p>
          )
        ) : !fetchError && slate ? (
          slate.matches.map((m) => {
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
        ) : null}

        {/* History — scoped to the selected title */}
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
