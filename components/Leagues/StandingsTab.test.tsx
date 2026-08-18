import React from 'react'
import { render, screen, fireEvent } from '@testing-library/react'
import StandingsTab from './StandingsTab'
import type { StandingGroup } from './types'

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


describe('standings season picker', () => {
  const renderWith = (props: Partial<{
    season: number | null
    availableSeasons: number[]
    onSelectSeason: (s: number) => void
  }>) => render(
    <StandingsTab
      error={null}
      loading={false}
      isWorldCup={false}
      knockout={[]}
      groups={mlsGroups}
      teams={[]}
      leagueName="MLS"
      league="mls"
      {...props}
    />,
  )

  it('offers the publisher’s seasons and reports the pick', () => {
    const onSelectSeason = jest.fn()
    renderWith({ season: 2026, availableSeasons: [2026, 2025, 2024], onSelectSeason })

    const select = screen.getByLabelText('Season') as HTMLSelectElement
    expect(select.value).toBe('2026')
    expect(screen.getByRole('option', { name: '2024' })).toBeTruthy()

    fireEvent.change(select, { target: { value: '2024' } })
    expect(onSelectSeason).toHaveBeenCalledWith(2024)
  })

  it('states the year without a control when only one season is offered', () => {
    // A standings table whose season is unstated is the defect; the missing
    // control is not. One year renders as a static pill.
    renderWith({ season: 2026, availableSeasons: [2026], onSelectSeason: jest.fn() })
    const season = screen.getByLabelText('Season')
    expect(season.tagName).toBe('SPAN')
    expect(season.textContent).toBe('2026')
  })

  it('renders no picker for a league that sends no season list', () => {
    renderWith({})
    expect(screen.queryByLabelText('Season')).toBeNull()
    expect(screen.getByRole('heading', { name: 'Eastern Conference' })).toBeTruthy()
  })
})
