import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import PlayerStatsPage from '../player'
import { SportsService } from '../../services/sports'

jest.mock('../../services/sports')

const mockPlayer = { playerId: 'P1', name: 'Test Player' }
;(SportsService.getPlayerStats as jest.Mock).mockResolvedValue(mockPlayer)

describe('PlayerStatsPage', () => {
  it('fetches player stats', async () => {
    render(<PlayerStatsPage />)
    fireEvent.change(screen.getByPlaceholderText(/player id/i), { target: { value: 'P1' } })
    fireEvent.click(screen.getByText(/Load Stats/i))
    await waitFor(() => expect(SportsService.getPlayerStats).toHaveBeenCalled())
    expect(screen.getByText(/Test Player/)).toBeInTheDocument()
  })
})
