import Head from 'next/head'
import ContestBrowser from '../components/ContestBrowser'

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


