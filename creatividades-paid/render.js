const { chromium } = require('playwright');
const path = require('path');
const fs = require('fs');

(async () => {
  const browser = await chromium.launch({
    executablePath: '/opt/pw-browsers/chromium-1194/chrome-linux/chrome',
    args: ['--no-sandbox', '--force-color-profile=srgb'],
  });
  const page = await browser.newPage({
    viewport: { width: 1080, height: 1350 },
    deviceScaleFactor: 2,
  });
  const files = fs.readdirSync(__dirname).filter(f => f.endsWith('.html'));
  for (const f of files) {
    await page.goto('file://' + path.join(__dirname, f));
    await page.waitForTimeout(300);
    const out = path.join(__dirname, f.replace('.html', '.png'));
    await page.screenshot({ path: out });
    console.log('rendered', out);
  }
  await browser.close();
})();
