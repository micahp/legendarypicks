import React from 'react'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import MarketSlateBoard from './MarketSlateBoard'

// Sorting a Leagues Cup board by raw hit rate put a 3-game Liga MX player above
// everyone, because the percentage discards the sample size. Confidence ranks by
// the rate a record can support instead.
const ROWS = [
  { id: 1, name: 'Thin Perfect', hits: 3, games: 3 },     // 100%, w=0.44
  { id: 2, name: 'Broad Good', hits: 16, games: 22 },     //  73%, w=0.52
  { id: 3, name: 'Broad Average', hits: 28, games: 48 },  //  58%, w=0.44
]
const LINE = 0.5

function json(body: any) {
  return { ok: true, status: 200, json: () => Promise.resolve(body) } as any
}

function historyResponse(id: number) {
  const r = ROWS.find(x => x.id === id)!
  return {
    player_id: r.id, player: r.name, team: 'LEO', league: 'ligamx',
    market: 'shots', line: LINE, side: 'over', projection: 1,
    hit_rate: { l5: 1, l10: r.hits / r.games, l20: r.hits / r.games, season: r.hits / r.games },
    hit_rate_n: { l5: Math.min(5, r.games), l10: Math.min(10, r.games), l20: Math.min(20, r.games), season: r.games },
    games: Array.from({ length: r.games }, (_, i) => ({
      date: '2026-08-0' + ((i % 9) + 1), value: 1, opponent: 'AME',
      home: true, hit: i < r.hits,
    })),
  }
}

beforeEach(() => {
  ;(global as any).fetch = jest.fn((url: string) => {
    if (url.includes('/api/props/slate')) {
      return Promise.resolve(json([{ markets: [{ market: 'shots', count: ROWS.length }] }]))
    }
    if (url.includes('/api/props/history')) {
      const id = Number(new URLSearchParams(url.split('?')[1]).get('player_id'))
      return Promise.resolve(json(historyResponse(id)))
    }
    return Promise.resolve(json(ROWS.map(r => ({
      id: r.id * 10, market: 'shots', line: LINE, side: 'over', source: 'prizepicks-goblin',
      captured_at: '2026-08-26T00:00:00Z', odds: null, player_id: r.id,
      player_name: r.name, player_team: 'LEO', league: 'ligamx',
      game_home: 'León', game_away: 'Salt Lake', game_date: '2026-08-26',
    }))))
  })
})

async function order(): Promise<string[]> {
  await waitFor(() => {
    expect(document.querySelectorAll('[data-market-row]').length).toBe(ROWS.length)
    expect(screen.getAllByText(/^Projection/).length).toBe(ROWS.length)
  })
  return Array.from(document.querySelectorAll('[data-market-row] h3'))
    .map(n => (n.textContent || '').trim())
}

describe('confidence sorts by the rate a record can support', () => {
  it('puts a thin perfect record below a broad good one', async () => {
    render(<MarketSlateBoard league="ligamx" date="2026-08-26" />)
    await order()
    fireEvent.click(screen.getByText('Confidence'))
    expect((await order())[0]).toBe('Broad Good')
  })

  it('still ranks the thin record above nothing — it is evidence, just less', async () => {
    render(<MarketSlateBoard league="ligamx" date="2026-08-26" />)
    await order()
    fireEvent.click(screen.getByText('Confidence'))
    expect(await order()).toContain('Thin Perfect')
  })

  it('raw hit rate still puts the thin perfect record on top', async () => {
    render(<MarketSlateBoard league="ligamx" date="2026-08-26" />)
    expect((await order())[0]).toBe('Thin Perfect')
  })

  it('explains itself only while it is the active sort', async () => {
    render(<MarketSlateBoard league="ligamx" date="2026-08-26" />)
    await order()
    expect(screen.queryByText(/can actually support/)).toBeNull()
    fireEvent.click(screen.getByText('Confidence'))
    expect(screen.getByText(/can actually support/)).toBeTruthy()
  })
})
