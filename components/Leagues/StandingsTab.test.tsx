import React from 'react'
import { render, screen } from '@testing-library/react'
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
