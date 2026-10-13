import { render, screen } from '@testing-library/react'

import SeasonStatsSection from './SeasonStatsSection'

it('renders NHL goaltending totals with goalie-specific labels', () => {
  render(
    <SeasonStatsSection
      league="nhl"
      seasonStats={{
        window: '2027',
        games: 1,
        stats: {
          saves: 32,
          shots_against: 36,
          goals_against: 4,
          save_pct: 88.9,
          gaa: 4.01,
          shutouts: 0,
          wins: 0,
          losses: 1,
          ot_losses: 0,
          games_started: 1,
        },
      }}
    />,
  )

  expect(screen.getByText('Saves')).toBeTruthy()
  expect(screen.getByText('Shots Against')).toBeTruthy()
  expect(screen.getByText('Goals Against')).toBeTruthy()
  expect(screen.getByText('Save %')).toBeTruthy()
  expect(screen.getByText('88.9%')).toBeTruthy()
  expect(screen.queryByText('Goals')).toBeNull()
})
