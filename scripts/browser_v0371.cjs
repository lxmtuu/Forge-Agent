/* v0.37.1 real-browser regression: SSE provider errors must remain visible.
 * Uses a mocked chat response and fake smoke credentials only; no real provider call.
 * Run against a production-bundle test server with the smoke admin account:
 *   FORGE_BASE_URL=http://127.0.0.1:8767 node scripts/browser_v0371.cjs
 */
const { chromium } = require('playwright');

const BASE = process.env.FORGE_BASE_URL || 'http://127.0.0.1:8767';
const EMAIL = process.env.FORGE_ADMIN_EMAIL || 'admin-v036@forge.local';
const PASSWORD = process.env.FORGE_ADMIN_PASSWORD || 'smoke-fake-password-036-not-real';

(async () => {
  const browser = await chromium.launch({ headless: true, args: ['--no-sandbox'] });
  const page = await browser.newPage({ viewport: { width: 1280, height: 850 } });
  const runtimeErrors = [];
  page.on('pageerror', (error) => runtimeErrors.push(String(error)));
  await page.goto(BASE, { waitUntil: 'networkidle' });
  await page.locator('input[type=email]').fill(EMAIL);
  await page.locator('input[type=password]').fill(PASSWORD);
  await page.getByRole('button', { name: 'Đăng nhập', exact: true }).click();
  await page.locator('.session-item').first().waitFor();
  const dialog = page.getByRole('dialog', { name: 'Cài đặt' });
  if (await dialog.count()) await dialog.getByRole('button', { name: 'Đóng cài đặt' }).click();
  const created = page.waitForResponse((response) =>
    response.url().endsWith('/api/sessions') && response.request().method() === 'POST');
  await page.getByRole('button', { name: '＋ Phiên mới' }).click();
  await created;
  await page.locator('.hero').waitFor({ state: 'visible' });
  await page.route('**/api/sessions/*/chat', (route) => route.fulfill({
    status: 200,
    contentType: 'text/event-stream',
    body: 'data: {"type":"error","message":"OpenRouter 401 — mocked auth failure"}\n\ndata: {"type":"done"}\n\n',
  }));
  const input = page.locator('.composer textarea');
  await input.fill('test giữ lỗi SSE');
  await page.locator('.btn-send').click();
  const error = page.locator('.error-msg').filter({ hasText: 'OpenRouter 401 — mocked auth failure' });
  await error.waitFor({ state: 'visible' });
  await page.waitForTimeout(1500);
  if (!await error.isVisible()) throw new Error('SSE error disappeared after reload');
  if (!await page.getByText('test giữ lỗi SSE', { exact: true }).isVisible()) {
    throw new Error('User prompt missing');
  }
  if (runtimeErrors.length) throw new Error(runtimeErrors.join('\n'));
  console.log('PASS: SSE provider error remains visible; prompt preserved; no runtime errors');
  await browser.close();
})().catch((error) => {
  console.error(error.stack || error);
  process.exit(1);
});
