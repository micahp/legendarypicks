import React from 'react'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import NflModelTab from './NflModelTab'

const V1 = 'nfl-v1 half_life=6 cap=14.0 prior_games=4 prior_shrink=0.3333 sigma=13.295'
const V2 = 'nfl-epa-v2 pure per-play'

const line = { spread: -1.5, total: 45.5, home_moneyline: null, away_moneyline: null,
  captured_at: 't', source: 'snapshot' as const }
const lock = (pHome: number, grade: unknown) => ({
  proj_home: 21, proj_away: 24, margin: -3, total: 45, p_home_win: pHome, locked_at: 't', line, grade,
})

const payload = {
  season: 2026, week: 5, weeks: [5],
  models: [
    { version: V1, family: 'v1', label: 'v1 points', adopted: true, locks: 1 },
    { version: V2, family: 'v2', label: 'v2 EPA', adopted: false, locks: 1 },
  ],
  games: [{
    game_id: 'g1', week: 5, home: 'GB', away: 'CHI', neutral: false, kickoff_utc: '2026-10-11T17:00:00Z',
    final: { home: 20, away: 27 },
    locks: {
      [V1]: lock(0.19, { brier: 0.03, margin_err: 4.5, total_err: -1.3, ats: 'win', su: 'win' }),
      [V2]: lock(0.7, { brier: 0.5, margin_err: 11, total_err: 2, ats: 'loss', su: 'loss' }),
    },
  }],
  record: [
    { version: V1, family: 'v1', label: 'v1 points', adopted: true, locked: 13, graded: 12, awaiting: 1,
      su: { win: 8, loss: 3, tie: 1, no_pick: 0 }, ats: { win: 5, loss: 6, push: 1, no_pick: 0, no_line: 0 } },
    { version: V2, family: 'v2', label: 'v2 EPA', adopted: false, locked: 4, graded: 0, awaiting: 4,
      su: null, ats: null },
  ],
}

beforeEach(() => {
  ;(global as any).fetch = jest.fn(() => Promise.resolve({ ok: true, json: () => Promise.resolve(payload) }))
})

describe('NFL model tab grading', () => {
  it('shows counts, the third outcome, n and what is waiting, never a win rate', async () => {
    render(<NflModelTab />)
    fireEvent.click(await screen.findByRole('button', { name: 'Record' }))
    await waitFor(() => expect(screen.getByText('2026 record · v1 points')).toBeTruthy())
    expect(screen.getByText('Winner 8-3 · 1 tie')).toBeTruthy()
    expect(screen.getByText('ATS 5-6 · 1 push')).toBeTruthy()
    expect(screen.getByText('12 graded · 1 awaiting')).toBeTruthy()
    expect(document.body.textContent).not.toMatch(/\d%\s*(correct|right|winner)/i)
  })

  it('a model with no graded game says so instead of showing 0-0', async () => {
    render(<NflModelTab />)
    fireEvent.click(await screen.findByRole('button', { name: 'Record' }))
    fireEvent.change(await screen.findByRole('combobox', { name: /Model/ }), { target: { value: V2 } })
    await waitFor(() => expect(screen.getByText('2026 record · v2 EPA')).toBeTruthy())
    expect(screen.getByText('No graded picks yet · 4 awaiting a final')).toBeTruthy()
    expect(document.body.textContent).not.toContain('0-0')
  })

  it('each graded lock shows whether the pick won', async () => {
    render(<NflModelTab />)
    fireEvent.click(await screen.findByRole('button', { name: 'Record' }))
    await waitFor(() => expect(screen.getByText('WIN')).toBeTruthy())
  })

  it('a preview lock is shown as a projection without a result', async () => {
    const preview = { ...payload, games: [{ ...payload.games[0], locks: { [V1]: { ...lock(0.6, null), preview: true }, [V2]: { ...lock(0.6, null), preview: true } } }] }
    ;(global as any).fetch = jest.fn(() => Promise.resolve({ ok: true, json: () => Promise.resolve(preview) }))
    render(<NflModelTab />)
    await waitFor(() => expect(screen.getByText('CHI @ GB')).toBeTruthy())
    expect(screen.queryByText('LOCKED')).toBeNull()
    expect(screen.queryByText('WIN')).toBeNull()
  })
})
