/**
 * Phase A browser smoke: avatar mesh loads, canvas paints, speak returns TTS.
 * Run: npx playwright test --config=playwright.avatar.config.mjs
 * Or:  node scripts/avatar_phase_a_smoke.mjs
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
await page.waitForTimeout(2500);

const canvas = await page.locator('canvas').count();
out.push(`canvas_count=${canvas}`);

const gltf = await page.evaluate(async () => {
  const r = await fetch('/avatar/characters/Brenin_Avatar/Brenin.gltf');
  return { status: r.status, cache: r.headers.get('cache-control'), len: (await r.arrayBuffer()).byteLength };
});
out.push(`gltf=${JSON.stringify(gltf)}`);

const btn = page.getByRole('button', { name: 'Speak Hindi' });
await btn.click();
await page.waitForTimeout(4000);

const speakingBadgeOrLog = await page.locator('p').last().innerText();
out.push(`log=${speakingBadgeOrLog}`);

// Allow WebGL context; fail on hard asset/TTS errors
const hard = errors.filter((e) =>
  /Failed to load|404|avatar tts|GLTF|WebGL|Cannot find/i.test(e)
);
out.push(`console_errors=${errors.length}`);
out.push(`hard_errors=${hard.length}`);
if (hard.length) out.push(`hard=${JSON.stringify(hard)}`);

await page.screenshot({ path: 'frontend/avatar-phase-a-smoke.png', fullPage: true });
out.push('screenshot=frontend/avatar-phase-a-smoke.png');

await browser.close();

console.log(out.join('\n'));
if (canvas < 1 || gltf.status !== 200 || hard.length) {
  process.exit(1);
}
console.log('PHASE_A_OK');
