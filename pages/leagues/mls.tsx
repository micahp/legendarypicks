import { useRouter } from 'next/router'
import SoccerLeaguePage from './soccer'

const MLS_TABS = new Set(['scores', 'standings', 'stats', 'news'])

export default function MlsSoccerPage() {
  const router = useRouter()
  const requested = typeof router.query.tab === 'string' ? router.query.tab : 'scores'
  const tab = MLS_TABS.has(requested) ? requested : 'scores'
  return <SoccerLeaguePage initialCompetition="mls" initialSection={tab as 'scores' | 'standings' | 'stats' | 'news'} />
}
