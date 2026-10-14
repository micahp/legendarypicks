import React from 'react'
import { render, screen } from '@testing-library/react'
import Layout from './Layout'

jest.mock('./GlobalSearch', () => ({ __esModule: true, default: () => null }))

describe('site navigation', () => {
  it('no longer lists the Watch tab, and keeps the other tabs', () => {
    render(<Layout><div /></Layout>)
    expect(screen.queryByRole('link', { name: 'Watch' })).toBeNull()
    for (const name of ['Scores', 'Props', 'Leagues', 'News', 'Esports', 'Predict']) {
      expect(screen.getByRole('link', { name }).getAttribute('href')).toBeTruthy()
    }
  })
})
