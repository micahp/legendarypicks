import Link from 'next/link'
import { useEffect, useRef, useState } from 'react'
import { trackEvent } from '../../lib/analytics'

type Moment = {
  challenge_id: string
  origin: 'observed_nfl_play'
  state: 'archived_verified'
  source_ref: { publisher: 'ESPN'; game_id: string; play_id: string; event_id: string; source_revision: string }
  source_verified_at_utc: string
  last_observed_at_utc?: string
  publisher_updated_at?: string | null
  observed_context: {
    away_team: string
    away_team_id?: string | null
    home_team: string
    home_team_id?: string | null
    period: number | null
    clock: string | null
    game_date: string | null
    attempt_distance_yards: number
  }
}
type LiveMoment = Omit<Moment, 'state'> & {
  state: 'live_observed'
  last_observed_at_utc: string
  publisher_updated_at: string | null
}

type Props = { compact?: boolean }

function formatDate(value: string | null) {
  if (!value) return 'date unavailable'
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? 'date unavailable' : date.toLocaleDateString(undefined, {
    month: 'short', day: 'numeric', year: 'numeric', timeZone: 'UTC',
  })
}

function formatObservedAt(value: string) {
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? 'time unavailable' : date.toLocaleString(undefined, {
    month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit', timeZone: 'UTC',
  }) + ' UTC'
}

function observationAgeBucket(value: string | undefined, now: number) {
  if (!value) return 'unknown'
  const timestamp = new Date(value).getTime()
  if (!Number.isFinite(timestamp)) return 'unknown'
  const ageSeconds = Math.max(0, now - timestamp) / 1000
  return ageSeconds < 60 ? 'under_1m'
    : ageSeconds < 300 ? '1_5m'
      : ageSeconds < 900 ? '5_15m' : 'over_15m'
}

