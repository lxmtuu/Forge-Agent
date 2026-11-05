/* Capture the three README Web screenshots from real English UI + scripted demo data.
 * Uses a disposable smoke account only; never supply real provider credentials.
 */
const { chromium } = require('playwright');
const path = require('node:path');
const assert = require('node:assert/strict');
const BASE = process.env.FORGE_BASE_URL || 'http://127.0.0.1:8767';
const EMAIL = process.env.FORGE_ADMIN_EMAIL || 'readme-admin@forge.local';
const PASSWORD = process.env.FORGE_ADMIN_PASSWORD || 'readme-fake-password-038-not-real';
const OUT = process.env.FORGE_SCREENSHOT_DIR || path.resolve(__dirname, '../docs/assets');
const VI_TEXT = /[àáạảãâầấậẩẫăằắặẳẵèéẹẻẽêềếệểễìíịỉĩòóọỏõôồốộổỗơờớợởỡùúụủũưừứựửữỳýỵỷỹđ]/i;

async function loginEnglish(page) {
  await page.goto(BASE, { waitUntil: 'networkidle' });
  await page.getByRole('button', { name: 'EN', exact: true }).click();
  await page.locator('input[type=email]').fill(EMAIL);
  await page.locator('input[type=password]').fill(PASSWORD);
  await page.getByRole('button', { name: 'Sign in', exact: true }).click();
  await page.locator('.session-item').first().waitFor({ state: 'attached', timeout: 20000 });
  const dialog = page.locator('.settings-modal');
  if (await dialog.count()) await dialog.getByRole('button', { name: 'Close settings' }).click();
}
async function assertNoVietnamese(page, name) {
  const lines = (await page.locator('body').innerText()).split('\n').map((line) => line.trim()).filter((line) => line && VI_TEXT.test(line));
  assert.deepEqual(lines, [], `${name}: unexpected visible Vietnamese: ${lines.join(' | ')}`);
  console.log(`PASS ${name}: no unintended visible Vietnamese`);
}
(async () => {
  const browser = await chromium.launch({ headless: true, args: ['--no-sandbox'] });
  const context = await browser.newContext({ viewport: { width: 1440, height: 1000 }, deviceScaleFactor: 1 });
  const page = await context.newPage();
  const errors = [];
  page.on('pageerror', (error) => errors.push(String(error)));
  await loginEnglish(page);
  const completed = page.waitForResponse((response) => response.request().method() === 'POST' && /\/api\/sessions\/[^/]+\/chat$/.test(new URL(response.url()).pathname), { timeout: 45000 });
  await page.getByLabel('Task for Forge').fill('Build a Python utility');
  await page.locator('.btn-send').click();
  assert.equal((await completed).status(), 200);
  await page.locator('.btn-send').waitFor({ state: 'visible', timeout: 10000 });
  await page.locator('.tool-card').first().waitFor();
  await page.locator('.tree-row.file').filter({ hasText: 'hello_forge.py' }).waitFor();
  await page.locator('.chat-scroll').evaluate((element) => { element.scrollTop = 0; });
  await page.waitForTimeout(300);
  await assertNoVietnamese(page, 'desktop agent');
  await page.screenshot({ path: path.join(OUT, 'forge-web-agent.png') });

  await page.getByRole('button', { name: '⚙ Settings' }).click();
  const dialog = page.locator('.settings-modal');
  await dialog.getByRole('tab', { name: /Connection/ }).click();
  await dialog.locator('.model-card input[list=models]').waitFor();
  await page.waitForTimeout(250);
  await assertNoVietnamese(page, 'desktop settings');
  await page.screenshot({ path: path.join(OUT, 'forge-web-settings.png') });
  assert.deepEqual(errors, [], errors.join('\n'));
  await context.close();

  const mobile = await browser.newContext({ viewport: { width: 390, height: 844 }, deviceScaleFactor: 1, isMobile: true, hasTouch: true });
  const mobilePage = await mobile.newPage();
  mobilePage.on('pageerror', (error) => errors.push(String(error)));
  await loginEnglish(mobilePage);
  await mobilePage.getByRole('button', { name: 'Session list' }).click();
  await mobilePage.getByRole('button', { name: '＋ New session' }).click();
  await mobilePage.getByRole('button', { name: 'Close sidebar' }).click();
  await mobilePage.locator('.hero').waitFor();
  await mobilePage.waitForTimeout(250);
  await assertNoVietnamese(mobilePage, 'mobile agent');
  await mobilePage.screenshot({ path: path.join(OUT, 'forge-web-mobile.png') });
  assert.deepEqual(errors, [], errors.join('\n'));
  await browser.close();
  console.log(`Saved real English UI screenshots to ${OUT}`);
})().catch((error) => { console.error(error.stack || error); process.exit(1); });
