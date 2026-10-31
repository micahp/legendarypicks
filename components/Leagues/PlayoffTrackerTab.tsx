// CFB Playoff Tracker tab — shows playoff bracket progression, conference championship results,
// and final four matchups for the current NCAA football season.
export default function PlayoffTrackerTab() {
  return (
    <div className="space-y-2 py-16 text-center text-zinc-500">
      <div aria-hidden="true" className="material-symbols-outlined text-4xl leading-none">
        undo
      </div>
      <p className="text-sm">Playoff Tracker</p>
      <p className="text-xs text-zinc-400">Conference championships • Final Four • National Championship</p>
    </div>
  );
}
