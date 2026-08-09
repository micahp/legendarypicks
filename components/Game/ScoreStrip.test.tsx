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
    render(<ScoreStrip {...baseProps} state="in" statusDetail="67'" />)
    expect(screen.getByText("67'")).toBeTruthy()
    expect(screen.queryByText('LIVE')).toBeNull()
  })

  it('falls back honestly when the publisher clock is unavailable', () => {
    render(<ScoreStrip {...baseProps} state="in" />)
    expect(screen.getByText('LIVE')).toBeTruthy()
  })
})
