import { render, screen } from '@testing-library/react'
import DraftBoardPage from './draft-board'

jest.mock('../components/Leagues/NflDraftBoardSurface', () => ({ standalone }: { standalone?: boolean }) => (
  <div data-testid="draft-board-surface" data-standalone={String(standalone)} />
))

describe('/draft-board', () => {
  it('is a stable standalone view of the shared research board', () => {
    render(<DraftBoardPage />)
    expect(screen.getByRole('heading', { name: 'Draft Board' })).toBeTruthy()
    expect(screen.getByTestId('draft-board-surface').getAttribute('data-standalone')).toBe('true')
    expect(screen.getByRole('link', { name: 'NFL home' }).getAttribute('href')).toBe('/leagues/nfl')
    expect(screen.getByRole('link', { name: 'Start a mock draft' }).getAttribute('href')).toBe('/mock-draft')
  })
})
