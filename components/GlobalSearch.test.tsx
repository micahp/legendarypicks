import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import GlobalSearch from './GlobalSearch'

const push = jest.fn()
jest.mock('next/router', () => ({ useRouter: () => ({ push }) }))

describe('GlobalSearch', () => {
  beforeEach(() => {
    push.mockReset()
    ;(global as any).fetch = jest.fn().mockResolvedValue({
      json: async () => [
        { id: 101, name: 'Jannik Sinner', team: null, league: 'atp' },
        { id: 202, name: 'Coco Gauff', team: null, league: 'wta' },
      ],
    })
  })

  it('shows teamless tennis players with tour labels and opens their profile', async () => {
    render(<GlobalSearch />)

    fireEvent.change(screen.getByPlaceholderText('Search players…'), { target: { value: 'Sin' } })

    expect(await screen.findByText('Jannik Sinner')).toBeTruthy()
    expect(screen.getByText('ATP').textContent).toBe('ATP')
    expect(screen.getByText('WTA').textContent).toBe('WTA')
    expect(screen.queryByText(/· ATP/)).toBeNull()

    fireEvent.click(screen.getByText('Jannik Sinner'))
    await waitFor(() => expect(push).toHaveBeenCalledWith('/player/101'))
  })
})
