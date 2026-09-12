/**
 * Phase C: Hindi expression cue is applied while speaking.
 */
import { chromium } from 'playwright';

const URL = process.env.AVATAR_SMOKE_URL || 'http://127.0.0.1:5173/#avatar-smoke';
const out = [];
const errors = [];

const browser = await chromium.launch({ headless: true });
const page = await browser.newPage();
page.on('console', (msg) => {
  if (msg.type() === 'error') errors.push(msg.text());
});
page.on('pageerror', (err) => errors.push(String(err)));

await page.goto(URL, { waitUntil: 'networkidle', timeout: 60000 });
await page.waitForTimeout(2000);

await page.getByRole('button', { name: /C · Hindi thinking/ }).click();
await page.waitForFunction(() => {
  const last = [...document.querySelectorAll('p')].at(-1)?.textContent || '';
  return /Phase C OK|Phase C failed/i.test(last);
}, { timeout: 120000 });

const log = await page.locator('p').last().innerText();
out.push(`log=${log}`);

const hard = errors.filter((e) =>
  /Failed to load|404|avatar|GLTF|WebGL|Cannot find/i.test(e)
);
out.push(`hard_errors=${hard.length}`);
if (hard.length) out.push(`hard=${JSON.stringify(hard)}`);

await page.screenshot({ path: 'avatar-phase-c-smoke.png', fullPage: true });
await browser.close();

console.log(out.join('\n'));
const ok = /Phase C OK/i.test(log) && /detect=thinking/i.test(log) && /liveExpr=thinking/i.test(log) && hard.length === 0;
if (!ok) process.exit(1);
console.log('PHASE_C_OK');
