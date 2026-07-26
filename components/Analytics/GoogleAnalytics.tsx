import Script from 'next/script'
import { useEffect } from 'react'
import { useRouter } from 'next/router'
import { trackPageView } from '../../lib/analytics'

interface Props {
  trackingId: string
}

/**
 * GA4 loader for the pages router.
 *
 * gtag('config') fires one page_view on hard load only, but LP's nav is
 * client-side -- so send_page_view is off and page_view is fired explicitly on
 * routeChangeComplete. (GA4 enhanced measurement can pick up history events,
 * but it double-counts against a manual handler.)
 */
export default function GoogleAnalytics({ trackingId }: Props) {
  const router = useRouter()

  useEffect(() => {
    if (!trackingId) return
    const onRouteChange = (url: string) => trackPageView(url)
    router.events.on('routeChangeComplete', onRouteChange)
    return () => router.events.off('routeChangeComplete', onRouteChange)
  }, [router.events, trackingId])

  if (!trackingId || process.env.NODE_ENV === 'development') {
    return null
  }

  return (
    <>
      <Script
        src={`https://www.googletagmanager.com/gtag/js?id=${trackingId}`}
        strategy="afterInteractive"
      />
      <Script
        id="google-analytics"
        strategy="afterInteractive"
        dangerouslySetInnerHTML={{
          __html: `
            window.dataLayer = window.dataLayer || [];
            function gtag(){dataLayer.push(arguments);}
            gtag('js', new Date());
            gtag('config', '${trackingId}', {
              send_page_view: false,
              cookie_flags: 'SameSite=Lax;Secure',
              cookie_domain: 'auto',
              cookie_expires: 63072000
            });
            gtag('event', 'page_view', {
              page_path: window.location.pathname + window.location.search,
              page_location: window.location.href,
              page_title: document.title
            });
          `,
        }}
      />
    </>
  )
}
