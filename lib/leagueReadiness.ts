export type ReadinessCheckStatus =
  | 'ready'
  | 'available'
  | 'missing'
  | 'stale'
  | 'pending'
  | 'unverified'
  | 'not_applicable'

export type ReadinessCheck = {
  status: ReadinessCheckStatus
  count?: number | null
  reason?: string
  season?: number | null
  refreshed_at?: string | null
}

export type LeagueReadiness = {
  league: string
  status: 'ready' | 'degraded' | 'attention' | 'offseason' | 'between_events' | 'unverified'
  phase: string
  expected_season: number | null
  season_start?: string
  season_end?: string
  reasons: string[]
  checks: Record<string, ReadinessCheck>
}

export type LeagueReadinessPayload = {
  contract: 'league-readiness-v1'
  as_of: string
  warnings: Array<{
    league: string
    code: string
    message: string
    starts_on?: string
    days_until_start?: number
  }>
  leagues: LeagueReadiness[]
}

export function nflHomepageCampaign(readiness?: LeagueReadiness | null) {
  switch (readiness?.phase) {
    case 'preseason':
      return {
        title: 'NFL Preseason',
        description: 'Track roster battles, preseason games, player news and draft preparation.',
        href: '/leagues/nfl',
      }
    case 'regular_season':
      return {
        title: 'NFL Season',
        description: 'Follow weekly scores, player performance, props and settled results.',
        href: '/leagues/nfl',
      }
    case 'postseason':
      return {
        title: 'NFL Playoffs',
        description: 'Follow the playoff schedule, scores, player props and settled results.',
        href: '/leagues/nfl',
      }
    default:
      return {
        title: 'NFL',
        description: 'Scores, player performance, props and league coverage.',
        href: '/leagues/nfl',
      }
  }
}
