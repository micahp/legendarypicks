import Head from 'next/head'
import Link from 'next/link'

export default function ContestsPage() {
  return (
    <>
      <Head>
        <title>Contests • Legendary Picks</title>
        <meta name="description" content="Browse and enter sports prediction contests" />
      </Head>
      <div className="max-w-2xl mx-auto text-center py-16 space-y-4">
        <h1 className="text-3xl font-extrabold tracking-tight">Contests</h1>
        <p className="text-zinc-400">Prediction contests are coming soon. For now, check out the scoreboard and make your picks.</p>
        <Link href="/predict" className="inline-block mt-4 px-5 py-2.5 rounded-lg bg-emerald-600 hover:bg-emerald-500 text-white font-semibold transition-colors">
          Make Predictions
        </Link>
      </div>
    </>
  )
}


