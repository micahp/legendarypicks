// GA4 event helpers.
//
// Everything here is a no-op unless NEXT_PUBLIC_GA_TRACKING_ID was present at
// BUILD time -- NEXT_PUBLIC_* is inlined by Next during the build, so setting it
// only in the runtime environment silently records nothing. See Dockerfile.

type GtagParams = Record<string, string | number | boolean | null | undefined>

declare global {
  interface Window {
    gtag?: (command: string, ...args: unknown[]) => void
    dataLayer?: unknown[]
  }
}

export const GA_TRACKING_ID = process.env.NEXT_PUBLIC_GA_TRACKING_ID || ''

/** True only when a measurement ID was baked in and gtag actually loaded. */
export function analyticsReady(): boolean {
  return typeof window !== 'undefined' && typeof window.gtag === 'function'
}

export function trackEvent(name: string, params: GtagParams = {}): void {
  if (!analyticsReady()) return
  window.gtag!('event', name, params)
}

type ArcadeVisitSurface = 'lobby' | 'challenge' | 'shared_challenge' | 'training'

const ARCADE_LAST_VISIT_KEY = 'lp-arcade-last-visit-at-v1'
const ARCADE_VISIT_SESSION_KEY = 'lp-arcade-visited-this-session-v1'

/** Track first use and return windows without sending a persistent user identifier. */
export function trackArcadeVisit(surface: ArcadeVisitSurface, now = Date.now()): void {
  if (!analyticsReady()) return
  try {
    if (window.sessionStorage.getItem(ARCADE_VISIT_SESSION_KEY) === '1') return
    window.sessionStorage.setItem(ARCADE_VISIT_SESSION_KEY, '1')
    const previous = Number(window.localStorage.getItem(ARCADE_LAST_VISIT_KEY))
    const hasPrevious = Number.isFinite(previous) && previous > 0 && now >= previous
    const daysSinceLastVisit = hasPrevious ? (now - previous) / 86_400_000 : null
    const returnWindow = daysSinceLastVisit === null ? 'first'
      : daysSinceLastVisit >= 1 && daysSinceLastVisit < 2 ? 'd1'
        : daysSinceLastVisit >= 7 && daysSinceLastVisit < 8 ? 'd7'
          : daysSinceLastVisit < 1 ? 'same_day'
            : daysSinceLastVisit < 7 ? 'd2_d6' : 'd8_plus'
    window.localStorage.setItem(ARCADE_LAST_VISIT_KEY, String(now))
    trackEvent('arcade_visit', {
      visit_type: hasPrevious ? 'return' : 'first',
      return_window: returnWindow,
      surface,
      ...(daysSinceLastVisit === null ? {} : { days_since_last_visit: Math.round(daysSinceLastVisit * 10) / 10 }),
    })
  } catch {
    trackEvent('arcade_visit', { visit_type: 'unknown', return_window: 'storage_unavailable', surface })
  }
}

/** Fired manually on route change: config sets send_page_view false. */
export function trackPageView(url: string): void {
  if (!analyticsReady()) return
  const safeUrl = new URL(url, window.location.origin)
  // Share IDs are bearer tokens: keep them out of GA page paths and locations.
  safeUrl.searchParams.delete('share')
  const pagePath = `${safeUrl.pathname}${safeUrl.search}${safeUrl.hash}`
  window.gtag!('event', 'page_view', {
    page_path: pagePath,
    page_location: safeUrl.href,
    page_title: document.title,
  })
}

// ── the five events ───────────────────────────────────────────────────
// Kept deliberately small. Activation is "made a pick in week N, came back in
// week N+1", so pick_made is the one that has to be right.

export function trackPickMade(params: {
  league: string
  surface: string
  pick_id?: string | number
  player_id?: string | number
}): void {
  trackEvent('pick_made', params)
}

export function trackPlayerViewed(params: {
  player_id: string | number
  league: string
  surface?: string
}): void {
  trackEvent('player_viewed', params)
}

export function trackUsageTrendViewed(params: {
  player_id: string | number
  season?: number
}): void {
  trackEvent('usage_trend_viewed', params)
}

export function trackPropChartOpened(params: {
  player_id: string | number
  league: string
  market?: string
}): void {
  trackEvent('prop_chart_opened', params)
}

export function trackStreamWatched(params: {
  match_id?: string | number
  game?: string
  source?: string
}): void {
  trackEvent('stream_watched', params)
}
