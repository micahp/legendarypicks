export function uniqueLineOptions<T extends { line: number }>(offers: T[]): T[] {
  const byLine = new Map<number, T>()
  for (const offer of offers) {
    if (!byLine.has(offer.line)) byLine.set(offer.line, offer)
  }
  return Array.from(byLine.values()).sort((a, b) => a.line - b.line)
}
