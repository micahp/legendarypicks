import { useRouter } from 'next/router'
import LeagueDesk from '../../components/Esports/LeagueDesk'

export default function EsportsTitlePage() {
  const router = useRouter()
  const title = typeof router.query.title === 'string' ? router.query.title : undefined

  if (!router.isReady || !title) return null

  return (
    <LeagueDesk
      slug={title}
      onSelectTitle={(slug) => router.push(`/esports/${slug}`)}
    />
  )
}
