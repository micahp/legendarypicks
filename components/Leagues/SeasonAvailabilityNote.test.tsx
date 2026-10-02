import { render, screen } from '@testing-library/react'
import SeasonAvailabilityNote from './SeasonAvailabilityNote'
import type { LeagueReadiness } from '../../lib/leagueReadiness'

const readiness = (phase: string, status: string): LeagueReadiness => ({
  league: 'nhl',
  status: 'degraded',
  phase,
  expected_season: 2027,
  reasons: [],
  checks: { player_stats: { status: status as any, count: 0 } },
})

describe('SeasonAvailabilityNote', () => {
  it('labels current NHL preseason stats as pending without hiding history', () => {
    render(<SeasonAvailabilityNote league="nhl" readiness={readiness('preseason', 'pending')} />)
    expect(screen.getByText('2026-27 regular-season stats are not available yet.')).toBeTruthy()
    expect(screen.getByText('Historical seasons remain available below.')).toBeTruthy()
  })

  it('renders nothing once current stats are available', () => {
    const { container } = render(
      <SeasonAvailabilityNote league="nhl" readiness={readiness('regular_season', 'available')} />,
    )
    expect(container.innerHTML).toBe('')
  })
})
