import React from 'react'
import { render, screen, waitFor } from '@testing-library/react'
import FightForm from './FightForm'

function response(body: any) {
  return { ok: true, status: 200, json: () => Promise.resolve(body) } as any
}

describe('UFC recent fight form', () => {
  it('shows round and clock for finishes and has no divider below the title', async () => {
    ;(global as any).fetch = jest.fn(() => Promise.resolve(response({
      player_id: 99001,
      fighter: 'Test Fighter',
      source: 'ufcstats',
      fights: [
        {
          result: 'W', method: 'KO/TKO', round: 2, time: '2:11',
          opponent: 'Finished Opponent', date: '2026-08-01',
          event_id: 'event-a', fight_id: 'fight-a',
        },
        {
          result: 'W', method: 'DEC', round: 3, time: '5:00',
          opponent: 'Decision Opponent', date: '2026-07-01',
          event_id: 'event-b', fight_id: 'fight-b',
        },
      ],
    })))

    const { container } = render(<FightForm playerId={99001} fighter="Test Fighter" />)
    await waitFor(() => expect(screen.getByText('Round 2 · 2:11')).toBeTruthy())
    expect(screen.getByRole('button', { name: /Last 5 fights/i }).getAttribute('aria-expanded')).toBe('true')
    expect((global.fetch as jest.Mock)).toHaveBeenCalledTimes(1)
    expect(screen.queryByText('Round 3 · 5:00')).toBeNull()
    expect(container.querySelector('[data-fight-form-content]')?.className).not.toContain('border-t')
  })
})
