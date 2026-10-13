import React from 'react'
import { render, screen, waitFor } from '@testing-library/react'
import { featured } from './fixtures'

jest.mock('next/head', () => ({ __esModule: true, default: () => null }))

import Home from '../../pages/index'

function load(flag: string | undefined) {
  if (flag === undefined) delete process.env.NEXT_PUBLIC_HOME_MEMBERSHIP
  else process.env.NEXT_PUBLIC_HOME_MEMBERSHIP = flag
  return Home
}

beforeEach(() => {
  ;(global as any).fetch = jest.fn(() => Promise.resolve({ ok: true, json: () => Promise.resolve(featured) }))
})

describe('home page', () => {
  it('reads the featured endpoint and shows the member plan by default', async () => {
    const Home = load(undefined)
    render(<Home />)
    await waitFor(() => expect(screen.getByText('Open the NFL board')).toBeTruthy())
    expect((global as any).fetch.mock.calls[0][0]).toBe('/api/home/featured')
    expect(screen.getByText('Price to be set')).toBeTruthy()
  })
  it('hides the whole plans section when NEXT_PUBLIC_HOME_MEMBERSHIP is off', async () => {
    const Home = load('off')
    render(<Home />)
    await waitFor(() => expect(screen.getByText('Open the NFL board')).toBeTruthy())
    expect(screen.queryByText('Free and member')).toBeNull()
    expect(screen.queryByText('Price to be set')).toBeNull()
  })
  it('still shows slide 1 text and the static sections when the endpoint fails', async () => {
    ;(global as any).fetch = jest.fn(() => Promise.reject(new Error('down')))
    const Home = load(undefined)
    render(<Home />)
    await waitFor(() => expect(screen.getByText(/not available right now/)).toBeTruthy())
    expect(screen.getByText('Live prop lines and hit rate history across 11 leagues.')).toBeTruthy()
    expect(screen.getByText('Questions it answers before you decide')).toBeTruthy()
  })
})
