import dynamic from 'next/dynamic'

// The landing page uses FCL (wallet + Top Shot moments), which is browser-only and breaks SSR.
// Render it client-side; with Flow disabled the FCL calls resolve to the no-op stub.
const HomeContent = dynamic(() => import('../components/HomeContent'), {
  ssr: false,
  loading: () => (
    <div className="min-h-screen bg-zinc-950 text-zinc-100 px-4 py-8">
      <div className="animate-pulse text-zinc-500">Loading…</div>
    </div>
  ),
})

export default function Home() {
  return <HomeContent />
}
