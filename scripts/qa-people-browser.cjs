/* Synthetic companion to qa-people-browser.py; uses no existing installation. */
const assert = require('node:assert/strict');
const path = require('node:path');
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const origin = process.env.RECORDBENCH_QA_ORIGIN;
assert.match(origin || '', /^https:\/\/127\.0\.0\.1:\d+$/);
const password = 'synthetic-browser-password';
const changedPassword = 'synthetic-reset-password';

(async () => {
  const browser = await chromium.launch({headless: true, channel: process.env.RECORDBENCH_QA_BROWSER_CHANNEL || undefined});
  try {
    const options = {ignoreHTTPSErrors: true, viewport: {width: 1440, height: 1000}};
    const admin = await (await browser.newContext(options)).newPage();
    const first = await (await browser.newContext(options)).newPage();
    const second = await (await browser.newContext(options)).newPage();
    const assetFailures = [];
    for (const page of [admin, first, second]) {
      page.on('requestfailed', request => {
        if (new URL(request.url()).pathname.startsWith('/static/')) assetFailures.push(request.url());
      });
      page.on('response', response => {
        if (new URL(response.url()).pathname.startsWith('/static/') && response.status() !== 200) {
          assetFailures.push(response.url() + ': ' + response.status());
        }
      });
    }
    async function login(page, username, value = password) {
      await page.goto(origin + '/auth/login');
      await page.getByRole('textbox', {name: 'Username', exact: true}).fill(username);
      await page.getByLabel('Password', {exact: true}).fill(value);
      await page.getByRole('button', {name: 'Open RecordBench'}).click();
      await page.waitForURL(url => !url.pathname.startsWith('/auth/'));
    }
    async function create(username, name) {
      await admin.goto(origin + '/admin/people');
      await admin.getByLabel('Name shown in RecordBench').fill(name);
      await admin.keyboard.press('Tab');
      await admin.keyboard.type(username);
      await admin.getByLabel('Password', {exact: true}).fill(password);
      await admin.getByLabel('Enter password again', {exact: true}).fill(password);
      await admin.getByRole('button', {name: 'Create account', exact: true}).click();
      await admin.waitForURL(url => url.pathname === '/admin/people/accounts/' + username);
      assert.ok((await admin.getByRole('status').innerText()).includes('Account created'));
      assert.ok(!(await admin.content()).includes(password));
    }
    await login(admin, 'alice.admin');
    assert.equal(new URL(admin.url()).pathname, '/admin/setup');
    await admin.getByRole('heading', {name: 'Bring your team into RecordBench'}).waitFor();
    const assets = await admin.evaluate(() => Array.from(document.querySelectorAll('link[rel="stylesheet"], script[src]'))
      .map(element => ({url: element.href || element.src, loaded: element.tagName !== 'LINK' || Boolean(element.sheet)})));
    assert.ok(assets.length >= 4);
    for (const asset of assets) {
      assert.equal(new URL(asset.url).origin, origin);
      assert.equal(asset.loaded, true);
    }
    await admin.getByRole('button', {name: 'Open background activity', exact: true}).click();
    await admin.locator('#workspace-activity-drawer[aria-hidden="false"]').waitFor();
    await admin.getByRole('button', {name: 'Close background activity', exact: true}).click();
    await admin.screenshot({path: path.join(process.env.RECORDBENCH_QA_ARTIFACTS, 'setup-desktop.png'), fullPage: true});
    await admin.setViewportSize({width: 390, height: 844});
    await admin.reload();
    assert.equal(await admin.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth), true);
    await admin.screenshot({path: path.join(process.env.RECORDBENCH_QA_ARTIFACTS, 'setup-mobile.png'), fullPage: true});
    await admin.setViewportSize({width: 1440, height: 1000});
    await admin.reload();
    await create('first.reviewer', 'Synthetic Reviewer');
    await create('second.reviewer', 'Synthetic Reviewer');
    await login(first, 'first.reviewer');
    await login(second, 'second.reviewer');
    await admin.goto(origin + '/matters/new');
    await admin.getByLabel('Matter name', {exact: true}).fill('Synthetic browser acceptance matter');
    await admin.getByRole('button', {name: 'Create matter', exact: true}).click();
    await admin.waitForURL(/\/matters\/[^/]+\/setup/);
    const slug = new URL(admin.url()).pathname.split('/')[2];
    const picker = admin.getByLabel('Add a case team member', {exact: true});
    assert.equal(await picker.inputValue(), '');
    assert.equal(await picker.evaluate(element => element.checkValidity()), false);
    await admin.getByRole('button', {name: 'Add member', exact: true}).click();
    assert.equal(await picker.inputValue(), '');
    const labels = await picker.locator('option:not([disabled])').allTextContents();
    assert.deepEqual([...labels].sort(), ['Synthetic Reviewer (first.reviewer)', 'Synthetic Reviewer (second.reviewer)']);
    const selectedLabel = labels[1];
    const selectedUsername = selectedLabel.includes('(first.reviewer)') ? 'first.reviewer' : 'second.reviewer';
    const selected = selectedUsername === 'first.reviewer' ? first : second;
    const unassigned = selected === first ? second : first;
    await picker.selectOption({label: selectedLabel});
    await admin.getByRole('button', {name: 'Add member', exact: true}).click();
    await admin.getByText(selectedLabel + ' added to the case team', {exact: true}).waitFor();
    await admin.locator('.case-team-list').getByText(selectedLabel, {exact: true}).waitFor();
    assert.equal((await selected.goto(origin + '/matters/' + slug + '/home')).status(), 200);
    assert.equal((await unassigned.goto(origin + '/matters/' + slug + '/home')).status(), 404);
    assert.equal((await unassigned.request.get(origin + '/matters/' + slug + '/notebook/export?format=markdown')).status(), 404);
    assert.equal((await unassigned.goto(origin + '/admin/people')).status(), 403);
    assert.equal((await unassigned.goto(origin + '/admin/setup')).status(), 403);
    await admin.goto(origin + '/admin/setup?matter=' + slug);
    await admin.getByText('A current teammate has opened this matter since their latest access grant.', {exact: true}).waitFor();
    await admin.goto(origin + '/matters/' + slug + '/setup');
    await admin.getByRole('button', {name: 'Remove direct grant', exact: true}).click();
    await admin.getByText('Direct grant removed for ' + selectedLabel + '; any group grants still apply', {exact: true}).waitFor();
    assert.equal((await selected.goto(origin + '/matters/' + slug + '/home')).status(), 404);
    assert.equal((await selected.request.get(origin + '/matters/' + slug + '/notebook/export?format=markdown')).status(), 404);
    await admin.getByLabel('Add a case team member').selectOption({label: selectedLabel});
    await admin.getByRole('button', {name: 'Add member', exact: true}).click();
    await admin.getByText(selectedLabel + ' added to the case team', {exact: true}).waitFor();
    assert.equal((await selected.goto(origin + '/matters/' + slug + '/home')).status(), 200);
    await admin.goto(origin + '/admin/people/accounts/' + selectedUsername);
    await admin.getByLabel('New password', {exact: true}).fill(changedPassword);
    await admin.getByLabel('Enter new password again', {exact: true}).fill(changedPassword);
    await admin.getByRole('button', {name: 'Change password', exact: true}).click();
    await admin.getByRole('status').filter({hasText: 'Password changed'}).waitFor();
    await selected.reload();
    assert.equal(new URL(selected.url()).pathname, '/auth/login');
    await login(selected, selectedUsername, changedPassword);
    await admin.getByRole('button', {name: 'Disable sign-in', exact: true}).click();
    await admin.getByRole('status').filter({hasText: 'Sign-in access updated'}).waitFor();
    await selected.reload();
    assert.equal(new URL(selected.url()).pathname, '/auth/login');
    await admin.getByLabel('Name shown in RecordBench', {exact: true}).fill('Renamed Offline Reviewer');
    await admin.getByRole('button', {name: 'Save name', exact: true}).click();
    await admin.getByRole('status').filter({hasText: 'Name updated'}).waitFor();
    await admin.goto(origin + '/matters/' + slug + '/setup');
    await admin.getByText('Renamed Offline Reviewer (' + selectedUsername + ')', {exact: true}).first().waitFor();
    await admin.goto(origin + '/admin/people');
    await admin.screenshot({path: path.join(process.env.RECORDBENCH_QA_ARTIFACTS, 'people-desktop.png'), fullPage: true});
    await admin.setViewportSize({width: 390, height: 844});
    await admin.reload();
    assert.equal(await admin.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth), true);
    await admin.screenshot({path: path.join(process.env.RECORDBENCH_QA_ARTIFACTS, 'people-mobile.png'), fullPage: true});
    assert.deepEqual(assetFailures, []);
    console.log('PASS: Same-origin HTTPS assets with backend HTTP scope, working activity control, explicit duplicate-name selection, named grant receipt, unassigned and revoked-session denial, People reset/disable revocation, disabled-account team-name refresh, and 390px layout.');
  } finally { await browser.close(); }
})().catch(error => { console.error(error.message); process.exitCode = 1; });
