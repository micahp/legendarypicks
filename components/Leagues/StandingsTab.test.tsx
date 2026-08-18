import React from 'react'
import { render, screen } from '@testing-library/react'
import StandingsTab from './StandingsTab'
import type { StandingGroup, StandingsSeason } from './types'

const liveSeason: StandingsSeason = {
  season: 2026, seasonLabel: '2026 MLS', phase: 'Regular Season',
  inProgress: true, asOf: '2026-08-17T23:52:30Z',
}

const mlsGroups: StandingGroup[] = [{
  group: 'Eastern Conference',
  rows: [{
    rank: 2, abbrev: 'MIA', name: 'Inter Miami CF', played: 18, wins: 11,
    draws: 5, losses: 2, gf: 45, ga: 32, gd: 13, points: 38,
  }],
}]

const ncaafGroups: StandingGroup[] = [{
  group: 'Sun Belt - East',
  rows: [{
    rank: null, abbrev: 'JMU', name: 'James Madison Dukes', played: null,
    wins: 0, draws: null, losses: null, gf: null, ga: null, gd: null, points: null,
  }],
}]

describe('grouped league standings', () => {
  it('renders MLS published draw and points columns', () => {
    render(
      <StandingsTab
        error={null}
        loading={false}
        isWorldCup={false}
        knockout={[]}
        groups={mlsGroups}
        teams={[]}
        leagueName="MLS"
        league="mls"
      />,
    )

    expect(screen.getByRole('heading', { name: 'Eastern Conference' })).toBeTruthy()
    expect(screen.getByRole('columnheader', { name: 'D' })).toBeTruthy()
    expect(screen.getByRole('columnheader', { name: 'Pts' })).toBeTruthy()
    expect(screen.getByText('5')).toBeTruthy()
    expect(screen.getByText('38')).toBeTruthy()
  })

  it('renders absent NCAAF publisher values as dashes instead of zeroes', () => {
    render(
      <StandingsTab
        error={null}
        loading={false}
        isWorldCup={false}
        knockout={[]}
        groups={ncaafGroups}
        teams={[]}
        leagueName="NCAAF"
        league="ncaaf"
      />,
    )

    expect(screen.getByRole('heading', { name: 'Sun Belt - East' })).toBeTruthy()
    expect(screen.getByRole('columnheader', { name: 'GP' })).toBeTruthy()
    expect(screen.queryByRole('columnheader', { name: 'Pts' })).toBeNull()
    expect(screen.getByText('0')).toBeTruthy()
    expect(screen.getAllByText('—')).toHaveLength(3)
  })
})

/**
 * Added 2026-08-17. MLS shipped the 2025 FINAL table in mid-August with nothing
 * on screen naming the season, so a finished table and a live one looked
 * identical. These assert the caption says which is which — and, in the third
 * case, that it declines to say when the publisher did not.
 */
describe('standings season caption', () => {
  const renderWith = (season?: StandingsSeason) => render(
    <StandingsTab
      error={null}
      loading={false}
      isWorldCup={false}
      knockout={[]}
      groups={mlsGroups}
      teams={[]}
      season={season}
      leagueName="MLS"
      league="mls"
    />,
  )

  it('names the season and says it is still being played', () => {
    renderWith(liveSeason)

    expect(screen.getByText('2026 MLS')).toBeTruthy()
    expect(screen.getByText('Regular Season')).toBeTruthy()
    expect(screen.getByText('in progress')).toBeTruthy()
    expect(screen.queryByText('final')).toBeNull()
  })

  it('marks a completed season final rather than implying it is live', () => {
    renderWith({ ...liveSeason, season: 2025, seasonLabel: '2025 MLS', inProgress: false })

    expect(screen.getByText('2025 MLS')).toBeTruthy()
    expect(screen.getByText('final')).toBeTruthy()
    expect(screen.queryByText('in progress')).toBeNull()
  })

  it('claims nothing when the publisher did not state the phase', () => {
    renderWith({ ...liveSeason, phase: null, inProgress: null })

    expect(screen.getByText('2026 MLS')).toBeTruthy()
    expect(screen.queryByText('in progress')).toBeNull()
    expect(screen.queryByText('final')).toBeNull()
  })

  it('renders no caption at all for a league that sends no season', () => {
    renderWith(undefined)

    expect(screen.getByRole('heading', { name: 'Eastern Conference' })).toBeTruthy()
    expect(screen.queryByText('in progress')).toBeNull()
    expect(screen.queryByText('final')).toBeNull()
  })
})
