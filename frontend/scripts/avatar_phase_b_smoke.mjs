/**
 * Phase B browser smoke: precompute clip once, replay via speakClip (file + alignment).
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

const canvas = await page.locator('canvas').count();
out.push(`canvas_count=${canvas}`);

const btn = page.getByRole('button', { name: /B · Precompute/ });
await btn.click();

// Wait for synthesis + replay log
await page.waitForFunction(() => {
  const p = document.querySelectorAll('p');
  const last = p[p.length - 1]?.textContent || '';
  return /Phase B OK|Phase B failed|replaying clip/i.test(last);
}, { timeout: 120000 });

await page.waitForTimeout(3500);
const log = await page.locator('p').last().innerText();
out.push(`log=${log}`);

const hard = errors.filter((e) =>
  /Failed to load|404|avatar clip|avatar tts|GLTF|WebGL|Cannot find|smoke-clip/i.test(e)
);
out.push(`console_errors=${errors.length}`);
out.push(`hard_errors=${hard.length}`);
if (hard.length) out.push(`hard=${JSON.stringify(hard)}`);

await page.screenshot({ path: 'avatar-phase-b-smoke.png', fullPage: true });
out.push('screenshot=avatar-phase-b-smoke.png');

await browser.close();
console.log(out.join('\n'));

const ok = canvas >= 1 && /Phase B OK/i.test(log) && hard.length === 0;
if (!ok) process.exit(1);
console.log('PHASE_B_OK');
