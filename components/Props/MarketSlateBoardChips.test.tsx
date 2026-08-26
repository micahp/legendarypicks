import React from 'react'
import { render, screen, waitFor } from '@testing-library/react'
import MarketSlateBoard from './MarketSlateBoard'

// Reported from the board 2026-08-26: a Liga MX player with three matches
// showed L5 100%, L10 100% and L20 100%. The API computes each window as
// games[:N], so one three-game sample printed three times as three different
// claims. MLS looked right only because those players have 25-42 games.
const PLAYER = { id: 1, name: 'Short Sample', games: 3 }
const LINE = 0.5

function json(body: any) {
  return { ok: true, status: 200, json: () => Promise.resolve(body) } as any
}

function historyResponse() {
  return {
    player_id: PLAYER.id, player: PLAYER.name, team: 'LEO', league: 'ligamx',
    market: 'shots', line: LINE, side: 'over', projection: 1,
    // Every window reports a perfect record off the same three games.
    hit_rate: { l5: 1, l10: 1, l20: 1, season: 1 },
    hit_rate_n: { l5: 3, l10: 3, l20: 3, season: 3 },
    games: Array.from({ length: PLAYER.games }, (_, i) => ({
      date: '2026-08-0' + (i + 1), value: 2, opponent: 'AME', home: true, hit: true,
    })),
  }
}

beforeEach(() => {
  ;(global as any).fetch = jest.fn((url: string) => {
    if (url.includes('/api/props/slate')) {
      return Promise.resolve(json([{ markets: [{ market: 'shots', count: 1 }] }]))
    }
    if (url.includes('/api/props/history')) return Promise.resolve(json(historyResponse()))
    return Promise.resolve(json([{
      id: 10, market: 'shots', line: LINE, side: 'over', source: 'prizepicks-goblin',
      captured_at: '2026-08-26T00:00:00Z', odds: null, player_id: PLAYER.id,
      player_name: PLAYER.name, player_team: 'LEO', league: 'ligamx',
      game_home: 'León', game_away: 'Real Salt Lake', game_date: '2026-08-26',
    }]))
  })
})

async function chips(): Promise<Record<string, string>> {
  render(<MarketSlateBoard league="ligamx" date="2026-08-26" />)
  await waitFor(() => {
    expect(screen.getAllByText(/^Projection/).length).toBe(1)
  })
  const out: Record<string, string> = {}
  for (const label of ['L5', 'L10', 'L20']) {
    // Scoped to the chip: the chart's window buttons carry the same text.
    const node = document.querySelector(`[data-rate-chip="${label}"]`)!
    out[label] = (node.textContent || '').replace(label, '').trim()
  }
  return out
}

describe('a window short of its own sample shows a dash on the board', () => {
  it('dashes every window a three-game player cannot fill', async () => {
    const c = await chips()
    expect(c.L5).toBe('—')
    expect(c.L10).toBe('—')
    expect(c.L20).toBe('—')
  })

  it('never prints a percentage the sample cannot support', async () => {
    const c = await chips()
    expect(Object.values(c)).not.toContain('100%')
  })
})
