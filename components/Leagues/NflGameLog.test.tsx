import { render, screen } from '@testing-library/react'

import { NflGameLog } from '../../pages/player/[id]'


describe('standalone NFL player game log', () => {
  it('uses published schedule venues for away markers and recovered labels', () => {
    render(
      <NflGameLog
        games={[
          {
            date: '2025-09-07',
            opponent: 'OLD',
            home: null,
            game_no: 1,
            stats: { cmp: 22, att: 31, carries: 8, fpts_ppr: 24.1 },
          },
          {
            date: '2025-09-14',
            opponent: 'OLD',
            home: null,
            game_no: 2,
            stats: { cmp: 24, att: 35, carries: 10, fpts_ppr: 27.2 },
          },
        ]}
        scheduleGames={[
          { week: 1, phase: 'regular', opponent: 'BAL', home: true },
          { week: 2, phase: 'regular', opponent: 'NYJ', home: false },
        ]}
      />,
    )

    expect(screen.getByText('Comp')).toBeTruthy()
    expect(screen.getByText('Att')).toBeTruthy()
    expect(screen.getByText('Car')).toBeTruthy()
    expect(screen.getByText('@ NYJ')).toBeTruthy()
    expect(screen.getByText('BAL')).toBeTruthy()
    expect(screen.queryByText('@ BAL')).toBeNull()
  })
})
