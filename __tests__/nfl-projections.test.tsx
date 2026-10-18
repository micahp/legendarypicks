import { fireEvent, render, waitFor } from '@testing-library/react'
import NflProjections from '../pages/nfl/projections'

jest.mock('../components/Props/ProjectionRecord', () => function MockRecord() {
  return <div data-mock-record>record</div>
})

function line(mean: number, p10: number | null = null, p90: number | null = null) {
  return { mean, median: null, p10, p90 }
}

function player(id: number, extra: Record<string, unknown> = {}) {
  return {
    game_id: '2026_06_LA_BAL', player_id: id, team: 'LAR', name: `Player ${id}`, position: 'WR',
    p_plays: 1.0, v2: { rec_yds: line(60.4, 21, 104), rec: line(5.2) }, marcel: { rec_yds: 55.0 },
    espn: { rec_yds: 58.3 }, ...extra,
  }
}

function mockFetch(byUrl: Record<string, { ok: boolean; body?: unknown }>) {
  const calls: string[] = []
  ;(global as any).fetch = jest.fn((url: string) => {
    calls.push(url)
    const hit = byUrl[url]
    if (!hit) return Promise.reject(new Error('unexpected ' + url))
    return Promise.resolve({ ok: hit.ok, status: hit.ok ? 200 : 500, json: () => Promise.resolve(hit.body) })
  })
  return calls
}

describe('/nfl/projections', () => {
  it('renders one row per player with the band, ESPN, Marcel and the chance he plays', async () => {
    mockFetch({ '/api/nfl/projections': { ok: true, body: {
      season: 2026, week: 6, weeks: [6],
      players: [player(1), player(2, { p_plays: 0.682, espn: {}, v2: { rec_yds: line(30.0) } })],
    } } })
    const { container } = render(<NflProjections />)
    await waitFor(() => expect(container.querySelector('[data-projection-slate]')).not.toBeNull())
    const rows = Array.from(container.querySelectorAll('tbody tr')).map(tr =>
      Array.from(tr.querySelectorAll('td')).map(td => td.textContent))
    expect(rows[0]).toEqual(['Player 1LAR WR', '60.4', '21 to 104', '5.2', '58.3', '55.0', '100%'])
    // missing values are a dash, never a zero
    expect(rows[1]).toEqual(['Player 2LAR WR', '30.0', '- to -', '-', '-', '55.0', '68%'])
    expect(container.textContent).toContain('Week 6')
    expect(container.textContent).toContain('if the player plays')
  })

  it('puts quarterbacks in their own table and keeps them out of the receiver table', async () => {
    mockFetch({ '/api/nfl/projections': { ok: true, body: {
      season: 2026, week: 6, weeks: [6],
      players: [player(1), {
        game_id: '2026_06_LA_BAL', player_id: 7, team: 'LAR', name: 'Q Passer', position: 'QB', p_plays: 0.682,
        v2: { pass_yds: line(244.6, 170, 320), att: line(34.2), cmp: line(22.1), pass_td: line(1.6) },
        marcel: { pass_yds: 251.0 }, espn: {},
      }],
    } } })
    const { container } = render(<NflProjections />)
    await waitFor(() => expect(container.querySelector('[data-projection-passers]')).not.toBeNull())
    expect(container.querySelectorAll('[data-projection-slate] tbody tr').length).toBe(1)
    const qb = Array.from(container.querySelectorAll('[data-projection-passers] tbody td')).map(td => td.textContent)
    expect(qb).toEqual(['Q PasserLAR', '245', '170 to 320', '34.2', '22.1', '1.6', '251', '68%'])
  })

  it('says nothing is projected instead of drawing an empty table', async () => {
    mockFetch({ '/api/nfl/projections': { ok: true, body: { season: 2026, week: null, weeks: [], players: [] } } })
    const { container } = render(<NflProjections />)
    await waitFor(() => expect(container.textContent).toContain('Nothing has been projected for this week.'))
    expect(container.textContent).toContain('No projections yet')
    expect(container.querySelector('table')).toBeNull()
  })

  it('reports a failed load', async () => {
    mockFetch({ '/api/nfl/projections': { ok: false } })
    const { container } = render(<NflProjections />)
    await waitFor(() => expect(container.textContent).toContain('The projections could not be loaded.'))
  })

  it('shows 40 rows, then all of them on request, and switches weeks by query', async () => {
    const players = Array.from({ length: 45 }, (_, i) => player(i + 1))
    const calls = mockFetch({
      '/api/nfl/projections': { ok: true, body: { season: 2026, week: 6, weeks: [5, 6], players } },
      '/api/nfl/projections?week=5': { ok: true, body: { season: 2026, week: 5, weeks: [5, 6], players: [player(99)] } },
    })
    const { container, getByText } = render(<NflProjections />)
    await waitFor(() => expect(container.querySelectorAll('tbody tr').length).toBe(40))
    fireEvent.click(getByText('Show all 45'))
    expect(container.querySelectorAll('tbody tr').length).toBe(45)
    fireEvent.click(getByText('5'))
    await waitFor(() => expect(container.textContent).toContain('Week 5'))
    expect(calls).toContain('/api/nfl/projections?week=5')
    expect(container.querySelectorAll('tbody tr').length).toBe(1)
  })
})
