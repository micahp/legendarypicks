import { trackPageView } from './analytics'

describe('trackPageView', () => {
  const originalGtag = window.gtag

  afterEach(() => {
    if (originalGtag) window.gtag = originalGtag
    else Reflect.deleteProperty(window, 'gtag')
  })

  it('removes bearer share IDs from analytics page paths and locations', () => {
    const gtag = jest.fn()
    window.gtag = gtag

    trackPageView('/arcade/nfl/field-goal/challenge-1?share=private-token&view=compact')

    expect(gtag).toHaveBeenCalledWith('event', 'page_view', expect.objectContaining({
      page_path: '/arcade/nfl/field-goal/challenge-1?view=compact',
      page_location: `${window.location.origin}/arcade/nfl/field-goal/challenge-1?view=compact`,
    }))
    expect(JSON.stringify(gtag.mock.calls)).not.toContain('private-token')
  })
})
