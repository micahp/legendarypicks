import { fireEvent, render, screen } from '@testing-library/react'
import NflPixelHQ from './NflPixelHQ'

describe('NflPixelHQ', () => {
  it('connects room objects to the existing NFL research routes', () => {
    render(<NflPixelHQ data={null} loading={false} error="unavailable" />)

    expect(screen.getByRole('link', { name: /scores from the television/i }).getAttribute('href')).toBe('/scores?league=nfl')
    expect(screen.getByRole('link', { name: /forecasts from the scouting board/i }).getAttribute('href')).toBe('/leagues/nfl?tab=model')
    expect(screen.getByRole('link', { name: /player props from the desk computer/i }).getAttribute('href')).toBe('/props?league=nfl')
    expect(screen.getByRole('link', { name: /player projections from the player card wall/i }).getAttribute('href')).toBe('/nfl/projections')
    expect(screen.getByRole('link', { name: 'Scores' }).getAttribute('href')).toBe('/scores?league=nfl')
    expect(screen.getByText('NFL season context is unavailable right now.')).toBeTruthy()
  })

  it('opens honest information panels for unfinished career and arcade features', () => {
    render(<NflPixelHQ data={null} loading={false} error={null} />)

    fireEvent.click(screen.getByRole('button', { name: /trophy shelf/i }))
    expect(screen.getByText('Career tracking is not available yet. No records or rewards are being generated here.')).toBeTruthy()

    fireEvent.click(screen.getByRole('button', { name: /console.*mini-games/i }))
    expect(screen.getByText('Mini-games are not available yet. This console has no game or rewards attached.')).toBeTruthy()
    expect(screen.getByRole('button', { name: /console.*mini-games/i }).getAttribute('aria-expanded')).toBe('true')
  })
})
