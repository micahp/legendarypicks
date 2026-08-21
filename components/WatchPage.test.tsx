import { render, screen, waitFor } from '@testing-library/react'
import WatchPage from '../pages/watch'

const broadcast = {
  id: 'fiba-u18-asia-2026-chn-phi',
  sourceId: 'fiba-youtube',
  title: 'China v Philippines',
  competition: 'FIBA U18 Asia Cup 2026',
  videoId: 'WhVHB8C9mPY',
  status: 'ended',
  checkedAt: '2026-08-21T17:00:00Z',
}

describe('Watch page', () => {
  const originalFetch = global.fetch

  afterEach(() => {
    global.fetch = originalFetch
    jest.restoreAllMocks()
  })

  it('embeds only the concrete verified video and labels it ended', async () => {
    global.fetch = jest.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ broadcasts: [broadcast] }),
    } as any)

    const { container } = render(<WatchPage />)

    await waitFor(() => expect(screen.getByText('China v Philippines')).toBeTruthy())
    expect(screen.getByText('No verified embeddable broadcast is live right now. Verified completed broadcasts remain available below.')).toBeTruthy()
    expect(screen.getByText('Broadcast ended · replay')).toBeTruthy()
    expect(container.querySelector('iframe')?.getAttribute('src')).toContain('/embed/WhVHB8C9mPY')
  })

  it('does not substitute an unverified source when the feed is empty', async () => {
    global.fetch = jest.fn().mockResolvedValue({ ok: true, json: async () => ({ broadcasts: [] }) } as any)
    render(<WatchPage />)
    await waitFor(() => expect(screen.getByText('No verified embeddable broadcasts are on the board right now.')).toBeTruthy())
    expect(screen.queryByTitle(/FIBA/)).toBeNull()
  })
})
