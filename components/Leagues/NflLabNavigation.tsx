import Link from 'next/link'

export type NflLabRoom = 'hq' | 'slate' | 'forecasts' | 'props' | 'projections' | 'matchups' | 'stats'

const ROOMS: { id: NflLabRoom; label: string; href: string }[] = [
  { id: 'hq', label: 'HQ', href: '/leagues/nfl?tab=camp' },
  { id: 'slate', label: 'Slate', href: '/leagues/nfl?tab=schedule' },
  { id: 'forecasts', label: 'Forecasts', href: '/leagues/nfl?tab=model' },
  { id: 'props', label: 'Player props', href: '/props?league=nfl' },
  { id: 'projections', label: 'Projections', href: '/nfl/projections' },
  { id: 'matchups', label: 'Matchups', href: '/props?league=nfl&tab=matchups' },
  { id: 'stats', label: 'Stats', href: '/leagues/nfl?tab=stats' },
]

export default function NflLabNavigation({ active }: { active: NflLabRoom }) {
  return (
    <nav aria-label="NFL lab rooms" className="lp-lab-nav">
      <span className="lp-lab-nav-title"><span aria-hidden="true">◆</span> NFL LAB</span>
      <div className="lp-lab-nav-links">
        {ROOMS.map(room => (
          <Link
            key={room.id}
            href={room.href}
            aria-current={active === room.id ? 'page' : undefined}
            className={`lp-lab-nav-link${active === room.id ? ' is-active' : ''}`}
          >
            {room.label}
          </Link>
        ))}
      </div>
    </nav>
  )
}
