import '../styles/globals.css'
import Head from 'next/head'
import Layout from '../components/Layout'

function MyApp({ Component, pageProps }) {
  return (
    <>
      <Head>
        <link rel="icon" href="/favicon.ico" sizes="32x32" />
        <link rel="icon" href="/logo-192.png" sizes="192x192" type="image/png" />
        <link rel="apple-touch-icon" href="/logo-180.png" />
        <link rel="manifest" href="/manifest.json" />
        <meta name="theme-color" content="#0f0f11" />
      </Head>
      <Layout>
        <Component {...pageProps} />
      </Layout>
    </>
  )
}

export default MyApp
