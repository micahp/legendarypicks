import Link from 'next/link'

export default function Layout({ children }: { children: React.ReactNode }) {
  return (
    <div className="min-h-screen bg-ink-900 text-zinc-100">
      <header className="sticky top-0 z-40 border-b border-zinc-800 bg-ink-900/80 backdrop-blur">
        <div className="mx-auto max-w-6xl px-4 h-14 flex items-center justify-between">
          <Link href="/" className="font-extrabold tracking-tight text-xl">
            Legendary Picks
          </Link>
          <nav className="flex items-center gap-4 text-sm">
            <Link href="/scores" className="hover:text-emerald-400">Scores</Link>
            <Link href="/predict" className="hover:text-emerald-400">Predict</Link>
            <Link href="/props" className="hover:text-emerald-400">Props</Link>
            <Link href="/stats" className="hover:text-emerald-400">Stats</Link>
            <Link href="/analytics" className="hover:text-emerald-400">Analytics</Link>
          </nav>
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


