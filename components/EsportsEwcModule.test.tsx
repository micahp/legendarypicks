import React from 'react'
import { render, screen, fireEvent } from '@testing-library/react'
import { EwcModule, ClubStandingsRail, EwcMatchRow } from './Esports/EwcModule'
import GameCard from './Scores/GameCard'

jest.mock('next/router', () => ({ useRouter: () => ({ push: jest.fn(), query: {} }) }))

const baseMatch = {
  startTime: Date.UTC(2026, 7, 8, 18, 0),
  endTime: null,
  live: false,
  finished: false,
  title: 'Call of Duty',
  league: 'Esports World Cup',
  teamA: 'Team Falcons',
  teamB: 'Gentle Mates',
  favorite: null,
  watch: null,
  ewcEventId: 'ewc-2026',
}

const standings = (status: 'current' | 'stale' | 'unavailable' = 'current') => ({
  event: 'ewc-2026',
  status,
  asOf: status === 'unavailable' ? null : '2026-08-08T12:00:00+00:00',
  source: status === 'unavailable' ? null : { label: 'EWC Official', url: 'https://example.invalid' },
  standings: status === 'unavailable' ? [] : [
    { rank: 1, clubId: 'team-falcons', clubName: 'Team Falcons', logo: null, points: 2600, eligibleTopEightCount: null, titleWins: null, eligibleToWin: null, movement: null },
    { rank: 2, clubId: 'natus-vincere', clubName: 'Natus Vincere', logo: null, points: 2250, eligibleTopEightCount: null, titleWins: null, eligibleToWin: null, movement: null },
    { rank: 3, clubId: 'zero-club', clubName: 'Zero Club', logo: null, points: 0, eligibleTopEightCount: null, titleWins: null, eligibleToWin: null, movement: null },
    { rank: 4, clubId: 'unknown-club', clubName: 'Unknown Club', logo: null, points: null, eligibleTopEightCount: null, titleWins: null, eligibleToWin: null, movement: null },
  ],
})

describe('EWC standings rail', () => {
  it('renders the honest unavailable state — no table, no zeros', () => {
    render(<ClubStandingsRail standings={standings('unavailable')} onExpand={() => {}} expanded={false} loading={false} />)
    expect(screen.getByText('Standings unavailable')).toBeTruthy()
    expect(screen.queryByText('Team Falcons')).toBeNull()
    expect(screen.queryByText('0')).toBeNull()
  })

  it('renders top rows with tabular points and source', () => {
    render(<ClubStandingsRail standings={standings('current')} onExpand={() => {}} expanded={false} loading={false} />)
    expect(screen.getByText('Team Falcons')).toBeTruthy()
    expect(screen.getByText('2600')).toBeTruthy()
    expect(screen.getByText('EWC Official')).toBeTruthy()
  })

  it('distinguishes a real zero from unknown (em dash)', () => {
    render(<ClubStandingsRail standings={standings('current')} onExpand={() => {}} expanded={false} loading={false} />)
    expect(screen.getByText('0')).toBeTruthy()          // real zero
    expect(screen.getByText('–')).toBeTruthy()           // unknown -> em dash
  })

  it('shows a visible stale badge without a tooltip', () => {
    render(<ClubStandingsRail standings={standings('stale')} onExpand={() => {}} expanded={false} loading={false} />)
    expect(screen.getByText('Stale')).toBeTruthy()
  })

  it('shows the expand action only when collapsed', () => {
    const { container } = render(<ClubStandingsRail standings={standings('current')} onExpand={() => {}} expanded={false} loading={false} />)
    expect(screen.getByText('Show full top ten →')).toBeTruthy()
  })

  it('loading skeleton while fetching', () => {
    render(<ClubStandingsRail standings={null} onExpand={() => {}} expanded={false} loading />)
    expect(screen.getByText('Club Championship')).toBeTruthy()
  })

  it('renders a compact logo image with alt text when the row has a verified logo', () => {
    const withLogo = standings('current')
    withLogo.standings = [
      { rank: 1, clubId: 'team-falcons', clubName: 'Team Falcons', logo: 'https://example.invalid/falcons.png', points: 2600, eligibleTopEightCount: null, titleWins: null, eligibleToWin: null, movement: null },
      { rank: 2, clubId: 'natus-vincere', clubName: 'Natus Vincere', logo: 'https://example.invalid/navi.png', points: 2250, eligibleTopEightCount: null, titleWins: null, eligibleToWin: null, movement: null },
    ]
    render(<ClubStandingsRail standings={withLogo} onExpand={() => {}} expanded={false} loading={false} />)
    const imgs = screen.getAllByAltText(/logo/)
    expect(imgs).toHaveLength(2)
    expect(imgs[0].getAttribute('src')).toBe('https://example.invalid/falcons.png')
    expect(imgs[0].getAttribute('width')).toBe('20')
    expect(imgs[0].getAttribute('referrerpolicy')).toBe('no-referrer')
    expect(screen.queryByText('TF')).toBeNull()
  })

  it('renders a neutral initials fallback when no logo exists', () => {
    const noLogo = standings('current')  // fixture rows carry logo: null
    render(<ClubStandingsRail standings={noLogo} onExpand={() => {}} expanded={false} loading={false} />)
    expect(screen.getByText('TF')).toBeTruthy()   // Team Falcons
    expect(screen.getByText('NV')).toBeTruthy()   // Natus Vincere
    expect(document.querySelectorAll('img')).toHaveLength(0)
  })

  it('falls back to initials when the logo image fails to load', () => {
    const withLogo = standings('current')
    withLogo.standings = [
      { rank: 1, clubId: 'team-falcons', clubName: 'Team Falcons', logo: 'https://example.invalid/broken.png', points: 2600, eligibleTopEightCount: null, titleWins: null, eligibleToWin: null, movement: null },
    ]
    render(<ClubStandingsRail standings={withLogo} onExpand={() => {}} expanded={false} loading={false} />)
    const img = screen.getByAltText('Team Falcons logo')
    fireEvent.error(img)
    expect(screen.queryByAltText('Team Falcons logo')).toBeNull()
    expect(screen.getByText('TF')).toBeTruthy()
  })
})

