import Head from 'next/head'
import Link from 'next/link'
import { useEffect, useState } from 'react'
import { EwcModule } from '../../components/Esports/EwcModule'
import type { EwcProjection, Standings } from '../../components/Esports/EwcModule'

export default function EsportsLeaguePage() {
  const [projection, setProjection] = useState<EwcProjection | null>(null)
  const [standings, setStandings] = useState<Standings | null>(null)
  const [standingsLoading, setStandingsLoading] = useState(true)
  const [standingsLimit, setStandingsLimit] = useState(5)
  const [host, setHost] = useState('')

  useEffect(() => {
    setHost(window.location.hostname)
    const mq = window.matchMedia('(min-width: 1024px)')
    const apply = () => setStandingsLimit(mq.matches ? 10 : 5)
    apply()
    mq.addEventListener('change', apply)
    return () => mq.removeEventListener('change', apply)
  }, [])

  useEffect(() => {
    let alive = true
    const load = () => fetch('/api/esports/events/ewc-2026', { cache: 'no-store' })
      .then((r) => r.json()).then((d) => { if (alive) setProjection(d) }).catch(() => {})
    load()
    const timer = setInterval(load, 10_000)
    return () => { alive = false; clearInterval(timer) }
  }, [])

  useEffect(() => {
    let alive = true
    setStandingsLoading(true)
    fetch(`/api/esports/events/ewc-2026/club-standings?limit=${standingsLimit}`, { cache: 'no-store' })
      .then((r) => r.json()).then((d) => { if (alive) setStandings(d) }).catch(() => {})
      .finally(() => { if (alive) setStandingsLoading(false) })
    return () => { alive = false }
  }, [standingsLimit])

  return (
    <>
      <Head><title>Esports League — Legendary Picks</title></Head>
      <div className="space-y-6">
        <div className="flex flex-wrap items-end justify-between gap-3">
          <div>
            <Link href="/leagues" className="text-xs font-semibold text-zinc-500 hover:text-zinc-300">Leagues</Link>
            <h1 className="mt-2 text-3xl font-extrabold tracking-tight text-zinc-50">Esports</h1>
            <p className="mt-1 text-sm text-zinc-500">Tournament center, club race, schedule, and results.</p>
          </div>
          <Link href="/esports" className="rounded-lg bg-zinc-800 px-4 py-2 text-sm font-semibold text-zinc-200 hover:bg-zinc-700">
            Live esports →
          </Link>
        </div>

        {projection ? (
          <EwcModule projection={projection} host={host} standings={standings}
            standingsLimit={standingsLimit} onExpandStandings={() => setStandingsLimit(10)}
            standingsLoading={standingsLoading} />
        ) : (
          <div className="rounded-xl bg-zinc-900/50 px-6 py-10 text-sm text-zinc-500">Loading EWC tournament center…</div>
        )}
      </div>
    </>
  )
}
