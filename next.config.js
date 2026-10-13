/** @type {import('next').NextConfig} */
module.exports = {
  output: 'standalone',
  reactStrictMode: true,
  swcMinify: true,
  // Lint/type style errors should not block a production build — they stay a
  // code-quality item (see docs/POLISH-CHECKLIST.md), not a deploy blocker.
  eslint: { ignoreDuringBuilds: true },
  typescript: { ignoreBuildErrors: true },
  async redirects() {
    return [
      { source: '/stats', destination: '/leagues', permanent: false },
      // The CoD-only league desk is generalized into the shared esports title
      // surface — keep the old URL working as a compatibility redirect.
      { source: '/cod', destination: '/esports/call-of-duty', permanent: false },
      // /plays was redirected here as "a locked dead-product decision". That was true of
      // the OLD curated board, fed by plays_board.json, which has not been written since
      // 2026-07-19 — and the redirect is why the live surface vanished from the app.
      // Revived 2026-09-02 as a different product: the live swing board plus upcoming
      // tradeable markets. Do not re-point this at /props without checking what is on it.
    ]
  },
  async rewrites() {
    // In docker-compose the backend is reachable as service `backend:8000`.
    // Locally it's on localhost:8000. Override with API_PROXY_TARGET (.env.local sets this to
    // :8095 for the dev-backend workflow) — a long-running `next dev` process that started
    // before .env.local was correct, or was launched from the wrong cwd, silently keeps proxying
    // to :8000 forever with no visible signal (cost 2 hours to diagnose on Jul-1). Log it loudly
    // every time so a wrong target is immediately visible in the frontend log, not discovered by
    // forensics later.
    const target = process.env.API_PROXY_TARGET || 'http://localhost:8000'
    console.log(`[next.config.js] API proxy target: ${target}${process.env.API_PROXY_TARGET ? '' : ' (DEFAULT — API_PROXY_TARGET not set, check .env.local)'}`)
    return [
      {
        source: '/api/:path*',
        destination: `${target}/api/:path*`,
      },
    ]
  },
}
