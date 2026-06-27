import Link from 'next/link'
import GlobalSearch from './GlobalSearch'

export default function Layout({ children }: { children: React.ReactNode }) {
  return (
    <div className="min-h-screen bg-ink-900 text-zinc-100">
      <header className="sticky top-0 z-40 border-b border-zinc-800 bg-ink-900/80 backdrop-blur">
        <div className="mx-auto max-w-6xl px-4 py-2 space-y-2">
          <Link href="/" className="block w-fit font-extrabold tracking-tight text-xl whitespace-nowrap">
            Legendary Picks
          </Link>
          <div className="flex items-center justify-between gap-3 min-w-0">
            <nav className="flex items-center gap-3 sm:gap-4 text-sm overflow-x-auto [scrollbar-width:none] [&::-webkit-scrollbar]:hidden">
              <Link href="/scores" className="hover:text-emerald-400 whitespace-nowrap">Scores</Link>
              <Link href="/predict" className="hover:text-emerald-400 whitespace-nowrap">Predict</Link>
              <Link href="/props" className="hover:text-emerald-400 whitespace-nowrap">Props</Link>
              <Link href="/stats" className="hover:text-emerald-400 whitespace-nowrap">Stats</Link>
              <Link href="/analytics" className="hover:text-emerald-400 whitespace-nowrap">Analytics</Link>
            </nav>
            <GlobalSearch />
          </div>
        </div>
      </header>
      <main className="mx-auto max-w-6xl px-4 py-8 space-y-6">{children}</main>
      <footer className="border-t border-zinc-800 py-8">
        <div className="mx-auto max-w-6xl px-4 text-sm text-zinc-500">
          © {new Date().getFullYear()} Legendary Picks. Not affiliated with the NBA.
        </div>
      </footer>
    </div>
  )
}