export default function ArchivedKickMoments({ compact = false }: Props) {
  const [moments, setMoments] = useState<Moment[]>([])
  const [liveMoments, setLiveMoments] = useState<LiveMoment[]>([])
  const [liveAvailable, setLiveAvailable] = useState(true)
  const [archiveLiveAvailable, setArchiveLiveAvailable] = useState(true)
  const [state, setState] = useState<'loading' | 'ready' | 'unavailable'>('loading')
  const lastAnalyticsSnapshotRef = useRef('')

  useEffect(() => {
    let controller: AbortController | null = null
    let timer: number | null = null
    let active = true

    const stopPolling = () => {
      if (timer !== null) window.clearInterval(timer)
      timer = null
    }
    const loadMoments = () => {
      controller?.abort()
      const request = new AbortController()
      controller = request
      fetch('/api/arcade/moments', { cache: 'no-store', signal: request.signal })
        .then(async response => {
          if (!response.ok) throw new Error('Arcade moments unavailable')
          return response.json() as Promise<{
            moments: Moment[]
            archived_live_moments?: Moment[]
            live_moments?: LiveMoment[]
            live_available?: boolean
            archive_live_available?: boolean
          }>
        })
        .then(payload => {
          if (!active || request.signal.aborted) return
          const moments = [
            ...(Array.isArray(payload.moments) ? payload.moments : []),
            ...(Array.isArray(payload.archived_live_moments) ? payload.archived_live_moments : []),
          ]
          const archivedMoments = moments.filter((moment, index) =>
            moments.findIndex(candidate => candidate.challenge_id === moment.challenge_id) === index,
          )
          const liveMoments = Array.isArray(payload.live_moments) ? payload.live_moments : []
          const liveAvailable = payload.live_available !== false
          const archiveAvailable = payload.archive_live_available !== false
          const now = Date.now()
          const ageCounts = liveMoments.reduce<Record<string, number>>((counts, moment) => {
            const bucket = observationAgeBucket(moment.last_observed_at_utc, now)
            counts[bucket] = (counts[bucket] || 0) + 1
            return counts
          }, {})
          const snapshot = JSON.stringify({
            liveAvailable,
            archiveAvailable,
            live: liveMoments.map(moment => [moment.challenge_id, moment.last_observed_at_utc, moment.publisher_updated_at]).sort(),
            archive: archivedMoments.map(moment => moment.challenge_id).sort(),
          })
          if (lastAnalyticsSnapshotRef.current !== snapshot) {
            lastAnalyticsSnapshotRef.current = snapshot
            trackEvent('arcade_source_moments_snapshot', {
              surface: compact ? 'nfl_hq' : 'arcade_lobby',
              request_available: true,
              live_available: liveAvailable,
              archive_available: archiveAvailable,
              live_moment_count: liveMoments.length,
              archive_moment_count: archivedMoments.length,
              live_source_age_under_1m: ageCounts.under_1m || 0,
              live_source_age_1_5m: ageCounts['1_5m'] || 0,
              live_source_age_5_15m: ageCounts['5_15m'] || 0,
              live_source_age_over_15m: ageCounts.over_15m || 0,
              live_source_age_unknown: ageCounts.unknown || 0,
              live_publisher_timestamp_known: liveMoments.filter(moment => Boolean(moment.publisher_updated_at)).length,
            })
          }
          setMoments(archivedMoments)
          setLiveMoments(liveMoments)
          setLiveAvailable(liveAvailable)
          setArchiveLiveAvailable(archiveAvailable)
          setState('ready')
        })
        .catch(() => {
          if (active && !request.signal.aborted) {
            setState('unavailable')
            if (lastAnalyticsSnapshotRef.current !== 'unavailable') {
              lastAnalyticsSnapshotRef.current = 'unavailable'
              trackEvent('arcade_source_moments_snapshot', {
                surface: compact ? 'nfl_hq' : 'arcade_lobby',
                request_available: false,
                live_available: false,
                archive_available: false,
                live_moment_count: 0,
                archive_moment_count: 0,
                live_source_age_unknown: 0,
                live_publisher_timestamp_known: 0,
              })
            }
          }
        })
    }
    const startPolling = () => {
      stopPolling()
      if (document.visibilityState === 'visible') {
        timer = window.setInterval(loadMoments, 60_000)
      }
    }
    const onVisibilityChange = () => {
      if (document.visibilityState === 'visible') loadMoments()
      startPolling()
    }

    loadMoments()
    startPolling()
    document.addEventListener('visibilitychange', onVisibilityChange)
    return () => {
      active = false
      stopPolling()
      controller?.abort()
      document.removeEventListener('visibilitychange', onVisibilityChange)
    }
  }, [])

  const visibleMoments = compact ? moments.slice(0, 3) : moments
  const visibleLiveMoments = compact ? liveMoments.slice(0, 3) : liveMoments
  return (
    <section className={`lp-arcade-archive${compact ? ' lp-arcade-archive-compact' : ''}`} aria-labelledby={compact ? 'lp-hq-arcade-archive-title' : 'lp-arcade-archive-title'}>
      <div className="lp-arcade-live-moments">
        <h3>Live ESPN kicks</h3>
        {state === 'loading' ? <p role="status">Checking the live ESPN channel…</p>
          : state === 'unavailable' || !liveAvailable ? <p role="status">Live kick capture is unavailable for this snapshot.</p>
            : liveMoments.length === 0 ? <p>No fresh, verified field-goal attempts are available from an in-progress game.</p>
              : <ul>
                {visibleLiveMoments.map(moment => {
                  const context = moment.observed_context
                  const teams = `${context.away_team} at ${context.home_team}`
                  const situation = [context.period ? `Q${context.period}` : null, context.clock || null].filter(Boolean).join(' · ')
                  const publisherFreshness = moment.publisher_updated_at
                    ? ` · ESPN summary updated ${formatObservedAt(moment.publisher_updated_at)}`
                    : ' · ESPN summary update time unavailable'
                  return <li key={moment.challenge_id}>
                    <div>
                      <strong>{context.attempt_distance_yards} yd · {teams}</strong>
                      <small>LP observed {formatObservedAt(moment.last_observed_at_utc)}{publisherFreshness}{situation ? ` · ${situation}` : ''}</small>
                    </div>
                    <Link href={`/arcade/nfl/field-goal/${encodeURIComponent(moment.challenge_id)}`}>
                      Play kick
                    </Link>
                  </li>
                })}
              </ul>}
      </div>
      <h2 id={compact ? 'lp-hq-arcade-archive-title' : 'lp-arcade-archive-title'}>Archived ESPN kicks</h2>
      {!archiveLiveAvailable && <p role="status">Recent game-captured ESPN kicks are unavailable. Source-checked archive games remain listed when present.</p>}
      {state === 'loading' ? <p role="status">Loading verified archive challenges…</p>
        : state === 'unavailable' ? <p role="status">The archived challenge list is unavailable. Live moments are not being substituted.</p>
          : moments.length === 0 ? <p>No archived field-goal attempts have a published distance and stable source identity yet.</p>
            : <ul>
              {visibleMoments.map(moment => {
                const context = moment.observed_context
                const teams = `${context.away_team} at ${context.home_team}`
                const situation = [context.period ? `Q${context.period}` : null, context.clock || null].filter(Boolean).join(' · ')
                return <li key={moment.challenge_id}>
                  <div>
                    <strong>{context.attempt_distance_yards} yd · {teams}</strong>
                    <small>{formatDate(context.game_date)}{situation ? ` · ${situation}` : ''} · Archived ESPN play
                      {moment.last_observed_at_utc ? ` · LP observed ${formatObservedAt(moment.last_observed_at_utc)}` : ''}
                      {moment.publisher_updated_at ? ` · ESPN summary updated ${formatObservedAt(moment.publisher_updated_at)}` : ''}
                    </small>
                  </div>
                  <Link href={`/arcade/nfl/field-goal/${encodeURIComponent(moment.challenge_id)}`}>
                    Play kick
                  </Link>
                </li>
              })}
            </ul>}
    </section>
  )
}
