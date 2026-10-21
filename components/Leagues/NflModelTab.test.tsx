import React from 'react'
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import NflModelTab from './NflModelTab'

const V1 = 'nfl-v1 half_life=6 cap=14.0 prior_games=4 prior_shrink=0.3333 sigma=13.295'
const V2 = 'nfl-epa-v2 pure per-play'

const line = { spread: -1.5, total: 45.5, home_moneyline: null, away_moneyline: null,
  captured_at: 't', source: 'snapshot' as const }

// Model Picks as the backend returns them. The label is what the card must show.
const chiPick = { market: 'spread', side: 'away', line: -1.5, rule: 1, status: 'pick', label: 'CHI -1.5' }
const gbPick = { market: 'ml', side: 'home', line: null, rule: 2, status: 'pick', label: 'GB ML' }

const lock = (pick: unknown, grade: unknown) => ({
  proj_home: 21, proj_away: 24, margin: -3, total: 45, p_home_win: 0.19, locked_at: 't', line, grade, pick,
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
      [V1]: lock(chiPick, { brier: 0.03, margin_err: 4.5, total_err: -1.3, su: 'loss', pick: 'win' }),
      [V2]: lock(gbPick, { brier: 0.5, margin_err: 11, total_err: 2, su: 'loss', pick: 'loss' }),
    },
  }],
  record: [
    { version: V1, family: 'v1', label: 'v1 points', adopted: true, locked: 13, graded: 12, awaiting: 1,
      su: { win: 8, loss: 3, tie: 1, no_pick: 0 },
      pick: { win: 5, loss: 4, push: 1, no_pick: 1, no_line: 1 },
      mean_brier: 0.1425, brier_n: 11 },
    { version: V2, family: 'v2', label: 'v2 EPA', adopted: false, locked: 4, graded: 0, awaiting: 4,
      su: null, pick: null, mean_brier: null, brier_n: 0 },
  ],
}

const withGames = (games: unknown[]) => ({ ...payload, games })

beforeEach(() => {
  ;(global as any).fetch = jest.fn(() => Promise.resolve({ ok: true, json: () => Promise.resolve(payload) }))
})

