import { render, screen } from '@testing-library/react'
import InjuryTag from './InjuryTag'

describe('InjuryTag', () => {
  it('renders a full designation on player detail', () => {
    render(<InjuryTag status="QUESTIONABLE" />)
    expect(screen.getByLabelText('Injury status: Questionable').textContent).toBe('Questionable')
  })

  it('uses compact pool labels and normalizes the stored reserve value', () => {
    render(<InjuryTag status="INJURY_RESERV" compact />)
    expect(screen.getByLabelText('Injury status: Injured reserve').textContent).toBe('IR')
  })

  it('does not warn for active or absent designations', () => {
    const { rerender } = render(<InjuryTag status="ACTIVE" />)
    expect(screen.queryByText('Active')).toBeNull()
    rerender(<InjuryTag status={null} />)
    expect(screen.queryByLabelText(/Injury status:/)).toBeNull()
  })
})
