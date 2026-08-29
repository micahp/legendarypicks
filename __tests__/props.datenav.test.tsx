// Lives in __tests__/, NOT in pages/. There is no `pageExtensions` in
// next.config.js, so every .tsx under pages/ is a ROUTE: a test file there is
// built as a page, and `next build` fails with "Failed to collect page data" /
// "beforeEach is not defined". Jest does not care where the file sits, so the
// unit suite stayed green while the production build was broken.
import React from 'react'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import PropsPage from '../pages/props'

// Date navigation walked raw calendar days, so pressing ‹ on a league that plays
// twice a week landed on an empty board indistinguishable from a data gap. The
// arrows now step between the dates the SELECTED league actually has a slate on.
const SLATE = [
  { date: '2026-08-26', league: 'mls' },
  { date: '2026-08-29', league: 'mls' },
  { date: '2026-08-30', league: 'mls' },
]

function json(body: any) {
  return { ok: true, status: 200, json: () => Promise.resolve(body) } as any
}

beforeEach(() => {
  window.history.replaceState({}, '', '/props?tab=props')
  ;(global as any).fetch = jest.fn((url: string) => {
    if (url.includes('/api/props/slate')) {
      return Promise.resolve(json(SLATE.map((g, i) => ({
        id: i + 1, date: g.date, league: g.league,
        home: 'H', away: 'A', markets: [],
      }))))
    }
    if (url.includes('/api/props/history')) return Promise.resolve(json({ games: [] }))
    return Promise.resolve(json([]))
  })
})

function shownDate(): string {
  const live = document.querySelector('[aria-live="polite"]')
  return (live?.textContent || '').trim()
}

// The date defaults to today, so waiting on the date TEXT succeeds before the
// slate has loaded and the arrows are still inert. Wait for the slate itself.
// jest-dom is not installed here, so assert the DOM property directly rather
// than reaching for toBeDisabled(), which silently is not a matcher.
function arrow(label: string): HTMLButtonElement {
  return screen.getByLabelText(label) as HTMLButtonElement
}

async function slateLoaded() {
  await waitFor(() => expect(arrow('Next slate date').disabled).toBe(false))
}

describe('the date navigator is bounded by the selected league slate', () => {
  it('steps to the next slate date, not the next calendar day', async () => {
    render(<PropsPage />)
    await slateLoaded()
    expect(shownDate()).toContain('Aug 26')
    // eslint-disable-next-line no-console
    console.log('DBG slate fetch calls:',
      ((global as any).fetch as jest.Mock).mock.calls.map((c: any[]) => c[0]).join(' | '))
    console.log('DBG prev disabled:', (screen.getByLabelText('Previous slate date') as HTMLButtonElement).disabled,
                'next disabled:', (screen.getByLabelText('Next slate date') as HTMLButtonElement).disabled)
    fireEvent.click(screen.getByLabelText('Next slate date'))
    // Aug 27 and 28 have no slate; the next real one is Aug 29.
    await waitFor(() => expect(shownDate()).toContain('Aug 29'))
  })

  it('disables the arrows at both ends of the slate', async () => {
    render(<PropsPage />)
    await slateLoaded()
    expect(shownDate()).toContain('Aug 26')
    expect(arrow('Previous slate date').disabled).toBe(true)
    fireEvent.click(screen.getByLabelText('Next slate date'))
    await waitFor(() => expect(shownDate()).toContain('Aug 29'))
    fireEvent.click(screen.getByLabelText('Next slate date'))
    await waitFor(() => expect(shownDate()).toContain('Aug 30'))
    expect(arrow('Next slate date').disabled).toBe(true)
  })
})