describe('NFL model tab', () => {
  it('shows Brier scores with the actual scored sample size and an absent state', async () => {
    render(<NflModelTab />)
    fireEvent.click(await screen.findByRole('button', { name: 'Model accuracy' }))
    expect(screen.getByRole('tooltip')).toBeTruthy()
    expect(screen.getByText('0.1425')).toBeTruthy()
    expect(screen.getByText('11')).toBeTruthy()
    expect(screen.getByText('Brier n')).toBeTruthy()
    expect(screen.getAllByText('—')).toHaveLength(1)
    expect(screen.getByText(/0.2500 is a constant 50% forecast/)).toBeTruthy()
  })

  it('labels a preview quote as current and a past unlocked game as a missed lock', async () => {
    const missed = { ...payload.games[0], game_id: 'g-missed', away: 'MIN', home: 'DET', kickoff_utc: '2026-10-01T17:00:00Z',
      final: { home: 17, away: 10 }, locks: { [V1]: { ...lock(chiPick, null), preview: true } } }
    const noForecast = { ...missed, game_id: 'g-no-forecast', away: 'PIT', home: 'BAL', locks: {} }
    ;(global as any).fetch = jest.fn(() => Promise.resolve({
      ok: true, json: () => Promise.resolve(withGames([...payload.games, missed, noForecast])),
    }))
    render(<NflModelTab />)
    await screen.findByRole('region', { name: 'Missed lock window' })
    expect(screen.getByText('MIN @ DET')).toBeTruthy()
    expect(screen.getByText('PIT @ BAL')).toBeTruthy()
    expect(screen.getByText('Line')).toBeTruthy()
    expect(screen.getByText('Total')).toBeTruthy()
    expect(screen.getByText('Model total')).toBeTruthy()
    expect(screen.getByText('Total edge')).toBeTruthy()
    expect(screen.getByText(/snapshot · captured t/)).toBeTruthy()
    expect(screen.getAllByText('No forecast locked before kickoff · 2026-10-01T17:00:00Z')).toHaveLength(2)
  })

  it('the record header shows the Model Pick W-L-P, straight-up and Brier as model metrics', async () => {
    render(<NflModelTab />)
    fireEvent.click(await screen.findByRole('button', { name: 'Record' }))
    await waitFor(() => expect(screen.getByText('2026 record · v1 points')).toBeTruthy())
    expect(screen.getByText('Model Pick 5-4-1')).toBeTruthy()
    expect(screen.getByText('1 no pick')).toBeTruthy()
    expect(screen.getByText('1 no line')).toBeTruthy()
    expect(screen.getByText('Straight-up 8-3 · 1 tie')).toBeTruthy()
    expect(screen.getByText('Brier 0.1425 · n 11')).toBeTruthy()
    expect(screen.getByText('12 graded · 1 awaiting')).toBeTruthy()
    expect(screen.queryByText(/^Winner/)).toBeNull()
    expect(screen.queryByText(/^Spread/)).toBeNull()
    expect(screen.queryByText(/^Total \d/)).toBeNull()
    expect(document.body.textContent).not.toMatch(/\d%\s*(correct|right|winner)/i)
  })

  it('a model with no graded game says so instead of showing 0-0', async () => {
    render(<NflModelTab />)
    fireEvent.click(await screen.findByRole('button', { name: 'Record' }))
    fireEvent.change(await screen.findByRole('combobox', { name: /Model/ }), { target: { value: V2 } })
    await waitFor(() => expect(screen.getByText('2026 record · v2 EPA')).toBeTruthy())
    expect(screen.getByText('No graded picks yet · 4 awaiting a final')).toBeTruthy()
    expect(await screen.findByText('Line · snapshot · captured t')).toBeTruthy()
    expect(document.body.textContent).not.toContain('0-0')
  })

  it('a preview lock is shown as a projection without a result', async () => {
    const preview = withGames([{ ...payload.games[0], kickoff_utc: new Date(Date.now() + 3_600_000).toISOString(),
      locks: { [V1]: { ...lock(chiPick, null), preview: true }, [V2]: { ...lock(gbPick, null), preview: true } } }])
    ;(global as any).fetch = jest.fn(() => Promise.resolve({ ok: true, json: () => Promise.resolve(preview) }))
    render(<NflModelTab />)
    await waitFor(() => expect(screen.getByText('CHI @ GB')).toBeTruthy())
    expect(screen.queryByText('PREVIEW')).toBeNull()
    expect(screen.queryByText('UNLOCKED')).toBeNull()
    expect(screen.getByText('Line')).toBeTruthy()
    expect(screen.getByText('Total')).toBeTruthy()
    expect(screen.queryByText('Current line')).toBeNull()
    expect(screen.queryByText('LOCKED')).toBeNull()
    expect(screen.queryByText('WIN')).toBeNull()
  })

  it('does not label a legacy lock timestamp as a market capture time', async () => {
    const legacy = withGames([{ ...payload.games[0], locks: {
      [V1]: { ...payload.games[0].locks[V1], line: { ...line, source: 'lock row' as const } },
    } }])
    ;(global as any).fetch = jest.fn(() => Promise.resolve({ ok: true, json: () => Promise.resolve(legacy) }))
    render(<NflModelTab />)
    expect(await screen.findByText('Line · lock row · captured t')).toBeTruthy()
  })

  it('shows exactly one Model Pick per game: the backend label and its grade, with no winner, spread or total grid', async () => {
    render(<NflModelTab />)
    const heading = await screen.findByText('Model Pick')
    const block = heading.parentElement as HTMLElement
    expect(within(block).getByText('CHI -1.5')).toBeTruthy()
    expect(within(block).getByText('WIN')).toBeTruthy()
    expect(screen.getAllByText('Model Pick')).toHaveLength(1)
    expect(screen.queryByText('Winner pick')).toBeNull()
    expect(screen.queryByText('Spread pick')).toBeNull()
    expect(screen.queryByText('Total pick')).toBeNull()
    expect(screen.queryByText('Under 45.5')).toBeNull()
    expect(document.body.textContent).not.toMatch(/qualifying wager|lean/i)
  })

  it('shows the backend label verbatim, never a side worked out from the line in the browser', async () => {
    const odd = { market: 'spread', side: 'home', line: -1.5, rule: 1, status: 'pick', label: 'KC -9' }
    ;(global as any).fetch = jest.fn(() => Promise.resolve({
      ok: true, json: () => Promise.resolve(withGames([{ ...payload.games[0], locks: { [V1]: lock(odd, null) } }])),
    }))
    render(<NflModelTab />)
    const block = (await screen.findByText('Model Pick')).parentElement as HTMLElement
    expect(within(block).getByText('KC -9')).toBeTruthy()
    expect(within(block).queryByText('GB -1.5')).toBeNull()
  })

  it('a no-pick lock shows the backend label No pick and its NO PICK grade', async () => {
    const noPick = { market: null, side: null, line: null, rule: 5, status: 'no_pick', label: 'No pick' }
    ;(global as any).fetch = jest.fn(() => Promise.resolve({
      ok: true, json: () => Promise.resolve(withGames([{ ...payload.games[0], locks: {
        [V1]: lock(noPick, { brier: 0.03, margin_err: 4.5, total_err: -1.3, su: 'win', pick: 'no_pick' }),
      } }])),
    }))
    render(<NflModelTab />)
    const block = (await screen.findByText('Model Pick')).parentElement as HTMLElement
    expect(within(block).getByText('No pick')).toBeTruthy()
    expect(within(block).getByText('NO PICK')).toBeTruthy()
  })

  it('a lock with no usable spread shows No line and its NO LINE grade', async () => {
    const noLine = { market: null, side: null, line: null, rule: null, status: 'no_line', label: 'No line' }
    ;(global as any).fetch = jest.fn(() => Promise.resolve({
      ok: true, json: () => Promise.resolve(withGames([{ ...payload.games[0], locks: {
        [V1]: { ...lock(noLine, { brier: 0.03, margin_err: 4.5, total_err: -1.3, su: 'win', pick: 'no_line' }),
          line: { ...line, spread: null } },
      } }])),
    }))
    render(<NflModelTab />)
    const block = (await screen.findByText('Model Pick')).parentElement as HTMLElement
    expect(within(block).getByText('No line')).toBeTruthy()
    expect(within(block).getByText('NO LINE')).toBeTruthy()
  })

  it('the record cards show each graded Model Pick result', async () => {
    render(<NflModelTab />)
    fireEvent.click(await screen.findByRole('button', { name: 'Record' }))
    await waitFor(() => expect(screen.getByText('2026 record · v1 points')).toBeTruthy())
    await waitFor(() => expect(screen.getAllByText('WIN').length).toBeGreaterThanOrEqual(1))
    expect(screen.queryByText('LOSS')).toBeNull()
  })

  it('renders the exact label the backend returned for a home pick', async () => {
    const homePick = { market: 'spread', side: 'home', line: -1.5, rule: 1, status: 'pick', label: 'GB +1.5' }
    ;(global as any).fetch = jest.fn(() => Promise.resolve({
      ok: true, json: () => Promise.resolve(withGames([{ ...payload.games[0], locks: { [V1]: lock(homePick, null) } }])),
    }))
    render(<NflModelTab />)
    expect(await screen.findByText('GB +1.5')).toBeTruthy()
  })
})
