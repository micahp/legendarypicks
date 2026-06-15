import Link from 'next/link'

export default function NotFound() {
  return (
    <div className="max-w-md mx-auto text-center py-24 space-y-5">
      <div className="text-8xl font-black text-zinc-800">404</div>
      <h1 className="text-2xl font-bold text-zinc-300">Page not found</h1>
      <p className="text-zinc-500">The page you're looking for doesn't exist or was moved.</p>
      <div className="flex gap-3 justify-center pt-4">
        <Link href="/" className="px-5 py-2.5 rounded-lg bg-emerald-600 hover:bg-emerald-500 text-white font-semibold transition-colors">
          Home
        </Link>
        <Link href="/scores" className="px-5 py-2.5 rounded-lg border border-zinc-700 hover:bg-zinc-800 transition-colors">
          Scores
        </Link>
      </div>
    </div>
  )
}
