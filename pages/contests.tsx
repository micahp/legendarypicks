import Head from 'next/head'
import dynamic from 'next/dynamic'

// ContestBrowser pulls in ContestService -> FCL (browser-only, breaks SSR). Render it client-side.
const ContestBrowser = dynamic(() => import('../components/ContestBrowser'), {
  ssr: false,
  loading: () => <div className="animate-pulse text-zinc-500">Loading contests…</div>,
})

export default function ContestsPage() {
  return (
    <>
      <Head>
        <title>Contests • Legendary Picks</title>
        <meta name="description" content="Browse and enter contests" />
      </Head>
      <h1 className="text-3xl font-extrabold tracking-tight">Contests</h1>
      <ContestBrowser />
    </>
  )
}


