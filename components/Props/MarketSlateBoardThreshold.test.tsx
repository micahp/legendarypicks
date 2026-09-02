import React from 'react'
import { render, screen, waitFor } from '@testing-library/react'
import MarketSlateBoard from './MarketSlateBoard'

const thresholdRows = ['over', 'under'].map((side, index) => ({
  id: index + 1,
  market: 'shots',
  line: 2.5,
  side,
  source: 'rotowire_prizepicks_relay',
  source_label: 'PrizePicks threshold via RotoWire',
  offer_kind: 'pickem_threshold' as const,
  captured_at: '2026-08-16T00:00:00Z',
  // This deliberately impossible-for-the-contract price proves the component
  // does not render an O/U price merely because a stale row contains one.
  odds: -137,
  player_id: 10,
  player_name: 'Alex Forward',
  player_team: 'ATX',
  league: 'mls',
  game_home: 'Austin FC',
  game_away: 'FC Dallas',
  game_date: '2026-08-17',
}))

function json(body: unknown) {
  return { ok: true, status: 200, json: () => Promise.resolve(body) } as any
}

beforeEach(() => {
  ;(global as any).fetch = jest.fn((url: string) => {
    if (url.includes('/api/props/slate')) return Promise.resolve(json([
      { markets: [{ market: 'shots', count: 1 }] },
    ]))
    if (url.includes('/api/props/source-status')) return Promise.resolve(json({ status: 'PUBLISHED' }))
    if (url.includes('/api/props/history')) return Promise.resolve(json({ error: 'not chartable', games: [] }))
    return Promise.resolve(json(thresholdRows))
  })
})

it('renders a RotoWire PrizePicks line as More/Less without sportsbook odds', async () => {
  render(<MarketSlateBoard league="mls" date="2026-08-17" />)

  await waitFor(() => expect(screen.getByText('PrizePicks threshold via RotoWire')).toBeTruthy())
  expect(screen.getByText('More')).toBeTruthy()
  expect(screen.getByText('Less')).toBeTruthy()
  expect(screen.queryByText('-137')).toBeNull()
  expect(screen.getByText('Model evidence unavailable')).toBeTruthy()
})

it('does not substitute stale Bovada rows when the MLS source has no capture', async () => {
  ;(global as any).fetch = jest.fn((url: string) => {
    if (url.includes('/api/props/source-status')) {
      return Promise.resolve(json({ status: 'never_captured', message: 'MLS PrizePicks thresholds have not been captured yet.' }))
    }
    return Promise.resolve(json([]))
  })

  render(<MarketSlateBoard league="mls" date="2026-08-17" />)

  await waitFor(() => expect(screen.getByText('MLS prop source unavailable for this slate.')).toBeTruthy())
  expect(screen.getByText('MLS PrizePicks thresholds have not been captured yet.')).toBeTruthy()
})
