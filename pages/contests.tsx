import Head from 'next/head'
import ContestBrowser from '../components/ContestBrowser'

export default function ContestsPage() {
  return (
    <div className="min-h-screen bg-gray-50">
      <Head>
        <title>Contests • Legendary Picks</title>
        <meta name="description" content="Browse and enter contests" />
      </Head>
      <div className="container mx-auto px-4 py-6">
        <h1 className="text-2xl font-bold mb-4">Contests</h1>
        <ContestBrowser />
      </div>
    </div>
  )
}


