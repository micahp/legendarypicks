import { useEffect, useState } from 'react'
import * as fcl from "@onflow/fcl"
import Head from 'next/head'
import styles from '../styles/Home.module.css'
import Links from '../components/Links'
import Container from '../components/Container'
import GameBrowser from '../components/GameBrowser'
import AccountManager from '../components/AccountManager'
import ContestBrowser from '../components/ContestBrowser'
import MomentGallery from '../components/MomentGallery'

export default function Home() {
  const [user, setUser] = useState({ loggedIn: false })

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
    <div className="container mx-auto px-4">
      <Head>
        <title>FCL Next Scaffold</title>
        <meta name="description" content="FCL Next Scaffold for the Flow Blockchain" />
        <link rel="icon" href="/favicon.ico" />
      </Head>

      <header className="py-6 flex justify-between items-center">
        <h1 className="text-3xl font-bold">Legendary Picks</h1>
        {user.loggedIn ? (
          <button 
            onClick={logout}
            className="bg-red-500 text-white px-4 py-2 rounded"
          >
            Logout
          </button>
        ) : (
          <button 
            onClick={login}
            className="bg-blue-500 text-white px-4 py-2 rounded"
          >
            Connect Wallet
          </button>
        )}
      </header>

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
  )
}
