import React from 'react'
import { render, screen } from '@testing-library/react'
import { GameCard } from './NflModelTab'

const game = {
  game_id: '2026_06_SEA_DEN', week: 6, home: 'DEN', away: 'SEA', neutral: false,
  kickoff_utc: '2026-10-16T00:15:00Z', final: null, locks: {},
}

const preview = {
  preview: true, proj_home: 21.4, proj_away: 22.8, margin: -1.4, total: 44.2, p_home_win: 0.46,
  locked_at: null, previewed_at: '2026-10-14T12:39:00Z', grade: null,
  line: { spread: -2.5, total: null, home_moneyline: null, away_moneyline: null, captured_at: null, source: 'lock row' },
}

const graded = {
  ...preview, preview: false, locked_at: '2026-10-15T22:45:00Z', previewed_at: null,
  grade: { brier: 0.2, margin_err: 3.1, total_err: 1.0, ats: 'win', su: 'win' },
}

describe('NFL game card', () => {
  it('a preview shows the projected scores with no status label, and no final', () => {
    render(<GameCard game={game as any} lock={preview as any} mode="projection" />)
    expect(screen.queryByText('NOT LOCKED')).toBeNull()
    expect(screen.queryByText('LOCKED')).toBeNull()
    expect(screen.getByText('22.8')).toBeTruthy()
    expect(screen.queryByText('Final')).toBeNull()
  })

  it('a graded pick in the record shows the final and the result', () => {
    const finished = { ...game, final: { home: 21, away: 27 } }
    render(<GameCard game={finished as any} lock={graded as any} mode="record" />)
    expect(screen.getByText('WIN')).toBeTruthy()
    expect(screen.getByText('Final')).toBeTruthy()
    expect(screen.getByText('27.0')).toBeTruthy()
  })
})
