import { fireEvent, render, screen } from '@testing-library/react'

import LogContextSelectors from './LogContextSelectors'

const CONTEXTS = [
  { league: 'mls', season: 2026, games: 24 },
  { league: 'mls', season: 2025, games: 34 },
  { league: 'lcup', season: 2025, games: 6 },
]

it('switches years within a competition', () => {
  const onChange = jest.fn()
  render(
    <LogContextSelectors
      contexts={CONTEXTS}
      league="mls"
      season={2026}
      onChange={onChange}
    />,
  )

  fireEvent.change(screen.getByLabelText('Year'), { target: { value: '2025' } })
  expect(onChange).toHaveBeenCalledWith('mls', 2025)
})

it('chooses the newest available year when the competition changes', () => {
  const onChange = jest.fn()
  render(
    <LogContextSelectors
      contexts={CONTEXTS}
      league="mls"
      season={2026}
      onChange={onChange}
    />,
  )

  expect(screen.getByRole('option', { name: 'Leagues Cup' })).toBeTruthy()
  fireEvent.change(screen.getByLabelText('League'), { target: { value: 'lcup' } })
  expect(onChange).toHaveBeenCalledWith('lcup', 2025)
})
