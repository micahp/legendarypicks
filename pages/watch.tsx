import Head from 'next/head'
import { useEffect, useState } from 'react'

type BroadcastStatus = 'live' | 'upcoming' | 'ended'

type WatchBroadcast = {
  id: string
  sourceId: string
  title: string
  competition: string
  videoId: string
  status: BroadcastStatus
  checkedAt: string
}

type BroadcastPayload = {
  broadcasts: WatchBroadcast[]
  publicationRule: string
}

const STATUS_COPY: Record<BroadcastStatus, string> = {
  live: 'Live now',
  upcoming: 'Upcoming',
  ended: 'Broadcast ended · replay',
}

function statusClass(status: BroadcastStatus) {
  if (status === 'live') return 'border-red-500/30 bg-red-500/10 text-red-400'
  if (status === 'upcoming') return 'border-amber-500/30 bg-amber-500/10 text-amber-300'
  return 'border-zinc-700 bg-zinc-800/70 text-zinc-400'
}

function YouTubePlayer({ broadcast }: { broadcast: WatchBroadcast }) {
  const [origin, setOrigin] = useState('')
  useEffect(() => setOrigin(window.location.origin), [])
  const suffix = origin ? `?rel=0&origin=${encodeURIComponent(origin)}` : '?rel=0'

  return (
    <div className="aspect-video overflow-hidden rounded-xl border border-zinc-800 bg-black">
      <iframe
        className="h-full w-full"
        src={`https://www.youtube.com/embed/${broadcast.videoId}${suffix}`}
        title={`${broadcast.title} — ${broadcast.competition}`}
        allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture; web-share"
        allowFullScreen
      />
    </div>
  )
}

export default function WatchPage() {
  const [data, setData] = useState<BroadcastPayload | null>(null)
  const [error, setError] = useState(false)

  useEffect(() => {
    let active = true
    fetch('/api/watch/broadcasts', { cache: 'no-store' })
      .then((response) => response.ok ? response.json() : Promise.reject(new Error('watch broadcasts unavailable')))
      .then((payload: BroadcastPayload) => { if (active) setData(payload) })
      .catch(() => { if (active) setError(true) })
    return () => { active = false }
  }, [])

  const broadcasts = data?.broadcasts ?? []
  const live = broadcasts.filter((broadcast) => broadcast.status === 'live')

  return (
    <>
      <Head><title>Watch — Legendary Picks</title></Head>
      <div className="space-y-8">
        <header className="flex items-start justify-between gap-4">
          <div>
            <p className="font-mono text-[11px] uppercase tracking-[0.18em] text-emerald-400">Official broadcasts</p>
            <h1 className="mt-1 text-3xl font-extrabold tracking-tight text-zinc-50">Watch</h1>
            <p className="mt-2 max-w-2xl text-sm text-zinc-400">Free official broadcasts verified to play here. No link-outs and no guessed streams.</p>
          </div>
          {live.length > 0 ? <span className="inline-flex shrink-0 items-center gap-1.5 rounded-full border border-red-500/30 bg-red-500/10 px-2.5 py-1 text-[11px] font-semibold uppercase tracking-wider text-red-400"><span className="h-1.5 w-1.5 rounded-full bg-red-400" />Live</span> : null}
        </header>

        {error ? (
          <div className="rounded-xl border border-amber-500/30 bg-amber-500/10 p-4 text-sm text-amber-200">Verified broadcasts are unavailable right now. Nothing has been substituted.</div>
        ) : !data ? (
          <div className="space-y-3 animate-pulse"><div className="h-5 w-32 rounded bg-zinc-800" /><div className="aspect-video rounded-xl bg-zinc-800" /></div>
        ) : broadcasts.length === 0 ? (
          <div className="rounded-xl border border-zinc-800 bg-zinc-900 p-5 text-sm text-zinc-400">No verified embeddable broadcasts are on the board right now.</div>
        ) : (
          <section className="space-y-4">
            {live.length === 0 ? <p className="text-sm text-zinc-400">No verified embeddable broadcast is live right now. Verified completed broadcasts remain available below.</p> : null}
            <div className="grid gap-5 lg:grid-cols-2">
              {broadcasts.map((broadcast) => (
                <article key={broadcast.id} className="overflow-hidden rounded-xl border border-zinc-800 bg-zinc-900/70 p-4 sm:p-5">
                  <div className="mb-3 flex items-start justify-between gap-3">
                    <div>
                      <p className="font-mono text-[10px] uppercase tracking-[0.16em] text-zinc-500">{broadcast.competition}</p>
                      <h2 className="mt-1 text-lg font-bold text-zinc-100">{broadcast.title}</h2>
                    </div>
                    <span className={`shrink-0 rounded-full border px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wider ${statusClass(broadcast.status)}`}>{STATUS_COPY[broadcast.status]}</span>
                  </div>
                  <YouTubePlayer broadcast={broadcast} />
                  <p className="mt-3 text-xs text-zinc-500">Last verified {new Date(broadcast.checkedAt).toLocaleString()} · Official FIBA YouTube</p>
                </article>
              ))}
            </div>
          </section>
        )}
      </div>
    </>
  )
}