describe('EWC module', () => {
  it('renders the EWC focus header and today’s slate when active', () => {
    const eventData = {
      eventId: 'ewc-2026',
      eventName: 'Esports World Cup 2026',
      active: true,
      asOf: '2026-08-08T12:00:00+00:00',
      matches: {
        live: [],
        upcoming: [{ ...baseMatch, teamA: 'FaZe Clan', teamB: 'OpTic Gaming' }],
        completed: [{ ...baseMatch, startTime: Date.UTC(2026, 7, 8, 13, 0), finished: true, teamA: 'G2 Esports', teamB: 'Team Heretics', score: { a: 3, b: 4 } }],
      },
    }
    render(<EwcModule eventData={eventData as any} host="localhost" standings={standings('current')} standingsLimit={10} onExpandStandings={() => {}} standingsLoading={false} />)
    expect(screen.getByText('EWC 2026')).toBeTruthy()
    expect(screen.getByText('Esports World Cup 2026')).toBeTruthy()
    expect(screen.getByText('FaZe Clan')).toBeTruthy()
    expect(screen.getByText('OpTic Gaming')).toBeTruthy()
    // results row with score
    expect(screen.getByText('Team Heretics')).toBeTruthy()
  })
})

describe('GameCard pending participants', () => {
  const game = (away: any) => ({
    gameId: 'BP-356983',
    detailGameId: '1609946',
    league: 'COD',
    homeTeam: { teamId: 'HTCS', name: 'Team Heretics', label: 'Team Heretics' },
    awayTeam: away,
    startTime: new Date(Date.UTC(2026, 7, 9, 13, 0)).toISOString(),
    status: 'SCHEDULED' as const,
  })

  it('renders a bracket dependency label for an undecided slot, not a score', () => {
    render(<GameCard {...game({ teamId: '', name: '', label: 'Winner of Team Falcons–Gentle Mates', pending: true })} />)
    expect(screen.getByText('Winner of Team Falcons–Gentle Mates')).toBeTruthy()
    expect(screen.queryByText('TBD')).toBeNull()
    expect(screen.queryByText('0')).toBeNull()
  })

  it('renders Participant unavailable for an unresolvable side', () => {
    render(<GameCard {...game({ teamId: '', name: '', label: 'Participant unavailable', unavailable: true })} />)
    expect(screen.getByText('Participant unavailable')).toBeTruthy()
  })

  it('keeps the decided side clickable via its detail id', () => {
    // The card is clickable when the match has a detail id; the pending side still renders.
    const { container } = render(<GameCard {...game({ teamId: '', name: '', label: 'Winner of Team Falcons–Gentle Mates', pending: true })} />)
    expect(container.querySelector('.cursor-pointer')).toBeTruthy()
  })

  it('never renders a raw TBD/TBA string next to a dependency label', () => {
    render(<GameCard {...game({ teamId: '', name: '', label: 'Winner of Team Falcons–Gentle Mates', pending: true })} />)
    expect(screen.getByText('Winner of Team Falcons–Gentle Mates')).toBeTruthy()
    expect(screen.queryByText('TBD')).toBeNull()
    expect(screen.queryByText('TBA')).toBeNull()
  })
})
