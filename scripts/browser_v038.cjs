/* v0.38.0 real-browser English/i18n regression. Fake smoke accounts and demo data only.
 * Requires a running production-bundle Forge server and Playwright.
 */
const { chromium } = require('playwright');
const assert = require('node:assert/strict');
const BASE = process.env.FORGE_BASE_URL || 'http://127.0.0.1:8766';
const ADMIN = [process.env.FORGE_ADMIN_EMAIL || 'admin-v036@forge.local', process.env.FORGE_ADMIN_PASSWORD || 'smoke-fake-password-036-not-real'];
const MEMBER = [process.env.FORGE_MEMBER_EMAIL || 'member-v036@forge.local', process.env.FORGE_MEMBER_PASSWORD || 'smoke-member-fake-036-not-real'];
const results = [];
const runtimeErrors = [];
const ok = (name, condition, detail = '') => {
  results.push({ name, ok: Boolean(condition), detail });
  console.log(`${condition ? 'PASS' : 'FAIL'} ${name}${detail ? ` — ${detail}` : ''}`);
};
function watch(page) {
  page.on('pageerror', (error) => runtimeErrors.push(String(error)));
  return page;
}
async function closeSettings(page) {
  const dialog = page.locator('.settings-modal');
  if (await dialog.count()) await dialog.getByRole('button', { name: /Close settings|Đóng cài đặt/ }).click();
}
async function login(page, credentials, english = true) {
  await page.goto(BASE, { waitUntil: 'networkidle' });
  if (english) await page.getByRole('button', { name: 'EN', exact: true }).click();
  await page.locator('input[type=email]').fill(credentials[0]);
  await page.locator('input[type=password]').fill(credentials[1]);
  await page.getByRole('button', { name: english ? 'Sign in' : 'Đăng nhập', exact: true }).click();
  await page.locator('.session-item').first().waitFor({ state: 'attached', timeout: 20000 });
}
async function section(name, fn) {
  try { await fn(); } catch (error) {
    ok(`${name} — section completed`, false, String(error.message || error).split('\n')[0]);
  }
}
(async () => {
  const browser = await chromium.launch({ headless: true, args: ['--no-sandbox'] });

  await section('login and persistence', async () => {
    const context = await browser.newContext({ viewport: { width: 1440, height: 950 } });
    const page = watch(await context.newPage());
    await page.goto(BASE, { waitUntil: 'networkidle' });
    ok('Login defaults to Vietnamese for a new device', await page.getByRole('button', { name: 'Đăng nhập', exact: true }).isVisible());
    await page.getByRole('button', { name: 'EN', exact: true }).click();
    ok('Login switches to English before authentication', await page.getByRole('heading', { name: 'Private team sign in' }).isVisible());
    ok('Language choice updates html lang and local storage', await page.evaluate(() => document.documentElement.lang === 'en' && localStorage.getItem('forge-language') === 'en'));
    await page.locator('input[type=email]').fill(ADMIN[0]);
    await page.locator('input[type=password]').fill('definitely-wrong-fake-password');
    await page.getByRole('button', { name: 'Sign in', exact: true }).click();
    await page.getByText('Incorrect email or password', { exact: true }).waitFor();
    ok('Login errors are localized', await page.getByText('Incorrect email or password', { exact: true }).isVisible());
    await page.locator('input[type=password]').fill(ADMIN[1]);
    await page.getByRole('button', { name: 'Sign in', exact: true }).click();
    await page.locator('.session-item').first().waitFor();
    await closeSettings(page);
    await page.reload({ waitUntil: 'networkidle' });
    await closeSettings(page);
    ok('English survives a full reload', await page.evaluate(() => document.documentElement.lang === 'en') && await page.getByRole('button', { name: '⚙ Settings' }).isVisible());
    ok('Composer and navigation use English accessible text', await page.getByLabel('Task for Forge').isVisible() && await page.getByRole('button', { name: '＋ New session' }).isVisible());
    await context.close();
  });

  await section('admin settings and validation', async () => {
    const context = await browser.newContext({ viewport: { width: 1440, height: 950 } });
    const page = watch(await context.newPage());
    await login(page, ADMIN);
    const dialog = page.locator('.settings-modal');
    await dialog.waitFor();
    const expectedTabs = ['Connection', 'Appearance', 'Team', 'Security', 'MCP', 'Connectors', 'Skills', 'Audit', 'System'];
    const tabs = await dialog.getByRole('tab').allTextContents();
    ok('Admin Settings tabs are English', expectedTabs.every((name) => tabs.some((tab) => tab.includes(name))), tabs.join(', '));
    for (const name of expectedTabs) {
      await dialog.getByRole('tab', { name: new RegExp(name) }).click();
      assert.equal(await dialog.getByRole('tab', { name: new RegExp(name) }).getAttribute('aria-selected'), 'true');
    }
    ok('Every admin Settings tab opens without runtime failure', runtimeErrors.length === 0, runtimeErrors.join('; '));
    await dialog.getByRole('tab', { name: /Appearance/ }).click();
    await dialog.getByRole('button', { name: 'Tiếng Việt', exact: true }).click();
    ok('Appearance selector switches English → Vietnamese', await dialog.getByRole('tab', { name: /Giao diện/ }).isVisible());
    await dialog.getByRole('button', { name: 'English', exact: true }).click();
    ok('Appearance selector switches Vietnamese → English', await dialog.getByRole('tab', { name: /Appearance/ }).isVisible());
    await dialog.getByRole('tab', { name: /Connection/ }).click();
    await dialog.locator('.model-card input[type=number]').fill('100');
    await dialog.getByRole('button', { name: '💾 Save changes' }).click();
    await dialog.getByRole('alert').waitFor();
    ok('Settings validation is English and remains non-destructive', (await dialog.getByRole('alert').innerText()).includes('between 256 and 65536'));
    await dialog.getByRole('button', { name: 'Close settings' }).click();
    await context.close();
  });

  await section('member capabilities', async () => {
    const context = await browser.newContext({ viewport: { width: 1100, height: 850 } });
    const page = watch(await context.newPage());
    await login(page, MEMBER);
    await page.getByRole('button', { name: '⚙ Settings' }).click();
    const dialog = page.locator('.settings-modal');
    await dialog.waitFor();
    const tabs = await dialog.getByRole('tab').allTextContents();
    ok('Member retains exactly Appearance, Skills and Audit in English', tabs.length === 3 && ['Appearance', 'Skills', 'Audit'].every((name) => tabs.some((tab) => tab.includes(name))), tabs.join(', '));
    ok('Member has the same local language control', await dialog.getByRole('button', { name: /^English/ }).isVisible() && await dialog.getByRole('button', { name: /^Tiếng Việt/ }).isVisible());
    ok('Member does not see admin-only global save/lock', await dialog.getByRole('button', { name: /Settings locked|Save settings/ }).count() === 0);
    await context.close();
  });

  await section('english demo streaming', async () => {
    const context = await browser.newContext({ viewport: { width: 1440, height: 1000 } });
    const page = watch(await context.newPage());
    await login(page, ADMIN);
    await closeSettings(page);
    const created = page.waitForResponse((response) => response.url().endsWith('/api/sessions') && response.request().method() === 'POST');
    await page.getByRole('button', { name: '＋ New session' }).click();
    await created;
    let requestLanguage = null;
    page.on('request', (request) => {
      if (request.method() === 'POST' && /\/api\/sessions\/[^/]+\/chat$/.test(new URL(request.url()).pathname)) {
        requestLanguage = request.postDataJSON().language;
      }
    });
    const completed = page.waitForResponse((response) => response.request().method() === 'POST' && /\/api\/sessions\/[^/]+\/chat$/.test(new URL(response.url()).pathname), { timeout: 45000 });
    await page.getByLabel('Task for Forge').fill('Create and run a small Python hello script');
    await page.locator('.btn-send').click();
    assert.equal((await completed).status(), 200);
    await page.locator('.btn-send').waitFor({ state: 'visible', timeout: 10000 });
    await page.locator('.tool-card').first().waitFor();
    await page.locator('.tree-row.file').first().waitFor();
    const timeline = await page.locator('.chat-scroll').innerText();
    ok('Chat request carries selected English language', requestLanguage === 'en', String(requestLanguage));
    ok('Scripted demo intro and final response are English', timeline.includes('This is Demo mode') && timeline.includes('Done! ✅') && timeline.includes('Open the Workspace panel'));
    ok('English demo does not leak scripted Vietnamese content', !timeline.includes('chế độ Demo') && !timeline.includes('Xong! ✅'));
    ok('English demo really creates a workspace file', await page.locator('.tree-row.file').filter({ hasText: 'hello_forge.py' }).count() > 0);
    await context.close();
  });

  await section('mobile english', async () => {
    const context = await browser.newContext({ viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true });
    const page = watch(await context.newPage());
    await login(page, ADMIN);
    await closeSettings(page);
    const dimensions = await page.evaluate(() => ({ body: document.body.scrollWidth, chat: document.querySelector('.chat-pane').getBoundingClientRect().width }));
    ok('English mobile has no horizontal overflow', dimensions.body === 390 && dimensions.chat === 390, JSON.stringify(dimensions));
    await page.getByRole('button', { name: 'Session list' }).click();
    ok('English mobile session drawer opens', await page.locator('.sidebar').isVisible());
    await page.getByRole('button', { name: 'Close sidebar' }).click();
    await page.getByRole('button', { name: 'Open Workspace' }).click();
    ok('English mobile Workspace drawer opens', await page.locator('.files-pane').isVisible());
    await page.getByRole('button', { name: 'Close Workspace panel' }).click();
    ok('English mobile Workspace drawer closes', !(await page.locator('.files-pane').isVisible()));
    await context.close();
  });

  await browser.close();
  ok('No browser runtime errors across English flows', runtimeErrors.length === 0, runtimeErrors.join('; '));
  const failed = results.filter((result) => !result.ok);
  console.log(`\n=== v0.38.0 English browser: ${results.length - failed.length}/${results.length} PASS ===`);
  if (failed.length) process.exit(1);
})().catch((error) => { console.error(error.stack || error); process.exit(1); });
