// Screenshots the dashboard views at 1920x1080 (1280x720 CSS px at 1.5x device scale).
// Usage: node shoot.mjs [outdir]
// The puppeteer require path is a dev-machine convenience; override with
// PUPPETEER_REQUIRE_PATH or install puppeteer-core locally if needed.
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { createRequire } from 'node:module';
const require = createRequire(process.env.PUPPETEER_REQUIRE_PATH || '/tmp/bya-arch/tools/gh/package.json');
const puppeteer = require('puppeteer-core');
const here = path.dirname(fileURLToPath(import.meta.url));
const out = process.argv[2] || path.join(here, 'shots');
import { mkdirSync } from 'node:fs';
mkdirSync(out, { recursive: true });
const browser = await puppeteer.launch({ executablePath: process.env.CHROME_PATH || '/usr/bin/google-chrome', args: ['--no-sandbox', '--disable-gpu', '--allow-file-access-from-files'] });
for (const v of ['live', 'score', 'board']) {
  const page = await browser.newPage();
  const errs = [];
  page.on('pageerror', e => errs.push(e.message));
  page.on('console', m => { if (m.type() === 'error') errs.push(m.text()); });
  await page.setViewport({ width: 1280, height: 720, deviceScaleFactor: 1.5 });
  await page.goto('file://' + path.join(here, 'index.html') + '?view=' + v, { waitUntil: 'networkidle0' });
  await page.evaluate(() => document.fonts.ready);
  const overflow = await page.evaluate(() => {
    const bad = [];
    document.querySelectorAll('.screen, .screen *').forEach(n => {
      if (n.scrollHeight > n.clientHeight + 2 && getComputedStyle(n).overflow === 'hidden') bad.push('clip:' + (n.className || n.tagName));
      const r = n.getBoundingClientRect();
      if (r.bottom > 720 + 1 || r.right > 1280 + 1 || r.top < -1 || r.left < -1) bad.push('off:' + (n.className || n.tagName));
    });
    return [...new Set(bad)].slice(0, 10);
  });
  await page.screenshot({ path: path.join(out, `${v}.png`) });
  console.log(v, 'errors:', errs.length ? errs : 'none', 'overflow:', overflow.length ? overflow : 'none');
  await page.close();
}
await browser.close();
