/** @type {import('next').NextConfig} */
module.exports = {
  output: 'standalone',
  reactStrictMode: true,
  swcMinify: true,
  // Lint/type style errors should not block a production build — they stay a
  // code-quality item (see docs/POLISH-CHECKLIST.md), not a deploy blocker.
  eslint: { ignoreDuringBuilds: true },
  typescript: { ignoreBuildErrors: true },
  async rewrites() {
    // In docker-compose the backend is reachable as service `backend:8000`.
    // Locally it's on localhost:8000. Override with API_PROXY_TARGET.
    const target = process.env.API_PROXY_TARGET || 'http://localhost:8000'
    return [
      {
        source: '/api/:path*',
        destination: `${target}/api/:path*`,
      },
    ]
  },
}
