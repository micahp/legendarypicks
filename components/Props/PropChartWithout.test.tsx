import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import PropChart, { PropHistory } from './PropChart'

const base: PropHistory = {
  player_id: 1, player: 'P Receiver', team: 'NO', league: 'nfl', market: 'receiving_yards',
  line: 40.5, side: 'over', projection: 61, hit_rate: { l5: 0.6, l10: 0.6, l20: 0.6, season: 0.6 },
  games: [30, 50, 70, 90, 10].map((value, i) => ({
    date: `2025-10-0${i + 1}`, value, opponent: 'ATL', home: true, hit: value >= 40.5,
  })),
}

const filteredBody = (nGames: number, unknown: number) => ({
  ...base, projection: null, n_games: nGames, n_excluded_unknown: unknown, n_excluded_not_teammate: 0,
  games: [70, 90].slice(0, nGames).map((value, i) => ({
    date: `2025-10-0${i + 2}`, value, opponent: 'ATL', home: true, hit: true,
  })),
})

function mockFetch(handlers: Record<string, unknown>) {
  const calls: string[] = []
  ;(global as any).fetch = jest.fn((url: string) => {
    calls.push(url)
    const key = Object.keys(handlers).find(k => url.includes(k))
    return Promise.resolve({ ok: key !== undefined, json: () => Promise.resolve(key ? handlers[key] : {}) })
  })
  return calls
}

const teammatesBody = { teammates: [
  { player_id: 2, name: 'X Teammate', position: 'WR', games_out: 2 },
  { player_id: 3, name: 'Y Back', position: 'RB', games_out: 1 },
] }

afterEach(() => { window.history.replaceState(null, '', '/'); jest.restoreAllMocks() })

describe('PropChart Without control', () => {
  it('renders no control for a league without availability', () => {
    const calls = mockFetch({})
    const { container } = render(<PropChart data={{ ...base, league: 'nba' }} />)
    expect(container.querySelector('[data-without-control]')).toBeNull()
    expect(calls).toEqual([])
  })

  it('lists teammates as chips with their missed-game counts', async () => {
    mockFetch({ 'teammates-out': teammatesBody })
    render(<PropChart data={base} />)
    expect(await screen.findByText('X Teammate')).toBeTruthy()
    expect(screen.getByText('Y Back')).toBeTruthy()
  })

  it('refetches with without=, shows the sample, and writes the URL', async () => {
    const calls = mockFetch({ 'teammates-out': teammatesBody, 'api/props/history': filteredBody(2, 1) })
    const { container } = render(<PropChart data={base} />)
    fireEvent.click(await screen.findByText('X Teammate'))
    await waitFor(() => expect(container.querySelector('[data-without-sample]')?.textContent)
      .toContain('Without X Teammate: 2 games'))
    const text = container.querySelector('[data-without-sample]')!.textContent!
    expect(text).toContain('small sample')
    expect(text).toContain('1 game not counted, availability unknown')
    expect(calls.some(c => c.includes('api/props/history') && c.includes('without=2'))).toBe(true)
    expect(window.location.search).toBe('?without=2')
    // the drawn bars are the filtered games only
    expect(container.querySelector('[data-game-labels]')!.textContent).toContain('90')
    expect(container.querySelector('[data-game-labels]')!.textContent).not.toContain('30')
  })

  it('does not call a sample of five or more small', async () => {
    const big = { ...filteredBody(2, 0), n_games: 6 }
    mockFetch({ 'teammates-out': teammatesBody, 'api/props/history': big })
    const { container } = render(<PropChart data={base} />)
    fireEvent.click(await screen.findByText('X Teammate'))
    await waitFor(() => expect(container.querySelector('[data-without-sample]')?.textContent)
      .toContain('Without X Teammate: 6 games'))
    expect(container.querySelector('[data-without-sample]')!.textContent).not.toContain('small sample')
  })

  it('applies a shared ?without= for a listed teammate and ignores an unlisted one', async () => {
    window.history.replaceState(null, '', '/?without=3')
    const calls = mockFetch({ 'teammates-out': teammatesBody, 'api/props/history': filteredBody(2, 0) })
    render(<PropChart data={base} />)
    await waitFor(() => expect(calls.some(c => c.includes('without=3'))).toBe(true))
  })

  it('ignores a ?without= that is not one of this player\'s teammates', async () => {
    window.history.replaceState(null, '', '/?without=999')
    const calls = mockFetch({ 'teammates-out': teammatesBody })
    render(<PropChart data={base} />)
    await screen.findByText('X Teammate')
    expect(calls.filter(c => c.includes('api/props/history'))).toEqual([])
  })

  it('clicking the selected chip clears the filter and the URL', async () => {
    mockFetch({ 'teammates-out': teammatesBody, 'api/props/history': filteredBody(2, 0) })
    const { container } = render(<PropChart data={base} />)
    const chip = await screen.findByText('X Teammate')
    fireEvent.click(chip)
    await waitFor(() => expect(container.querySelector('[data-without-sample]')?.textContent).toContain('Without'))
    await act(async () => { fireEvent.click(screen.getByText('X Teammate')) })
    expect(container.querySelector('[data-without-sample]')).toBeNull()
    expect(window.location.search).toBe('')
  })

  it('says so when the filtered games cannot be loaded, instead of drawing the unfiltered ones as filtered', async () => {
    mockFetch({ 'teammates-out': teammatesBody })
    const { container } = render(<PropChart data={base} />)
    fireEvent.click(await screen.findByText('X Teammate'))
    await waitFor(() => expect(container.querySelector('[data-without-sample]')?.textContent)
      .toContain('Could not load'))
  })
})
