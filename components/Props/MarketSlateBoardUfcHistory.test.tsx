import React from 'react'
import { render, screen, waitFor } from '@testing-library/react'
import MarketSlateBoard from './MarketSlateBoard'

function json(body: any) {
  return { ok: true, status: 200, json: () => Promise.resolve(body) } as any
}

function prop(market: string) {
  return {
    id: 10, market, line: 50.5, side: 'over', source: 'underdog',
    captured_at: '2026-08-29T00:00:00Z', odds: null, player_id: 7,
    player_name: 'Test Fighter', player_team: '', league: 'ufc',
    game_home: 'Test Fighter', game_away: 'Opponent', game_date: '2026-08-29',
  }
}

function history(market: string) {
  return {
    player_id: 7, player: 'Test Fighter', team: '', league: 'ufc', market,
    line: 50.5, side: 'over', projection: 55,
    hit_rate: { l5: 0.6, l10: 0.6, l20: 0.6, season: 0.6 },
    hit_rate_n: { l5: 5, l10: 5, l20: 5, season: 5 },
    games: Array.from({ length: 5 }, (_, index) => ({
      date: `2026-0${index + 1}-01`, value: 60 - index,
      opponent: `Opponent ${index + 1}`, home: null, hit: index < 3,
    })),
  }
}

describe('UFC numeric history', () => {
  it('requests and renders a prop chart for significant strikes', async () => {
    ;(global as any).fetch = jest.fn((url: string) => {
      if (url.includes('/api/props/slate')) {
        return Promise.resolve(json([{ markets: [{ market: 'significant_strikes', count: 1 }] }]))
      }
      if (url.includes('/api/props/history')) {
        return Promise.resolve(json(history('significant_strikes')))
      }
      return Promise.resolve(json([prop('significant_strikes')]))
    })

    render(<MarketSlateBoard league="ufc" date="2026-08-29" />)

    await waitFor(() => expect(screen.getByText(/Projection/)).toBeTruthy())
    expect((global as any).fetch).toHaveBeenCalledWith(
      expect.stringContaining('/api/props/history?'),
      expect.objectContaining({ signal: expect.anything() }),
    )
    expect(screen.queryByText('Last 5 fights')).toBeNull()
  })

  it.each(['win_by_decision', 'knockouts', 'finishes', 'submissions'])(
    'keeps %s on fight form without requesting numeric history', async market => {
    ;(global as any).fetch = jest.fn((url: string) => {
      if (url.includes('/api/props/slate')) {
        return Promise.resolve(json([{ markets: [{ market, count: 1 }] }]))
      }
      if (url.includes('/api/ufc/fighter/7/form')) {
        return Promise.resolve(json({
          player_id: 7, fighter: 'Test Fighter', source: 'ufcstats',
          fights: [{ result: 'W', method: 'DEC', opponent: 'Opponent',
            date: '2026-08-01', event_id: 'event', fight_id: 'fight' }],
        }))
      }
      return Promise.resolve(json([prop(market)]))
    })

    render(<MarketSlateBoard league="ufc" date="2026-08-29" />)

    await waitFor(() => expect(screen.getByText('Last 5 fights')).toBeTruthy())
    await waitFor(() => expect(screen.getByText('W · DEC')).toBeTruthy())
    const urls = (global as any).fetch.mock.calls.map((call: any[]) => call[0])
    expect(urls.some((url: string) => url.includes('/api/props/history'))).toBe(false)
  })
})
