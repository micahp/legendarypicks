import { render, screen } from '@testing-library/react'

import LeagueGameLog from './LeagueGameLog'

const GAME = {
  date: '2026-08-24',
  opponent: 'SEA',
  home: true,
  stats: {
    goals: 0,
    assists: 0,
    shots: 2,
    sot: 1,
    saves: 5,
    shots_faced: 7,
    goals_conceded: 2,
  },
}

it('uses goalkeeper columns for a soccer identity in any competition', () => {
  render(
    <LeagueGameLog
      games={[GAME]}
      league="lcup"
      identityLeague="mls"
      position="G"
      positionGroup="Goalkeeper"
    />,
  )

  expect(screen.getByRole('columnheader', { name: 'SV' })).toBeTruthy()
  expect(screen.getByRole('columnheader', { name: 'SF' })).toBeTruthy()
  expect(screen.getByRole('columnheader', { name: 'GA' })).toBeTruthy()
  expect(screen.queryByRole('columnheader', { name: 'SH' })).toBeNull()
})

it('uses outfield columns only when position_group is not goalkeeper', () => {
  render(
    <LeagueGameLog
      games={[GAME]}
      league="mls"
      identityLeague="mls"
      position="F"
      positionGroup="Forward"
    />,
  )

  expect(screen.getByRole('columnheader', { name: 'SH' })).toBeTruthy()
  expect(screen.queryByRole('columnheader', { name: 'SV' })).toBeNull()
})

it('does not guess a soccer role when position_group is unavailable', () => {
  render(
    <LeagueGameLog
      games={[GAME]}
      league="mls"
      identityLeague="mls"
      position="G"
      positionGroup={null}
    />,
  )

  expect(screen.queryByRole('columnheader', { name: 'SH' })).toBeNull()
  expect(screen.queryByRole('columnheader', { name: 'SV' })).toBeNull()
  expect(screen.getByRole('columnheader', { name: 'G' })).toBeTruthy()
})

it('states when an older goalkeeper context has appearances but no keeper stats', () => {
  render(
    <LeagueGameLog
      games={[{ ...GAME, stats: { goals: 0, shots: 0 } }]}
      league="mls"
      identityLeague="mls"
      position="G"
      positionGroup="Goalkeeper"
    />,
  )

  expect(screen.getByText('No goalkeeping stats on file for this competition and year.')).toBeTruthy()
  expect(screen.queryByRole('columnheader', { name: 'SH' })).toBeNull()
})
