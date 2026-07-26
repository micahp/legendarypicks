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

/** Fired manually on route change: config sets send_page_view false. */
export function trackPageView(url: string): void {
  if (!analyticsReady()) return
  window.gtag!('event', 'page_view', {
    page_path: url,
    page_location: window.location.href,
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
