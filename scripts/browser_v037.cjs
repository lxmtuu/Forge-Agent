/* v0.37 real-browser UX regression. Uses fake smoke accounts only.
 * Requires a running Forge server and Playwright (npm i --no-save playwright).
 * Override FORGE_BASE_URL and FORGE_{ADMIN,MEMBER}_{EMAIL,PASSWORD} as needed.
 */
const { chromium } = require('playwright');
const assert = require('node:assert/strict');
const BASE = process.env.FORGE_BASE_URL || 'http://127.0.0.1:8766';
const ADMIN = [process.env.FORGE_ADMIN_EMAIL || 'admin-v036@forge.local', process.env.FORGE_ADMIN_PASSWORD || 'smoke-fake-password-036-not-real'];
const MEMBER = [process.env.FORGE_MEMBER_EMAIL || 'member-v036@forge.local', process.env.FORGE_MEMBER_PASSWORD || 'smoke-member-fake-036-not-real'];
const results = [];
const ok = (name, condition, detail = '') => {
  results.push({ name, ok: Boolean(condition), detail });
  console.log(`${condition ? 'PASS' : 'FAIL'} ${name}${detail ? ` — ${detail}` : ''}`);
};
async function login(page, credentials) {
  await page.goto(BASE, { waitUntil: 'networkidle' });
  await page.locator('input[type=email]').fill(credentials[0]);
  await page.locator('input[type=password]').fill(credentials[1]);
  await page.getByRole('button', { name: 'Đăng nhập', exact: true }).click();
  await page.locator('.session-item').first().waitFor({ state: 'attached', timeout: 20000 });
}
async function closeAutoSettings(page) {
  const dialog = page.getByRole('dialog', { name: 'Cài đặt' });
  if (await dialog.count()) await dialog.getByRole('button', { name: 'Đóng cài đặt' }).click();
}
async function section(name, fn) {
  try { await fn(); } catch (error) {
    ok(`${name} — section completed`, false, String(error.message || error).split('\n')[0]);
  }
}
(async () => {
  const browser = await chromium.launch({ headless: true, args: ['--no-sandbox'] });

  await section('settings shell', async () => {
    const context = await browser.newContext({ viewport: { width: 1440, height: 1000 } });
    const page = await context.newPage();
    const errors = [];
    page.on('pageerror', (e) => errors.push(String(e)));
    await login(page, ADMIN);
    const dialog = page.getByRole('dialog', { name: 'Cài đặt' });
    await dialog.waitFor();
    await page.waitForTimeout(220);
    const modal = await dialog.boundingBox();
    const footer = await dialog.locator('.settings-footer').boundingBox();
    ok('Settings footer starts inside dialog viewport', footer.y >= modal.y && footer.y + footer.height <= modal.y + modal.height + 1);
    await dialog.locator('.settings-body').evaluate((el) => { el.scrollTop = el.scrollHeight; });
    await page.waitForTimeout(100);
    const footerAfter = await dialog.locator('.settings-footer').boundingBox();
    ok('Settings footer remains fixed while body scrolls', Math.abs(footer.y - footerAfter.y) < 1);
    ok('Settings body, not whole modal, owns overflow', await dialog.evaluate((el) => el.scrollHeight <= el.clientHeight + 1));
    ok('Dialog receives initial focus', await page.evaluate(() => document.activeElement?.classList.contains('settings-modal')));
    await page.keyboard.press('Shift+Tab');
    ok('Focus trap keeps reverse Tab inside dialog', await page.evaluate(() => Boolean(document.activeElement?.closest('.settings-modal'))));
    await dialog.locator('.settings-body').evaluate((el) => { el.scrollTop = 0; });
    await dialog.getByRole('button', { name: 'Đóng cài đặt' }).click();
    ok('Closing Settings restores trigger focus', await page.evaluate(() => document.activeElement?.textContent?.includes('Cài đặt')));
    ok('No browser runtime error in Settings shell', errors.length === 0, errors.join('; '));
    await context.close();
  });

  await section('settings validation', async () => {
    const context = await browser.newContext({ viewport: { width: 1280, height: 900 } });
    const page = await context.newPage();
    await login(page, ADMIN);
    const dialog = page.getByRole('dialog', { name: 'Cài đặt' });
    await dialog.waitFor();
    const before = await page.evaluate(() => fetch('/api/settings').then((r) => r.json()).then((x) => x.max_tokens));
    let posts = 0;
    page.on('request', (r) => { if (r.url().endsWith('/api/settings') && r.method() === 'POST') posts += 1; });
    await dialog.locator('.model-card input[type=number]').fill('100');
    await dialog.getByRole('button', { name: '💾 Lưu thay đổi' }).click();
    await dialog.getByRole('alert').waitFor();
    ok('Invalid max tokens keeps dialog open', await dialog.isVisible());
    ok('Invalid max tokens shows actionable error', (await dialog.getByRole('alert').innerText()).includes('256 đến 65536'));
    ok('Invalid max tokens does not call settings API', posts === 0);
    const valid = before === 4096 ? 5120 : 4096;
    await dialog.locator('.model-card input[type=number]').fill(String(valid));
    await dialog.getByRole('button', { name: '💾 Lưu thay đổi' }).click();
    await dialog.waitFor({ state: 'hidden' });
    const saved = await page.evaluate(() => fetch('/api/settings').then((r) => r.json()).then((x) => x.max_tokens));
    ok('Valid max tokens still persists', saved === valid, `${before} → ${saved}`);
    await page.getByRole('button', { name: '⚙ Cài đặt' }).click();
    await dialog.locator('.model-card input[type=number]').fill(String(before));
    await dialog.getByRole('button', { name: '💾 Lưu thay đổi' }).click();
    await dialog.waitFor({ state: 'hidden' });
    await context.close();
  });

  await section('connection and appearance', async () => {
    const context = await browser.newContext({ viewport: { width: 1280, height: 900 } });
    const page = await context.newPage();
    await login(page, ADMIN);
    const dialog = page.getByRole('dialog', { name: 'Cài đặt' });
    await dialog.waitFor();
    const provider = dialog.getByLabel('Provider của API key');
    await provider.selectOption('custom');
    ok('Custom base URL appears only in Custom context', await dialog.getByPlaceholder('vd: http://localhost:11434/v1').isVisible());
    await provider.selectOption('openrouter');
    ok('Custom base URL hides after leaving Custom', await dialog.getByPlaceholder('vd: http://localhost:11434/v1').count() === 0);
    await dialog.getByRole('tab', { name: '🎨 Giao diện' }).click();
    await dialog.getByRole('button', { name: '☀ Sáng' }).click();
    ok('Light theme applies immediately', await page.evaluate(() => document.documentElement.dataset.theme === 'light' && localStorage.getItem('forge-theme') === 'light'));
    await dialog.getByRole('button', { name: '🌑 Tối (mặc định)' }).click();
    ok('Dark theme restores cleanly', await page.evaluate(() => !document.documentElement.dataset.theme));
    await context.close();
  });

  await section('model request discipline', async () => {
    const context = await browser.newContext({ viewport: { width: 1440, height: 900 } });
    const page = await context.newPage();
    await login(page, ADMIN);
    await closeAutoSettings(page);
    const input = page.getByLabel('Model cho phiên này');
    await input.waitFor();
    const original = await input.inputValue();
    let patches = 0;
    page.on('request', (r) => { if (r.method() === 'PATCH' && /\/api\/sessions\/[^/]+\/model$/.test(new URL(r.url()).pathname)) patches += 1; });
    await input.focus();
    await page.getByLabel('Nhiệm vụ gửi cho Forge').focus();
    await page.waitForTimeout(180);
    ok('Blur with unchanged model sends no PATCH', patches === 0);
    const alternate = original === 'openrouter:openrouter/free' ? 'google:gemini-3.8-flash' : 'openrouter:openrouter/free';
    let response = page.waitForResponse((r) => r.request().method() === 'PATCH' && /\/model$/.test(r.url()));
    await input.fill(alternate);
    await input.blur();
    await response;
    ok('Changed model sends exactly one PATCH', patches === 1);
    await input.focus();
    await input.blur();
    await page.waitForTimeout(180);
    ok('Second unchanged blur still sends no PATCH', patches === 1);
    response = page.waitForResponse((r) => r.request().method() === 'PATCH' && /\/model$/.test(r.url()));
    await input.fill(original);
    await input.blur();
    await response;
    ok('Original model restored after test', (await input.inputValue()) === original && patches === 2);
    await context.close();
  });

  await section('member capabilities', async () => {
    const context = await browser.newContext({ viewport: { width: 1024, height: 800 } });
    const page = await context.newPage();
    await login(page, MEMBER);
    await page.getByRole('button', { name: '⚙ Cài đặt' }).click();
    const dialog = page.getByRole('dialog', { name: 'Cài đặt' });
    await dialog.waitFor();
    const tabs = await dialog.getByRole('tab').allTextContents();
    ok('Member sees exactly Appearance, Skills and Audit', tabs.length === 3 && tabs.some((x) => x.includes('Giao diện')) && tabs.some((x) => x.includes('Skills')) && tabs.some((x) => x.includes('Audit')), tabs.join(', '));
    ok('Member does not see misleading global lock/save', await dialog.getByRole('button', { name: /Settings đã khóa|Lưu cài đặt/ }).count() === 0);
    ok('Member lands on usable Appearance tab', await dialog.getByRole('tab', { name: '🎨 Giao diện' }).getAttribute('aria-selected') === 'true');
    await dialog.getByRole('button', { name: '☀ Sáng' }).click();
    ok('Member can use local theme without admin ACL change', await page.evaluate(() => document.documentElement.dataset.theme === 'light'));
    await dialog.getByRole('button', { name: '🌑 Tối (mặc định)' }).click();
    await dialog.getByRole('tab', { name: '🎨 Giao diện' }).focus();
    await page.keyboard.press('ArrowRight');
    ok('Arrow key moves Settings tab to Skills', await dialog.getByRole('tab', { name: '🧩 Skills' }).getAttribute('aria-selected') === 'true');
    await context.close();
  });

  await section('mobile drawers', async () => {
    const context = await browser.newContext({ viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true });
    const page = await context.newPage();
    await login(page, ADMIN);
    const dialog = page.getByRole('dialog', { name: 'Cài đặt' });
    await dialog.waitFor();
    const mobileFooter = await dialog.locator('.settings-footer').boundingBox();
    ok('Mobile Settings Save footer is visible', mobileFooter.y >= 0 && mobileFooter.y + mobileFooter.height <= 845);
    await closeAutoSettings(page);
    const dimensions = await page.evaluate(() => ({ body: document.body.scrollWidth, chat: document.querySelector('.chat-pane').getBoundingClientRect().width, files: getComputedStyle(document.querySelector('.files-pane')).display }));
    ok('Mobile has no horizontal overflow or zero-width chat', dimensions.body === 390 && dimensions.chat === 390, JSON.stringify(dimensions));
    ok('Closed mobile Workspace is actually hidden', dimensions.files === 'none');
    await page.getByRole('button', { name: 'Danh sách phiên' }).click();
    ok('Mobile sidebar opens', await page.locator('.sidebar').isVisible());
    const deleteStyle = await page.locator('.session-del').first().evaluate((el) => ({ display: getComputedStyle(el).display, opacity: Number(getComputedStyle(el).opacity) }));
    ok('Touch session delete is visible without hover', deleteStyle.display === 'flex' && deleteStyle.opacity > 0);
    await page.getByRole('button', { name: 'Đóng sidebar' }).click();
    ok('Sidebar close button works', !(await page.locator('.sidebar').isVisible()));
    await page.getByRole('button', { name: 'Danh sách phiên' }).click();
    await page.keyboard.press('Escape');
    ok('Escape closes mobile sidebar', !(await page.locator('.sidebar').isVisible()));
    await page.getByRole('button', { name: 'Mở Workspace' }).click();
    const workspace = page.locator('.files-pane');
    await workspace.waitFor({ state: 'visible' });
    const wr = await workspace.boundingBox();
    ok('Workspace opens as usable mobile drawer', wr.width > 300 && wr.x >= 0 && wr.x + wr.width <= 391, JSON.stringify(wr));
    const actionInside = await workspace.locator('.files-actions button').evaluateAll((els) => els.every((el) => { const r = el.getBoundingClientRect(); return r.left >= 0 && r.right <= innerWidth; }));
    ok('Workspace actions stay inside mobile viewport', actionInside);
    await page.getByRole('button', { name: 'Đóng panel Workspace' }).click();
    ok('Workspace close button works', !(await workspace.isVisible()));
    await page.getByRole('button', { name: 'Mở Workspace' }).click();
    await page.locator('.workspace-scrim').click({ position: { x: 5, y: 400 } });
    ok('Workspace scrim closes drawer', !(await workspace.isVisible()));
    await context.close();
  });

  await section('late session response', async () => {
    const context = await browser.newContext({ viewport: { width: 1440, height: 900 } });
    const page = await context.newPage();
    await login(page, ADMIN);
    await closeAutoSettings(page);
    const input = page.getByLabel('Model cho phiên này');
    const sidA = (await page.locator('.session-heading span').innerText()).replace(/^ID\s+/, '');
    const modelA = await input.inputValue();
    await page.getByRole('button', { name: '＋ Phiên mới' }).click();
    await page.waitForFunction((old) => !document.querySelector('.session-heading span')?.textContent?.includes(old), sidA);
    const sidB = (await page.locator('.session-heading span').innerText()).replace(/^ID\s+/, '');
    const modelB = modelA === 'openrouter:openrouter/free' ? 'google:gemini-3.8-flash' : 'openrouter:openrouter/free';
    let patch = page.waitForResponse((r) => r.request().method() === 'PATCH' && r.url().includes(sidB));
    await input.fill(modelB);
    await input.blur();
    await patch;
    const order = await page.evaluate(() => fetch('/api/sessions').then((r) => r.json()).then((x) => x.sessions.map((s) => s.id)));
    let armed = true;
    let release;
    const gate = new Promise((resolve) => { release = resolve; });
    await page.route(`**/api/sessions/${sidA}`, async (route) => {
      if (armed && route.request().method() === 'GET') { armed = false; await gate; }
      await route.continue();
    });
    const delayed = page.waitForRequest((r) => r.url().endsWith(`/api/sessions/${sidA}`) && r.method() === 'GET');
    await page.locator('.session-item').nth(order.indexOf(sidA)).click();
    await delayed;
    await page.locator('.session-item').nth(order.indexOf(sidB)).click();
    await page.waitForFunction((model) => document.querySelector('#session-model-input')?.value === model, modelB);
    release();
    await page.waitForTimeout(450);
    const currentId = (await page.locator('.session-heading span').innerText()).replace(/^ID\s+/, '');
    ok('Late GET cannot replace current session model', (await input.inputValue()) === modelB && currentId === sidB, `${currentId} · ${await input.inputValue()}`);
    const cookies = await context.cookies();
    const csrf = cookies.find((c) => c.name === 'forge_csrf')?.value;
    const cleanup = await context.request.delete(`${BASE}/api/sessions/${sidB}`, { headers: { 'X-CSRF-Token': csrf || '' } });
    ok('Race-test session cleanup preserves CSRF boundary', cleanup.ok());
    await context.close();
  });

  await browser.close();
  const failed = results.filter((r) => !r.ok);
  console.log(`\n=== v0.37 UX browser: ${results.length - failed.length}/${results.length} PASS ===`);
  if (failed.length) process.exit(1);
})().catch((error) => { console.error(error.stack || error); process.exit(1); });
