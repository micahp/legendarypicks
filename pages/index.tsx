import Head from 'next/head'
import HeroCarousel from '../components/Home/HeroCarousel'
import QuestionsSection from '../components/Home/QuestionsSection'
import ChainSection from '../components/Home/ChainSection'
import TrustSection from '../components/Home/TrustSection'
import PlansSection from '../components/Home/PlansSection'
import { useFeatured } from '../components/Home/useFeatured'

const TITLE = 'Legendary Picks: live prop lines and hit rate history across 11 leagues'
const DESCRIPTION =
  'See how often any player has cleared a line over their last 5, 10 and 20 games and the full season before you decide.'

// Production hides the member plan until a price exists by setting NEXT_PUBLIC_HOME_MEMBERSHIP=off
// at build time. Every number in the hero and the chain cards is read from /api/home/featured.
export default function Home() {
  const featured = useFeatured()
  const showMembership = process.env.NEXT_PUBLIC_HOME_MEMBERSHIP !== 'off'
  return (
    <>
      <Head>
        <title>{TITLE}</title>
        <meta name="description" content={DESCRIPTION} />
        <link rel="canonical" href="https://legendarypicks.xyz/" />
        {/* Open Graph (Facebook/LinkedIn/iMessage/etc.) */}
        <meta property="og:title" content={TITLE} />
        <meta property="og:description" content={DESCRIPTION} />
        <meta property="og:image" content="https://legendarypicks.xyz/og-image.png" />
        <meta property="og:image:width" content="1200" />
        <meta property="og:image:height" content="630" />
        <meta property="og:url" content="https://legendarypicks.xyz/" />
        <meta property="og:type" content="website" />
        <meta property="og:site_name" content="Legendary Picks" />
        {/* Twitter / X card */}
        <meta name="twitter:card" content="summary_large_image" />
        <meta name="twitter:title" content={TITLE} />
        <meta name="twitter:description" content={DESCRIPTION} />
        <meta name="twitter:image" content="https://legendarypicks.xyz/og-image.png" />
      </Head>

      <div className="space-y-11">
        <HeroCarousel featured={featured} />
        <QuestionsSection />
        <ChainSection featured={featured} />
        <TrustSection featured={featured} />
        {showMembership && <PlansSection />}
      </div>
    </>
  )
}
