import Link from 'next/link'
import { useEffect, useState } from 'react'
import {
  LeagueReadiness,
  LeagueReadinessPayload,
  nflHomepageCampaign,
} from '../lib/leagueReadiness'

export default function SeasonalNflCard() {
  const [readiness, setReadiness] = useState<LeagueReadiness | null>(null)

  useEffect(() => {
    let live = true
    fetch('/api/readiness/leagues', { cache: 'no-store' })
      .then(response => response.ok ? response.json() : null)
      .then((payload: LeagueReadinessPayload | null) => {
        if (live) setReadiness(payload?.leagues?.find(row => row.league === 'nfl') || null)
      })
      .catch(() => { /* The generic NFL copy remains honest without readiness data. */ })
    return () => { live = false }
  }, [])

  const campaign = nflHomepageCampaign(readiness)
  return (
    <Link href={campaign.href} className="rounded-xl border border-zinc-800 bg-zinc-900 p-6 hover:border-zinc-700 transition-colors">
      <h3 className="font-bold text-lg mb-2">{campaign.title}</h3>
      <p className="text-sm text-zinc-400">{campaign.description}</p>
    </Link>
  )
}
