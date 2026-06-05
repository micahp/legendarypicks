import '../styles/globals.css'
import { useEffect } from 'react'
import Layout from '../components/Layout'

function MyApp({ Component, pageProps }) {
  // PHASE 1 (games + scores) needs no blockchain. The Flow/FCL stack (@onflow/transport-http) currently
  // crashes on load here, so it's gated OFF by default. Phase 2: set NEXT_PUBLIC_ENABLE_FLOW=true to
  // load the wallet/chain config (after the FCL deps are upgraded to a working version).
  useEffect(() => {
    if (process.env.NEXT_PUBLIC_ENABLE_FLOW === 'true') {
      import('../config/fcl')
    }
  }, [])

  return (
    <Layout>
      <Component {...pageProps} />
    </Layout>
  )
}

export default MyApp
