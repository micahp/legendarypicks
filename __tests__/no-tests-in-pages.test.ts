import fs from 'fs'
import path from 'path'

// A ROUTE is a page file and nothing else. There is no `pageExtensions` in
// next.config.js (it is a whitelist of extensions, and cannot exclude
// `.test.tsx` without renaming every page to `.page.tsx`), so EVERY .tsx under
// pages/ is built as a page. A test file there fails `next build` with
// "Failed to collect page data" / "ReferenceError: beforeEach is not defined".
//
// This has happened TWICE. 8b296db on 2026-08-17 -- "fix(build): a test file
// inside pages/ is a route, and it broke the production build" -- fixed the
// instance by moving the file. On 2026-08-26 it was reintroduced exactly the
// same way, and was caught by a failed prod deploy rather than by anything
// cheaper.
//
// Moving the file fixes the instance; this fixes the mechanism. It lives in the
// jest suite because that is what gets run before a build: jest does not care
// where a test file sits, and `tsc` does not either, so both stayed green while
// the production image could not be built at all.
function walk(dir: string, hits: string[] = []): string[] {
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    const full = path.join(dir, entry.name)
    if (entry.isDirectory()) walk(full, hits)
    else if (/\.(test|spec)\.(tsx?|jsx?)$/.test(entry.name)) hits.push(full)
  }
  return hits
}

describe('pages/ contains routes only', () => {
  it('has no test files, which next build would treat as pages', () => {
    const pagesDir = path.join(__dirname, '..', 'pages')
    const offenders = walk(pagesDir).map(p => path.relative(path.join(__dirname, '..'), p))
    expect(offenders).toEqual([])
  })
})
