import React from 'react'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import MarketSlateBoard from './MarketSlateBoard'

// Four players on one market, deliberately named so that alphabetical order and
// evidence order disagree. All four share an L10 of 0.4 — which is the normal case,
// not a contrived one: a ten-game rate takes eleven distinct values, so a real slate
// put six rows on 40% at once and the board rendered them A–Z.
const ROWS = [
  { id: 1, name: 'Aaron Alpha', proj: 1.6, season: 0.30, games: 20 },
  { id: 2, name: 'Zeb Zulu', proj: 4.0, season: 0.55, games: 90 },
  { id: 3, name: 'Bob Bravo', proj: 1.5, season: 0.50, games: 60 },
  { id: 4, name: 'Yuri Yankee', proj: 2.6, season: 0.45, games: 40 },
]
const LINE = 1.5

function slateResponse() {
  return [{ markets: [{ market: 'total_bases', count: ROWS.length }] }]
}

function propsResponse() {
  return ROWS.flatMap(r => ([
    {
      id: r.id * 10, market: 'total_bases', line: LINE, side: 'over', source: 'bovada',
      captured_at: '2026-08-09T00:00:00Z', odds: 120, player_id: r.id, player_name: r.name,
      player_team: 'WSH', league: 'mlb', game_home: 'WSH', game_away: 'CIN',
      game_date: '2026-08-09',
    },
  ]))
}

function historyResponse(playerId: number) {
  const row = ROWS.find(r => r.id === playerId)!
  return {
    player_id: row.id, player: row.name, team: 'WSH', league: 'mlb',
    market: 'total_bases', line: LINE, side: 'over',
    projection: row.proj,
    hit_rate: { l5: 0.4, l10: 0.4, l20: 0.4, season: row.season },
    games: Array.from({ length: row.games }, (_, i) => ({
      date: '2026-08-0' + ((i % 9) + 1), value: 1, opponent: 'CIN', home: true, hit: false,
    })),
  }
}

beforeEach(() => {
  ;(global as any).fetch = jest.fn((url: string) => {
    if (url.includes('/api/props/slate')) return Promise.resolve(json(slateResponse()))
    if (url.includes('/api/props/history')) {
      const id = Number(new URLSearchParams(url.split('?')[1]).get('player_id'))
      return Promise.resolve(json(historyResponse(id)))
    }
    return Promise.resolve(json(propsResponse()))
  })
})

function json(body: any) {
  return { ok: true, status: 200, json: () => Promise.resolve(body) } as any
}

async function renderedOrder(): Promise<string[]> {
  render(<MarketSlateBoard league="mlb" date="2026-08-09" />)
  // The order is only meaningful once EVERY row has its history: a row still
  // loading has a null sort value and parks at the bottom, so asserting early
  // reads a mid-load arrangement rather than the comparator's answer.
  await waitFor(() => {
    expect(document.querySelectorAll('[data-market-row]').length).toBe(ROWS.length)
    expect(document.querySelectorAll('[data-market-chart]').length).toBe(ROWS.length)
    expect(screen.getAllByText(/^Projection/).length).toBe(ROWS.length)
  })
  return Array.from(document.querySelectorAll('[data-market-row] h3'))
    .map(n => (n.textContent || '').trim())
}

describe('the research board never falls back to alphabetical order', () => {
  it('breaks an L10 tie on edge, not on the player name', async () => {
    const order = await renderedOrder()

    // Edge = |projection - line|: Zulu 2.5, Yankee 1.1, Alpha 0.1, Bravo 0.0.
    expect(order).toEqual(['Zeb Zulu', 'Yuri Yankee', 'Aaron Alpha', 'Bob Bravo'])
  })

  it('does not render the tied rows in name order', async () => {
    const order = await renderedOrder()
    const alphabetical = [...order].sort((a, b) => a.localeCompare(b))

    // The specific defect: every primary value equal, so the comparator's last
    // clause decided the board. If these ever match again, the tiebreakers are gone.
    expect(order).not.toEqual(alphabetical)
  })
})

describe('filtered empty states', () => {
  it('identifies the selected league and can clear the filter', async () => {
    ;(global as any).fetch = jest.fn(() => Promise.resolve(json([])))
    const onViewAll = jest.fn()

    render(
      <MarketSlateBoard
        league="nhl"
        date="2026-08-25"
        filterLabel="NHL"
        onViewAll={onViewAll}
      />,
    )

    const message = await screen.findByText('No upcoming games with props. Check back closer to game time.')
    expect(message.parentElement?.className).not.toMatch(/border|bg-/)
    fireEvent.click(screen.getByRole('button', { name: 'View All Leagues' }))
    expect(onViewAll).toHaveBeenCalledTimes(1)
  })
})
