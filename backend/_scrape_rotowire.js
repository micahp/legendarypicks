const { chromium } = require('playwright');

(async () => {
  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage();

  // Capture ALL network requests
  const allRequests = [];
  page.on('request', req => {
    const url = req.url();
    if (!url.includes('.css') && !url.includes('.js') && !url.includes('.png') && !url.includes('.svg') && !url.includes('.ico') && !url.includes('fonts')) {
      allRequests.push(url);
    }
  });
  page.on('response', async (resp) => {
    const url = resp.url();
    const ct = resp.headers()['content-type'] || '';
    if (ct.includes('json') && !url.includes('fonts')) {
      try {
        const text = await resp.text();
        console.log(`JSON [${resp.status()}] ${url.slice(0, 120)}`);
        console.log(`  ${text.slice(0, 300)}`);
        console.log();
      } catch {}
    }
  });

  // Try NFL — should have offseason/futures data
  console.log('=== ROTOWIRE NFL PROPS ===');
  await page.goto('https://www.rotowire.com/betting/nfl/player-props.php', {
    waitUntil: 'networkidle',
    timeout: 30000
  }).catch(e => console.log(`Goto error: ${e.message}`));
  await page.waitForTimeout(5000);

  // Dump tables
  const tables = await page.$$('table');
  for (let i = 0; i < Math.min(tables.length, 5); i++) {
    const text = await tables[i].textContent();
    if (text.trim().length > 5) {
      console.log(`\nTable ${i}:`);
      console.log(text.slice(0, 500));
    }
  }

  // Any rows with odds data?
  const bodyText = await page.textContent('body');
  const overMatches = bodyText.match(/OVER\s+\d+\.?\d*/gi) || [];
  const underMatches = bodyText.match(/UNDER\s+\d+\.?\d*/gi) || [];
  console.log(`\n'OVER X.X' matches: ${overMatches.length} — ${overMatches.slice(0,10).join(', ')}`);
  console.log(`'UNDER X.X' matches: ${underMatches.length} — ${underMatches.slice(0,5).join(', ')}`);

  await browser.close();
})();
