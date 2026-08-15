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

describe('ScoreStrip live status', () => {
  it('shows the publisher minute for a live soccer game', () => {
    render(<ScoreStrip {...baseProps} state="in" league="lcup" period={2} clock="67'" statusDetail="67'" />)
    expect(screen.getByText("LIVE · 2nd Half · 67'")).toBeTruthy()
  })

  it('falls back honestly when the publisher clock is unavailable', () => {
    render(<ScoreStrip {...baseProps} state="in" />)
    expect(screen.getByText('LIVE')).toBeTruthy()
  })

  it('keeps the publisher inning state instead of ESPN\'s live 0:00 placeholder', () => {
    render(<ScoreStrip {...baseProps} state="in" league="mlb" period={6} clock="0:00" statusDetail="Top 6th" />)
    expect(screen.getByText('LIVE · Top 6th')).toBeTruthy()
    expect(screen.queryByText('0:00')).toBeNull()
  })

  it('shows both the NFL quarter and running clock', () => {
    render(<ScoreStrip {...baseProps} state="in" league="nfl" period={4} clock="1:51" statusDetail="1:51 - 4th" />)
    expect(screen.getByText('LIVE · Q4 · 1:51')).toBeTruthy()
  })
})
