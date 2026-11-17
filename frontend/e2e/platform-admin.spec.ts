import { Browser, Page, expect, test } from '@playwright/test';

/** Phase 11: restaurant reports & dashboard; Super Admin overview, plans, subscriptions, content, support, audit. */

const OWNER = 'e2e.owner@urbanbites.example.com';
const ADMIN = 'e2e.admin@waitless.example.com';
const PASSWORD = 'Demo-pass-123';

async function signIn(browser: Browser, email: string, landing: RegExp): Promise<Page> {
  const page = await (await browser.newContext()).newPage();
  await page.goto('/login');
  await page.getByLabel('Email or mobile number').fill(email);
  await page.getByLabel('Password', { exact: true }).fill(PASSWORD);
  await page.getByRole('button', { name: 'Sign in' }).click();
  await expect(page).toHaveURL(landing, { timeout: 15_000 });
  return page;
}

test('owner sees today on the dashboard and reports with a chart, table and CSV', async ({ browser }) => {
  const page = await signIn(browser, OWNER, /\/restaurant-admin/);
  await expect(page.getByTestId('dashboard-kpis')).toContainText("Today's revenue");
  await expect(page.getByTestId('dashboard-kpis')).toContainText('Serving time');

  await page.goto('/restaurant-admin/reports');
  await expect(page.getByTestId('report-totals')).toContainText('Net revenue');
  await expect(page.locator('wl-chart canvas')).toBeVisible();
  await expect(page.getByTestId('report-table')).toContainText('Average bill');
  await page.getByTestId('report-serving').click();
  await expect(page.getByTestId('report-table')).toContainText('On time %');
  await page.getByTestId('report-range').selectOption('7');
  const download = page.waitForEvent('download');
  await page.getByTestId('report-csv').click();
  expect((await download).suggestedFilename()).toMatch(/^serving-.*\.csv$/);

  await page.goto('/restaurant-admin/settings');
  await expect(page.getByTestId('plan-panel')).toContainText(/Professional|Enterprise|Starter/);
  await expect(page.getByTestId('usage-max_branches')).toContainText('Branches');
  await page.context().close();
});

test('restaurant asks for help; Super Admin answers it on the support desk', async ({ browser }, info) => {
  test.skip(info.project.name !== 'desktop', 'shared platform data: run once');
  const text = `E2E help ${Date.now()} — the printer prints blank receipts.`;
  const owner = await signIn(browser, OWNER, /\/restaurant-admin/);
  await owner.goto('/restaurant-admin/settings');
  await owner.getByRole('tab', { name: 'Help' }).click();
  await owner.getByTestId('help-message').fill(text);
  await owner.getByTestId('help-send').click();
  await expect(owner.getByTestId('help-list')).toContainText(text);

  const admin = await signIn(browser, ADMIN, /\/super-admin$/);
  await expect(admin.getByTestId('overview-tiles')).toContainText('Restaurants');
  await admin.goto('/super-admin/support');
  await admin.getByTestId('ticket-item').filter({ hasText: text }).click();
  const detail = admin.getByTestId('ticket-detail');
  await expect(detail).toContainText(text);
  await detail.getByTestId('ticket-status').selectOption('in_progress');
  await detail.getByTestId('note-text').fill('Asked them to update the printer driver.');
  await detail.getByTestId('note-add').click();
  await expect(detail).toContainText('Asked them to update the printer driver.');

  await owner.reload();
  await owner.getByRole('tab', { name: 'Help' }).click();
  await expect(owner.getByTestId('help-list').locator('li', { hasText: text })).toContainText('in progress');
  await expect(owner.getByTestId('help-list')).not.toContainText('printer driver'); // internal note stays internal

  await admin.goto('/super-admin/audit');
  await admin.getByTestId('audit-action').fill('support');
  await admin.getByRole('button', { name: 'Filter' }).click();
  await expect(admin.getByTestId('audit-table')).toContainText('support.ticket_updated');
  await owner.context().close();
  await admin.context().close();
});

test('Super Admin edits a plan, sees subscriptions, and changes website content', async ({ browser }, info) => {
  test.skip(info.project.name !== 'desktop', 'shared platform data: run once');
  const admin = await signIn(browser, ADMIN, /\/super-admin$/);

  // One reusable test plan (hidden from sign-up), so repeated runs do not pile up plans.
  await admin.goto('/super-admin/plans');
  await expect(admin.getByTestId('plan-card').first()).toBeVisible(); // list loaded before deciding new vs edit
  const existing = admin.getByTestId('edit-plan-e2e-test');
  if (await existing.count()) await existing.click();
  else {
    await admin.getByTestId('new-plan').click();
    await admin.getByTestId('plan-code').fill('e2e-test');
  }
  const dlg = admin.getByRole('dialog');
  await dlg.getByTestId('plan-name').fill('E2E Test Plan');
  await dlg.getByTestId('plan-monthly').fill('499');
  await dlg.getByLabel('Shown to restaurants when they sign up').uncheck();
  await dlg.getByTestId('feat-ordering').check();
  const unlimited = dlg.locator('.limit', { hasText: 'Branches' }).getByLabel('Unlimited');
  await unlimited.uncheck();
  await dlg.getByLabel('Branches limit').fill('1');
  await dlg.getByTestId('save-plan').click();
  await expect(admin.getByText('E2E Test Plan saved.')).toBeVisible();
  const card = admin.getByTestId('plan-card').filter({ hasText: 'E2E Test Plan' });
  await expect(card).toContainText('Branches: 1');
  await expect(card).toContainText('Hidden');

  await admin.goto('/super-admin/subscriptions');
  await expect(admin.getByTestId('subs-table')).toContainText('Urban Bites');

  // Website content: an announcement banner, then cleared again.
  const note = `E2E announcement ${Date.now()}`;
  await admin.goto('/super-admin/content');
  await admin.getByTestId('section-branding').click();
  await admin.getByTestId('content-announcement').fill(note);
  await admin.getByTestId('save-content').click();
  await expect(admin.getByText('Saved — the website shows it within a minute.')).toBeVisible();
  const visitor = await (await browser.newContext()).newPage();
  await visitor.goto('/');
  await expect(visitor.getByTestId('site-banner')).toHaveText(note);
  await expect(visitor.getByRole('heading', { level: 1 })).toContainText('Skip the wait.');
  await admin.getByTestId('content-announcement').fill('');
  await admin.getByTestId('save-content').click();
  await visitor.context().close();
  await admin.context().close();
});
