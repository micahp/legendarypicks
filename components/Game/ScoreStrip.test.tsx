import React from 'react'
import { render, screen } from '@testing-library/react'
import ScoreStrip from './ScoreStrip'

const baseProps = {
  ctx: { venue_name: '', venue_city: '', attendance: 0, officials: [], home_team: 'MIA', away_team: 'PUM' },
  score: { home: 1, away: 0 },
  homeName: 'Inter Miami CF',
  awayName: 'Pumas UNAM',
  homeRecord: '',
  awayRecord: '',
}

// The word LIVE was dropped wherever we can name the phase (Micah, 2026-08-17):
// a quarter number already means the game is in progress, and the badge is
// already coloured for live. It survives only when the phase is unknown, which
// is the 'falls back honestly' case below.
describe('ScoreStrip live status', () => {
  it('shows the publisher minute for a live soccer game', () => {
    render(<ScoreStrip {...baseProps} state="in" league="lcup" period={2} clock="67'" statusDetail="67'" />)
    expect(screen.getByText("67'")).toBeTruthy()
  })

  it('falls back honestly when the publisher clock is unavailable', () => {
    render(<ScoreStrip {...baseProps} state="in" />)
    expect(screen.getByText('LIVE')).toBeTruthy()
  })

  it('shows the kickoff time without repeating that the game is scheduled', () => {
    const startTime = '2026-10-10T19:30:00Z'
    const localTime = new Date(startTime).toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' })
    render(<ScoreStrip {...baseProps} state="pre" startTime={startTime} statusDetail="Scheduled" />)
    expect(screen.getByText(localTime)).toBeTruthy()
    expect(screen.queryByText(/scheduled/i)).toBeNull()
  })

  it('keeps the publisher inning state instead of ESPN\'s live 0:00 placeholder', () => {
    render(<ScoreStrip {...baseProps} state="in" league="mlb" period={6} clock="0:00" statusDetail="Top 6th" />)
    expect(screen.getByText('Top 6th')).toBeTruthy()
    expect(screen.queryByText('0:00')).toBeNull()
  })

  it('shows the NFL running clock and ordinal quarter', () => {
    render(<ScoreStrip {...baseProps} state="in" league="nfl" period={4} clock="1:51" statusDetail="1:51 - 4th" />)
    expect(screen.getByText('01:51 - 4th')).toBeTruthy()
  })

  it('shows football overtime as OT rather than a fifth quarter', () => {
    render(<ScoreStrip {...baseProps} state="in" league="ncaaf" period={5} clock="7:31" statusDetail="7:31 - OT" />)
    expect(screen.getByText('07:31 - OT')).toBeTruthy()
  })

  it('recovers the football period from publisher wording when the period number is missing', () => {
    render(<ScoreStrip {...baseProps} state="in" league="nfl" statusDetail="0:00 - 3rd" />)
    expect(screen.getByText('00:00 - 3rd')).toBeTruthy()
  })

  it('treats final state aliases as finished instead of scheduled', () => {
    render(<ScoreStrip {...baseProps} state="final" league="nfl" statusDetail="Final" />)
    expect(screen.getByText('Final')).toBeTruthy()
  })

  it('labels a finished soccer match Full Time', () => {
    render(<ScoreStrip {...baseProps} state="post" league="mls" statusDetail="Final" />)
    expect(screen.getByText('FULL TIME')).toBeTruthy()
  })
})

describe('ScoreStrip postponed match', () => {
  it('labels it postponed and shows no 0-0', () => {
    const { container } = render(<ScoreStrip ctx={null} score={{ away: 0, home: 0 }} state="post"
      league="mls" statusDetail="Postponed" homeName="Red Bull New York" awayName="St. Louis CITY SC"
      homeRecord="" awayRecord="" />)
    expect(screen.getByText('POSTPONED')).toBeTruthy()
    expect(container.textContent).not.toContain('0')
  })
})

describe('ScoreStrip preseason label', () => {
  it('labels a preseason game', () => {
    render(<ScoreStrip ctx={null} score={null} state="pre" league="nba" statusDetail="10/3 - 7:00 PM EDT"
      isPreseason homeName="Toronto Raptors" awayName="Miami Heat" homeRecord="" awayRecord="" />)
    expect(screen.getByText('Preseason')).toBeTruthy()
  })
})
