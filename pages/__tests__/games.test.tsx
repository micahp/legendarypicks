import { render, screen, waitFor } from '@testing-library/react'
import GamesPage from '../games'
import { SportsService } from '../../services/sports'

jest.mock('../../services/sports')

const mockGames = [
  { gameId: '1', homeTeam: { teamId: 'H', name: 'Home' }, awayTeam: { teamId: 'A', name: 'Away' }, status: 'SCHEDULED' }
]

;(SportsService.getGames as jest.Mock).mockResolvedValue(mockGames)

describe('GamesPage', () => {
  it('fetches and displays games', async () => {
    render(<GamesPage />)
    expect(SportsService.getGames).toHaveBeenCalledWith('nba')
    await waitFor(() => expect(screen.getByText(/Home/)).toBeInTheDocument())
    expect(screen.getByText(/Away/)).toBeInTheDocument()
  })
})
