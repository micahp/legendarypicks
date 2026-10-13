import { useRouter } from 'next/router'
import SoccerLeaguePage from './soccer'

const LCUP_TABS = new Set(['bracket', 'scores', 'leaders', 'news'])

export default function LeaguesCupSoccerPage() {
  const router = useRouter()
  const requested = typeof router.query.tab === 'string' ? router.query.tab : 'bracket'
  const tab = LCUP_TABS.has(requested) ? requested : 'bracket'
  return <SoccerLeaguePage initialCompetition="lcup" initialSection={tab as 'bracket' | 'scores' | 'leaders' | 'news'} />
}
