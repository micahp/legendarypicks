import { useEffect, useState } from 'react'
import * as fcl from "@onflow/fcl"
import Head from 'next/head'
import GameBrowser from '../components/GameBrowser'
import AccountManager from '../components/AccountManager'
import ContestBrowser from '../components/ContestBrowser'
import MomentGallery from '../components/MomentGallery'

export default function Home() {
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
    <div className="min-h-screen bg-gray-50">
      {/* Sticky Header */}
      <header className="sticky top-0 z-50 bg-white border-b border-gray-200 shadow-sm">
        <div className="container mx-auto px-4">
          <div className="flex justify-between items-center h-16">
            <h1 className="text-2xl font-bold bg-gradient-to-r from-blue-600 to-blue-400 bg-clip-text text-transparent">
              Legendary Picks
            </h1>
            <div className="flex items-center gap-4">
              {user.loggedIn && (
                <span className="text-sm text-gray-500">
                  {user.addr?.slice(0, 6)}...{user.addr?.slice(-4)}
                </span>
              )}
              <button 
                onClick={user.loggedIn ? logout : login}
                className={`px-4 py-2 rounded-lg font-medium transition-all duration-200 ${
                  user.loggedIn 
                    ? 'bg-red-500 text-white hover:bg-red-600' 
                    : 'bg-gradient-to-r from-blue-600 to-blue-400 text-white hover:from-blue-700 hover:to-blue-500'
                }`}
              >
                {user.loggedIn ? "Disconnect" : "Connect Wallet"}
              </button>
            </div>
          </div>
        </div>
      </header>

      {/* Main Content */}
      <div className="container mx-auto px-4 py-6">
        <Head>
          <title>Legendary Picks</title>
          <meta name="description" content="NBA Fantasy Game on Flow" />
          <link rel="icon" href="/favicon.ico" />
        </Head>

        <main className="space-y-8">
          {user.loggedIn && (
            <>
              <AccountManager />
              <MomentGallery />
              <GameBrowser />
              <ContestBrowser />
            </>
          )}
        </main>
      </div>
    </div>
  )
}
