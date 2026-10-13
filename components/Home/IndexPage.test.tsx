import React from 'react'
import { act, render, screen, waitFor } from '@testing-library/react'
import { featured } from './fixtures'

jest.mock('next/head', () => ({ __esModule: true, default: () => null }))

import Home from '../../pages/index'

beforeEach(() => {
  ;(global as any).fetch = jest.fn(() => Promise.resolve({ ok: true, json: () => Promise.resolve(featured) }))
})

describe('home page', () => {
  it('loads the hero data and keeps the existing homepage sections', async () => {
    await act(async () => { render(<Home />) })
    await waitFor(() => expect(screen.getByText('Test Receiver')).toBeTruthy())

    expect((global as any).fetch.mock.calls.some(([url]: [string]) => url === '/api/home/featured')).toBe(true)
    expect(screen.getByText('Player props, with the history')).toBeTruthy()
    expect(screen.getByText('Live Scores')).toBeTruthy()
    expect(screen.getByText('Predictions')).toBeTruthy()
    expect(screen.getByText('News')).toBeTruthy()
    expect(screen.getByText('Esports')).toBeTruthy()
    expect(screen.queryByText('Questions it answers before you decide')).toBeNull()
    expect(screen.queryByText('Free and member')).toBeNull()
  })

  it('keeps the prop-led homepage visible when the hero data read fails', async () => {
    ;(global as any).fetch = jest.fn(() => Promise.reject(new Error('down')))
    await act(async () => { render(<Home />) })

    await waitFor(() => expect(screen.getByText(/not available right now/)).toBeTruthy())
    expect(screen.getByText('Live prop lines and hit rate history across 11 leagues.')).toBeTruthy()
    expect(screen.getByText('Player props, with the history')).toBeTruthy()
  })
})
