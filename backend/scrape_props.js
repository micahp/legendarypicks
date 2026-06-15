#!/usr/bin/env node
/**
 * scrape_props.js — scrape RotoWire player props into JSON via Playwright.
 *
 * Usage: node scrape_props.js <league>   # nba | mlb | nfl | nhl
 * Output: NDJSON on stdout, one prop per line.
 *
 * Each line:
 *   {"player_name":"Jayson Tatum","team":"BOS","market":"points","line":27.5,"side":"over","sportsbook":"DraftKings","opponent":"GSW","game_time":"2026-06-15T19:00:00Z"}
 *
 * Only works during game hours — pages show "no odds available" otherwise.
 */

const { chromium } = require('playwright');

const LEAGUE_MAP = {
  nba: 'nba',
  mlb: 'mlb',
  nfl: 'nfl',
  nhl: 'nhl',
};

const league = process.argv[2];
if (!league || !LEAGUE_MAP[league]) {
  console.error('Usage: node scrape_props.js <nba|mlb|nfl|nhl>');
  process.exit(1);
}

// Market name normalization: what RotoWire calls it → our canonical name
const MARKET_MAP = {
  'batting moneylines': null, // skip
  'strikeouts': 'strikeouts',
  'earned runs': 'earned_runs',
  'total bases': 'total_bases',
  'runs scored': 'runs',
  'hits': 'hits',
  'home runs': 'home_runs',
  'rbis': 'rbis',
  'stolen bases': 'stolen_bases',
  'points': 'points',
  'rebounds': 'rebounds',
  'assists': 'assists',
  'threes': 'threes',
  'blocks': 'blocks',
  'steals': 'steals',
  'turnovers': 'turnovers',
  'pass yards': 'passing_yards',
  'pass tds': 'passing_tds',
  'rush yards': 'rushing_yards',
  'rush + rec yards': 'rush_rec_yards',
  'rec yards': 'receiving_yards',
  'receptions': 'receptions',
  'completions': 'completions',
  'pass attempts': 'pass_attempts',
  'ints thrown': 'interceptions',
  'sacks': 'sacks',
  'total tackles': 'tackles',
  'fantasy score': 'fantasy_score',
  'goals': 'goals',
  'shots': 'shots',
  'saves': 'saves',
  'power play points': 'powerplay_points',
};

const SPORTSBOOKS = ['DraftKings', 'FanDuel', 'BetMGM', 'Caesars', 'BetRivers', 'Hard Rock', 'theScore'];

async function main() {
  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage({ viewport: { width: 1400, height: 900 } });

  const url = `https://www.rotowire.com/betting/${league}/player-props.php`;
  console.error(`Loading ${url}...`);

  await page.goto(url, { waitUntil: 'networkidle', timeout: 30000 });
  await page.waitForTimeout(3000);

  // ── Extract sportsbook columns from the "Pick Your Sportsbook" selector ──
  // The page has a sportsbook picker; find which books are active
  const activeBooks = await page.$$eval('[class*="sportsbook"] button, [class*="book"] button, .book-selector button', els =>
    els.filter(el => el.textContent.trim()).map(el => el.textContent.trim())
  );
  console.error(`Active sportsbooks: ${activeBooks.join(', ') || 'none found'}`);

  // ── Extract prop sections ──
  // Each section has: a heading (market name) + a table with player rows
  const sections = await page.$$('[class*="prop-group"], [class*="prop-section"], section[class*="prop"], .prop-table-container');
  console.error(`Found ${sections.length} prop sections`);

  const results = [];

  for (const section of sections) {
    // Get the market name from the heading
    const heading = await section.$('h2, h3, h4, [class*="title"], [class*="heading"]');
    let marketName = heading ? (await heading.textContent()).trim().toLowerCase() : '';

    // Clean market name
    marketName = marketName.replace(/loading.*/i, '').trim();
    const canonicalMarket = MARKET_MAP[marketName];
    if (!canonicalMarket) {
      // Try to find the closest match
      const matched = Object.entries(MARKET_MAP).find(([k]) => marketName.includes(k) || k.includes(marketName));
      if (!matched || !matched[1]) continue;
      marketName = matched[1];
    } else {
      marketName = canonicalMarket;
    }

    // Get all rows in the table
    const rows = await section.$$('tr');
    for (const row of rows) {
      const cells = await row.$$('td');
      if (cells.length < 3) continue; // skip header rows

      const cellTexts = await Promise.all(cells.map(c => c.textContent().then(t => t.trim())));

      // First cell should be player name, remaining are odds from different books
      const playerText = cellTexts[0];
      if (!playerText || playerText === 'Player' || playerText.includes('Loading')) continue;

      // Parse player name + team (format: "Jayson Tatum BOS")
      const playerMatch = playerText.match(/^(.+?)\s+([A-Z]{2,4})$/) || playerText.match(/^(.+?)$/);
      const playerName = playerMatch ? playerMatch[1].trim() : playerText;
      const team = playerMatch && playerMatch[2] ? playerMatch[2] : '';

      // Parse odds cells — format is typically "O 27.5\n-110" or "O 27.5 (-110)"
      for (let i = 1; i < cellTexts.length && i <= SPORTSBOOKS.length; i++) {
        const cellText = cellTexts[i];
        if (!cellText || cellText === '-' || cellText === '—') continue;

        // Try to parse over/under line
        // Patterns: "O 27.5\n-110", "U 4.5\n+105", "O 27.5", "OVER 27.5"
        const overMatch = cellText.match(/[OU]\s*(\d+\.?\d*)/i);
        const overMatch2 = cellText.match(/(?:OVER|UNDER)\s+(\d+\.?\d*)/i);
        const match = overMatch || overMatch2;

        if (match) {
          const side = cellText.match(/^O|OVER/i) ? 'over' : 
                       cellText.match(/^U|UNDER/i) ? 'under' : null;
          if (!side) continue;

          results.push({
            player_name: playerName,
            team: team,
            market: marketName,
            line: parseFloat(match[1]),
            side: side,
            sportsbook: SPORTSBOOKS[i - 1] || `book${i}`,
            league: league,
          });
        }
      }
    }
  }

  // ── Also try a broader scrape: look for any elements with data attributes ──
  // Many sites store prop data in data-* attributes or JSON blobs
  if (results.length === 0) {
    console.error('No results from table parsing, trying data attributes...');

    // Try to find script tags with JSON
    const scripts = await page.$$('script[type="application/json"], script[data-props]');
    for (const script of scripts) {
      const text = await script.textContent();
      try {
        const data = JSON.parse(text);
        console.error(`Found JSON blob with keys: ${Object.keys(data).join(', ')}`);
      } catch {}
    }

    // Dump any element with 'prop' in class
    const propElements = await page.$$('[class*="prop"]');
    for (const el of propElements.slice(0, 20)) {
      const text = (await el.textContent()).trim();
      if (text.length > 10 && text.length < 200 && /\d+\.\d+/.test(text)) {
        console.error(`  Prop element: ${text.slice(0, 150)}`);
      }
    }
  }

  // Output NDJSON
  for (const r of results) {
    console.log(JSON.stringify(r));
  }

  console.error(`Total props scraped: ${results.length}`);
  await browser.close();
}

main().catch(e => {
  console.error(`Fatal: ${e.message}`);
  process.exit(1);
});
