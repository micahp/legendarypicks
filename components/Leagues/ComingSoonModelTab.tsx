import Head from 'next/head'

export default function ComingSoonModelTab() {
  return (
    <>
      <Head>
        <link
          rel="stylesheet"
          href="https://fonts.googleapis.com/css2?family=Material+Symbols+Outlined:opsz,wght,FILL,GRAD@24,400,0,0&display=block&icon_names=neurology"
        />
      </Head>
      <div className="space-y-2 py-16 text-center text-zinc-500">
        <div aria-hidden="true" className="material-symbols-outlined text-4xl leading-none">neurology</div>
        <p className="text-sm">Coming soon</p>
      </div>
    </>
  )
}
