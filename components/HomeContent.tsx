import { useEffect, useState } from 'react'
import * as fcl from "@onflow/fcl"
import Head from 'next/head'
import GameBrowser from './GameBrowser'
import AccountManager from './AccountManager'
import MomentGallery from './MomentGallery'

// Client-only (loaded via next/dynamic ssr:false from pages/index.tsx). FCL is a browser/wallet lib;
// when Flow is disabled it resolves to config/fcl-stub via the webpack replacement, so this all no-ops.
export default function HomeContent() {
  const [user, setUser] = useState({ loggedIn: false, addr: null })

  useEffect(() => {
    fcl.currentUser.subscribe(setUser)
  }, [])

  const login = () => {
    fcl.authenticate()
  }

  const logout = () => {
    fcl.unauthenticate()
  }

  return (
    <div className="min-h-screen bg-zinc-950 text-zinc-100 px-4 py-8">
      <Head>
        <title>Legendary Picks</title>
        <meta name="description" content="NBA Fantasy Game on Flow" />
        <link rel="icon" href="/favicon.ico" />
      </Head>

      {/* Hero */}
      <section className="relative overflow-hidden rounded-2xl border border-zinc-800 bg-gradient-to-br from-zinc-900 via-ink-900 to-zinc-900 p-8 md:p-12">
        <div className="relative z-10 max-w-3xl">
          <h1 className="text-4xl md:text-6xl font-extrabold tracking-tight leading-tight">
            Own the Moment. Rule the Board.
          </h1>
          <p className="mt-4 text-zinc-300 max-w-xl">
            Draft with on-chain clout and track the NBA like a pro. Connect your wallet,
            browse Top Shot moments, and make the picks that matter.
          </p>
          <div className="mt-6 flex flex-wrap gap-3">
            <button onClick={user.loggedIn ? logout : login} className="btn-primary">
              {user.loggedIn ? 'Disconnect' : 'Connect Wallet'}
            </button>
            <a href="/scores" className="px-4 py-2 rounded-lg border border-zinc-700 hover:bg-zinc-800">View Scores</a>
            <a href="/contests" className="px-4 py-2 rounded-lg border border-zinc-700 hover:bg-zinc-800">Contests</a>
          </div>
          {user.loggedIn && (
            <div className="mt-4 text-sm text-zinc-400">
              Connected: {user.addr?.slice(0, 6)}...{user.addr?.slice(-4)}
            </div>
          )}
        </div>
        <div className="pointer-events-none absolute -right-24 -bottom-24 h-72 w-72 rounded-full bg-emerald-500/10 blur-3xl" />
      </section>

      {/* Main */}
      <main className="space-y-8 mt-8">
        <section>
          <h2 className="text-xl font-bold mb-3">Moments Gallery</h2>
          <MomentGallery />
        </section>


        {user.loggedIn && (
          <>
            <section>
              <h2 className="text-xl font-bold mb-3">Account</h2>
              <AccountManager />
            </section>
            <section>
              <h2 className="text-xl font-bold mb-3">Upcoming Games</h2>
              <GameBrowser />
            </section>
          </>
        )}
      </main>
    </div>
  )
}
